# Frequency security of the islands formed at the fixed boundary
# (proposal, "Frequency security": RoCoF, quasi-steady-state and nadir bounds).
#
# When the boundary opens, each island loses the import its boundary lines were carrying,
# ΔP = Σ P_ij into the island. The system frequency response (SFR) model of Anderson &
# Mirheydar (1990), one frequency for the whole island with each generator's own governor
# from the .dyr, turns the island's three frequency requirements into limits on that one number:
#   RoCoF:               |ΔP| <= 2 H MAX_ROCOF / f0
#   quasi-steady state:  |ΔP| <= (D + K) MAX_QSS_DEVIATION / f0
#   nadir:               |ΔP| <= ΔP_nadir, the largest step whose nadir stays above
#                        MIN_NADIR_FREQUENCY, found offline by bisection on the SFR model
#
# Workflow:
#   offline (run_islanding):  add_frequency_security! embeds the limits of every island in
#                             network_data["frequency_islands"]
#   model (build_custom_pf):  constraint_island_frequency_security, when that key exists
#   report (run_islanding):   print_frequency_security
#
# This file is included into the PowerModels module by src/prob/opf.jl, so `using PowerModels`
# already exports everything here; do not include it again from the runners.


# ==================== Frequency security settings ====================
const NOMINAL_FREQUENCY = 60.0          # Hz (base_freq in dynamic.py)
const MAX_ROCOF = 0.5                   # Hz/s, initial rate of change of frequency
const MAX_QSS_DEVIATION = 0.3           # Hz, deviation of the settling frequency
const MIN_NADIR_FREQUENCY = 59.5        # Hz, first UFLS stage of the PSS®E model

# SFR model: one frequency for the whole island
const LOAD_DAMPING = 1.0                # pu load change per pu frequency change
const REHEAT_FRACTION = 0.3             # F_H, fast share of governors read without speed data (IEEEG1, IEESGO)
const REHEAT_TIME = 7.0                 # s, T_R, slow time of those governors
const SFR_DURATION = 20.0               # s, post-event window simulated in dynamic.py
const SFR_TIME_STEP = 0.01              # s
const NADIR_SEARCH_TOLERANCE = 1e-5     # pu (system base)


# ==================== Machine data from the .dyr file ====================
# Position of the parameter among the values after `bus 'MODEL' id` in a PSS®E .dyr record
const DYR_INERTIA_POSITION = Dict("GENROU" => 5, "GENROE" => 5, "GENTPJ" => 5, "GENTPF" => 5, "GENSAL" => 4, "GENSAE" => 4, "GENCLS" => 1)
const DYR_GOVERNOR_POSITIONS = Dict(                # permanent droop R and the numbers that set the speed
    "TGOV1" => Dict("R" => 1, "T1" => 2, "T2" => 5, "T3" => 6),
    "HYGOV" => Dict("R" => 1, "r" => 2, "Tr" => 3, "Tf" => 4, "Tg" => 5, "Tw" => 9, "At" => 10, "Dturb" => 11, "qNL" => 12),
    "GAST" => Dict("R" => 1, "T1" => 2, "T2" => 3),
)
const DYR_GAIN_POSITION = Dict("IEEEG1" => 3, "IEESGO" => 7)                   # governor gain 1/R

"""
    read_dyr_machine_data(dyr_file)

Inertia `"H"` (s), governor droop `"R"` (pu), governor `"model"` and its speed numbers (named
as in `DYR_GOVERNOR_POSITIONS`), all on the machine base, for each generator `(bus, id)` of a
PSS®E .dyr file. Models missing from the tables above are ignored.
"""
function read_dyr_machine_data(dyr_file)
    # a record can span several lines and ends at '/', the rest of that line is a comment
    records = String[]
    current_record = ""
    for line in eachline(dyr_file)
        if occursin('/', line)
            push!(records, current_record * " " * first(split(line, '/')))
            current_record = ""
        else
            current_record *= " " * line
        end
    end

    machines = Dict{Tuple{Int,String},Dict{String,Any}}()
    for record in records
        fields = split(replace(record, ',' => ' '))
        length(fields) >= 3 || continue
        bus = tryparse(Int, fields[1])
        bus === nothing && continue
        model = strip(fields[2], '\'')
        gen_id = String(strip(fields[3], [' ', '\'']))
        machine = get!(machines, (bus, gen_id), Dict{String,Any}())

        if haskey(DYR_INERTIA_POSITION, model)
            machine["H"] = parse(Float64, fields[3+DYR_INERTIA_POSITION[model]])
        elseif haskey(DYR_GOVERNOR_POSITIONS, model)
            machine["model"] = String(model)
            for (name, position) in DYR_GOVERNOR_POSITIONS[model]
                machine[name] = parse(Float64, fields[3+position])
            end
        elseif haskey(DYR_GAIN_POSITION, model)
            machine["model"] = String(model)
            machine["R"] = 1 / parse(Float64, fields[3+DYR_GAIN_POSITION[model]])
        end
    end

    return machines
end


# ==================== Islands and their frequency response ====================
"Buses of each island left once `target_lines` are opened, smallest island first."
function calc_islands_after_opening(network_data, target_lines)
    opened_network = deepcopy(network_data)
    for line in target_lines
        opened_network["branch"][string(line)]["br_status"] = 0
    end
    return sort(collect(calc_connected_components(opened_network)), by=length)
end

"In-service target lines on the island's boundary, as arcs `(branch, island bus, outside bus)` leaving the island."
function calc_island_boundary_arcs(network_data, target_lines, island_buses)
    arcs = Tuple{Int,Int,Int}[]
    for line in target_lines
        branch = network_data["branch"][string(line)]
        branch["br_status"] != 0 || continue        # out of service: no flow, no variable in the model
        f_bus = branch["f_bus"]
        t_bus = branch["t_bus"]
        if f_bus in island_buses && !(t_bus in island_buses)
            push!(arcs, (line, f_bus, t_bus))
        elseif t_bus in island_buses && !(f_bus in island_buses)
            push!(arcs, (line, t_bus, f_bus))
        end
    end
    return arcs
end

"""
Linear response of one generator's governor and turbine to a frequency deviation, for the SFR
model, on the system base. A held deviation of 1 pu ends at `gain` (pu). `fast_share` of that
follows frequency at once and the rest comes through the lag `slow_time` (s); the sum then
passes the lags `delay` and `second_delay` (s). `pg` (pu, system base) sets a hydro unit's gate
opening, which sets its water column's wrong-way start `water_ratio` and `turbine_damping` (pu).
"""
function calc_governor_unit(machine, machine_share, pg)
    gain = 1 / machine["R"]
    fast_share = REHEAT_FRACTION
    slow_time = REHEAT_TIME
    delay = 0.0
    second_delay = 0.0
    water_ratio = 0.0
    turbine_damping = 0.0

    if machine["model"] == "TGOV1"
        # (1 + s T2) / (1 + s T3) = T2/T3 + (1 - T2/T3) / (1 + s T3)
        fast_share = machine["T2"] / machine["T3"]
        slow_time = machine["T3"]
        delay = machine["T1"]

    elseif machine["model"] == "HYGOV"
        R, r, Tr, Tw, At, qNL = machine["R"], machine["r"], machine["Tr"], machine["Tw"], machine["At"], machine["qNL"]
        gate_opening = clamp(pg / (machine_share * At) + qNL, max(qNL, 0.01), 1.0)      # pu, from the case dispatch

        # gate / speed = (1/R) (1 + s Tr) / (1 + s Tr (r + R)/R), R being a gate droop
        gain = At / R
        fast_share = R / (r + R)
        slow_time = Tr * (r + R) / R
        delay = machine["Tg"] + machine["Tf"]           # servo and filter as one lag

        # power / gate = (1 - s Tw (g - qNL)) / (1 + 0.5 s Tw g), linearized at the gate opening g
        second_delay = 0.5 * gate_opening * Tw
        water_ratio = 2 * (gate_opening - qNL) / gate_opening
        turbine_damping = machine["Dturb"] * gate_opening

    elseif machine["model"] == "GAST"
        fast_share = 1.0
        slow_time = Inf
        delay = machine["T1"]
        second_delay = machine["T2"]
    end

    return (
        gain=machine_share * gain,
        fast_share=fast_share,
        slow_time=slow_time,
        delay=max(delay, SFR_TIME_STEP),                # forward Euler needs a lag of at least one step
        second_delay=max(second_delay, SFR_TIME_STEP),
        water_ratio=water_ratio,
        turbine_damping=machine_share * turbine_damping,
    )
end

"""
Frequency response of an island on the system base: inertia `H` (s), governor gain
`K` = Σ 1/R (pu), load damping `D` (pu) and each governor's own response `governor_units`
(`calc_governor_unit`), from its online generators and loads.
"""
function calc_island_frequency_params(network_data, island_buses, machines)
    base_mva = network_data["baseMVA"]
    inertia = 0.0
    governor_gain = 0.0
    governor_units = []
    gens = 0
    governors = 0

    for (_, gen) in network_data["gen"]
        gen["gen_status"] == 1 || continue
        gen["gen_bus"] in island_buses || continue
        gen_id = strip(string(gen["source_id"][3]))
        machine = get(machines, (gen["gen_bus"], gen_id), Dict{String,Any}())
        haskey(machine, "H") || println("Gen $(gen_id) at bus $(gen["gen_bus"]) has no machine model in the .dyr, counted with zero inertia")

        machine_share = gen["mbase"] / base_mva             # machine base -> system base
        inertia += machine_share * get(machine, "H", 0.0)
        gens += 1
        if haskey(machine, "R")
            governor_gain += machine_share / machine["R"]
            push!(governor_units, calc_governor_unit(machine, machine_share, gen["pg"]))
            governors += 1
        end
    end

    island_load = sum(
        (load["pd"] for (_, load) in network_data["load"] if load["status"] == 1 && load["load_bus"] in island_buses);
        init=0.0,
    )

    return Dict{String,Any}(
        "inertia" => inertia,
        "governor_gain" => governor_gain,
        "governor_units" => identity.(governor_units),      # a concretely typed vector, for the nadir search
        "damping" => LOAD_DAMPING * island_load,
        "gens" => gens,
        "governors" => governors,
    )
end


# ==================== Nadir limit by search ====================
"""
Total power (pu) of the governor `units` at frequency deviation `df` (pu), advancing each one
forward Euler step. `states` has one column per unit: slow stage, gate and flow deviations (pu).
"""
function step_governor_units!(states, units, df, time_step)
    total_response = 0.0
    for (i, unit) in enumerate(units)
        slow, gate, flow = states[1, i], states[2, i], states[3, i]

        demand = -(unit.fast_share * df + (1 - unit.fast_share) * slow)
        output = (1 + unit.water_ratio) * flow - unit.water_ratio * gate
        total_response += unit.gain * output - unit.turbine_damping * df

        states[1, i] += time_step * (df - slow) / unit.slow_time
        states[2, i] += time_step * (demand - gate) / unit.delay
        states[3, i] += time_step * (gate - flow) / unit.second_delay
    end
    return total_response
end

"""
Lowest frequency (Hz) after the island loses `deficit` (pu) at t = 0, from the SFR model

    2H dΔf/dt = ΣΔPm - D Δf - deficit,    ΔPm from each unit of `step_governor_units!`

integrated with forward Euler over `SFR_DURATION`. Governor limits and deadbands are not
modeled, so the nadir deviation scales linearly with the deficit.
"""
function simulate_frequency_nadir(params, deficit)
    H = params["inertia"]
    D = params["damping"]
    units = params["governor_units"]

    df = 0.0            # frequency deviation, pu
    states = zeros(3, length(units))
    df_min = 0.0
    for _ in 1:round(Int, SFR_DURATION / SFR_TIME_STEP)
        governor_response = step_governor_units!(states, units, df, SFR_TIME_STEP)
        df += SFR_TIME_STEP * (governor_response - D * df - deficit) / (2 * H)
        df_min = min(df_min, df)
    end

    return NOMINAL_FREQUENCY * (1 + df_min)
end

"""
Largest deficit (pu) whose SFR nadir stays at or above `MIN_NADIR_FREQUENCY`. A larger
deficit always gives a deeper nadir, so the crossing is unique and bisection finds it.
The model is symmetric, so the same limit keeps a surplus island's peak equally far above f0.
"""
function search_nadir_limit(params)
    clears_ufls(deficit) = simulate_frequency_nadir(params, deficit) >= MIN_NADIR_FREQUENCY

    # bracket the crossing
    low = 0.0
    high = 1.0
    while clears_ufls(high)
        low = high
        high *= 2
    end

    # bisect it
    while high - low > NADIR_SEARCH_TOLERANCE
        mid = (low + high) / 2
        if clears_ufls(mid)
            low = mid
        else
            high = mid
        end
    end

    return low
end


# ==================== Offline step: limits per island ====================
"""
    add_frequency_security!(network_data, target_lines, dyr_file)

Offline, once per island: compute the RoCoF, quasi-steady-state and nadir limits on each
island's scheduled import and embed them in `network_data["frequency_islands"]`, where the
optimization model reads them. Islands without synchronous inertia are skipped, since the
SFR model does not apply to them.
"""
function add_frequency_security!(network_data, target_lines, dyr_file)
    machines = read_dyr_machine_data(dyr_file)
    frequency_islands = Dict{String,Any}[]

    for island_buses in calc_islands_after_opening(network_data, target_lines)
        boundary_arcs = calc_island_boundary_arcs(network_data, target_lines, island_buses)
        isempty(boundary_arcs) && continue          # not separated by the target lines

        params = calc_island_frequency_params(network_data, island_buses, machines)
        if params["inertia"] == 0.0
            println("Island at bus $(minimum(island_buses)) has no synchronous inertia, no frequency limits added")
            continue
        end

        limits = Dict(
            "rocof" => 2 * params["inertia"] * MAX_ROCOF / NOMINAL_FREQUENCY,
            "qss" => (params["damping"] + params["governor_gain"]) * MAX_QSS_DEVIATION / NOMINAL_FREQUENCY,
            "nadir" => search_nadir_limit(params),
        )

        push!(frequency_islands, merge(params, Dict(
            "buses" => sort(collect(island_buses)),
            "boundary_arcs" => boundary_arcs,
            "limits" => limits,
        )))
    end

    network_data["frequency_islands"] = frequency_islands
end


# ==================== Optimization model ====================
"""
Each island's scheduled import, the power it loses when the boundary opens, stays within
the tightest of its RoCoF, quasi-steady-state and nadir limits, in both directions.
"""
function constraint_island_frequency_security(pm::AbstractPowerModel)
    p = var(pm, :p)
    for island in pm.data["frequency_islands"]
        scheduled_import = sum(-p[arc] for arc in island["boundary_arcs"])
        import_limit = minimum(values(island["limits"]))
        JuMP.@constraint(pm.model, -import_limit <= scheduled_import <= import_limit)
    end
end


# ==================== Report ====================
"Print each island's frequency response, its import limits and the solved scheduled import."
function print_frequency_security(network_data, result)
    base_mva = network_data["baseMVA"]
    to_mw(value) = round(value * base_mva, digits=2)
    sol_branches = result["solution"]["branch"]

    println("---------------------------")
    println("Frequency security (limits on each island's scheduled import)")
    for island in network_data["frequency_islands"]
        limits = island["limits"]

        scheduled_import = 0.0
        for (branch_id, island_bus, _) in island["boundary_arcs"]
            island_end = network_data["branch"][string(branch_id)]["f_bus"] == island_bus ? "pf" : "pt"
            scheduled_import -= sol_branches[string(branch_id)][island_end]
        end

        println("Island at bus $(first(island["buses"])): $(length(island["buses"])) buses, $(island["gens"]) gens ($(island["governors"]) with governor)")
        println("  H = $(round(island["inertia"], digits=3)) s, K = $(round(island["governor_gain"], digits=3)) pu, D = $(round(island["damping"], digits=3)) pu (system base)")
        println("  limits: RoCoF $(to_mw(limits["rocof"])) MW, QSS $(to_mw(limits["qss"])) MW, nadir $(to_mw(limits["nadir"])) MW ($(argmin(limits)) binds)")
        println("  scheduled import: $(to_mw(scheduled_import)) MW")
    end
end
