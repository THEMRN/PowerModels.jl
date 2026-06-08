using Dates
using Graphs
using Combinatorics
using Printf

function find_case_files(src_case_path::AbstractString; require_dyr::Bool=false)
    isdir(src_case_path) || error("Directory does not exist: $src_case_path")
    files = readdir(src_case_path; join=true)

    raw_files = filter(f -> endswith(lowercase(f), ".raw"), files)
    dyr_files = filter(f -> endswith(lowercase(f), ".dyr"), files)

    isempty(raw_files) && error("No .raw file found in $src_case_path")
    if require_dyr && isempty(dyr_files)
        error("No .dyr file found in $src_case_path (required when run_psse=true)")
    end

    raw_file = first(raw_files)
    dyr_file = isempty(dyr_files) ? nothing : first(dyr_files)
    return (raw=raw_file, dyr=dyr_file)
end

function prepare_for_pti_export(network_data)
    # Ensure the network data is in the correct format for PTI export

    # fix load status if load shed is applied
    for (i, load) in network_data["load"]
        if haskey(load, "status")
            load["status"] = load["status"] > 0 ? 1 : 0
        else
            load["status"] = 1  # Default to connected if no status is provided
        end
        if haskey(load, "pd") && abs(load["pd"]) < 1e-3
            load["pd"] = 0.0
        end
        if haskey(load, "qd") && abs(load["qd"]) < 1e-3
            load["qd"] = 0.0
        end
    end

    # fix shunt status if load shed is applied
    for (i, shunt) in network_data["shunt"]
        if haskey(shunt, "status") && shunt["status"] != 0
            shunt["status"] = 1
        else
            shunt["status"] = 0
        end
    end

    for (i, gen) in network_data["gen"]
        # prevent negative active power generation
        if haskey(gen, "pg") && gen["pg"] < 0
            println("Generator $i has negative active power generation (pg=$(gen["pg"])). Setting pg to 0 for PTI export.")
            gen["pg"] = 0.0
        end
        # if haskey(gen, "qg") && gen["qg"] < 0
        #     gen["qg"] = 0.0
        # end

        # add scheduled voltage (vg) for each generator based on its bus voltage
        gen_bus = string(gen["gen_bus"])
        gen_bus_voltage = network_data["bus"][gen_bus]["vm"]
        gen["vg"] = gen_bus_voltage
    end

    return network_data
end

function analyze_load_shedding_results(result, network_data)
    println("=== Load Shedding Analysis ===")
    println("Termination Status: ", result["termination_status"])
    println("Objective Value: ", result["objective"])

    println("\n--- Load Serving Status ---")
    for (i, load) in network_data["load"]
        if haskey(result["solution"]["load"][i], "status")
            status = result["solution"]["load"][i]["status"]
            original_pd = load["pd"]
            served_pd = result["solution"]["load"][i]["pd"]
            shed_amount = original_pd - served_pd
            shed_percentage = (shed_amount / original_pd) * 100

            println("Load $i:")
            println("  Original demand: $(original_pd)")
            println("  Served demand: $(round(served_pd, digits=2))")
            println("  Load shed: $(round(shed_percentage, digits=2))%")
        end
    end

    println("\n--- Generator Dispatch ---")
    for (i, gen) in network_data["gen"]
        if haskey(result["solution"]["gen"][i], "pg")
            pg = result["solution"]["gen"][i]["pg"]
            pmax = gen["pmax"]
            utilization = (pg / pmax) * 100
            println("Gen $i: $(round(pg, digits=2)) MW / $(pmax) MW ($(round(utilization, digits=1))% utilization)")
        end
    end

    println("\n--- Bus Voltages ---")
    for (i, bus) in network_data["bus"]
        if haskey(result["solution"]["bus"][i], "vm")
            vm = result["solution"]["bus"][i]["vm"]
            println("Bus $i: $(round(vm, digits=3)) pu")
        end
    end
end


function add_load_shedding_penalty!(network_data; uniform=false, uniform_penalty=1e10, penalties=Dict())
    println("=== Adding Load Shedding Penalties ===")
    if uniform
        # Apply a uniform penalty to all loads
        for (i, load) in network_data["load"]
            load["shed_penalty"] = uniform_penalty
        end
    else
        # Apply specific penalties to each load based on the provided list
        # iterate over penalties, find components at the bus, and apply the penalty
        # and also apply a large default penalty to loads not in the list
        for (i, load) in network_data["load"]
            load_bus = load["load_bus"]
            if haskey(penalties, string(load_bus))
                penalty = penalties[string(load_bus)]
                # println("  Load at bus $(load_bus) (load $i): penalty = $penalty")
                load["shed_penalty"] = penalty
            else
                load["shed_penalty"] = 1e4   # Default to a large penalty if not specified
            end
        end
    end
end

function get_timestamp()
    now_dt = now()
    yr = lpad(Dates.year(now_dt), 2, "0")
    mon = lpad(Dates.month(now_dt), 2, "0")
    dy = lpad(Dates.day(now_dt), 2, "0")
    hr = lpad(Dates.hour(now_dt), 2, "0")
    min = lpad(Dates.minute(now_dt), 2, "0")
    sec = lpad(Dates.second(now_dt), 2, "0")

    return "$(yr)_$(mon)_$(dy)_$(hr)_$(min)_$(sec)"
end

function get_zone_name_by_index(network_data, zone_index)
    for (_, zone) in network_data["zone"]
        if zone["i"] == zone_index
            return zone["zoname"]
        end
    end
    error("Zone index $zone_index not found in network data")
end

function get_zone_index_by_name(network_data, zone_name::AbstractString)
    for (_, zone) in network_data["zone"]
        if lowercase(strip(zone["zoname"])) == lowercase(strip(zone_name))
            return zone["i"]
        end
    end
    error("Zone '$zone_name' not found in network data")
end

function find_buses_by_zone(network_data, zone_name::AbstractString)
    zone_index = get_zone_index_by_name(network_data, zone_name)
    zone_buses = Set{Int}()
    for (_, bus) in network_data["bus"]
        if bus["zone"] == zone_index
            push!(zone_buses, Int(bus["bus_i"]))
        end
    end
    return sort(collect(zone_buses))
end

function find_branches_by_zone(network_data, zone_name::AbstractString)
    zone_index = get_zone_index_by_name(network_data, zone_name)

    # Collect all bus IDs belonging to this zone
    zone_buses = Set{Int}()
    for (_, bus) in network_data["bus"]
        if bus["zone"] == zone_index
            push!(zone_buses, Int(bus["bus_i"]))
        end
    end

    # Find branches where exactly one endpoint is in the zone (zone bridges)
    branch_keys = Set{Int}()
    for (branch_key, branch) in network_data["branch"]
        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])
        if xor(f_bus in zone_buses, t_bus in zone_buses)
            push!(branch_keys, parse(Int, branch_key))
        end
    end

    return sort(collect(branch_keys))
end

function find_branches_by_bus_pairs(network_data, bus_pairs)
    branch_keys = Int[]

    for (branch_key, branch) in network_data["branch"]
        f_bus = branch["f_bus"]
        t_bus = branch["t_bus"]

        for (bus1, bus2) in bus_pairs
            if (f_bus == bus1 && t_bus == bus2) || (f_bus == bus2 && t_bus == bus1)
                push!(branch_keys, parse(Int, branch_key))
                break
            end
        end
    end

    return sort(branch_keys)
end


function find_branches_by_bus(network_data, buses)
    bus_set = Set(buses)
    branch_keys = Int[]

    for (branch_key, branch) in network_data["branch"]
        f_bus = branch["f_bus"]
        t_bus = branch["t_bus"]
        if (f_bus in bus_set) || (t_bus in bus_set)
            push!(branch_keys, parse(Int, branch_key))
        end
    end

    return sort(branch_keys)
end

# Scale all loads (or only those at `buses`) by a fixed percentage.
function scale_loads!(network_data, scale::Real, buses=nothing)
    for (i, load) in network_data["load"]
        if buses !== nothing && !(load["load_bus"] in buses)
            continue
        end
        println("Scaling load at bus $(load["load_bus"]) by $((scale - 1) * 100)%")
        load["pd"] *= scale
        load["qd"] *= scale
    end
end

# Scale all loads in a zone (matched case-insensitively) by a fixed percentage.
function scale_loads!(network_data, scale::Real, zone_name::AbstractString)
    zone_index = nothing
    for (_, zone) in network_data["zone"]
        if lowercase(strip(zone["zoname"])) == lowercase(strip(zone_name))
            zone_index = zone["i"]
            break
        end
    end
    zone_index === nothing && error("Zone '$zone_name' not found in network data")

    for (i, load) in network_data["load"]
        load["zone"] == zone_index || continue
        println("Scaling load at bus $(load["load_bus"]) (zone '$zone_name') by $((scale - 1) * 100)%")
        load["pd"] *= scale
        load["qd"] *= scale
    end
end

# Scale loads per-bus using a Dict{bus_number => scale_percent}.
function scale_loads!(network_data, bus_scale_dict::AbstractDict)
    for (i, load) in network_data["load"]
        bus = load["load_bus"]
        haskey(bus_scale_dict, bus) || continue
        scale = bus_scale_dict[bus]
        println("Scaling load at bus $bus by $((scale - 1) * 100)%")
        load["pd"] *= scale
        load["qd"] *= scale
    end
end


function find_components_by_bus(network_data, component, bus_number)
    component_keys = String[]

    if !haskey(network_data, component)
        return component_keys
    end

    for (key, comp_data) in network_data[component]
        if component == "gen"
            if haskey(comp_data, "gen_bus") && comp_data["gen_bus"] == bus_number
                push!(component_keys, key)
            end
        elseif component == "load"
            if haskey(comp_data, "load_bus") && comp_data["load_bus"] == bus_number
                push!(component_keys, key)
            end
        elseif component == "branch"
            if (haskey(comp_data, "f_bus") && comp_data["f_bus"] == bus_number) ||
               (haskey(comp_data, "t_bus") && comp_data["t_bus"] == bus_number)
                push!(component_keys, key)
            end
        end
    end

    return sort(component_keys)
end

function build_network_graph(network_data)
    # Graph mapping bus_id => Dict(:connections, :gens, :loads, :pd, :qd, :pmax, :qmax)
    graph = Dict{Int,Dict{Symbol,Any}}()

    # Helper to initialize a node entry if missing
    ensure_node!(bus_id) =
        get!(graph, bus_id) do
            Dict{Symbol,Any}(
                :connections => Set{Int}(),
                :gens => String[],
                :loads => String[],
                :pd => 0.0,
                :qd => 0.0,
                :pmax => 0.0,
                :qmax => 0.0,
                :w => 0.0
            )
        end

    # 1) Initialize nodes from buses
    if haskey(network_data, "bus")
        for (_, bus) in network_data["bus"]
            bus_id = Int(bus["bus_i"])  # bus_i is the unique bus number
            ensure_node!(bus_id)
        end
    end

    # 2) Accumulate loads (only in-service if "status" present)
    if haskey(network_data, "load")
        for (lid, load) in network_data["load"]
            status_ok = !haskey(load, "status") || load["status"] != 0
            if status_ok
                bus_id = Int(load["load_bus"])
                node = ensure_node!(bus_id)
                push!(node[:loads], String(lid))
                node[:pd] += get(load, "pd", 0.0)
                node[:qd] += get(load, "qd", 0.0)
                node[:w] -= get(load, "pd", 0.0)
            end
        end
    end

    # 3) Accumulate generators (only in-service if "gen_status" present)
    if haskey(network_data, "gen")
        for (gid, gen) in network_data["gen"]
            status_ok = !haskey(gen, "gen_status") || gen["gen_status"] != 0
            if status_ok
                bus_id = Int(gen["gen_bus"])
                node = ensure_node!(bus_id)
                push!(node[:gens], String(gid))
                node[:pmax] += get(gen, "pmax", 0.0)
                node[:qmax] += get(gen, "qmax", 0.0)
                node[:w] += get(gen, "pmax", 0.0)
            end
        end
    end

    # 4) Build connections (deduplicate parallel branches, only in-service if "br_status" present)
    if haskey(network_data, "branch")
        for (_, br) in network_data["branch"]
            status_ok = !haskey(br, "br_status") || br["br_status"] != 0
            if status_ok
                f = Int(br["f_bus"])
                t = Int(br["t_bus"])
                if f != t
                    push!(ensure_node!(f)[:connections], t)
                    push!(ensure_node!(t)[:connections], f)
                end
            end
        end
    end

    return graph
end

function reduce_graph(graph)
    graph = deepcopy(graph)
    for (bus, node) in graph
        connections = node[:connections]
        connections_num = length(connections)
        w = node[:w]
        if connections_num == 1
            # target is the only connection, merge into target and remove self
            target = first(node[:connections])
            target_node = graph[target]
            target_node[:w] += w
            push!(target_node[:gens], node[:gens]...)
            push!(target_node[:loads], node[:loads]...)
            delete!(graph, bus)
            delete!(target_node[:connections], bus)
        end
    end
    for (bus, node) in graph
        connections = node[:connections]
        w = node[:w]
        # remove self if there is now weight and connect adjacent nodes
        if w == 0
            for (b1, b2) in combinations(collect(connections), 2)
                graph[b1][:connections] = union(graph[b1][:connections], Set([b2]))
                graph[b2][:connections] = union(graph[b2][:connections], Set([b1]))
            end
            for conn in connections
                delete!(graph[conn][:connections], bus)
            end
            delete!(graph, bus)
        end
    end
    return graph
end

function print_branch_flows(result, modified_network_data, target_lines, detailed=false, zone=nothing)
    println("---------------------------")

    zone_buses = zone === nothing ? nothing : find_buses_by_zone(modified_network_data, zone)

    p_flow_sum = 0.0
    q_flow_sum = 0.0
    total_flow_sum = 0.0
    abs_p_flow_sum = 0.0
    abs_q_flow_sum = 0.0
    abs_total_flow_sum = 0.0
    for line in target_lines
        branch = modified_network_data["branch"][string(line)]
        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])

        p_flow_key = "pf"
        q_flow_key = "qf"
        fr = branch["source_id"][2]
        to = branch["source_id"][3]
        if zone_buses !== nothing && !(f_bus in zone_buses) && (t_bus in zone_buses)
            p_flow_key = "pt"
            q_flow_key = "qt"
            fr, to = to, fr
        end

        p_flow = result["solution"]["branch"][string(line)][p_flow_key]
        q_flow = result["solution"]["branch"][string(line)][q_flow_key]
        p_flow_sum += p_flow
        q_flow_sum += q_flow
        total_flow_sum += p_flow + q_flow
        abs_p_flow_sum += abs(p_flow)
        abs_q_flow_sum += abs(q_flow)
        abs_total_flow_sum += abs(p_flow) + abs(q_flow)
        if detailed
            println("Line $line (Bus $fr -> Bus $to) flow: $total_flow")
        end
    end
    println("Total net flow through target lines:\t\t P = $(round(p_flow_sum, digits=3)), Q = $(round(q_flow_sum, digits=3)), Total = $(round(total_flow_sum, digits=3))")
    println("Sum of absolute flows through target lines:\t P = $(round(abs_p_flow_sum, digits=3)), Q = $(round(abs_q_flow_sum, digits=3)), Total = $(round(abs_total_flow_sum, digits=3))")
end

"""
Print generation capacity of a given zone
if zone_name is nothing, print generation capacity of the whole network
print in format: zone_name: Pmin, Pmax, Qmin, Qmax
"""
function print_zone_capacity(network_data, zone_name=nothing)
    zone_index = nothing
    zone_buses = nothing
    if zone_name !== nothing
        for (_, zone) in get(network_data, "zone", Dict())
            if lowercase(strip(zone["zoname"])) == lowercase(strip(zone_name))
                zone_index = zone["i"]
                break
            end
        end
        zone_index === nothing && error("Zone '$zone_name' not found in network data")
        zone_buses = Set{Int}()
        for (_, bus) in network_data["bus"]
            if bus["zone"] == zone_index
                push!(zone_buses, Int(bus["bus_i"]))
            end
        end
    end

    pmin_tot = 0.0
    pmax_tot = 0.0
    qmin_tot = 0.0
    qmax_tot = 0.0
    for (_, g) in get(network_data, "gen", Dict())
        get(g, "gen_status", 1) == 0 && continue
        if zone_buses !== nothing && !(Int(g["gen_bus"]) in zone_buses)
            continue
        end
        pmin_tot += get(g, "pmin", 0.0)
        pmax_tot += get(g, "pmax", 0.0)
        qmin_tot += get(g, "qmin", 0.0)
        qmax_tot += get(g, "qmax", 0.0)
    end

    label = zone_name === nothing ? "Whole network" : strip(string(zone_name))
    println(
        "$label: Pmin=$(round(pmin_tot, digits=4)), Pmax=$(round(pmax_tot, digits=4)), " *
        "Qmin=$(round(qmin_tot, digits=4)), Qmax=$(round(qmax_tot, digits=4))",
    )
end

"""
    print_generation_status(network_data, result)

Print active generation status by zone:
- P: `Pg`, `Pmax`, used % of `Pmax` (printed as `Used`); `Pg` from `result["solution"]["gen"]`
- Q: `Qg`, `Qmax`, used % of `Qmax` (printed as `Used`, after the Q values); `Qg` from solution

`Pmax` and `Qmax` still come from `network_data["gen"]`. Inactive generators are skipped.

If no zones are available in the network data, print the same values for the
whole network.
"""
function print_generation_status(network_data, result)
    gens = get(network_data, "gen", Dict())
    sol_gens = get(get(result, "solution", Dict()), "gen", Dict())
    zones = get(network_data, "zone", Dict())
    buses = get(network_data, "bus", Dict())

    bus_zone_by_bus = Dict{Int,Int}()
    for (_, bus) in buses
        bus_zone_by_bus[Int(bus["bus_i"])] = Int(get(bus, "zone", 0))
    end

    zone_name_by_index = Dict{Int,String}()
    for (_, zone) in zones
        zone_name_by_index[Int(zone["i"])] = strip(string(zone["zoname"]))
    end

    if isempty(zones)
        pg_total = 0.0
        pmax_total = 0.0
        qg_total = 0.0
        qmax_total = 0.0
        for (gen_id, g) in gens
            get(g, "gen_status", 1) == 0 && continue
            g_sol = get(sol_gens, gen_id, get(sol_gens, string(gen_id), Dict()))
            pg_total += get(g_sol, "pg", 0.0)
            pmax_total += get(g, "pmax", 0.0)
            qg_total += get(g_sol, "qg", 0.0)
            qmax_total += get(g, "qmax", 0.0)
        end
        p_used_pct = pmax_total > 0 ? 100 * pg_total / pmax_total : 0.0
        q_used_pct = qmax_total > 0 ? 100 * qg_total / qmax_total : 0.0
        println("Generation status (whole network):")
        println(
            "Network: Pg=$(round(pg_total, digits=4)), " *
            "Pmax=$(round(pmax_total, digits=4)), " *
            "Used=$(round(p_used_pct, digits=2))%, " *
            "Qg=$(round(qg_total, digits=4)), " *
            "Qmax=$(round(qmax_total, digits=4)), " *
            "Used=$(round(q_used_pct, digits=2))%",
        )
        return
    end

    zone_pg = Dict{Int,Float64}()
    zone_pmax = Dict{Int,Float64}()
    zone_qg = Dict{Int,Float64}()
    zone_qmax = Dict{Int,Float64}()
    for zone_index in keys(zone_name_by_index)
        zone_pg[zone_index] = 0.0
        zone_pmax[zone_index] = 0.0
        zone_qg[zone_index] = 0.0
        zone_qmax[zone_index] = 0.0
    end

    for (gen_id, g) in gens
        get(g, "gen_status", 1) == 0 && continue
        gen_bus = Int(get(g, "gen_bus", 0))
        zone_index = get(bus_zone_by_bus, gen_bus, 0)
        zone_index == 0 && continue
        g_sol = get(sol_gens, gen_id, get(sol_gens, string(gen_id), Dict()))
        zone_pg[zone_index] = get(zone_pg, zone_index, 0.0) + get(g_sol, "pg", 0.0)
        zone_pmax[zone_index] = get(zone_pmax, zone_index, 0.0) + get(g, "pmax", 0.0)
        zone_qg[zone_index] = get(zone_qg, zone_index, 0.0) + get(g_sol, "qg", 0.0)
        zone_qmax[zone_index] = get(zone_qmax, zone_index, 0.0) + get(g, "qmax", 0.0)
    end

    println("Generation status by zone:")
    println(@sprintf("%-16s %-12.4s %-12.4s %-12s %-12s %-10s %-10s", "Zone", "Pg", "Pmax", "Used", "Qg", "Qmax", "Used"))
    for zone_index in sort(collect(keys(zone_name_by_index)))
        zone_name = zone_name_by_index[zone_index]
        pg_total = get(zone_pg, zone_index, 0.0)
        pmax_total = get(zone_pmax, zone_index, 0.0)
        qg_total = get(zone_qg, zone_index, 0.0)
        qmax_total = get(zone_qmax, zone_index, 0.0)
        p_used_pct = pmax_total > 0 ? 100 * pg_total / pmax_total : 0.0
        q_used_pct = qmax_total > 0 ? 100 * qg_total / qmax_total : 0.0
        # println(
        #     @sprintf("%-10s ", zone_name) *
        #     @sprintf("%-10.4f ", pg_total) *
        #     @sprintf("%-10.4f ", pmax_total) *
        #     @sprintf("%-10.2f%% ", p_used_pct) *
        #     @sprintf("%-10.4f ", qg_total) *
        #     @sprintf("%-10.4f ", qmax_total) *
        #     @sprintf("%-10.2f%% ", q_used_pct))
        println(@sprintf(
            "%-10s %12.4f %12.4f %10.2f%% %12.4f %12.4f %10.2f%%",
            zone_name,
            pg_total,
            pmax_total,
            p_used_pct,
            qg_total,
            qmax_total,
            q_used_pct
        ))
    end
end

"""
    print_network_summary(network_data; zone_name=nothing)

Print a summary of the network data. If `zone_name` is specified (matched case-insensitively),
print statistics for that zone only; otherwise print statistics for the whole network.

Summary includes:
- Available voltage levels (base kV)
- Total number of buses, generators, loads
- Total number of AC branches and transformers
- Number of zones and their names
- Total generation capacity (active and reactive)
- Total generation (active and reactive)
- Total load (active and reactive)
- Total shunt susceptance (B, per-unit)
"""
function print_network_summary(network_data; zone_name::Union{String,Nothing}=nothing)
    # Resolve zone index and filter set if zone_name is specified
    zone_index = nothing
    zone_buses = nothing
    if zone_name !== nothing
        zone_index = nothing
        for (_, zone) in get(network_data, "zone", Dict())
            if lowercase(strip(zone["zoname"])) == lowercase(strip(zone_name))
                zone_index = zone["i"]
                break
            end
        end
        zone_index === nothing && error("Zone '$zone_name' not found in network data")
        zone_buses = Set{Int}()
        for (_, bus) in network_data["bus"]
            if bus["zone"] == zone_index
                push!(zone_buses, Int(bus["bus_i"]))
            end
        end
    end

    # --- Buses ---
    buses = get(network_data, "bus", Dict())
    bus_list = [b for (_, b) in buses if zone_buses === nothing || Int(b["bus_i"]) in zone_buses]
    n_buses = length(bus_list)

    # --- Voltage levels (base_kv) ---
    base_kv_set = Set{Float64}()
    for b in bus_list
        push!(base_kv_set, Float64(b["base_kv"]))
    end
    base_kv_sorted = sort(collect(base_kv_set))

    # --- Generators ---
    gens = get(network_data, "gen", Dict())
    gen_list = [
        g for (_, g) in gens
        if (zone_buses === nothing || Int(g["gen_bus"]) in zone_buses) &&
        get(g, "gen_status", 1) != 0
    ]
    n_gens = length(gen_list)

    # --- Loads ---
    loads = get(network_data, "load", Dict())
    load_list = [
        l for (_, l) in loads
        if (zone_buses === nothing || Int(get(l, "zone", 0)) == zone_index) &&
        get(l, "status", 1) != 0
    ]
    n_loads = length(load_list)

    # --- Branches: AC lines vs transformers ---
    branches = get(network_data, "branch", Dict())
    ac_branches = []
    transformers = []
    for (_, br) in branches
        get(br, "br_status", 1) == 0 && continue
        f_bus = Int(br["f_bus"])
        t_bus = Int(br["t_bus"])
        if zone_buses !== nothing && !(f_bus in zone_buses && t_bus in zone_buses)
            continue
        end
        if get(br, "transformer", false)
            push!(transformers, br)
        else
            push!(ac_branches, br)
        end
    end
    n_ac_branches = length(ac_branches)
    n_transformers = length(transformers)

    # --- Zones ---
    zones = get(network_data, "zone", Dict())
    zone_names = [strip(z["zoname"]) for (_, z) in sort(zones, by=x -> parse(Int, x[1]))]
    n_zones = length(zones)

    # --- Generation capacity and actual generation ---
    pmax_tot = sum(get(g, "pmax", 0.0) for g in gen_list)
    qmax_tot = sum(get(g, "qmax", 0.0) for g in gen_list)
    pmin_tot = sum(get(g, "pmin", 0.0) for g in gen_list)
    qmin_tot = sum(get(g, "qmin", 0.0) for g in gen_list)
    pg_tot = sum(get(g, "pg", 0.0) for g in gen_list)
    qg_tot = sum(get(g, "qg", 0.0) for g in gen_list)

    # --- Total load ---
    pd_tot = sum(get(l, "pd", 0.0) for l in load_list)
    qd_tot = sum(get(l, "qd", 0.0) for l in load_list)

    # --- Total shunt susceptance (B) ---
    shunts = get(network_data, "shunt", Dict())
    shunt_B_tot = 0.0
    shunt_G_tot = 0.0
    for (_, sh) in shunts
        get(sh, "status", 1) == 0 && continue
        shunt_bus = Int(get(sh, "shunt_bus", 0))
        if zone_buses !== nothing && !(shunt_bus in zone_buses)
            continue
        end
        bs = get(sh, "bs", 0.0)
        gs = get(sh, "gs", 0.0)
        B_step = 0.0
        for i in 1:8
            bi = get(sh, "b$i", 0.0)
            ni = Int(get(sh, "n$i", 0))
            B_step += ni * bi
        end
        shunt_B_tot += bs + B_step
        shunt_G_tot += gs
    end

    # --- Print ---
    scope = zone_name === nothing ? "Whole network" : "Zone: $(strip(zone_name))"
    println("========================================")
    println("Network Summary - $scope")
    println("========================================")
    println("Available voltage levels (base kV): ", base_kv_sorted)
    println("Total number of buses:              ", n_buses)
    println("Total number of generators:         ", n_gens)
    println("Total number of loads:              ", n_loads)
    println("Total number of AC branches:        ", n_ac_branches)
    println("Total number of transformers:       ", n_transformers)
    println("Number of zones:                    ", n_zones)
    println("Zone names:                         ", zone_names)
    println("--- Generation ---")
    println("Total generation capacity (P max):  ", round(pmax_tot, digits=4), " pu")
    println("Total generation capacity (Q max):  ", round(qmax_tot, digits=4), " pu")
    println("Total generation capacity (P min):  ", round(pmin_tot, digits=4), " pu")
    println("Total generation capacity (Q min):  ", round(qmin_tot, digits=4), " pu")
    println("Total generation (P):               ", round(pg_tot, digits=4), " pu")
    println("Total generation (Q):               ", round(qg_tot, digits=4), " pu")
    println("--- Load ---")
    println("Total load (P):                     ", round(pd_tot, digits=4), " pu")
    println("Total load (Q):                     ", round(qd_tot, digits=4), " pu")
    println("--- Shunt ---")
    println("Total shunt susceptance (B):        ", round(shunt_B_tot, digits=4), " pu")
    println("Total shunt conductance (G):        ", round(shunt_G_tot, digits=4), " pu")
    println("========================================")
end

function print_load_shedding_status(result, modified_network_data, detailed=false)
    println("Load shedding results:")
    sol_loads = get(get(result, "solution", Dict()), "load", Dict())
    has_split_shedding = any(
        haskey(load_sol, "planned_shed") || haskey(load_sol, "forced_shed")
        for (_, load_sol) in sol_loads
    )
    if detailed
        println("---  Load Serving Status by Bus ---")
        if has_split_shedding
            println("Bus \t PDn \t PD \t Shed \t Planned \t Forced \t Shed Percentage")
        else
            println("Bus \t PDn \t PD \t Shed \t Shed Percentage")
        end
    end
    total_shed = 0.0
    total_planned_shed = 0.0
    total_forced_shed = 0.0
    total_load = 0.0
    zone_name_by_index = Dict{Int,String}()
    for (_, zone) in get(modified_network_data, "zone", Dict())
        zone_name_by_index[Int(zone["i"])] = strip(zone["zoname"])
    end
    bus_zone_by_bus = Dict{Int,Int}()
    for (_, bus) in get(modified_network_data, "bus", Dict())
        bus_zone_by_bus[Int(bus["bus_i"])] = Int(get(bus, "zone", 0))
    end
    zone_total_load = Dict{Int,Float64}()
    zone_total_shed = Dict{Int,Float64}()
    zone_total_planned_shed = Dict{Int,Float64}()
    zone_total_forced_shed = Dict{Int,Float64}()
    for (i, load) in modified_network_data["load"]
        total_load += load["pd"]
        load_bus = Int(load["load_bus"])
        zone_index = Int(get(load, "zone", get(bus_zone_by_bus, load_bus, 0)))
        if zone_index != 0
            zone_total_load[zone_index] = get(zone_total_load, zone_index, 0.0) + load["pd"]
        end
        if haskey(sol_loads, i) && haskey(sol_loads[i], "status")
            status = sol_loads[i]["status"]

            if status >= 1.0
                continue
            end
            original_pd = load["pd"]
            served_pd = get(sol_loads[i], "pd", original_pd * status)
            shed_amount = original_pd - served_pd
            planned_shed_amount = 0.0
            forced_shed_amount = 0.0
            if has_split_shedding
                planned_shed_amount = original_pd * get(sol_loads[i], "planned_shed", 0.0)
                forced_shed_amount = original_pd * get(sol_loads[i], "forced_shed", 0.0)
            end
            shed_percentage = (shed_amount / original_pd) * 100
            total_shed += shed_amount
            total_planned_shed += planned_shed_amount
            total_forced_shed += forced_shed_amount
            if zone_index != 0
                zone_total_shed[zone_index] = get(zone_total_shed, zone_index, 0.0) + shed_amount
                zone_total_planned_shed[zone_index] = get(zone_total_planned_shed, zone_index, 0.0) + planned_shed_amount
                zone_total_forced_shed[zone_index] = get(zone_total_forced_shed, zone_index, 0.0) + forced_shed_amount
            end
            if detailed
                if has_split_shedding
                    println("$(load_bus) \t $(round(original_pd, digits=2)) \t $(round(served_pd, digits=2)) \t $(round(shed_amount, digits=2)) \t $(round(planned_shed_amount, digits=2)) \t $(round(forced_shed_amount, digits=2)) \t $(round(shed_percentage, digits=2))%")
                else
                    println("$(load_bus) \t $(round(original_pd, digits=2)) \t $(round(served_pd, digits=2)) \t $(round(shed_amount, digits=2)) \t $(round(shed_percentage, digits=2))%")
                end
            end
        end
    end
    base_mva = modified_network_data["baseMVA"]
    if !isempty(zone_total_load)
        println("---  Load Shed by Zone ---")
        for zone_index in sort(collect(keys(zone_total_load)))
            zone_name = get(zone_name_by_index, zone_index, "Zone $zone_index")
            zone_shed_mw = round(get(zone_total_shed, zone_index, 0.0) * base_mva, digits=2)
            zone_planned_shed_mw = round(get(zone_total_planned_shed, zone_index, 0.0) * base_mva, digits=2)
            zone_forced_shed_mw = round(get(zone_total_forced_shed, zone_index, 0.0) * base_mva, digits=2)
            zone_load_mw = round(zone_total_load[zone_index] * base_mva, digits=2)
            if has_split_shedding
                println(@sprintf(
                    "%-10s: total %12.4f planned %12.4f forced %12.4f load %12.4f %10.2f%%",
                    zone_name,
                    zone_shed_mw,
                    zone_planned_shed_mw,
                    zone_forced_shed_mw,
                    zone_load_mw,
                    round(zone_shed_mw / zone_load_mw * 100, digits=2)
                ))
            else
                println(@sprintf(
                    "%-10s: %12.4f %12.4f %10.2f%%",
                    zone_name,
                    zone_shed_mw,
                    zone_load_mw,
                    round(zone_shed_mw / zone_load_mw * 100, digits=2)
                ))
            end
        end
        println("--------------------------------")
    end
    total_shed_mw = round(total_shed * base_mva, digits=2)
    total_planned_shed_mw = round(total_planned_shed * base_mva, digits=2)
    total_forced_shed_mw = round(total_forced_shed * base_mva, digits=2)
    total_load_mw = round(total_load * base_mva, digits=2)
    if has_split_shedding
        println("Total load shed: $(total_shed_mw) MW (planned $(total_planned_shed_mw) MW, forced $(total_forced_shed_mw) MW) from $(total_load_mw) MW")
    else
        println("Total load shed: $(total_shed_mw) MW from $(total_load_mw) MW")
    end
end
