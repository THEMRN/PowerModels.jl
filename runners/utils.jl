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
    for (_, zone) in get(network_data, "zone", Dict())
        if lowercase(strip(zone["zoname"])) == lowercase(strip(zone_name))
            return zone["i"]
        end
    end
    zone_index = find_group_index_by_number(network_data, "zone", zone_name)
    zone_index === nothing && error("Zone '$zone_name' not found in network data")
    return zone_index
end

"""
The group index written in `name` (e.g. "3"), when some bus carries it in its `kind` field
("zone" or "area"), else `nothing`. Lets cases without zone or area records name groups by number.
"""
function find_group_index_by_number(network_data, kind::AbstractString, name::AbstractString)
    index = tryparse(Int, strip(name))
    index === nothing && return nothing
    for (_, bus) in network_data["bus"]
        bus[kind] == index && return index
    end
    return nothing
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

"Index of the area named `area_name` (case insensitive, or its number when the case has no area records)."
function get_area_index_by_name(network_data, area_name::AbstractString)
    for (_, area) in get(network_data, "area interchange", Dict())
        if lowercase(strip(area["arname"])) == lowercase(strip(area_name))
            return area["i"]
        end
    end
    area_index = find_group_index_by_number(network_data, "area", area_name)
    area_index === nothing && error("Area '$area_name' not found in network data")
    return area_index
end

"Buses of the area named `area_name`, sorted."
function find_buses_by_area(network_data, area_name::AbstractString)
    area_index = get_area_index_by_name(network_data, area_name)
    area_buses = Set{Int}()
    for (_, bus) in network_data["bus"]
        if bus["area"] == area_index
            push!(area_buses, Int(bus["bus_i"]))
        end
    end
    return sort(collect(area_buses))
end

"Branches with exactly one end in the area named `area_name` (the area's boundary), sorted ids."
function find_branches_by_area(network_data, area_name::AbstractString)
    area_buses = Set(find_buses_by_area(network_data, area_name))

    branch_keys = Set{Int}()
    for (branch_key, branch) in network_data["branch"]
        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])
        if xor(f_bus in area_buses, t_bus in area_buses)
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
# A load belongs to its bus's zone.
function scale_loads!(network_data, scale::Real, zone_name::AbstractString)
    zone_buses = Set(find_buses_by_zone(network_data, zone_name))

    for (i, load) in network_data["load"]
        Int(load["load_bus"]) in zone_buses || continue
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

"""
    calc_branch_flows(result, network_data, target_lines, zone=nothing)

Flows (pu) on the in-service target lines. `"lines"`: id, from, to, p, q, with `from` the end
the flow is measured at: the end inside `zone` (a zone name, or the target buses themselves,
e.g. an area's) when the line's from end is outside it, else the RAW from end. `"net"` and
`"abs_sum"`: p, q and total (p + q) summed over the lines, signed and absolute.
"""
function calc_branch_flows(result, network_data, target_lines, zone=nothing)
    zone_buses = nothing
    if zone isa AbstractString
        zone_buses = find_buses_by_zone(network_data, zone)
    elseif zone !== nothing
        zone_buses = Set(zone)
    end

    lines = Dict{String,Any}[]
    p_flow_sum = 0.0
    q_flow_sum = 0.0
    total_flow_sum = 0.0
    abs_p_flow_sum = 0.0
    abs_q_flow_sum = 0.0
    abs_total_flow_sum = 0.0
    for line in target_lines
        branch = network_data["branch"][string(line)]
        branch["br_status"] != 0 || continue        # out of service: no flow, no solution entry
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
        push!(lines, Dict{String,Any}("id" => line, "from" => fr, "to" => to, "p" => p_flow, "q" => q_flow))
        p_flow_sum += p_flow
        q_flow_sum += q_flow
        total_flow_sum += p_flow + q_flow
        abs_p_flow_sum += abs(p_flow)
        abs_q_flow_sum += abs(q_flow)
        abs_total_flow_sum += abs(p_flow) + abs(q_flow)
    end

    return Dict{String,Any}(
        "lines" => lines,
        "net" => Dict("p" => p_flow_sum, "q" => q_flow_sum, "total" => total_flow_sum),
        "abs_sum" => Dict("p" => abs_p_flow_sum, "q" => abs_q_flow_sum, "total" => abs_total_flow_sum),
    )
end

"Print the flows on the target lines (`calc_branch_flows`): their net and absolute sums, and each line when `detailed`."
function print_branch_flows(result, modified_network_data, target_lines, detailed=false, zone=nothing)
    println("---------------------------")
    flows = calc_branch_flows(result, modified_network_data, target_lines, zone)

    if detailed
        for line in flows["lines"]
            println("Line $(line["id"]) (Bus $(line["from"]) -> Bus $(line["to"])) flow: $(line["p"] + line["q"])")
        end
    end
    net = flows["net"]
    abs_sum = flows["abs_sum"]
    println("Total net flow through target lines:\t\t P = $(round(net["p"], digits=3)), Q = $(round(net["q"], digits=3)), Total = $(round(net["total"], digits=3))")
    println("Sum of absolute flows through target lines:\t P = $(round(abs_sum["p"], digits=3)), Q = $(round(abs_sum["q"], digits=3)), Total = $(round(abs_sum["total"], digits=3))")
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
The kind of group ("zone" or "area") a study's reports group by: the target's own kind, and with
no target group (a bus-pair boundary) the kind the case divides its buses into: zones when the
buses are in more than one zone, else areas when they are in more than one area, else zones.
"""
function find_group_kind(network_data, target_zone=nothing, target_area=nothing)
    target_area !== nothing && return "area"
    target_zone !== nothing && return "zone"
    for group_kind in ("zone", "area")
        groups = Set{Int}()
        for (_, bus) in network_data["bus"]
            push!(groups, Int(bus[group_kind]))
        end
        length(groups) > 1 && return group_kind
    end
    return "zone"
end

"Names of the case's zone or area records (`group_kind` \"zone\" or \"area\"), by index."
function find_group_names(network_data, group_kind::AbstractString)
    group_kind in ("zone", "area") || error("unknown group kind \"$group_kind\", use \"zone\" or \"area\"")
    records_key = group_kind == "zone" ? "zone" : "area interchange"
    name_field = group_kind == "zone" ? "zoname" : "arname"
    names = Dict{Int,String}()
    for (_, record) in get(network_data, records_key, Dict())
        names[Int(record["i"])] = strip(string(record[name_field]))
    end
    return names
end

"Generation sums (pu) with the used shares of Pmax and Qmax (%, 0 when the maximum is 0)."
function calc_generation_shares(sums)
    pg = sums["pg"]
    pmax = sums["pmax"]
    qg = sums["qg"]
    qmax = sums["qmax"]
    return Dict{String,Any}(
        "pg" => pg, "pmax" => pmax, "qg" => qg, "qmax" => qmax,
        "p_used_pct" => pmax > 0 ? 100 * pg / pmax : 0.0,
        "q_used_pct" => qmax > 0 ? 100 * qg / qmax : 0.0,
    )
end

"""
    calc_generation_status(network_data, result; group_kind="zone")

Generation of the in-service generators (pu): `"groups"` (index, name, pg, pmax, qg, qmax and the
used shares in %), sorted by index, and `"total"` for the whole network. The groups are the zone or
area records of the case, plus, when the buses are in more than one group, the groups that have
no record (named by their number); none for a case without records and with one group.
`pg`/`qg` come from the solution, `pmax`/`qmax` from `network_data["gen"]`.
"""
function calc_generation_status(network_data, result; group_kind::AbstractString="zone")
    gens = get(network_data, "gen", Dict())
    sol_gens = get(get(result, "solution", Dict()), "gen", Dict())
    group_name_by_index = find_group_names(network_data, group_kind)

    group_by_bus = Dict{Int,Int}()
    for (_, bus) in get(network_data, "bus", Dict())
        group_by_bus[Int(bus["bus_i"])] = Int(get(bus, group_kind, 0))
    end

    # sums over the in-service generators, for the whole network and per group
    total = Dict("pg" => 0.0, "pmax" => 0.0, "qg" => 0.0, "qmax" => 0.0)
    group_sums = Dict{Int,Dict{String,Float64}}()
    for (gen_id, g) in gens
        get(g, "gen_status", 1) == 0 && continue
        g_sol = get(sol_gens, gen_id, get(sol_gens, string(gen_id), Dict()))
        pg = get(g_sol, "pg", 0.0)
        pmax = get(g, "pmax", 0.0)
        qg = get(g_sol, "qg", 0.0)
        qmax = get(g, "qmax", 0.0)
        total["pg"] += pg
        total["pmax"] += pmax
        total["qg"] += qg
        total["qmax"] += qmax

        group_index = get(group_by_bus, Int(get(g, "gen_bus", 0)), 0)
        group_index == 0 && continue
        sums = get!(group_sums, group_index, Dict("pg" => 0.0, "pmax" => 0.0, "qg" => 0.0, "qmax" => 0.0))
        sums["pg"] += pg
        sums["pmax"] += pmax
        sums["qg"] += qg
        sums["qmax"] += qmax
    end

    # the records, and the groups the buses use without a record when they use more than one
    group_indices = Set(keys(group_name_by_index))
    bus_groups = setdiff(Set(values(group_by_bus)), [0])
    if length(bus_groups) > 1
        union!(group_indices, bus_groups)
    end

    groups = Dict{String,Any}[]
    for group_index in sort(collect(group_indices))
        sums = get(group_sums, group_index, Dict("pg" => 0.0, "pmax" => 0.0, "qg" => 0.0, "qmax" => 0.0))
        group = calc_generation_shares(sums)
        group["index"] = group_index
        group["name"] = get(group_name_by_index, group_index, string(group_index))
        push!(groups, group)
    end

    return Dict{String,Any}(
        "group_kind" => group_kind,
        "groups" => groups,
        "total" => calc_generation_shares(total),
    )
end

"""
    print_generation_status(network_data, result; group_kind="zone")

Print active generation status by zone or area (`group_kind`, see `find_group_kind`; from
`calc_generation_status`):
- P: `Pg`, `Pmax`, used % of `Pmax` (printed as `Used`); `Pg` from `result["solution"]["gen"]`
- Q: `Qg`, `Qmax`, used % of `Qmax` (printed as `Used`, after the Q values); `Qg` from solution

`Pmax` and `Qmax` still come from `network_data["gen"]`. Inactive generators are skipped.

If the network data has no such groups, print the same values for the whole network.
"""
function print_generation_status(network_data, result; group_kind::AbstractString="zone")
    status = calc_generation_status(network_data, result; group_kind=group_kind)

    if isempty(status["groups"])
        total = status["total"]
        println("Generation status (whole network):")
        println(
            "Network: Pg=$(round(total["pg"], digits=4)), " *
            "Pmax=$(round(total["pmax"], digits=4)), " *
            "Used=$(round(total["p_used_pct"], digits=2))%, " *
            "Qg=$(round(total["qg"], digits=4)), " *
            "Qmax=$(round(total["qmax"], digits=4)), " *
            "Used=$(round(total["q_used_pct"], digits=2))%",
        )
        return
    end

    println("Generation status by $(group_kind):")
    println(@sprintf("%-16s %-12.4s %-12.4s %-12s %-12s %-10s %-10s", titlecase(group_kind), "Pg", "Pmax", "Used", "Qg", "Qmax", "Used"))
    for group in status["groups"]
        group_name = group["name"]
        pg_total = group["pg"]
        pmax_total = group["pmax"]
        qg_total = group["qg"]
        qmax_total = group["qmax"]
        p_used_pct = group["p_used_pct"]
        q_used_pct = group["q_used_pct"]
        # println(
        #     @sprintf("%-10s ", group_name) *
        #     @sprintf("%-10.4f ", pg_total) *
        #     @sprintf("%-10.4f ", pmax_total) *
        #     @sprintf("%-10.2f%% ", p_used_pct) *
        #     @sprintf("%-10.4f ", qg_total) *
        #     @sprintf("%-10.4f ", qmax_total) *
        #     @sprintf("%-10.2f%% ", q_used_pct))
        println(@sprintf(
            "%-10s %12.4f %12.4f %10.2f%% %12.4f %12.4f %10.2f%%",
            group_name,
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
        if (zone_buses === nothing || Int(l["load_bus"]) in zone_buses) &&
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

"""
    calc_load_shedding_status(result, network_data; group_kind="zone")

Load shedding of a solved run (pu): `"loads"` that shed (id, bus, pd, served_pd, shed,
planned_shed, forced_shed, shed_pct in %), in the order of `network_data["load"]`; `"groups"`, one
per zone or area that has load (index, name, load, shed, planned_shed, forced_shed), sorted by
index; the totals; and `"has_split_shedding"` (the solution splits planned and forced shedding).

A load belongs to its bus's zone or area, like the boundary (a RAW load record can name another
area, e.g. the two loads at savnw bus 154).
"""
function calc_load_shedding_status(result, network_data; group_kind::AbstractString="zone")
    sol_loads = get(get(result, "solution", Dict()), "load", Dict())
    has_split_shedding = any(
        haskey(load_sol, "planned_shed") || haskey(load_sol, "forced_shed")
        for (_, load_sol) in sol_loads
    )
    group_name_by_index = find_group_names(network_data, group_kind)
    group_by_bus = Dict{Int,Int}()
    for (_, bus) in get(network_data, "bus", Dict())
        group_by_bus[Int(bus["bus_i"])] = Int(get(bus, group_kind, 0))
    end

    total_shed = 0.0
    total_planned_shed = 0.0
    total_forced_shed = 0.0
    total_load = 0.0
    group_total_load = Dict{Int,Float64}()
    group_total_shed = Dict{Int,Float64}()
    group_total_planned_shed = Dict{Int,Float64}()
    group_total_forced_shed = Dict{Int,Float64}()
    shed_loads = Dict{String,Any}[]
    for (i, load) in network_data["load"]
        total_load += load["pd"]
        load_bus = Int(load["load_bus"])
        group_index = get(group_by_bus, load_bus, 0)
        if group_index != 0
            group_total_load[group_index] = get(group_total_load, group_index, 0.0) + load["pd"]
        end
        haskey(sol_loads, i) && haskey(sol_loads[i], "status") || continue
        status = sol_loads[i]["status"]
        status >= 1.0 && continue

        original_pd = load["pd"]
        served_pd = get(sol_loads[i], "pd", original_pd * status)
        shed_amount = original_pd - served_pd
        planned_shed_amount = 0.0
        forced_shed_amount = 0.0
        if has_split_shedding
            planned_shed_amount = original_pd * get(sol_loads[i], "planned_shed", 0.0)
            forced_shed_amount = original_pd * get(sol_loads[i], "forced_shed", 0.0)
        end
        total_shed += shed_amount
        total_planned_shed += planned_shed_amount
        total_forced_shed += forced_shed_amount
        if group_index != 0
            group_total_shed[group_index] = get(group_total_shed, group_index, 0.0) + shed_amount
            group_total_planned_shed[group_index] = get(group_total_planned_shed, group_index, 0.0) + planned_shed_amount
            group_total_forced_shed[group_index] = get(group_total_forced_shed, group_index, 0.0) + forced_shed_amount
        end
        push!(shed_loads, Dict{String,Any}(
            "id" => i,
            "bus" => load_bus,
            "pd" => original_pd,
            "served_pd" => served_pd,
            "shed" => shed_amount,
            "planned_shed" => planned_shed_amount,
            "forced_shed" => forced_shed_amount,
            "shed_pct" => (shed_amount / original_pd) * 100,
        ))
    end

    groups = Dict{String,Any}[]
    for group_index in sort(collect(keys(group_total_load)))
        push!(groups, Dict{String,Any}(
            "index" => group_index,
            "name" => get(group_name_by_index, group_index, "$(titlecase(group_kind)) $group_index"),
            "load" => group_total_load[group_index],
            "shed" => get(group_total_shed, group_index, 0.0),
            "planned_shed" => get(group_total_planned_shed, group_index, 0.0),
            "forced_shed" => get(group_total_forced_shed, group_index, 0.0),
        ))
    end

    return Dict{String,Any}(
        "group_kind" => group_kind,
        "has_split_shedding" => has_split_shedding,
        "loads" => shed_loads,
        "groups" => groups,
        "total_load" => total_load,
        "total_shed" => total_shed,
        "total_planned_shed" => total_planned_shed,
        "total_forced_shed" => total_forced_shed,
    )
end

"""
Print the load shedding of a solved run (`calc_load_shedding_status`): by zone or area
(`group_kind`, see `find_group_kind`), the total, and each shed load when `detailed`.
"""
function print_load_shedding_status(result, modified_network_data, detailed=false; group_kind::AbstractString="zone")
    println("Load shedding results:")
    status = calc_load_shedding_status(result, modified_network_data; group_kind=group_kind)
    has_split_shedding = status["has_split_shedding"]
    if detailed
        println("---  Load Serving Status by Bus ---")
        if has_split_shedding
            println("Bus \t PDn \t PD \t Shed \t Planned \t Forced \t Shed Percentage")
        else
            println("Bus \t PDn \t PD \t Shed \t Shed Percentage")
        end
        for load in status["loads"]
            load_bus = load["bus"]
            original_pd = load["pd"]
            served_pd = load["served_pd"]
            shed_amount = load["shed"]
            shed_percentage = load["shed_pct"]
            if has_split_shedding
                println("$(load_bus) \t $(round(original_pd, digits=2)) \t $(round(served_pd, digits=2)) \t $(round(shed_amount, digits=2)) \t $(round(load["planned_shed"], digits=2)) \t $(round(load["forced_shed"], digits=2)) \t $(round(shed_percentage, digits=2))%")
            else
                println("$(load_bus) \t $(round(original_pd, digits=2)) \t $(round(served_pd, digits=2)) \t $(round(shed_amount, digits=2)) \t $(round(shed_percentage, digits=2))%")
            end
        end
    end
    total_shed = status["total_shed"]
    total_planned_shed = status["total_planned_shed"]
    total_forced_shed = status["total_forced_shed"]
    total_load = status["total_load"]
    base_mva = modified_network_data["baseMVA"]
    if !isempty(status["groups"])
        println("---  Load Shed by $(titlecase(group_kind)) ---")
        for group in status["groups"]
            group_name = group["name"]
            group_shed_mw = round(group["shed"] * base_mva, digits=2)
            group_planned_shed_mw = round(group["planned_shed"] * base_mva, digits=2)
            group_forced_shed_mw = round(group["forced_shed"] * base_mva, digits=2)
            group_load_mw = round(group["load"] * base_mva, digits=2)
            if has_split_shedding
                println(@sprintf(
                    "%-10s: total %12.4f planned %12.4f forced %12.4f load %12.4f %10.2f%%",
                    group_name,
                    group_shed_mw,
                    group_planned_shed_mw,
                    group_forced_shed_mw,
                    group_load_mw,
                    round(group_shed_mw / group_load_mw * 100, digits=2)
                ))
            else
                println(@sprintf(
                    "%-10s: %12.4f %12.4f %10.2f%%",
                    group_name,
                    group_shed_mw,
                    group_load_mw,
                    round(group_shed_mw / group_load_mw * 100, digits=2)
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
