# Voltage viability of the islands formed at the fixed boundary
# (proposal, "Voltage viability": the loop between the optimizer and the indicator).
#
# The indicator of Tuan et al. (1994) says how close a load bus j is to voltage collapse,
# from 0 (no load) to 1 (collapse):
#   B_j = |1 - Σ_i C_ji V_i / V_j|,    [C] = -[B_LL]^-1 [B_LG]
# i runs over the generator buses that hold their voltage, [B_LL] and [B_LG] are the imaginary
# parts of the island's admittance matrix (load-load and load-generator blocks) and V is the
# predicted island state: the island power flow with the boundary lines removed. A generator at
# its reactive limit no longer holds its voltage, so its bus is moved to the load buses
# (PV -> PQ) and the indicator is computed that way.
#
# One round of the loop (solve_voltage_secure_opf):
#   1. solve the pre-event optimization
#   2. solve each island's power flow with the boundary lines removed
#   3. compute B_j at every load bus; all at or below INDICATOR_THRESHOLD: verified, stop
#   4. otherwise size a shed at the worst bus from ΔB = [T][J]^-1 [ΔP; ΔQ], in pieces that end
#      at the first generator reaching or leaving its reactive limit, where the island state
#      and the matrices are rebuilt
#   5. hand the shed back to the optimization as a lower bound on the shed of those loads
#
# Workflow:
#   loop (run_islanding):     solve_voltage_secure_opf, in place of the single solve
#   model (build_custom_pf):  constraint_voltage_shed_requirement, for loads with "voltage_shed"
#
# This file is included into the PowerModels module by src/prob/opf.jl, so `using PowerModels`
# already exports everything here; do not include it again from the runners.


# ==================== Voltage viability settings ====================
const INDICATOR_THRESHOLD = 0.4         # B_thr, a bus above it is critical (published 0.35 to 0.5, calibrate per system)
const INDICATOR_TARGET = 0.35           # a shed is sized to bring the worst bus here, below the threshold (Tuan, Fig. IV.1)
const MAX_VOLTAGE_ROUNDS = 10           # rounds of the loop between the optimizer and the indicator

# sizing a shed in pieces
const MIN_SHED_PIECE = 0.01             # pu (system base), so a piece gets past the limit event the last one ended at
const MAX_SHED_PIECES = 100             # per island and round

# island power flow (Newton, polar coordinates)
const POWER_FLOW_TOLERANCE = 1e-8       # pu, largest bus power mismatch
const POWER_FLOW_ITERATIONS = 30
const REACTIVE_LIMIT_TOLERANCE = 1e-6   # pu, a generator further than this beyond its reactive limit has reached it
const REACTIVE_LIMIT_PASSES = 20        # power flows re-solved while generators reach or leave their limits


# ==================== Predicted island state ====================
"""
    calc_island_state(opened_network, admittance, island_buses)

One island at the pre-event operating point, ready for its power flow. `opened_network` is the
network with the solution applied and the boundary lines out of service, `admittance` its
admittance matrix. The vectors follow `buses`, and powers are bus totals in pu:

- `Y`: the island's admittance matrix
- `vm`, `va`: bus voltages (pu, rad), starting from the pre-event solution
- `vm_setpoint`: the voltage a generator bus holds, its pre-event voltage
- `pg`, `qg`, `qmin`, `qmax`: generation and its reactive range
- `pd`, `qd`: load
- `has_gen`: an in-service generator sits at the bus
- `holds_voltage`: the generators at the bus hold its voltage (slack and PV buses); false for
  buses without generation and for generators at a reactive limit (PQ buses)
- `slack`: position of the bus that balances the island, its largest generator (Babaei et al., 2021)

Returns `nothing` for an island without a generator that can hold a voltage.
"""
function calc_island_state(opened_network, admittance, island_buses)
    buses = sort(collect(island_buses))
    position = Dict(bus => i for (i, bus) in enumerate(buses))
    bus_count = length(buses)

    vm = [opened_network["bus"][string(bus)]["vm"] for bus in buses]
    va = [opened_network["bus"][string(bus)]["va"] for bus in buses]

    pg = zeros(bus_count)
    qg = zeros(bus_count)
    qmin = zeros(bus_count)
    qmax = zeros(bus_count)
    pmax = zeros(bus_count)
    has_gen = falses(bus_count)
    for (_, gen) in opened_network["gen"]
        gen["gen_status"] != 0 || continue
        haskey(position, gen["gen_bus"]) || continue
        i = position[gen["gen_bus"]]
        pg[i] += gen["pg"]
        qg[i] += gen["qg"]
        qmin[i] += gen["qmin"]
        qmax[i] += gen["qmax"]
        pmax[i] += gen["pmax"]
        has_gen[i] = true
    end

    pd = zeros(bus_count)
    qd = zeros(bus_count)
    for (_, load) in opened_network["load"]
        load["status"] != 0 || continue
        haskey(position, load["load_bus"]) || continue
        i = position[load["load_bus"]]
        pd[i] += load["pd"]
        qd[i] += load["qd"]
    end

    # a generator without a reactive range cannot hold a voltage
    holds_voltage = has_gen .& (qmax .> qmin)
    any(holds_voltage) || return nothing
    slack = argmax(i -> pmax[i], findall(holds_voltage))

    matrix_position = [admittance.bus_to_idx[bus] for bus in buses]
    Y = Matrix(admittance.matrix[matrix_position, matrix_position])

    return (
        buses=buses, Y=Y,
        vm=vm, va=va, vm_setpoint=copy(vm),
        pg=pg, qg=qg, qmin=qmin, qmax=qmax,
        pd=pd, qd=qd,
        has_gen=has_gen, holds_voltage=holds_voltage, slack=slack,
    )
end

"Positions of the buses whose generators hold the voltage (slack and PV buses): the generator buses of the indicator."
find_generator_buses(island) = findall(island.holds_voltage)

"Positions of all the other buses, generators at a reactive limit included (PQ buses): the load buses of the indicator."
find_load_buses(island) = findall(.!island.holds_voltage)

"Positions of the buses whose voltage angle is free: all but the slack."
find_free_angle_buses(island) = setdiff(eachindex(island.buses), island.slack)


# ==================== Island power flow ====================
"""
Derivatives of the island's bus power injections S = V conj(Y V) to the voltage angles and to
the voltage magnitudes of all its buses, as two complex matrices (one row per injection).
"""
function calc_injection_derivatives(island)
    V = island.vm .* cis.(island.va)
    voltage = LinearAlgebra.Diagonal(V)
    direction = LinearAlgebra.Diagonal(cis.(island.va))         # V / |V|
    current = LinearAlgebra.Diagonal(island.Y * V)

    dS_dva = im * voltage * conj(current - island.Y * voltage)
    dS_dvm = voltage * conj(island.Y * direction) + conj(current) * direction
    return dS_dva, dS_dvm
end

"""
Power flow Jacobian [J] of the island for its present generator status. Rows: active power of
every bus but the slack, then reactive power of the load buses. Columns: voltage angles of
the first, then voltage magnitudes of the second.
"""
function calc_power_flow_jacobian(island)
    dS_dva, dS_dvm = calc_injection_derivatives(island)
    free_angle = find_free_angle_buses(island)
    load_buses = find_load_buses(island)
    return [
        real(dS_dva[free_angle, free_angle]) real(dS_dvm[free_angle, load_buses])
        imag(dS_dva[load_buses, free_angle]) imag(dS_dvm[load_buses, load_buses])
    ]
end

"""
Solve the island's power flow by Newton's method for its present generator status. Updates
`vm` and `va`, the slack's `pg` and the `qg` of the buses holding their voltage. Returns true
when it converged.
"""
function solve_newton_power_flow!(island)
    free_angle = find_free_angle_buses(island)
    load_buses = find_load_buses(island)
    scheduled = complex.(island.pg .- island.pd, island.qg .- island.qd)

    for _ in 1:POWER_FLOW_ITERATIONS
        V = island.vm .* cis.(island.va)
        injection = V .* conj.(island.Y * V)
        mismatch = [real.(injection .- scheduled)[free_angle]; imag.(injection .- scheduled)[load_buses]]
        all(isfinite, mismatch) || return false

        if maximum(abs, mismatch; init=0.0) < POWER_FLOW_TOLERANCE
            # outputs the power flow leaves free
            generator_buses = find_generator_buses(island)
            island.pg[island.slack] = real(injection[island.slack]) + island.pd[island.slack]
            island.qg[generator_buses] .= imag.(injection[generator_buses]) .+ island.qd[generator_buses]
            return true
        end

        correction = calc_power_flow_jacobian(island) \ mismatch
        island.va[free_angle] .-= correction[1:length(free_angle)]
        island.vm[load_buses] .-= correction[length(free_angle)+1:end]
    end

    return false
end

"""
Move the generators that reached a reactive limit to the load buses, their output fixed at the
limit (PV -> PQ), and bring back those whose voltage has recovered to its setpoint (PQ -> PV).
The slack keeps holding the island's voltage. Returns true when a status changed.
"""
function update_generator_status!(island)
    changed = false
    for i in findall(island.has_gen)
        i == island.slack && continue
        island.qmax[i] > island.qmin[i] || continue             # no reactive range, never holds a voltage

        if island.holds_voltage[i]
            within_limits = island.qmin[i] - REACTIVE_LIMIT_TOLERANCE <= island.qg[i] <= island.qmax[i] + REACTIVE_LIMIT_TOLERANCE
            within_limits && continue
            island.qg[i] = clamp(island.qg[i], island.qmin[i], island.qmax[i])
            island.holds_voltage[i] = false
        else
            at_upper_limit = island.qg[i] == island.qmax[i]
            recovered = at_upper_limit ? island.vm[i] > island.vm_setpoint[i] : island.vm[i] < island.vm_setpoint[i]
            recovered || continue
            island.vm[i] = island.vm_setpoint[i]
            island.holds_voltage[i] = true
        end
        changed = true
    end
    return changed
end

"""
    solve_island_power_flow!(island)

Predicted state of the island once the boundary lines are open: its power flow, re-solved
until no generator reaches or leaves a reactive limit. Returns true when it solved.
"""
function solve_island_power_flow!(island)
    for _ in 1:REACTIVE_LIMIT_PASSES
        solve_newton_power_flow!(island) || return false
        update_generator_status!(island) || return true
    end
    return solve_newton_power_flow!(island)         # still changing after the last pass: keep that status
end


# ==================== Indicator ====================
"""
    calc_voltage_indicators(island)

Indicator of every load bus of the island in complex form, 1 - Σ_i C_ji V_i / V_j, whose
magnitude is B_j (Tuan et al., eq. II.1), and the matrix [C] = -[B_LL]^-1 [B_LG] (eq. II.2).
The generator buses are those holding their voltage; all the others are load buses.
"""
function calc_voltage_indicators(island)
    generator_buses = find_generator_buses(island)
    load_buses = find_load_buses(island)

    susceptance = imag(island.Y)
    C = -(susceptance[load_buses, load_buses] \ susceptance[load_buses, generator_buses])

    V = island.vm .* cis.(island.va)
    indicators = 1 .- (C * V[generator_buses]) ./ V[load_buses]
    return indicators, C
end

"Largest indicator B_j of the island and the position of its bus (0.0 and 0 for an island without load buses)."
function find_worst_indicator(island)
    load_buses = find_load_buses(island)
    isempty(load_buses) && return 0.0, 0

    indicators = abs.(first(calc_voltage_indicators(island)))
    worst = argmax(indicators)
    return indicators[worst], load_buses[worst]
end


# ==================== Sizing a shed ====================
"""
    calc_shed_response(island, shed_bus)

Linear response of the island to shedding 1 pu of load at `shed_bus` at constant power factor,
ΔQ = ΔP tan φ, for its present generator status (Tuan et al., section III):

- `vm`: voltage magnitude of every bus (pu per pu shed), from [J][Δδ; Δ|V|] = [ΔP; ΔQ]
- `qg`: reactive output of the generators holding their voltage, by bus (pu per pu shed)
- `indicator`: B_j of every load bus (per pu shed), from [ΔB] = [T][Δδ; Δ|V|]
"""
function calc_shed_response(island, shed_bus)
    free_angle = find_free_angle_buses(island)
    generator_buses = find_generator_buses(island)
    load_buses = find_load_buses(island)
    bus_count = length(island.buses)

    # [Δδ; Δ|V|] = [J]^-1 [ΔP; ΔQ]: the shed raises the injection at its bus
    injection_change = zeros(length(free_angle) + length(load_buses))
    injection_change[findfirst(==(shed_bus), free_angle)] = 1.0
    injection_change[length(free_angle)+findfirst(==(shed_bus), load_buses)] = island.qd[shed_bus] / island.pd[shed_bus]
    state_change = calc_power_flow_jacobian(island) \ injection_change
    dva = zeros(bus_count)
    dvm = zeros(bus_count)
    dva[free_angle] = state_change[1:length(free_angle)]
    dvm[load_buses] = state_change[length(free_angle)+1:end]

    # a generator holding its voltage supplies whatever its bus injection becomes
    dS_dva, dS_dvm = calc_injection_derivatives(island)
    dqg = imag(dS_dva * dva + dS_dvm * dvm)

    # indicator B = 1 - (C V_G) / V_L, so dB = -(C dV_G) / V_L + (1 - B) dV_L / V_L, which is the
    # matrix [T] of Tuan et al. (A.1 to A.12) in complex form; its magnitude changes by
    # d|B| = Re(conj(B) dB) / |B| (Babaei et al., eq. 25)
    V = island.vm .* cis.(island.va)
    dV = V .* (dvm ./ island.vm .+ im .* dva)
    indicators, C = calc_voltage_indicators(island)
    d_indicators = -(C * dV[generator_buses]) ./ V[load_buses] .+ (1 .- indicators) .* dV[load_buses] ./ V[load_buses]
    d_magnitudes = real.(conj.(indicators) .* d_indicators) ./ abs.(indicators)

    return (vm=dvm, qg=dqg, indicator=d_magnitudes)
end

"""
Shed (pu) at which the first generator of the island reaches or leaves its reactive limit,
from the linear `response` to that shed; Inf when none does. The response holds up to there.
"""
function calc_shed_to_limit_event(island, response)
    first_event = Inf
    for i in findall(island.has_gen)
        i == island.slack && continue
        island.qmax[i] > island.qmin[i] || continue

        if island.holds_voltage[i]
            # reaches the limit its reactive output is moving towards
            limit = response.qg[i] > 0 ? island.qmax[i] : island.qmin[i]
            shed_to_event = (limit - island.qg[i]) / response.qg[i]
        else
            # leaves its limit when its voltage is back at the setpoint
            shed_to_event = (island.vm_setpoint[i] - island.vm[i]) / response.vm[i]
        end

        shed_to_event > 0 || continue                           # moving away from the event
        first_event = min(first_event, shed_to_event)
    end
    return first_event
end

"""
    size_island_shed!(island)

Step 4 of the loop: shed load in the island, piece by piece, until every indicator is at or
below the threshold (Tuan et al., Fig. IV.2). A piece is shed at the bus with the largest
indicator that still has load, and sized by the linear response to bring the worst indicator
to `INDICATOR_TARGET`. It ends earlier at the load left at the bus, or at the first generator
reaching or leaving its reactive limit. After every piece the island power flow is solved
again, so the next one starts from rebuilt matrices. The island is left in the state after
the shed. Returns the shed at each island bus (pu).
"""
function size_island_shed!(island)
    shed = zeros(length(island.buses))

    for _ in 1:MAX_SHED_PIECES
        load_buses = find_load_buses(island)
        indicators = abs.(first(calc_voltage_indicators(island)))
        worst = argmax(indicators)
        indicators[worst] > INDICATOR_THRESHOLD || break

        # bus to shed at
        with_load = findall(bus -> island.pd[bus] > MIN_SHED_PIECE, load_buses)
        isempty(with_load) && break
        shed_bus = load_buses[with_load[argmax(indicators[with_load])]]

        # size of the piece
        response = calc_shed_response(island, shed_bus)
        response.indicator[worst] < 0 || break                  # a shed there does not lower the worst indicator
        piece = (INDICATOR_TARGET - indicators[worst]) / response.indicator[worst]
        piece = min(piece, calc_shed_to_limit_event(island, response))
        piece = min(max(piece, MIN_SHED_PIECE), island.pd[shed_bus])

        # shed it at constant power factor, then rebuild the island state
        island.qd[shed_bus] -= piece * island.qd[shed_bus] / island.pd[shed_bus]
        island.pd[shed_bus] -= piece
        shed[shed_bus] += piece
        solve_island_power_flow!(island) || break
    end

    return shed
end

"""
    add_voltage_shed_requirement!(network_data, result, island, shed)

Step 5 of the loop: hand the sized `shed` (pu at each island bus) back to the optimization.
Every load at a shed bus gets `"voltage_shed"`, the least share of its demand the next solve
has to shed: what this solve already shed of it, plus the share of the rest that the bus
sheds. A requirement only grows from round to round.
"""
function add_voltage_shed_requirement!(network_data, result, island, shed)
    sol_loads = result["solution"]["load"]
    for (i, load) in network_data["load"]
        haskey(sol_loads, i) || continue
        position = findfirst(==(load["load_bus"]), island.buses)
        position === nothing && continue
        shed[position] > 0 || continue

        bus_load_served = island.pd[position] + shed[position]              # by this solve, pu
        served_share = sol_loads[i]["status"] * (1 - shed[position] / bus_load_served)
        load["voltage_shed"] = max(get(load, "voltage_shed", 0.0), 1 - served_share)
    end
end


# ==================== Optimization model ====================
"Every load with a shed sized by the voltage step sheds at least that share of its demand."
function constraint_voltage_shed_requirement(pm::AbstractPowerModel)
    z_demand = var(pm, :z_demand)
    for (i, load) in ref(pm, :load)
        haskey(load, "voltage_shed") || continue
        JuMP.@constraint(pm.model, z_demand[i] <= 1 - load["voltage_shed"])
    end
end


# ==================== Report ====================
"""
The predicted state of a checked island, as data (pu): its first bus, bus counts, the buses of
its generators at the upper and at the lower reactive limit, its slack bus with P and Q, and its
three largest indicators (value, bus, V, load). `"shed"` is filled by the loop when one is sized.
"""
function calc_island_voltage(island)
    limited = findall(island.has_gen .& .!island.holds_voltage)
    at_upper_limit = [island.buses[i] for i in limited if island.qg[i] >= island.qmax[i]]
    at_lower_limit = [island.buses[i] for i in limited if island.qg[i] < island.qmax[i]]
    slack = island.slack

    largest_indicators = Dict{String,Any}[]
    load_buses = find_load_buses(island)
    if !isempty(load_buses)
        indicators = abs.(first(calc_voltage_indicators(island)))
        for k in sortperm(indicators, rev=true)[1:min(3, end)]
            bus = load_buses[k]
            push!(largest_indicators, Dict{String,Any}(
                "value" => indicators[k],
                "bus" => island.buses[bus],
                "vm" => island.vm[bus],
                "pd" => island.pd[bus],
            ))
        end
    end

    return Dict{String,Any}(
        "status" => "checked",
        "bus" => first(island.buses),
        "n_buses" => length(island.buses),
        "n_with_generation" => count(island.has_gen),
        "n_holding_voltage" => count(island.holds_voltage),
        "at_upper_limit" => at_upper_limit,
        "at_lower_limit" => at_lower_limit,
        "slack_bus" => island.buses[slack],
        "slack_pg" => island.pg[slack],
        "slack_qg" => island.qg[slack],
        "largest_indicators" => largest_indicators,
        "shed" => nothing,
    )
end

"Print the predicted state of an island (`calc_island_voltage`): its generators at a reactive limit, its slack and its largest indicators."
function print_island_voltage(island_voltage, base_mva)
    to_mw(value) = round(value * base_mva, digits=2)
    list(buses) = isempty(buses) ? "none" : join(buses, ", ")

    println("Island at bus $(island_voltage["bus"]): $(island_voltage["n_buses"]) buses, $(island_voltage["n_with_generation"]) with generation, $(island_voltage["n_holding_voltage"]) holding their voltage")
    println("  generators at a reactive limit: upper $(list(island_voltage["at_upper_limit"])); lower $(list(island_voltage["at_lower_limit"]))")
    println("  slack bus $(island_voltage["slack_bus"]): P = $(to_mw(island_voltage["slack_pg"])) MW, Q = $(to_mw(island_voltage["slack_qg"])) Mvar")
    for indicator in island_voltage["largest_indicators"]
        println("  indicator $(round(indicator["value"], digits=3)) at bus $(indicator["bus"]) (V = $(round(indicator["vm"], digits=3)) pu, load $(to_mw(indicator["pd"])) MW)")
    end
end

"""
The shed sized in an island, as data (pu): `"sheds"` (bus, shed, and the load it was taken from)
and the worst indicator it leaves with its bus; no sheds and no indicator when none could be sized.
"""
function calc_island_shed(island, shed)
    sheds = Dict{String,Any}[]
    for i in findall(>(0), shed)
        push!(sheds, Dict{String,Any}("bus" => island.buses[i], "shed" => shed[i], "of" => island.pd[i] + shed[i]))
    end
    isempty(sheds) && return Dict{String,Any}("sheds" => sheds, "indicator_after" => nothing, "indicator_after_bus" => nothing)

    worst_indicator, worst_bus = find_worst_indicator(island)
    return Dict{String,Any}(
        "sheds" => sheds,
        "indicator_after" => worst_indicator,
        "indicator_after_bus" => island.buses[worst_bus],
    )
end

"Print the shed sized in an island (`calc_island_shed`, MW at each bus) and the worst indicator it leaves."
function print_island_shed(island_shed, base_mva)
    to_mw(value) = round(value * base_mva, digits=2)
    if isempty(island_shed["sheds"])
        println("  no shed could be sized")
        return
    end

    for shed in island_shed["sheds"]
        println("  shed sized at bus $(shed["bus"]): $(to_mw(shed["shed"])) MW of $(to_mw(shed["of"])) MW")
    end
    println("  indicator after that shed: $(round(island_shed["indicator_after"], digits=3)) at bus $(island_shed["indicator_after_bus"])")
end


# ==================== The loop between the optimizer and the indicator ====================
"""
    solve_voltage_secure_opf(network_data, model_type, optimizer, target_lines)

Solve the pre-event optimization (`solve_custom_opf`) inside the voltage loop: after each
solve, every island left by opening `target_lines` is checked with the voltage indicator, and
where a bus is above the threshold a preemptive shed is sized and handed back to the next
solve as `load["voltage_shed"]`. Objectives without load shedding are only checked.

Returns the result of the last solve, with `result["voltage_security"]`: `"verified"`,
`"rounds"`, the `"worst_indicator"` of the last round, and `"details"`, one entry per round
(round, optimization status, threshold, and each island: `calc_island_voltage` with its worst
indicator and the `calc_island_shed` sized there, or only its status when it was not checked).
"""
function solve_voltage_secure_opf(network_data, model_type, optimizer, target_lines)
    base_mva = network_data["baseMVA"]
    can_shed = contains(network_data["objective"], "shed")
    for (_, load) in network_data["load"]
        delete!(load, "voltage_shed")               # requirements of an earlier run
    end

    # the boundary is fixed, so the islands are known before the first solve
    islands = Set{Int}[]
    for island_buses in calc_islands_after_opening(network_data, target_lines)
        isempty(calc_island_boundary_arcs(network_data, target_lines, island_buses)) && continue     # not separated by the target lines
        push!(islands, island_buses)
    end

    result = Dict{String,Any}()
    details = Dict{String,Any}[]                     # one entry per round, kept across the solves
    for round in 1:MAX_VOLTAGE_ROUNDS
        # 1. solve the pre-event optimization
        result = solve_custom_opf(network_data, model_type, optimizer)

        # 2. predict the island states: the solved network with the boundary lines removed
        opened_network = deepcopy(network_data)
        update_data!(opened_network, result["solution"])
        for line in target_lines
            opened_network["branch"][string(line)]["br_status"] = 0
        end
        admittance = calc_admittance_matrix(opened_network)

        println("---------------------------")
        println("Voltage viability, round $round: optimization $(result["termination_status"]), indicator threshold $INDICATOR_THRESHOLD")
        verified = true
        shed_handed_back = false
        worst_indicator = 0.0
        round_islands = Dict{String,Any}[]
        for island_buses in islands
            island = calc_island_state(opened_network, admittance, island_buses)
            if island === nothing
                println("Island at bus $(minimum(island_buses)) has no generator to hold its voltage, not checked")
                push!(round_islands, Dict{String,Any}("status" => "no_generator", "bus" => minimum(island_buses), "n_buses" => length(island_buses)))
                continue
            end
            if !solve_island_power_flow!(island)
                println("Island at bus $(first(island.buses)): the island power flow did not solve, not verified")
                push!(round_islands, Dict{String,Any}("status" => "power_flow_failed", "bus" => first(island.buses), "n_buses" => length(island.buses)))
                verified = false
                continue
            end

            # 3. indicator at every load bus of the island
            island_voltage = calc_island_voltage(island)
            print_island_voltage(island_voltage, base_mva)
            push!(round_islands, island_voltage)
            island_indicator, _ = find_worst_indicator(island)
            island_voltage["worst_indicator"] = island_indicator
            worst_indicator = max(worst_indicator, island_indicator)
            island_indicator <= INDICATOR_THRESHOLD && continue
            verified = false
            can_shed || continue

            # 4. size a shed at the worst buses
            shed = size_island_shed!(island)
            island_shed = calc_island_shed(island, shed)
            print_island_shed(island_shed, base_mva)
            island_voltage["shed"] = island_shed

            # 5. hand it back to the optimization
            add_voltage_shed_requirement!(network_data, result, island, shed)
            shed_handed_back = shed_handed_back || any(>(0), shed)
        end

        push!(details, Dict{String,Any}(
            "round" => round,
            "termination_status" => string(result["termination_status"]),
            "indicator_threshold" => INDICATOR_THRESHOLD,
            "islands" => round_islands,
        ))
        result["voltage_security"] = Dict("verified" => verified, "rounds" => round, "worst_indicator" => worst_indicator, "details" => details)
        if verified
            println("Voltage verified in round $round")
            break
        end
        if !shed_handed_back
            println("Voltage not verified, and no shed to hand back to the optimization")
            break
        end
        round == MAX_VOLTAGE_ROUNDS && println("Voltage not verified after $round rounds")
    end

    return result
end
