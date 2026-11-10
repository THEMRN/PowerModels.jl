# Test 1: the offline part of frequency.jl, no optimization.
#   1. machine data read from the .dyr (H, R per online unit), cross-checked by ANDES's own reader
#   2. islands, H, K, D and the RoCoF / quasi-steady-state limits of every scenario, recomputed by hand
#   3. the nadir limit: SFR nadir at the limit, linearity, Euler step against the exact solution
#   4. sensitivity of the three limits to H, K and D: which one binds
#
#     julia --project=. runners/frequency_tests/1_offline.jl

include("common.jl")

const OUTPUT_DIR = joinpath(TEST_RESULTS, "offline")
const CASES = ["cases/psse/savnw", "cases/psse/ACTIVSg500"]
const SENSITIVITY_ISLANDS = ["savnw_north", "activsg_spartanb", "activsg_midlands"]   # first island of each
const SCALES_H = exp.(range(log(0.25), log(4.0), length=41))     # multiples of the island's H
const SCALES_K = range(0.0, 3.0, length=41)                      # multiples of K
const SCALES_D = range(0.0, 10.0, length=41)                     # multiples of D
const MAP_SIZE = 31                                              # grid points per axis of the H x K map
const CHECK_TOLERANCE = 1e-9                                     # pu, hand calculation against the code

"Model names of each `(bus, id)` record of a .dyr file, in file order."
function read_dyr_models(dyr_file)
    models = Dict{Tuple{Int,String},Vector{String}}()
    record = ""
    for line in eachline(dyr_file)
        record *= " " * line
        occursin('/', line) || continue
        fields = split(replace(first(split(record, '/')), ',' => ' '))
        record = ""
        length(fields) >= 3 || continue
        bus = tryparse(Int, fields[1])
        bus === nothing && continue
        key = (bus, String(strip(fields[3], [' ', '\''])))
        push!(get!(models, key, String[]), String(strip(fields[2], '\'')))
    end
    return models
end


# ==================== 1. Machine data from the .dyr ====================
println("==================== 1. Machine data ====================")
for case_path in CASES
    case_files = find_case_files(case_path)
    case_name = basename(case_path)
    network_data = PowerModels.parse_file(case_files.raw, import_all=true)
    machines = read_dyr_machine_data(case_files.dyr)
    models = read_dyr_models(case_files.dyr)
    base_mva = network_data["baseMVA"]

    rows = Dict{String,Any}[]
    for (_, gen) in sort(collect(network_data["gen"]), by=x -> (x[2]["gen_bus"], x[1]))
        gen["gen_status"] == 1 || continue
        gen_id = strip(string(gen["source_id"][3]))
        machine = get(machines, (gen["gen_bus"], gen_id), Dict{String,Float64}())
        push!(rows, Dict(
            "bus" => gen["gen_bus"],
            "id" => gen_id,
            "models" => get(models, (gen["gen_bus"], gen_id), String[]),
            "mbase" => gen["mbase"],
            "pg_mw" => gen["pg"] * base_mva,
            "pmax_mw" => gen["pmax"] * base_mva,
            "H" => get(machine, "H", nothing),
            "R" => get(machine, "R", nothing),
        ))
    end

    without_inertia = count(row -> row["H"] === nothing, rows)
    without_governor = count(row -> row["R"] === nothing, rows)
    println("$case_name: $(length(rows)) online units, $without_inertia without H, $without_governor without governor")

    machines_file = joinpath(OUTPUT_DIR, "machines_$(case_name).json")
    write_json(machines_file, Dict("case" => case_name, "dyr" => case_files.dyr, "units" => rows))

    # independent reading of the same .dyr by ANDES
    check_script = joinpath(@__DIR__, "andes_dyr_check.py")
    run(`python $check_script $(case_files.raw) $(case_files.dyr) $machines_file`)
end


# ==================== 2. Islands, H, K, D and limits ====================
println("==================== 2. Islands and limits ====================")

"Hand calculation of an island's H, K, D (system base), independent of calc_island_frequency_params."
function calc_island_params_by_hand(network_data, island_buses, machines)
    base_mva = network_data["baseMVA"]
    H = 0.0
    K = 0.0
    D = 0.0
    contributions = Dict{String,Any}[]
    for (_, gen) in sort(collect(network_data["gen"]), by=x -> x[2]["gen_bus"])
        gen["gen_status"] == 1 && gen["gen_bus"] in island_buses || continue
        machine = get(machines, (gen["gen_bus"], strip(string(gen["source_id"][3]))), Dict{String,Float64}())
        H_share = get(machine, "H", 0.0) * gen["mbase"] / base_mva
        K_share = haskey(machine, "R") ? gen["mbase"] / (base_mva * machine["R"]) : 0.0
        H += H_share
        K += K_share
        push!(contributions, Dict("bus" => gen["gen_bus"], "mbase" => gen["mbase"], "H" => get(machine, "H", nothing),
            "R" => get(machine, "R", nothing), "H_share" => H_share, "K_share" => K_share))
    end
    for (_, load) in network_data["load"]
        load["status"] == 1 && load["load_bus"] in island_buses && (D += LOAD_DAMPING * load["pd"])
    end
    return H, K, D, contributions
end

"Checks of the island split: islands partition the buses, only target lines join them, boundary arcs are complete."
function check_island_split(network_data, target_lines, components)
    island_of_bus = Dict{Int,Int}()
    for (k, component) in enumerate(components), bus in component
        island_of_bus[bus] = k
    end
    active_buses = [bus["bus_i"] for bus in values(network_data["bus"]) if bus["bus_type"] != 4]
    partition_ok = sort(collect(keys(island_of_bus))) == sort(active_buses) && sum(length, components) == length(active_buses)

    separated_ok = true
    for (key, branch) in network_data["branch"]
        branch["br_status"] == 1 || continue
        parse(Int, key) in target_lines && continue
        island_of_bus[branch["f_bus"]] == island_of_bus[branch["t_bus"]] || (separated_ok = false)
    end
    return partition_ok, separated_ok
end

island_rows = Dict{String,Any}[]
nadir_rows = Dict{String,Any}[]
sensitivity_islands = Dict{String,Any}()
for name in sort(collect(keys(SCENARIOS)))
    network_data, target_lines, case_files = load_scenario(name)
    machines = read_dyr_machine_data(case_files.dyr)
    islands = find_test_islands(network_data, target_lines, case_files.dyr)
    components = calc_islands_after_opening(network_data, target_lines)
    partition_ok, separated_ok = check_island_split(network_data, target_lines, components)

    dead_islands = find_dead_islands(network_data, target_lines, islands)

    for (k, island) in enumerate(islands)
        H, K, D, contributions = calc_island_params_by_hand(network_data, island["buses"], machines)
        rocof_by_hand = 2 * H * MAX_ROCOF / NOMINAL_FREQUENCY
        qss_by_hand = (D + K) * MAX_QSS_DEVIATION / NOMINAL_FREQUENCY

        # boundary arcs: island end inside, far end outside, and every in-service target line crossing the island edge listed
        arcs_ok = all(arc[2] in island["buses"] && !(arc[3] in island["buses"]) for arc in island["boundary_arcs"])
        crossing_lines = [line for line in target_lines if network_data["branch"][string(line)]["br_status"] != 0 && xor(network_data["branch"][string(line)]["f_bus"] in island["buses"],
            network_data["branch"][string(line)]["t_bus"] in island["buses"])]
        arcs_ok &= sort(crossing_lines) == sort([arc[1] for arc in island["boundary_arcs"]])

        limits_mw, binding = calc_limits_mw(network_data, island)
        balance = calc_island_balance(network_data, island["buses"])
        row = Dict(
            "scenario" => name,
            "description" => SCENARIOS[name].description,
            "island" => k,
            "n_buses" => length(island["buses"]),
            "first_bus" => first(island["buses"]),
            "balance" => balance,
            "gens" => island["gens"],
            "governors" => island["governors"],
            "H" => island["inertia"],
            "K" => island["governor_gain"],
            "D" => island["damping"],
            "limits_mw" => limits_mw,
            "binding" => binding,
            "contributions" => contributions,
            "checks" => Dict(
                "partition" => partition_ok,
                "separated" => separated_ok,
                "boundary_arcs" => arcs_ok,
                "H_by_hand" => abs(H - island["inertia"]) < CHECK_TOLERANCE,
                "K_by_hand" => abs(K - island["governor_gain"]) < CHECK_TOLERANCE,
                "D_by_hand" => abs(D - island["damping"]) < CHECK_TOLERANCE,
                "rocof_by_hand" => abs(rocof_by_hand - island["limits"]["rocof"]) < CHECK_TOLERANCE,
                "qss_by_hand" => abs(qss_by_hand - island["limits"]["qss"]) < CHECK_TOLERANCE,
            ),
            "dead_islands" => k == 1 ? dead_islands : [],
        )
        push!(island_rows, row)
        println("$name island $k: $(length(island["buses"])) buses, H $(round(island["inertia"], digits=2)) K $(round(island["governor_gain"], digits=1)) D $(round(island["damping"], digits=1)), ",
            "limits $(Dict(n => round(v, digits=1) for (n, v) in limits_mw)) MW, checks ", all(values(row["checks"])) ? "pass" : "FAIL $(row["checks"])")

        # ==================== 3. Nadir limit ====================
        nadir_limit = island["limits"]["nadir"]
        nadir_at_limit = simulate_frequency_nadir(island, nadir_limit)
        nadir_above_limit = simulate_frequency_nadir(island, nadir_limit + 2 * NADIR_SEARCH_TOLERANCE)
        times, response_at_limit = calc_sfr_response(island, nadir_limit)
        nadir_step = argmin(response_at_limit)

        # nadir deviation per pu of deficit, at several deficits (constant for a linear model)
        deficits = [0.25, 0.5, 1.0, 2.0, 4.0] .* nadir_limit
        deviation_per_pu = [(NOMINAL_FREQUENCY - simulate_frequency_nadir(island, deficit)) / deficit for deficit in deficits]
        linearity_spread = (maximum(deviation_per_pu) - minimum(deviation_per_pu)) / maximum(deviation_per_pu)

        # integration accuracy: limit with the code's Euler step, a 10x finer Euler step, and the exact solution
        limit_fine_euler = search_limit_of_response(deficit -> calc_sfr_response(island, deficit; time_step=SFR_TIME_STEP / 10)[2])
        _, exact_at_unit = calc_sfr_response_exact(island, 1.0; time_step=0.001)     # linear, so one solution scales
        limit_exact = (NOMINAL_FREQUENCY - MIN_NADIR_FREQUENCY) / (NOMINAL_FREQUENCY - minimum(exact_at_unit))
        _, exact_at_limit = calc_sfr_response_exact(island, nadir_limit; time_step=SFR_TIME_STEP)

        push!(nadir_rows, Dict(
            "scenario" => name,
            "island" => k,
            "nadir_limit_mw" => nadir_limit * network_data["baseMVA"],
            "nadir_at_limit_hz" => nadir_at_limit,
            "nadir_above_limit_hz" => nadir_above_limit,
            "trajectory_matches_code" => minimum(response_at_limit) == nadir_at_limit,
            "nadir_time_s" => times[nadir_step],
            "nadir_inside_window" => nadir_step < length(times),
            "deviation_per_pu_hz" => deviation_per_pu,
            "linearity_spread" => linearity_spread,
            "limit_fine_euler_mw" => limit_fine_euler * network_data["baseMVA"],
            "limit_exact_mw" => limit_exact * network_data["baseMVA"],
            "euler_error_pct" => 100 * (nadir_limit - limit_exact) / limit_exact,
            # trajectories at the nadir limit, every 0.05 s, for the report figure
            "t" => times[1:5:end],
            "f_euler" => response_at_limit[1:5:end],
            "f_exact" => exact_at_limit[1:5:end],
        ))

        # keep the parameters of the islands used for the sensitivity sweeps
        if k == 1 && name in SENSITIVITY_ISLANDS
            sensitivity_islands[name] = (island=island, base_mva=network_data["baseMVA"], description=SCENARIOS[name].description)
        end
    end
end
write_json(joinpath(OUTPUT_DIR, "islands.json"), island_rows)
write_json(joinpath(OUTPUT_DIR, "nadir.json"), nadir_rows)


# ==================== 4. Sensitivity of the limits ====================
println("==================== 4. Sensitivity ====================")

"The three limits (MW) of an island whose H, K, D are scaled by the given factors."
function calc_scaled_limits(island, base_mva; scale_H=1.0, scale_K=1.0, scale_D=1.0)
    params = Dict(
        "inertia" => island["inertia"] * scale_H,
        "governor_gain" => island["governor_gain"] * scale_K,
        "governor_units" => [merge(unit, (gain=unit.gain * scale_K,)) for unit in island["governor_units"]],
        "damping" => island["damping"] * scale_D,
    )
    return Dict(
        "rocof" => 2 * params["inertia"] * MAX_ROCOF / NOMINAL_FREQUENCY * base_mva,
        "qss" => (params["damping"] + params["governor_gain"]) * MAX_QSS_DEVIATION / NOMINAL_FREQUENCY * base_mva,
        "nadir" => search_nadir_limit(params) * base_mva,
    )
end

sensitivity = Dict{String,Any}()
for (name, entry) in sensitivity_islands
    island = entry.island
    sweeps = Dict{String,Any}()
    for (parameter, scales) in (("H", SCALES_H), ("K", SCALES_K), ("D", SCALES_D))
        limits = [calc_scaled_limits(island, entry.base_mva;
            scale_H=parameter == "H" ? s : 1.0,
            scale_K=parameter == "K" ? s : 1.0,
            scale_D=parameter == "D" ? s : 1.0) for s in scales]
        sweeps[parameter] = Dict("scale" => collect(scales), "limits" => limits)
    end

    # map of the binding limit over H and K
    map_H = exp.(range(log(0.25), log(4.0), length=MAP_SIZE))
    map_K = range(0.0, 3.0, length=MAP_SIZE)
    binding_map = [string(argmin(calc_scaled_limits(island, entry.base_mva; scale_H=h, scale_K=k))) for k in map_K, h in map_H]
    tightest_map = [minimum(values(calc_scaled_limits(island, entry.base_mva; scale_H=h, scale_K=k))) for k in map_K, h in map_H]

    sensitivity[name] = Dict(
        "description" => entry.description,
        "H" => island["inertia"],
        "K" => island["governor_gain"],
        "D" => island["damping"],
        "sweeps" => sweeps,
        "map" => Dict("scale_H" => collect(map_H), "scale_K" => collect(map_K),
            "binding" => [binding_map[i, :] for i in 1:MAP_SIZE], "tightest_mw" => [tightest_map[i, :] for i in 1:MAP_SIZE]),
    )
    println("$name: sensitivity sweeps done")
end
write_json(joinpath(OUTPUT_DIR, "sensitivity.json"), sensitivity)
println("Offline results written to $OUTPUT_DIR")
