using Dates
using Graphs
using Combinatorics

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

    # Fix load status if load shed is applied
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

    # prevent negative active power generation
    for (i, gen) in network_data["gen"]
        if haskey(gen, "pg") && gen["pg"] < 0
            warning("Generator $i has negative active power generation (pg=$(gen["pg"])). Setting pg to 0 for PTI export.")
            gen["pg"] = 0.0
        end
        # if haskey(gen, "qg") && gen["qg"] < 0
        #     gen["qg"] = 0.0
        # end
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


function add_load_shedding_penalty(network_data; uniform=false, uniform_penalty=1e10, penalties=Dict())
    network = deepcopy(network_data)
    println("=== Adding Load Shedding Penalties ===")
    if uniform
        # Apply a uniform penalty to all loads
        for (i, load) in network["load"]
            load["shed_penalty"] = uniform_penalty
        end
    else
        # Apply specific penalties to each load based on the provided list
        # println("Applying specific load shedding penalties:")
        # iterate over penalties, find components at the bus, and apply the penalty
        # and also apply a default penalty to loads not in the list
        for (i, load) in network["load"]
            load_bus = load["load_bus"]
            if haskey(penalties, string(load_bus))
                penalty = penalties[string(load_bus)]
                # println("  Load at bus $(load_bus) (load $i): penalty = $penalty")
                load["shed_penalty"] = penalty
            else
                load["shed_penalty"] = lambda^2   # Default penalty if not specified
            end
        end
    end
    return network
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

function scale_loads!(network_data, scale_percent, buses=nothing)
    for (i, load) in network_data["load"]
        if buses !== nothing && !(load["load_bus"] in buses)
            continue
        end
        println("Scaling load at bus $(load["load_bus"]) by $(scale_percent)%")
        load["pd"] *= (1 + scale_percent / 100)
        load["qd"] *= (1 + scale_percent / 100)
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

function print_branch_flows(result, modified_network_data, target_lines)
    println("---------------------------")
    flow_sum = 0.0
    abs_flow_sum = 0.0
    for line in target_lines
        flow = result["solution"]["branch"][string(line)]["pf"]
        flow_sum += flow
        abs_flow_sum += abs(flow)
        fr = modified_network_data["branch"][string(line)]["source_id"][2]
        to = modified_network_data["branch"][string(line)]["source_id"][3]
        println("Line $line (Bus $fr -> Bus $to) flow: $flow")
    end
    println("Total flow through target lines: $flow_sum")
    println("Total absolute flow through target lines: $abs_flow_sum")
end

function print_load_shedding_status(result, modified_network_data)
    println("Preemtive load shedding results:")
    println("\n---  Load Serving Status ---")
    println("Bus \t PDn \t PD \t Shed \t Shed Percentage")
    total_shed = 0.0
    for (i, load) in modified_network_data["load"]
        if haskey(result["solution"]["load"][i], "status")
            status = result["solution"]["load"][i]["status"]
            if status >= 1.0
                continue
            end
            load_bus = load["load_bus"]
            original_pd = load["pd"]
            served_pd = result["solution"]["load"][i]["pd"]
            shed_amount = original_pd - served_pd
            shed_percentage = (shed_amount / original_pd) * 100
            total_shed += shed_amount

            println("$(load_bus) \t $(original_pd) \t $(round(served_pd, digits=2)) \t $(round(shed_amount, digits=2)) \t $(round(shed_percentage, digits=2))%")
        end
    end
    println("Total load shed: $(round(total_shed, digits=2)) MW")
end