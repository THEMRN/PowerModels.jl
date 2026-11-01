# Shared setup of the frequency-security tests: packages, runner files, the test scenarios and
# the helpers used by the numbered test scripts. Run every script from the repository root:
#
#     julia --project=. runners/frequency_tests/1_offline.jl
#
# Each script writes JSON into results/frequency_tests/<test>/; build_report.py turns it into
# the HTML report.

using PowerModels
using Ipopt
using JuMP
using JSON3
using XLSX
using LinearAlgebra
include("../calc_line_flow.jl")
include("../excel_generator.jl")
include("../utils.jl")
include("../islanding_core.jl")

PowerModels.silence()


# ==================== Settings ====================
const TEST_RESULTS = "results/frequency_tests"
const SHED_PENALTY = 1000.0             # per pu of shed load, 10x the generation cost (100 per pu) in both cases
const BINDING_TOLERANCE = 0.05          # MW, an import this close to its limit counts as binding
const RELAY_MODELS = ["FRQTPAT", "LDSHBL"]   # removed from the .dyr for the calibration sweeps
const NO_BROWSER = raw"C:\Program Files\Git\usr\bin\true.exe"   # does nothing, keeps dynamic.py from opening its report


# ==================== Test scenarios ====================
# Boundaries and network changes follow the scenario blocks of islanding.jl. `modify` is applied
# to the parsed network before anything else; `zone` replaces `bus_pairs` for zone boundaries.
const SAVNW_NORTH_SOUTH = [(154, 3008), (154, 153), (152, 153), (152, 3004)]

const SCENARIOS = Dict(
    # savnw -----------------------------------------------
    "savnw_top" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(3001, 3002), (3005, 3004), (3005, 3006), (3005, 3008), (3005, 3007)],
        zone=nothing,
        modify=data -> nothing,
        description="island on top: gen 3011 (900 MW) with the 100 MW load at bus 3005",
    ),
    "savnw_top_heavy" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(3001, 3002), (3005, 3004), (3005, 3006), (3005, 3008), (3005, 3007)],
        zone=nothing,
        modify=data -> (data["load"]["6"]["pd"] = 4.0),     # 400 MW at 3005, as in islanding.jl
        description="island on top with the load at 3005 raised to 400 MW (as in islanding.jl)",
    ),
    "savnw_north" => (
        case_path="cases/psse/savnw",
        bus_pairs=SAVNW_NORTH_SOUTH,
        zone=nothing,
        modify=data -> nothing,
        description="north-south separation",
    ),
    "savnw_north_heavy" => (
        case_path="cases/psse/savnw",
        bus_pairs=SAVNW_NORTH_SOUTH,
        zone=nothing,
        modify=data -> scale_loads!(data, 1.6, [3005, 3007, 3008, 153]),
        description="north-south separation, north loads x1.6 (as in islanding.jl)",
    ),
    "savnw_bottom" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(201, 151), (202, 152), (203, 154), (205, 154)],
        zone=nothing,
        modify=data -> nothing,
        description="island on bottom with the loads at 203 and 205",
    ),
    "savnw_left" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(3007, 3008), (154, 3008), (3005, 3008)],
        zone=nothing,
        modify=data -> nothing,
        description="island on left: gen 3018 (no governor in the .dyr) with the 200 MW load at 3008",
    ),
    "savnw_gen_only" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(3008, 3018)],
        zone=nothing,
        modify=data -> nothing,
        description="gen 3018 alone: no load, no governor",
    ),
    "savnw_dead_bus" => (
        case_path="cases/psse/savnw",
        bus_pairs=[(202, 152), (202, 201), (202, 203)],
        zone=nothing,
        modify=data -> nothing,
        description="bus 202 alone: no generation",
    ),
    "savnw_north_line_out" => (
        case_path="cases/psse/savnw",
        bus_pairs=SAVNW_NORTH_SOUTH,
        zone=nothing,
        modify=data -> (data["branch"]["5"]["br_status"] = 0),     # 152-3004 already open
        description="north-south separation with one boundary line (152-3004) already out of service",
    ),
    # ACTIVSg500 ------------------------------------------
    "activsg_spartanb" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="SPARTANB",
        modify=data -> nothing,
        description="SPARTANB zone: importing island, hydro units only",
    ),
    "activsg_midlands" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="MIDLANDS",
        modify=data -> nothing,
        description="MIDLANDS zone: importing island, hydro, gas and steam units",
    ),
    "activsg_york" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="YORK",
        modify=data -> nothing,
        description="YORK zone: exporting island",
    ),
    "activsg_columbia" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="COLUMBIA",
        modify=data -> nothing,
        description="COLUMBIA zone: small exchange",
    ),
    "activsg_greenvil" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="GREENVIL",
        modify=data -> nothing,
        description="GREENVIL zone: 1340 MW of load, 12 MW of generation",
    ),
    "activsg_midlands_light" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="MIDLANDS",
        modify=data -> scale_loads!(data, 0.7, "MIDLANDS"),
        description="MIDLANDS zone, zone loads x0.7 so its units can cover them",
    ),
    "activsg_spartanb_light" => (
        case_path="cases/psse/ACTIVSg500",
        bus_pairs=Tuple{Int,Int}[],
        zone="SPARTANB",
        modify=data -> scale_loads!(data, 0.5, "SPARTANB"),
        description="SPARTANB zone, zone loads x0.5 so its units can cover them",
    ),
)


# ==================== Scenario setup and solve ====================
const PARSED_CASES = Dict{String,Any}()     # each case is parsed once per session

"Network data of a scenario (its modification applied), its boundary lines and its case files."
function load_scenario(name)
    scenario = SCENARIOS[name]
    case_files = find_case_files(scenario.case_path)
    base_network = get!(PARSED_CASES, scenario.case_path) do
        PowerModels.parse_file(case_files.raw, import_all=true)
    end
    network_data = deepcopy(base_network)
    redirect_stdout(devnull) do         # scale_loads! prints one line per load
        scenario.modify(network_data)
    end

    if scenario.zone === nothing
        target_lines = find_branches_by_bus_pairs(network_data, scenario.bus_pairs)
    else
        target_lines = find_branches_by_zone(network_data, scenario.zone)
        network_data["target_zone_buses"] = find_buses_by_zone(network_data, scenario.zone)
    end
    return network_data, target_lines, case_files
end

"Islands left by opening `target_lines`, with their limits, as add_frequency_security! embeds them (the network data is not changed)."
function find_test_islands(network_data, target_lines, dyr_file)
    island_data = deepcopy(network_data)
    add_frequency_security!(island_data, target_lines, dyr_file)
    return island_data["frequency_islands"]
end

"""
Solve a scenario the way run_islanding does (settings embedded in the network data), without
its reports and export. `frequency_security` adds the island limits. `forced_import` (MW)
instead fixes the scheduled import of `islands[1]`, for the dynamic sweeps. Shedding
objectives get the uniform `SHED_PENALTY` unless the loads already carry penalties.
Mutates `network_data`. Returns the solve result.
"""
function solve_scenario!(network_data, target_lines, dyr_file;
    objective="opf",
    opf_model="AC",
    frequency_security=false,
    forced_import=nothing,
    islands=nothing,
    lambda=500,
    flow_model="squared",
)
    network_data["objective"] = ObjectiveType[objective]
    network_data["target_ids"] = target_lines
    network_data["opf_model"] = opf_model
    network_data["p_model"] = flow_model
    network_data["lambda"] = lambda
    delete!(network_data, "frequency_islands")

    has_penalties = all(haskey(load, "shed_penalty") for load in values(network_data["load"]))
    if contains(objective, "shed") && !has_penalties
        redirect_stdout(devnull) do
            add_load_shedding_penalty!(network_data; uniform=true, uniform_penalty=SHED_PENALTY)
        end
    end
    if frequency_security
        add_frequency_security!(network_data, target_lines, dyr_file)
    end

    optimizer = optimizer_with_attributes(Ipopt.Optimizer, "print_level" => 0)
    power_model = PowerModelType[opf_model]
    if forced_import === nothing
        return PowerModels.solve_custom_opf(network_data, power_model, optimizer)
    end

    # forced import (test only): the custom model plus one equality on the first island's import
    pm = PowerModels.instantiate_model(network_data, power_model, PowerModels.build_custom_pf)
    p = var(pm, :p)
    scheduled_import = sum(-p[arc] for arc in islands[1]["boundary_arcs"])
    JuMP.@constraint(pm.model, scheduled_import == forced_import / network_data["baseMVA"])
    return PowerModels.optimize_model!(pm, optimizer=optimizer)
end

"True when Ipopt found a (locally) optimal solution."
is_solved(result) = string(result["termination_status"]) in ("LOCALLY_SOLVED", "ALMOST_LOCALLY_SOLVED", "OPTIMAL")


# ==================== Quantities of a solution ====================
"Scheduled import (MW) of each island: the power flowing in over its boundary arcs, measured at the island end."
function calc_island_imports(network_data, islands, result)
    sol_branches = result["solution"]["branch"]
    imports = Float64[]
    for island in islands
        scheduled_import = 0.0
        for (branch_id, island_bus, _) in island["boundary_arcs"]
            haskey(sol_branches, string(branch_id)) || continue      # out of service: no flow, no solution entry
            island_end = network_data["branch"][string(branch_id)]["f_bus"] == island_bus ? "pf" : "pt"
            scheduled_import -= sol_branches[string(branch_id)][island_end]
        end
        push!(imports, scheduled_import * network_data["baseMVA"])
    end
    return imports
end

"Load shed by the solution (MW), zero for objectives without shedding."
function calc_total_shed(network_data, result)
    sol_loads = get(result["solution"], "load", Dict())
    shed = 0.0
    for (i, load) in network_data["load"]
        haskey(sol_loads, i) && haskey(sol_loads[i], "pd") || continue
        shed += load["pd"] - sol_loads[i]["pd"]
    end
    return shed * network_data["baseMVA"]
end

"Load (MW), dispatch and capacity (MW) of the online generators of an island."
function calc_island_balance(network_data, island_buses, result=nothing)
    base_mva = network_data["baseMVA"]
    load = 0.0
    for (_, l) in network_data["load"]
        l["status"] == 1 && l["load_bus"] in island_buses && (load += l["pd"])
    end
    dispatch = 0.0
    capacity = 0.0
    capacity_min = 0.0
    for (i, gen) in network_data["gen"]
        gen["gen_status"] == 1 && gen["gen_bus"] in island_buses || continue
        dispatch += result === nothing ? gen["pg"] : result["solution"]["gen"][i]["pg"]
        capacity += gen["pmax"]
        capacity_min += gen["pmin"]
    end
    return Dict(
        "load_mw" => load * base_mva,
        "dispatch_mw" => dispatch * base_mva,
        "pmax_mw" => capacity * base_mva,
        "pmin_mw" => capacity_min * base_mva,
    )
end

"Islands left without synchronous inertia, which add_frequency_security! skips: their buses and load (MW), lost at the split."
function find_dead_islands(network_data, target_lines, islands)
    dead_islands = Dict{String,Any}[]
    for component in calc_islands_after_opening(network_data, target_lines)
        isempty(calc_island_boundary_arcs(network_data, target_lines, component)) && continue   # not cut by the target lines
        buses = sort(collect(component))
        any(island["buses"] == buses for island in islands) && continue
        push!(dead_islands, Dict("buses" => buses, "load_mw" => calc_island_balance(network_data, buses)["load_mw"]))
    end
    return dead_islands
end

"""
Hand check that the frequency limits can be met without shedding, losses ignored: each island's
import must lie in [max(load - pmax, -limit), min(load - pmin, limit)], and the imports of all
islands must add up to minus the load of the islands without generation (fed over the boundary).
Returns whether that is possible, the import range of each island (MW) and the dead-island load (MW).
"""
function check_limits_feasible_by_hand(network_data, islands, dead_islands)
    import_ranges = Tuple{Float64,Float64}[]
    for island in islands
        balance = calc_island_balance(network_data, island["buses"])
        limit = minimum(values(island["limits"])) * network_data["baseMVA"]
        low = max(balance["load_mw"] - balance["pmax_mw"], -limit)
        high = min(balance["load_mw"] - balance["pmin_mw"], limit)
        push!(import_ranges, (low, high))
    end
    dead_load = sum((dead["load_mw"] for dead in dead_islands); init=0.0)
    ranges_exist = all(low <= high for (low, high) in import_ranges)
    balance_possible = sum(first, import_ranges) <= -dead_load <= sum(last, import_ranges)
    return ranges_exist && balance_possible, import_ranges, dead_load
end

"Island limits in MW and the name of the tightest one."
function calc_limits_mw(network_data, island)
    limits_mw = Dict(name => value * network_data["baseMVA"] for (name, value) in island["limits"])
    return limits_mw, argmin(island["limits"])
end


# ==================== SFR model (frequency.jl) ====================
"""
Frequency (Hz) of the SFR model at every time step after the island loses `deficit` (pu) at
t = 0: the equations and forward Euler integration of simulate_frequency_nadir (frequency.jl),
returning the whole trajectory. `damping` (pu) replaces the island's load damping D when given.
"""
function calc_sfr_response(params, deficit; damping=params["damping"], time_step=SFR_TIME_STEP)
    H = params["inertia"]
    K = params["governor_gain"]
    D = damping

    steps = round(Int, SFR_DURATION / time_step)
    times = collect(0:steps) .* time_step
    frequency = fill(NOMINAL_FREQUENCY, steps + 1)
    df = 0.0            # frequency deviation, pu
    z = 0.0             # reheat stage state, pu
    for k in 1:steps
        governor_response = -K * (REHEAT_FRACTION * df + (1 - REHEAT_FRACTION) * z)
        ddf = (governor_response - D * df - deficit) / (2 * H)
        dz = (df - z) / REHEAT_TIME
        df += time_step * ddf
        z += time_step * dz
        frequency[k+1] = NOMINAL_FREQUENCY * (1 + df)
    end
    return times, frequency
end

"""
Exact solution (Hz) of the same linear SFR model at `time_step` intervals, from the matrix
exponential of the model (exact for a step deficit), to check the Euler integration.
"""
function calc_sfr_response_exact(params, deficit; time_step=0.001)
    H = params["inertia"]
    K = params["governor_gain"]
    D = params["damping"]

    # state x = [Δf, z] (pu), dx/dt = A x + b
    A = [-(K * REHEAT_FRACTION + D)/(2H) -K*(1-REHEAT_FRACTION)/(2H);
        1/REHEAT_TIME -1/REHEAT_TIME]
    b = [-deficit / (2H), 0.0]

    # exact one-step update x+ = Φ x + Γ, from the exponential of the augmented matrix [A b; 0 0]
    augmented = exp([A b; zeros(1, 3)] .* time_step)
    Φ = augmented[1:2, 1:2]
    Γ = augmented[1:2, 3]

    steps = round(Int, SFR_DURATION / time_step)
    times = collect(0:steps) .* time_step
    frequency = fill(NOMINAL_FREQUENCY, steps + 1)
    x = zeros(2)
    for k in 1:steps
        x = Φ * x + Γ
        frequency[k+1] = NOMINAL_FREQUENCY * (1 + x[1])
    end
    return times, frequency
end

"Largest deficit (pu) whose frequency from `response(deficit)` stays at or above MIN_NADIR_FREQUENCY, by bisection as search_nadir_limit does."
function search_limit_of_response(response)
    clears_ufls(deficit) = minimum(response(deficit)) >= MIN_NADIR_FREQUENCY
    low = 0.0
    high = 1.0
    while clears_ufls(high)
        low = high
        high *= 2
    end
    while high - low > NADIR_SEARCH_TOLERANCE
        mid = (low + high) / 2
        clears_ufls(mid) ? (low = mid) : (high = mid)
    end
    return low
end


# ==================== ANDES runs ====================
"Copy of `dyr_file` without the records of `RELAY_MODELS` (multi-line records end at '/')."
function write_dyr_without_relays(dyr_file, output_file)
    kept_lines = String[]
    record_lines = String[]
    for line in eachline(dyr_file)
        push!(record_lines, line)
        occursin('/', line) || continue
        fields = split(replace(join(record_lines, " "), ',' => ' '))
        model = length(fields) >= 2 ? strip(fields[2], '\'') : ""
        model in RELAY_MODELS || append!(kept_lines, record_lines)
        empty!(record_lines)
    end
    append!(kept_lines, record_lines)
    mkpath(dirname(output_file))
    write(output_file, join(kept_lines, "\n") * "\n")
    return output_file
end

"Lines to trip as dynamic.py reads them, from the branch source ids (same as run_islanding)."
function calc_line_outages(network_data, target_lines)
    outages = Dict{String,Any}[]
    for line in target_lines
        source_id = network_data["branch"][string(line)]["source_id"]
        id_position = source_id[1] == "branch" ? 4 : 5
        push!(outages, Dict("from" => source_id[2], "to" => source_id[3], "id" => source_id[id_position]))
    end
    return outages
end

"""
What analyze_andes.py needs about one island: its buses, boundary (as RAW bus pairs and
circuits), machines with their inertia weights, H/K/D, limits (MW), scheduled import (MW) and
the SFR response to a 1 pu deficit (with and without load damping), in Hz deviation.
"""
function calc_island_record(network_data, island, scheduled_import, machines)
    base_mva = network_data["baseMVA"]
    limits_mw, binding = calc_limits_mw(network_data, island)

    boundary = Dict{String,Any}[]
    for (branch_id, island_bus, _) in island["boundary_arcs"]
        source_id = network_data["branch"][string(branch_id)]["source_id"]
        circuit_position = source_id[1] == "branch" ? 4 : 5
        push!(boundary, Dict(
            "from" => source_id[2],
            "to" => source_id[3],
            "circuit" => strip(string(source_id[circuit_position])),
            "island_bus" => island_bus,
        ))
    end

    island_machines = Dict{String,Any}[]
    for (_, gen) in network_data["gen"]
        gen["gen_status"] == 1 && gen["gen_bus"] in island["buses"] || continue
        gen_id = strip(string(gen["source_id"][3]))
        H = get(get(machines, (gen["gen_bus"], gen_id), Dict()), "H", 0.0)
        push!(island_machines, Dict("bus" => gen["gen_bus"], "id" => gen_id, "mbase" => gen["mbase"], "H" => H))
    end

    times, unit_response = calc_sfr_response(island, 1.0)
    _, unit_response_undamped = calc_sfr_response(island, 1.0; damping=0.0)

    return Dict(
        "buses" => island["buses"],
        "boundary" => boundary,
        "machines" => island_machines,
        "inertia" => island["inertia"],
        "governor_gain" => island["governor_gain"],
        "damping" => island["damping"],
        "base_mva" => base_mva,
        "limits_mw" => limits_mw,
        "binding" => binding,
        "scheduled_import_mw" => scheduled_import,
        "sfr_unit" => Dict(
            "t" => times,
            "df_hz" => unit_response .- NOMINAL_FREQUENCY,
            "df_hz_undamped" => unit_response_undamped .- NOMINAL_FREQUENCY,
        ),
    )
end

"Write islands.json, what analyze_andes.py needs about every island of a solved run."
function write_islands_json(network_data, result, islands, dyr_file, output_dir; run_info=Dict())
    machines = read_dyr_machine_data(dyr_file)
    imports = calc_island_imports(network_data, islands, result)
    island_records = [calc_island_record(network_data, island, imports[k], machines) for (k, island) in enumerate(islands)]
    write_json(joinpath(output_dir, "islands.json"), Dict("run_info" => run_info, "islands" => island_records))
end

"""
Export a solved scenario for ANDES into `output_dir` as run_islanding does (case.raw from the
solution, line_outage.json, case.dyr) and write islands.json for analyze_andes.py.
"""
function export_for_andes(network_data, result, target_lines, islands, dyr_file, output_dir; run_info=Dict())
    mkpath(output_dir)
    solved_data = deepcopy(network_data)
    PowerModels.update_data!(solved_data, result["solution"])
    redirect_stdout(devnull) do
        PowerModels.export_pti(joinpath(output_dir, "case.raw"), prepare_for_pti_export(solved_data))
    end
    write_json(joinpath(output_dir, "line_outage.json"), calc_line_outages(network_data, target_lines))
    cp(dyr_file, joinpath(output_dir, "case.dyr"), force=true)
    write_islands_json(network_data, result, islands, dyr_file, output_dir; run_info=run_info)
end

"Run andes_scripts/dynamic.py on an exported case, its console output to console.txt. Returns true when it exited cleanly."
function run_andes(output_dir)
    script = joinpath(@__DIR__, "..", "andes_scripts", "dynamic.py")
    raw_file = joinpath(output_dir, "case.raw")
    dyr_file = joinpath(output_dir, "case.dyr")
    excel_name = joinpath(output_dir, "pm_res_case.xlsx")       # only names ANDES's report
    command = addenv(`python $script $raw_file $dyr_file $excel_name`, "BROWSER" => NO_BROWSER)
    process = open(joinpath(output_dir, "console.txt"), "w") do io
        run(pipeline(ignorestatus(command), stdout=io, stderr=io))
    end
    return success(process)
end

"Measure each island's frequency response in an ANDES run folder (analyze_andes.py writes metrics.json)."
function run_analysis(output_dir)
    script = joinpath(@__DIR__, "analyze_andes.py")
    run(`python $script $output_dir`)
end


# ==================== Output ====================
"Write `data` as JSON (NaN and Inf as null)."
function write_json(path, data)
    mkpath(dirname(path))
    open(path, "w") do io
        JSON3.write(io, replace_non_finite(data))
    end
end

replace_non_finite(x::AbstractFloat) = isfinite(x) ? x : nothing
replace_non_finite(x::AbstractDict) = Dict(string(k) => replace_non_finite(v) for (k, v) in x)
replace_non_finite(x::Union{AbstractVector,Tuple}) = [replace_non_finite(v) for v in x]
replace_non_finite(x) = x
