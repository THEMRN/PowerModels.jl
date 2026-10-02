using PowerModels
using Ipopt
using JuMP
using JSON3
using XLSX

include("excel_generator.jl")
include("calc_line_flow.jl")
include("utils.jl")


const PRE_EVENT_NW_ID = 1


function load_config(path::String)
    raw = read(path, String)
    return JSON3.read(raw, Dict{String,Any})
end


function linearized_absolute_value(pm::AbstractPowerModel, expr; base_name::String)
    t = JuMP.@variable(pm.model, base_name = base_name, lower_bound = 0.0)
    JuMP.@constraint(pm.model, expr <= t)
    JuMP.@constraint(pm.model, expr >= -t)
    return t
end


function target_branch_flow_terms(pm::AbstractPowerModel, nw::Int, branch_id::Int; is_ac::Bool=false)
    branch = ref(pm, nw, :branch, branch_id)
    f_bus = branch["f_bus"]
    t_bus = branch["t_bus"]

    flow_bus_from = f_bus
    flow_bus_to = t_bus

    target_zone_buses = Set(Int.(get(pm.data, "target_zone_buses", Int[])))
    if !isempty(target_zone_buses) && !(f_bus in target_zone_buses) && (t_bus in target_zone_buses)
        flow_bus_from = t_bus
        flow_bus_to = f_bus
    end

    p_term = var(pm, nw, :p)[(branch_id, flow_bus_from, flow_bus_to)]
    q_term = is_ac ? var(pm, nw, :q)[(branch_id, flow_bus_from, flow_bus_to)] : 0.0

    return p_term, q_term
end


function branch_flow_penalty(pm::AbstractPowerModel, nw::Int, branch_ids, p_model::String; is_ac::Bool, abs_var_base_name::String)
    p_sum = JuMP.AffExpr()
    q_sum = JuMP.AffExpr()
    p_penalty = JuMP.AffExpr()
    q_penalty = JuMP.AffExpr()

    for branch_id in branch_ids
        p_term, q_term = target_branch_flow_terms(pm, nw, Int(branch_id); is_ac=is_ac)
        if p_model == "abs_sum"
            p_sum += p_term
            q_sum += q_term
        elseif p_model == "squared"
            p_penalty += p_term^2
            q_penalty += q_term^2
        elseif p_model == "combined"
            p_sum += p_term
            q_penalty += q_term^2
        else
            error("unknown flow model: $p_model")
        end
    end

    if p_model == "abs_sum"
        abs_p_sum = linearized_absolute_value(pm, p_sum; base_name="$(abs_var_base_name)_p")
        abs_q_sum = linearized_absolute_value(pm, q_sum; base_name="$(abs_var_base_name)_q")
        return abs_p_sum + abs_q_sum
    elseif p_model == "squared"
        return p_penalty + q_penalty
    elseif p_model == "combined"
        abs_p_sum = linearized_absolute_value(pm, p_sum; base_name=abs_var_base_name)
        return abs_p_sum + q_penalty
    end
end


function variable_load_shed_split(pm::AbstractPowerModel; nw::Int=nw_id_default, report::Bool=true)
    # Relaxed by default, no binary option (compared to standard method of PowerModels.jl)
    planned = var(pm, nw)[:z_planned_shed] = JuMP.@variable(
        pm.model,
        [i in ids(pm, nw, :load)],
        base_name = "$(nw)_z_planned_shed",
        lower_bound = 0.0,
        upper_bound = 1.0,
        start = 0.0,
    )
    forced = var(pm, nw)[:z_forced_shed] = JuMP.@variable(
        pm.model,
        [i in ids(pm, nw, :load)],
        base_name = "$(nw)_z_forced_shed",
        lower_bound = 0.0,
        upper_bound = 1.0,
        start = 0.0,
    )

    # Constraint to ensure that the sum of planned and forced load shedding does not exceed 1.0
    for i in ids(pm, nw, :load)
        JuMP.@constraint(pm.model, planned[i] + forced[i] <= 1.0)
    end

    if report
        served = Dict(i => 1.0 - planned[i] - forced[i] for i in ids(pm, nw, :load))
        sol_component_value(pm, nw, :load, :status, ids(pm, nw, :load), served)
        sol_component_value(pm, nw, :load, :planned_shed, ids(pm, nw, :load), planned)
        sol_component_value(pm, nw, :load, :forced_shed, ids(pm, nw, :load), forced)
        sol_component_value(pm, nw, :load, :pd, ids(pm, nw, :load), Dict(i => served[i] * ref(pm, nw, :load, i)["pd"] for i in ids(pm, nw, :load)))
        sol_component_value(pm, nw, :load, :qd, ids(pm, nw, :load), Dict(i => served[i] * ref(pm, nw, :load, i)["qd"] for i in ids(pm, nw, :load)))
    end
end


function constraint_power_balance_split_ls(pm::AbstractACPModel, bus_id::Int; nw::Int=nw_id_default)
    vm = var(pm, nw, :vm, bus_id)
    p = get(var(pm, nw), :p, Dict())
    q = get(var(pm, nw), :q, Dict())
    pg = get(var(pm, nw), :pg, Dict())
    qg = get(var(pm, nw), :qg, Dict())
    p_dc = get(var(pm, nw), :p_dc, Dict())
    q_dc = get(var(pm, nw), :q_dc, Dict())
    ps = get(var(pm, nw), :ps, Dict())
    qs = get(var(pm, nw), :qs, Dict())
    z_shunt = get(var(pm, nw), :z_shunt, Dict())
    planned = get(var(pm, nw), :z_planned_shed, Dict())
    forced = get(var(pm, nw), :z_forced_shed, Dict())

    bus_arcs = ref(pm, nw, :bus_arcs, bus_id)
    bus_arcs_dc = ref(pm, nw, :bus_arcs_dc, bus_id)
    bus_gens = ref(pm, nw, :bus_gens, bus_id)
    bus_storage = ref(pm, nw, :bus_storage, bus_id)
    bus_loads = ref(pm, nw, :bus_loads, bus_id)
    bus_shunts = ref(pm, nw, :bus_shunts, bus_id)

    JuMP.@constraint(pm.model,
        sum(p[a] for a in bus_arcs)
        +
        sum(p_dc[a] for a in bus_arcs_dc)
        ==
        sum(pg[g] for g in bus_gens)
        -
        sum(ps[s] for s in bus_storage)
        -
        sum(ref(pm, nw, :load, l, "pd") * (1.0 - planned[l] - forced[l]) for l in bus_loads)
        -
        sum(ref(pm, nw, :shunt, s, "gs") * z_shunt[s] for s in bus_shunts) * vm^2
    )
    JuMP.@constraint(pm.model,
        sum(q[a] for a in bus_arcs)
        +
        sum(q_dc[a] for a in bus_arcs_dc)
        ==
        sum(qg[g] for g in bus_gens)
        -
        sum(qs[s] for s in bus_storage)
        -
        sum(ref(pm, nw, :load, l, "qd") * (1.0 - planned[l] - forced[l]) for l in bus_loads)
        +
        sum(ref(pm, nw, :shunt, s, "bs") * z_shunt[s] for s in bus_shunts) * vm^2
    )
end


function voltage_penalty(pm::AbstractPowerModel, post_nw_ids)
    penalty = JuMP.AffExpr()
    voltage_weights = Dict{String,Float64}(string(k) => Float64(v) for (k, v) in get(pm.data, "voltage_weights", Dict()))
    default_weight = Float64(get(pm.data, "voltage_weight_floor", 1.0))
    desired_vmin = Float64(get(pm.data, "voltage_penalty_vmin", 0.95))
    desired_vmax = Float64(get(pm.data, "voltage_penalty_vmax", 1.05))

    for nw in post_nw_ids
        for bus_id in ids(pm, nw, :bus)
            vm = var(pm, nw, :vm, bus_id)
            low_slack = JuMP.@variable(pm.model, base_name = "$(nw)_vm_low_slack_$(bus_id)", lower_bound = 0.0)
            high_slack = JuMP.@variable(pm.model, base_name = "$(nw)_vm_high_slack_$(bus_id)", lower_bound = 0.0)
            JuMP.@constraint(pm.model, desired_vmin - vm <= low_slack)
            JuMP.@constraint(pm.model, vm - desired_vmax <= high_slack)

            weight = get(voltage_weights, string(bus_id), default_weight)
            penalty += weight * (low_slack + high_slack)
        end
    end

    return penalty
end


function load_shed_penalties(pm::AbstractPowerModel)
    planned_penalty = JuMP.AffExpr()
    forced_penalty = JuMP.AffExpr()

    for (nw, nw_ref) in nws(pm)
        planned = var(pm, nw, :z_planned_shed)
        forced = var(pm, nw, :z_forced_shed)
        for (load_id, load) in nw_ref[:load]
            pd = abs(load["pd"])
            planned_penalty += get(load, "shed_penalty", 1.0) * pd * planned[load_id]
            forced_penalty += pd * forced[load_id]
        end
    end

    return planned_penalty, forced_penalty
end


function add_feedback_coupling_constraints(pm::AbstractPowerModel)
    # Find pre-event network and its generators and loads
    pre_nw = Int(get(pm.data, "pre_nw_id", PRE_EVENT_NW_ID))
    pre_gens = Set(ids(pm, pre_nw, :gen))
    pre_loads = Set(ids(pm, pre_nw, :load))

    # Set forced load shedding to 0.0 for pre-event network
    # It is only a post-event feasibility relief variable
    forced_pre = var(pm, pre_nw, :z_forced_shed)
    for load_id in pre_loads
        JuMP.@constraint(pm.model, forced_pre[load_id] == 0.0)
    end

    for nw in setdiff(nw_ids(pm), [pre_nw]) # Iterate over all post-event networks

        # pg of generators must stay the same pre and post event
        # Note that qg and vm are coupled (should we couple them?)
        for gen_id in intersect(pre_gens, Set(ids(pm, nw, :gen)))
            JuMP.@constraint(pm.model, var(pm, nw, :pg, gen_id) == var(pm, pre_nw, :pg, gen_id))
        end

        # planned load shedding must be the same pre and post event
        # Each load shed may penalized more than once, in each network
        planned_post = var(pm, nw, :z_planned_shed)
        planned_pre = var(pm, pre_nw, :z_planned_shed)
        for load_id in intersect(pre_loads, Set(ids(pm, nw, :load)))
            JuMP.@constraint(pm.model, planned_post[load_id] == planned_pre[load_id])
        end
    end
end


function objective_feedback_islanding(pm::AbstractPowerModel)
    alpha = Float64(get(pm.data, "alpha", 1.0))
    beta = Float64(get(pm.data, "beta", 1.0))
    gamma = Float64(get(pm.data, "gamma", 1.0))
    kappa = Float64(get(pm.data, "kappa", 1.0e6))
    pre_nw = Int(get(pm.data, "pre_nw_id", PRE_EVENT_NW_ID))
    post_nw_ids = setdiff(nw_ids(pm), [pre_nw])
    target_ids = Int.(pm.data["target_ids"])
    flow_model = string(pm.data["p_model"])
    is_ac = string(pm.data["opf_model"]) == "AC"

    flow = branch_flow_penalty(pm, pre_nw, target_ids, flow_model; is_ac=is_ac, abs_var_base_name="pre_event_flow")
    vpen = voltage_penalty(pm, post_nw_ids)
    planned_shed, forced_shed = load_shed_penalties(pm)

    JuMP.@objective(pm.model, Min, alpha * flow + beta * vpen + gamma * planned_shed + kappa * forced_shed)
end


function build_feedback_islanding_opf(pm::AbstractPowerModel)
    for (nw, _) in nws(pm)
        # what do variables do?
        variable_bus_voltage(pm, nw=nw)
        variable_gen_power(pm, nw=nw)
        variable_branch_power(pm, nw=nw)
        variable_dcline_power(pm, nw=nw)
        # variable_load_power_factor(pm, nw=nw; relax=true) # Not need this anymore, used split method instead
        variable_load_shed_split(pm, nw=nw)  # Includes embedded constraint to ensure sum of planned and forced <= 1.0
        variable_shunt_admittance_factor(pm; nw=nw, relax=true)

        # constraints
        constraint_model_voltage(pm, nw=nw)  # Does nothing, place holder for consistency

        for bus_id in ids(pm, :ref_buses, nw=nw)
            constraint_theta_ref(pm, bus_id, nw=nw)
        end

        for bus_id in ids(pm, :bus, nw=nw)
            # split vs non-split
            constraint_power_balance_split_ls(pm, bus_id, nw=nw)
        end

        for branch_id in ids(pm, :branch, nw=nw)
            constraint_ohms_yt_from(pm, branch_id, nw=nw)
            constraint_ohms_yt_to(pm, branch_id, nw=nw)
            constraint_voltage_angle_difference(pm, branch_id, nw=nw)
            constraint_thermal_limit_from(pm, branch_id, nw=nw)
            constraint_thermal_limit_to(pm, branch_id, nw=nw)
        end

        for dcline_id in ids(pm, :dcline, nw=nw)
            constraint_dcline_power_losses(pm, dcline_id, nw=nw)
        end
    end

    # new constraint: feedback coupling constraints
    add_feedback_coupling_constraints(pm)

    # objective function
    objective_feedback_islanding(pm)
end


function active_bus_ids(network_data)
    return Set(Int(bus["bus_i"]) for (_, bus) in network_data["bus"] if Int(get(bus, "bus_type", 1)) != 4)
end


function build_opened_graph(network_data, target_lines)
    target_set = Set(string.(target_lines))         # Lookup for lines to skip
    graph = Dict{Int,Set{Int}}()

    for (_, bus) in network_data["bus"]
        bus_id = Int(bus["bus_i"])
        if Int(get(bus, "bus_type", 1)) != 4       # Only include active buses
            graph[bus_id] = Set{Int}()             # Initialize empty neighbor set for this bus
        end
    end

    for (branch_id, branch) in network_data["branch"]
        get(branch, "br_status", 1) == 0 && continue   # Skip inactive branches (offline by default)
        branch_id in target_set && continue            # Skip target lines (opened lines)

        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])
        haskey(graph, f_bus) || continue                 # Skip branches if either end point is not in the graph
        haskey(graph, t_bus) || continue                 # Skip branches if either end point is not in the graph
        push!(graph[f_bus], t_bus)                       # Add bidirectional connection
        push!(graph[t_bus], f_bus)                       # Add bidirectional connection
    end

    return graph
end


function connected_components_from_graph(graph::Dict{Int,Set{Int}})
    # Use BFS to find connected components
    seen = Set{Int}()                   # Track visited buses
    components = Vector{Vector{Int}}()  # Store list of islands (connected components)

    for start in sort(collect(keys(graph)))    # Iterate over all buses in the graph
        start in seen && continue              # Skip if already visited (already in an island)
        queue = [start]                        # Initialize BFS queue
        component = Int[]                      # Initialize current island (a new island group)
        push!(seen, start)                     # Mark starting bus as visited

        while !isempty(queue)                 # Explore all buses in the current island
            bus = popfirst!(queue)            # Get next bus from queue
            push!(component, bus)             # Add it to current island
            for neighbor in graph[bus]        # Check all of its neighbors
                if !(neighbor in seen)        # If neighbor is not visited
                    push!(seen, neighbor)     # Mark neighbor as visited
                    push!(queue, neighbor)    # Add neighbor to queue
                end
            end
        end

        push!(components, sort(component))
    end

    return components
end


function component_has_active_load_and_gen(network_data, component::Vector{Int})
    bus_set = Set(component)
    has_gen = any(get(gen, "gen_status", 1) != 0 && Int(gen["gen_bus"]) in bus_set for (_, gen) in network_data["gen"]) # Check if any generators in the component are active
    has_load = any(get(load, "status", 1) != 0 && Int(load["load_bus"]) in bus_set && abs(get(load, "pd", 0.0)) > 0.0 for (_, load) in network_data["load"]) # Check if any loads in the component are active
    return has_gen && has_load
end


function detect_post_event_islands(network_data, target_lines)
    graph = build_opened_graph(network_data, target_lines)                 # Build graph of the network with target lines opened
    components = connected_components_from_graph(graph)                    # Find connected components in the graph
    # Filter out components that do not have active load and generation
    components = [component for component in components if component_has_active_load_and_gen(network_data, component)]
    sort!(components, by=component -> (length(component), first(component)), rev=true)
    length(components) >= 2 || error("Opening target branches produced fewer than two active islands.")
    return components
end


function set_island_reference_bus!(network_data, island_buses::Set{Int})
    active_gen_buses = sort(unique(collect(
        Int(gen["gen_bus"])                           # Extract bus ID
        for (_, gen) in network_data["gen"]           # Loop through generators
        if get(gen, "gen_status", 1) != 0 &&          # Only if generator is ON
        Int(gen["gen_bus"]) in island_buses           # Only if it's in this island
    )))
    if isempty(active_gen_buses)
        error("Island $(sort(collect(island_buses))) has no active generator; post-event AC OPF cannot assign a reference bus.")
    end

    existing_refs = sort(collect(
        Int(bus["bus_i"])                           # Extract bus ID
        for (_, bus) in network_data["bus"]         # Loop through buses
        if Int(get(bus, "bus_type", 1)) == 3 &&     # Only if bus is a reference bus
        Int(bus["bus_i"]) in island_buses           # Only if it's in this island
    ))

    # If no existing reference bus, use the first active generator bus
    # Otherwise, use the first existing reference bus
    ref_bus = isempty(existing_refs) ? first(active_gen_buses) : first(existing_refs)
    active_gen_bus_set = Set(active_gen_buses)

    for (_, bus) in network_data["bus"]
        bus_id = Int(bus["bus_i"])
        bus_id in island_buses || continue
        if bus_id == ref_bus        # Set the chosen reference bus to type 3
            bus["bus_type"] = 3
        elseif Int(get(bus, "bus_type", 1)) == 3
            bus["bus_type"] = bus_id in active_gen_bus_set ? 2 : 1  # Demote other bus types 3 if exists
            # elseif Int(get(bus, "bus_type", 1)) == 4
            #     bus["bus_type"] = bus_id in active_gen_bus_set ? 2 : 1
        end
    end

    return ref_bus
end


function deactivate_outside_island!(network_data, island_component, target_lines)
    island_buses = Set(Int.(island_component))
    target_set = Set(string.(target_lines))

    for (_, bus) in network_data["bus"]
        if !(Int(bus["bus_i"]) in island_buses)
            bus["bus_type"] = 4
        end
    end

    for (branch_id, branch) in network_data["branch"]
        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])
        if branch_id in target_set || !(f_bus in island_buses && t_bus in island_buses)
            branch["br_status"] = 0
        end
    end

    for (_, gen) in network_data["gen"]
        if !(Int(gen["gen_bus"]) in island_buses)
            gen["gen_status"] = 0
        end
    end

    for (_, load) in network_data["load"]
        if !(Int(load["load_bus"]) in island_buses)
            load["status"] = 0
        end
    end

    for (_, shunt) in get(network_data, "shunt", Dict())
        if !(Int(shunt["shunt_bus"]) in island_buses)
            shunt["status"] = 0
        end
    end

    for (_, dcline) in get(network_data, "dcline", Dict())
        if !(Int(dcline["f_bus"]) in island_buses && Int(dcline["t_bus"]) in island_buses)
            dcline["br_status"] = 0
        end
    end

    ref_bus = set_island_reference_bus!(network_data, island_buses)
    return ref_bus
end


function build_feedback_multinetwork_data(base_network_data, target_lines; voltage_weights=Dict{String,Float64}(), alpha=1.0, beta=1.0, gamma=1.0, kappa=1.0e6, voltage_weight_floor=1.0, voltage_penalty_vmin=0.95, voltage_penalty_vmax=1.05)
    islands = detect_post_event_islands(base_network_data, target_lines)
    mn_data = Dict{String,Any}(
        "name" => "$(get(base_network_data, "name", "case")) feedback islanding",
        "per_unit" => true,
        "multinetwork" => true,
        "nw" => Dict{String,Any}(),
        "pre_nw_id" => PRE_EVENT_NW_ID,
        "target_ids" => target_lines,
        "opf_model" => get(base_network_data, "opf_model", "AC"),
        "p_model" => get(base_network_data, "p_model", "combined"),
        "alpha" => alpha,
        "beta" => beta,
        "gamma" => gamma,
        "kappa" => kappa,
        "voltage_weights" => voltage_weights,
        "voltage_weight_floor" => voltage_weight_floor,
        "voltage_penalty_vmin" => voltage_penalty_vmin,
        "voltage_penalty_vmax" => voltage_penalty_vmax,
    )

    if haskey(base_network_data, "target_zone_buses")
        mn_data["target_zone_buses"] = base_network_data["target_zone_buses"]
    end

    pre_network = deepcopy(base_network_data)
    for key in ["objective", "target_ids", "opf_model", "p_model", "lambda", "target_zone_buses"]
        delete!(pre_network, key)
    end
    delete!(pre_network, "multinetwork")
    delete!(pre_network, "per_unit")
    mn_data["nw"][string(PRE_EVENT_NW_ID)] = pre_network

    for (idx, island) in enumerate(islands)
        island_network = deepcopy(base_network_data)
        for key in ["objective", "target_ids", "opf_model", "p_model", "lambda", "target_zone_buses"]
            delete!(island_network, key)
        end
        delete!(island_network, "multinetwork")
        delete!(island_network, "per_unit")
        ref_bus = deactivate_outside_island!(island_network, island, target_lines)
        island_network["name"] = "post_event_island_$(idx)"
        island_network["island_buses"] = island
        island_network["reference_bus"] = ref_bus
        mn_data["nw"][string(PRE_EVENT_NW_ID + idx)] = island_network
        println("Post-event island $(idx): $(length(island)) buses, reference bus $(ref_bus)")
    end

    return mn_data
end


function write_line_outage_file(network_data, target_lines, output_dir)
    outages = Vector{Dict{String,Any}}()
    for branch_id in target_lines
        branch = network_data["branch"][string(branch_id)]
        src = branch["source_id"]
        line_type = src[1]
        id_idx = line_type == "branch" ? 4 : 5
        push!(outages, Dict(
            "from" => src[2],
            "to" => src[3],
            "id" => src[id_idx],
        ))
    end

    line_outage_file = joinpath(output_dir, "line_outage.json")
    open(line_outage_file, "w") do io
        JSON3.write(io, outages)
    end
    println("Line outage file created: $line_outage_file")
    return line_outage_file
end


function copy_dyr_file(case_files, output_dir, case_name, label)
    if case_files.dyr === nothing
        println("No dyr file found, skipping dynamic simulation.")
        return ""
    end

    dest = joinpath(output_dir, "$(case_name)_$(label).dyr")
    cp(case_files.dyr, dest, force=true)
    println("Dyr file copied: $dest")
    return dest
end


function export_solution_for_psse(network_data, result, output_dir, case_name, label)
    export_data = deepcopy(network_data)
    PowerModels.update_data!(export_data, result["solution"])
    pti_network_data = prepare_for_pti_export(export_data)

    raw_file = joinpath(output_dir, "$(case_name)_$(label).raw")
    PowerModels.export_pti(raw_file, pti_network_data)
    println("Raw file created: $raw_file")

    excel_file = joinpath(output_dir, "pm_res_$(label)_$(get_timestamp()).xlsx")
    create_excel_report(result, export_data, excel_file, powerworld=true)
    println("Excel file created: $excel_file")

    return raw_file, excel_file, export_data
end


function run_dynamic2(raw_file, dyr_file, excel_file)
    if isempty(dyr_file)
        println("Skipping dynamic2.py because no DYR file is available.")
        return nothing
    end

    python_script = joinpath(@__DIR__, "psse_scripts", "dynamic2.py")
    println("Running dynamic2.py...")
    run(`python $python_script $raw_file $dyr_file $excel_file`)

    stats_file = joinpath(dirname(raw_file), "voltage_stats.json")
    return isfile(stats_file) ? stats_file : nothing
end


function read_voltage_weights(stats_file; base_weight=1.0, feedback_gain=100.0)
    weights = Dict{String,Float64}()
    stats_file === nothing && return weights
    isfile(stats_file) || return weights

    stats = JSON3.read(read(stats_file, String), Dict{String,Any})
    buses = get(stats, "buses", Dict())
    for (bus, record) in buses
        violation = Float64(get(record, "worst_violation", 0.0))
        weights[string(bus)] = base_weight + feedback_gain * violation
    end

    return weights
end


function print_voltage_stats_summary(stats_file, label)
    if stats_file === nothing || !isfile(stats_file)
        println("$label voltage stats: unavailable")
        return
    end

    stats = JSON3.read(read(stats_file, String), Dict{String,Any})
    summary = get(stats, "summary", Dict())
    wtvsi = get(stats, "wtvsi", Dict())["wtvsi"]
    println(
        "$label voltage stats: outside band=$(get(summary, "outside_band_count", "N/A")), " *
        "worst bus=$(get(summary, "worst_bus", "N/A")), " *
        "worst violation=$(get(summary, "worst_violation", "N/A")), " *
        "WTVSI=$(wtvsi)"
    )
end


function extract_pre_event_result(result)
    pre_solution = deepcopy(result["solution"]["nw"][string(PRE_EVENT_NW_ID)])
    extracted = deepcopy(result)
    extracted["solution"] = pre_solution
    return extracted
end


function solve_feedback_opf(network_data, power_model, optimizer, target_lines, voltage_weights; alpha, beta, gamma, kappa, voltage_weight_floor, voltage_penalty_vmin, voltage_penalty_vmax)
    mn_data = build_feedback_multinetwork_data(
        network_data,
        target_lines;
        voltage_weights=voltage_weights,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        kappa=kappa,
        voltage_weight_floor=voltage_weight_floor,
        voltage_penalty_vmin=voltage_penalty_vmin,
        voltage_penalty_vmax=voltage_penalty_vmax,
    )

    return PowerModels.solve_model(mn_data, power_model, optimizer, build_feedback_islanding_opf; multinetwork=true)
end

println("******************************************************************************")
println("Starting islanding2 workflow...")
println("******************************************************************************")

# ==================== Configuration Mode =====================
use_config_file = false
config_file_path = joinpath(@__DIR__, "config.json")
# =============================================================

if use_config_file
    println("Loading configuration from: $config_file_path")
    cfg = load_config(config_file_path)

    src_case_path = cfg["src_case_path"]
    run_psse = get(cfg, "run_psse", true)
    case_files = find_case_files(src_case_path; require_dyr=run_psse)
    case_name = basename(src_case_path)
    PowerModels.silence()
    network_data = PowerModels.parse_file(case_files.raw, import_all=true)
    modified_network_data = deepcopy(network_data)

    objective = get(cfg, "objective", "flow")
    bus_pairs = [(Int(p[1]), Int(p[2])) for p in cfg["target_bus_pairs"]]
    target_lines = find_branches_by_bus_pairs(modified_network_data, bus_pairs)
    lambda = get(cfg, "lambda", 500.0)
    opf_model = get(cfg, "opf_model", "AC")
    flow_model = get(cfg, "p_model", "combined")
    alpha = Float64(get(cfg, "alpha", lambda))
    beta = Float64(get(cfg, "beta", 1.0e3))
    gamma = Float64(get(cfg, "gamma", 1.0))
    kappa = Float64(get(cfg, "kappa", 1.0e6))
    voltage_weight_floor = Float64(get(cfg, "voltage_weight_floor", 1.0))
    voltage_feedback_gain = Float64(get(cfg, "voltage_feedback_gain", 100.0))
    voltage_penalty_vmin = Float64(get(cfg, "voltage_penalty_vmin", 0.95))
    voltage_penalty_vmax = Float64(get(cfg, "voltage_penalty_vmax", 1.05))

    load_shedding_penalties = Dict{String,Float64}(string(k) => Float64(v) for (k, v) in get(cfg, "load_shedding_penalties", Dict()))
    add_load_shedding_penalty!(modified_network_data; uniform=false, penalties=load_shedding_penalties)
else
    src_case_path = "cases/psse/ACTIVSg500"
    run_psse = true
    case_files = find_case_files(src_case_path; require_dyr=run_psse)
    case_name = basename(src_case_path)
    PowerModels.silence()
    network_data = PowerModels.parse_file(case_files.raw, import_all=true)
    modified_network_data = deepcopy(network_data)

    objective = "flow_shed"
    lambda = 500.0
    opf_model = "AC"
    flow_model = "squared"

    alpha = lambda
    beta = 1.0e2
    gamma = 1.0
    kappa = 1.0e6
    voltage_weight_floor = 1.0
    voltage_feedback_gain = 100.0
    voltage_penalty_vmin = 0.95
    voltage_penalty_vmax = 1.05

    target_zone = "spartanb"
    target_lines = find_branches_by_zone(modified_network_data, target_zone)
    selected_buses = find_buses_by_zone(modified_network_data, target_zone)

    load_shedding_penalties = Dict{String,Float64}()
    for bus in keys(network_data["bus"])
        if parse(Int, bus) in selected_buses
            load_shedding_penalties[bus] = 1 * lambda
        else
            # load_shedding_penalties[bus] = 0 * lambda
        end
    end

    add_load_shedding_penalty!(
        modified_network_data;
        uniform=false,
        penalties=load_shedding_penalties,
    )
end

opf_model == "AC" || error("islanding2 voltage-feedback OPF requires opf_model = \"AC\".")

const ObjectiveType = Dict(
    "pf" => "opf",
    "opf" => "opf",
    "flow" => "flow",
    "opf_flow" => "opf_flow",
    "opf_shed" => "opf_shed",
    "flow_shed" => "flow_shed",
    "opf_flow_shed" => "opf_flow_shed",
)
const PowerModelType = Dict(
    "AC" => ACPPowerModel,
)

modified_network_data["objective"] = ObjectiveType[objective]
modified_network_data["target_ids"] = target_lines
modified_network_data["opf_model"] = opf_model
modified_network_data["p_model"] = flow_model
modified_network_data["lambda"] = lambda
if @isdefined(selected_buses)
    modified_network_data["target_zone_buses"] = selected_buses
end

power_model = PowerModelType[opf_model]
optimizer = optimizer_with_attributes(Ipopt.Optimizer, "print_level" => 4, "mumps_mem_percent" => 2000)

output_root = joinpath("results", "psse", "$(case_name)_islanding2")
baseline_output_path = joinpath(output_root, "baseline")
feedback_output_path = joinpath(output_root, "feedback")
mkpath(baseline_output_path)
mkpath(feedback_output_path)

println("--------------------------------------------------")
println("Baseline pre-event OPF")
baseline_result = PowerModels.solve_custom_opf(modified_network_data, power_model, optimizer)
println("Baseline objective: ", baseline_result["objective"])
print_generation_status(modified_network_data, baseline_result)
if occursin("shed", objective)
    print_load_shedding_status(baseline_result, modified_network_data)
end
if @isdefined(target_zone)
    print_branch_flows(baseline_result, modified_network_data, target_lines, false, target_zone)
else
    print_branch_flows(baseline_result, modified_network_data, target_lines)
end

baseline_stats_file = nothing
if run_psse
    baseline_raw, baseline_excel, _ = export_solution_for_psse(modified_network_data, baseline_result, baseline_output_path, case_name, "baseline")
    write_line_outage_file(modified_network_data, target_lines, baseline_output_path)
    baseline_dyr = copy_dyr_file(case_files, baseline_output_path, case_name, "baseline")
    baseline_stats_file = run_dynamic2(baseline_raw, baseline_dyr, baseline_excel)
    print_voltage_stats_summary(baseline_stats_file, "Baseline")
end

println("--------------------------------------------------")
println("Feedback multinetwork OPF")
voltage_weights = read_voltage_weights(baseline_stats_file; base_weight=voltage_weight_floor, feedback_gain=voltage_feedback_gain)
feedback_result = solve_feedback_opf(
    modified_network_data,
    power_model,
    optimizer,
    target_lines,
    voltage_weights;
    alpha=alpha,
    beta=beta,
    gamma=gamma,
    kappa=kappa,
    voltage_weight_floor=voltage_weight_floor,
    voltage_penalty_vmin=voltage_penalty_vmin,
    voltage_penalty_vmax=voltage_penalty_vmax,
)
println("Feedback objective: ", feedback_result["objective"])

pre_event_feedback_result = extract_pre_event_result(feedback_result)
print_generation_status(modified_network_data, pre_event_feedback_result)
print_load_shedding_status(pre_event_feedback_result, modified_network_data)
if @isdefined(target_zone)
    print_branch_flows(pre_event_feedback_result, modified_network_data, target_lines, false, target_zone)
else
    print_branch_flows(pre_event_feedback_result, modified_network_data, target_lines)
end

if run_psse
    feedback_raw, feedback_excel, _ = export_solution_for_psse(modified_network_data, pre_event_feedback_result, feedback_output_path, case_name, "feedback")
    write_line_outage_file(modified_network_data, target_lines, feedback_output_path)
    feedback_dyr = copy_dyr_file(case_files, feedback_output_path, case_name, "feedback")
    feedback_stats_file = run_dynamic2(feedback_raw, feedback_dyr, feedback_excel)
    print_voltage_stats_summary(feedback_stats_file, "Feedback")
end

println("islanding2 workflow complete.")
