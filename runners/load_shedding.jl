using PowerModels

# scenario: Reduce generation capacity to force load shedding
function create_load_shedding_test_case(network_data)
    test_data = deepcopy(network_data)
    test_data["gen"]["1"]["pmax"] = 5
    test_data["gen"]["2"]["pmax"] = 5
    test_data["gen"]["3"]["pmax"] = 5
    test_data["load"]["1"]["pd"] = 0.5
    test_data["load"]["2"]["pd"] = 3
    test_data["load"]["3"]["pd"] = 0.5
    test_data["load"]["1"]["qd"] = 0.4
    test_data["load"]["2"]["qd"] = 0.4
    test_data["load"]["3"]["qd"] = 0.4
    test_data["load"]["1"]["shed_penalty"] = 0
    test_data["load"]["2"]["shed_penalty"] = 0
    test_data["load"]["3"]["shed_penalty"] = 0

    # for (i, gen) in test_data["gen"]
    #     gen["pmax"] = gen["pmax"] * 1
    #     gen["qmax"] = gen["qmax"] * 1
    # end


    return test_data
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

const PowerModelType = Dict(
    "DC" => DCPPowerModel,
    "AC" => ACPPowerModel,
)
casefile = "case9.m"
network_data = PowerModels.parse_file("test/data/matpower/$(casefile)");
power_model = PowerModelType["AC"]
test_network_data = create_load_shedding_test_case(network_data)
result = PowerModels.solve_load_shedding_opf(test_network_data, power_model, Ipopt.Optimizer)
analyze_load_shedding_results(result, test_network_data)