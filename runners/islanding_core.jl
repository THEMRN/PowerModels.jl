# Shared islanding pipeline: settings embedding, solve, reports, voltage
# prediction, and PSSE export. Used by islanding.jl (single run) and
# batch_islanding.jl (multiple runs in one session).

# define objectives and power model modes
if !@isdefined(ObjectiveType)
    const ObjectiveType = Dict(
        "pf" => "opf",
        "opf" => "opf",
        "flow" => "flow",
        "opf_flow" => "opf_flow",
        "opf_shed" => "opf_shed",
        "flow_shed" => "flow_shed",
        "opf_flow_shed" => "opf_flow_shed",
    )
end
if !@isdefined(PowerModelType)
    const PowerModelType = Dict(
        "DC" => DCPPowerModel,
        "AC" => ACPPowerModel,
    )
end

# Jacobian voltage prediction -------------------------------------------------
function predict_voltage_change_from_opened_lines(network_data, result, target_lines)
    #Only buses connected to opened lines get nonzero dP/dQ.
    #For each opened line, the endpoint bus injection change is that endpoint's solved line flow.
    #Then predicted dV = S_pv*dP + S_qv*dQ for every bus in the system.
    solved_data = deepcopy(network_data)
    PowerModels.update_data!(solved_data, result["solution"])
    base_mva = Float64(solved_data["baseMVA"])

    # Build the voltage sensitivity matrices around the solved operating point.
    basic = make_basic_network(solved_data)
    buses = sort(collect(values(basic["bus"])), by=bus -> bus["index"])
    n = length(buses)
    bus_ids = [parse(Int, string(get(bus, "source_id", ["", bus["bus_i"]])[2])) for bus in buses]
    bus_to_idx = Dict(bus => idx for (idx, bus) in enumerate(bus_ids))

    J = Matrix(calc_basic_jacobian_matrix(basic))
    H = J[1:n, 1:n]              # dP/dtheta
    N = J[1:n, (n+1):2n]           # dP/dV
    M = J[(n+1):2n, 1:n]           # dQ/dtheta
    L = J[(n+1):2n, (n+1):2n]        # dQ/dV
    K = L - M * (H \ N)
    S_pv = -(K \ (M / H))        # dV/dP after eliminating angle changes
    S_qv = inv(K)                # dV/dQ after eliminating angle changes

    # model: Opening a line removes the endpoint flows that were connected
    # to each endpoint bus. Only buses touched by opened lines get nonzero dP/dQ.
    delta_p = zeros(n)
    delta_q = zeros(n)
    opened_buses = Set{Int}()
    opened_line_count = Dict{Int,Int}()

    for line in target_lines
        branch = solved_data["branch"][string(line)]
        flow = result["solution"]["branch"][string(line)]
        f_bus = Int(branch["f_bus"])
        t_bus = Int(branch["t_bus"])

        for (bus, p_key, q_key) in ((f_bus, "pf", "qf"), (t_bus, "pt", "qt"))
            idx = get(bus_to_idx, bus, nothing)
            idx === nothing && continue
            delta_p[idx] += Float64(get(flow, p_key, 0.0))
            delta_q[idx] += Float64(get(flow, q_key, 0.0))
            push!(opened_buses, bus)
            opened_line_count[bus] = get(opened_line_count, bus, 0) + 1
        end
    end

    # Propagate the endpoint injection changes to voltage changes at all buses.
    delta_v_from_p = S_pv * delta_p
    delta_v_from_q = S_qv * delta_q
    delta_v = delta_v_from_p + delta_v_from_q

    rows = [
        Dict(
            :bus => bus_ids[i],
            :vm0 => Float64(buses[i]["vm"]),
            :delta_p => delta_p[i],
            :delta_q => delta_q[i],
            :delta_v_from_p => delta_v_from_p[i],
            :delta_v_from_q => delta_v_from_q[i],
            :delta_v => delta_v[i],
            :predicted_vm => Float64(buses[i]["vm"]) + delta_v[i],
            :is_opened_endpoint => bus_ids[i] in opened_buses,
            :opened_line_count => get(opened_line_count, bus_ids[i], 0),
        )
        for i in 1:n
    ]

    endpoint_rows = filter(row -> row[:is_opened_endpoint], rows)
    worst = rows[argmax(abs.([row[:delta_v] for row in rows]))]
    min_vm = rows[argmin([row[:predicted_vm] for row in rows])]
    max_vm = rows[argmax([row[:predicted_vm] for row in rows])]

    println("---------------------------")
    println("Voltage prediction from opened-line endpoint injection changes")
    println("Opened line ids: ", join(target_lines, ", "))
    println(
        "Total endpoint injection change: dP=$(round(sum(delta_p) * base_mva, digits=3)) MW, " *
            "dQ=$(round(sum(delta_q) * base_mva, digits=3)) MVar",
    )
    println(
        "Predicted voltage range: min=$(round(min_vm[:predicted_vm], digits=5)) pu at bus $(min_vm[:bus]), " *
            "max=$(round(max_vm[:predicted_vm], digits=5)) pu at bus $(max_vm[:bus])",
    )
    println(
        "Worst |dV|: bus $(worst[:bus]), dV=$(round(worst[:delta_v], digits=5)) pu " *
            "(from P=$(round(worst[:delta_v_from_p], digits=5)), from Q=$(round(worst[:delta_v_from_q], digits=5)))",
    )

    println("Opened endpoint buses:")
    println(@sprintf("%-8s %-8s %-12s %-12s %-12s %-12s", "Bus", "Lines", "dP MW", "dQ MVar", "dV", "Vm pred"))
    for row in sort(endpoint_rows, by=row -> abs(row[:delta_p]) + abs(row[:delta_q]), rev=true)[1:min(20, length(endpoint_rows))]
        println(@sprintf(
            "%-8d %-8d %-12.3f %-12.3f %-12.5f %-12.5f",
            row[:bus],
            row[:opened_line_count],
            row[:delta_p] * base_mva,
            row[:delta_q] * base_mva,
            row[:delta_v],
            row[:predicted_vm],
        ))
    end

    println("Largest predicted voltage changes anywhere in the system:")
    println(@sprintf("%-8s %-12s %-12s %-12s %-12s", "Bus", "Vm0", "dV", "Vm pred", "Endpoint?"))
    for row in sort(rows, by=row -> abs(row[:delta_v]), rev=true)[1:min(10, length(rows))]
        println(@sprintf(
            "%-8d %-12.5f %-12.5f %-12.5f %-12s",
            row[:bus],
            row[:vm0],
            row[:delta_v],
            row[:predicted_vm],
            row[:is_opened_endpoint] ? "yes" : "no",
        ))
    end
    println("---------------------------")

    return Dict(:rows => rows, :endpoint_rows => endpoint_rows, :delta_p => delta_p, :delta_q => delta_q, :delta_v => delta_v)
end

"""
    run_islanding(network_data; kwargs...)

Run the full islanding pipeline on `network_data` (which is mutated: settings
are embedded and, when `run_dynamic_sim=true`, the solution is written back into it).
Load shedding penalties are expected to already be applied to the network via
`add_load_shedding_penalty!` before calling this function.

`output_tag` optionally suffixes the results folder so multiple runs with the
same case/objective don't overwrite each other.

`frequency_security=true` limits each island's scheduled import by its RoCoF,
quasi-steady-state and nadir bounds (see frequency.jl); it needs the case .dyr.

`simulator` picks the dynamic simulation run after the export: "psse"
(psse_scripts/dynamic.py) or "andes" (andes_scripts/dynamic.py).

Returns the solve `result`.
"""
function run_islanding(network_data;
    case_name::AbstractString,
    case_files,
    objective::AbstractString,
    lambda::Real,
    opf_model::AbstractString,
    flow_model::AbstractString,
    target_lines,
    run_dynamic_sim::Bool,
    uniform_shedding::Bool=false,
    uniform_penalty::Real=0.0,
    load_shedding_penalties=Dict(),
    target_zone=nothing,
    selected_buses=nothing,
    output_tag=nothing,
    frequency_security::Bool=false,
    simulator::AbstractString="psse",
)
    simulator in ("psse", "andes") || error("unknown simulator \"$simulator\", use \"psse\" or \"andes\"")

    # embed additional configurations in the network data
    network_data["objective"] = ObjectiveType[objective]
    network_data["target_ids"] = target_lines
    network_data["opf_model"] = opf_model
    network_data["p_model"] = flow_model
    if selected_buses !== nothing
        network_data["target_zone_buses"] = selected_buses
    end
    power_model = PowerModelType[opf_model]
    network_data["lambda"] = lambda

    # frequency limits on each island's import, computed offline once per island
    if frequency_security
        case_files.dyr === nothing && error("frequency_security needs the case .dyr file (inertia and governor droop)")
        add_frequency_security!(network_data, target_lines, case_files.dyr)
    end

    # solve the power flow
    optimizer = optimizer_with_attributes(Ipopt.Optimizer, "print_level" => 4)
    result = PowerModels.solve_custom_opf(network_data, power_model, optimizer)
    println("---------------------------")
    println("Power Flow Solved")
    println("objective:", result["objective"])

    # log flow results and load shedding status
    print_generation_status(network_data, result)
    if occursin("shed", objective)
        print_load_shedding_status(result, network_data)
    end
    if target_zone !== nothing
        print_branch_flows(result, network_data, target_lines, false, target_zone)
    else
        print_branch_flows(result, network_data, target_lines)
    end
    if frequency_security
        print_frequency_security(network_data, result)
    end
    println("---------------------------")

    # generate excel report
    output_path = "results/psse/$(case_name)_$(objective)"
    if output_tag !== nothing && !isempty(string(output_tag))
        output_path *= "_$(output_tag)"
    end
    mkpath(output_path)

    # write run information for the python report header
    run_info = Dict{String,Any}(
        "objective" => objective,
        "flow_model" => flow_model,
        "uniform_shedding" => uniform_shedding,
        "frequency_security" => frequency_security,
    )
    if target_zone !== nothing
        run_info["target_zone"] = target_zone
    end
    if uniform_shedding
        run_info["uniform_penalty_rel"] = lambda != 0 ? uniform_penalty / lambda : uniform_penalty
    elseif !isempty(load_shedding_penalties) && lambda != 0
        ratios = sort(unique(round.(collect(values(load_shedding_penalties)) ./ lambda, digits=4)))
        run_info["shed_penalty_rel"] = length(ratios) == 1 ? ratios[1] : ratios
        if selected_buses !== nothing
            penalized_buses = Set(parse(Int, k) for k in keys(load_shedding_penalties))
            zone_buses = Set(selected_buses)
            if issubset(penalized_buses, zone_buses)
                run_info["shed_penalty_scope"] = "inside zone"
            elseif isempty(intersect(penalized_buses, zone_buses))
                run_info["shed_penalty_scope"] = "outside zone"
            else
                run_info["shed_penalty_scope"] = "mixed"
            end
        end
    end
    if occursin("shed", objective)
        sol_loads = get(get(result, "solution", Dict()), "load", Dict())
        preemptive_shed = sum(
            (load["pd"] - get(sol_loads[i], "pd", load["pd"] * sol_loads[i]["status"])
             for (i, load) in network_data["load"]
             if haskey(sol_loads, i) && haskey(sol_loads[i], "status") && sol_loads[i]["status"] < 1.0);
            init=0.0,
        )
        run_info["preemptive_shed_mw"] = round(preemptive_shed * Float64(network_data["baseMVA"]), digits=2)
    end
    open("$output_path/run_info.json", "w") do io
        JSON3.write(io, run_info)
    end
    excel_file = "$output_path/pm_res_$(objective)_$(get_timestamp()).xlsx"
    create_excel_report(result, network_data, excel_file, powerworld=true)
    println("Excel file created successfully!")

    voltage_prediction = predict_voltage_change_from_opened_lines(network_data, result, target_lines)

    # dynamic simulation -------------------------------------------------------------
    if run_dynamic_sim
        # generate psse raw file
        PowerModels.update_data!(network_data, result["solution"])
        pti_network_data = prepare_for_pti_export(network_data)
        raw_file = "$(output_path)/$(case_name)_$(objective).raw"
        PowerModels.export_pti(raw_file, pti_network_data)
        println("Raw file created successfully!")

        # generate line outage file
        line_outage_file = "$(output_path)/line_outage.json"
        outages = Vector{Dict{String,Any}}()
        for br_id in target_lines
            branch = network_data["branch"][string(br_id)]
            src = branch["source_id"]  # expected: (from, to, id)
            line_type = src[1]
            id_idx = line_type == "branch" ? 4 : 5
            push!(outages, Dict(
                "from" => src[2],
                "to" => src[3],
                "id" => src[id_idx],
            ))
        end
        open(line_outage_file, "w") do io
            JSON3.write(io, outages)
        end
        println("Line outage file created successfully!")

        # copy dyr file if available
        if case_files.dyr !== nothing
            dest = joinpath(output_path, "$(case_name)_$(objective).dyr")
            cp(case_files.dyr, dest, force=true)
            println("Dyr file copied successfully!")
            dyr_file = dest
        else
            println("No dyr file found, skipping dynamic simulation.")
            dyr_file = ""
        end

        # call python dynamic simulation script
        println("Running $simulator simulation script...")
        python_script = joinpath(@__DIR__, "$(simulator)_scripts", "dynamic.py")
        simulation_seconds = @elapsed run(`python $python_script $raw_file $dyr_file $excel_file`)
        println("$simulator simulation script finished in $(round(simulation_seconds, digits=1)) s")
    end

    return result
end
