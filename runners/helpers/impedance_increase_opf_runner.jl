using PowerModels
using Ipopt
using JuMP
using JSON3
include("../utils.jl")
include("../excel_generator.jl")

casefile = "results/psse/ACTIVSG500_flow_shed/ACTIVSG500_flow_shed.raw"
network_data = PowerModels.parse_file(casefile, import_all=true);

target_lines = find_branches_by_zone(network_data, "YORK")
branch_ids = [string(line) for line in target_lines]

# Controls for the gradual outage workflow.
impedance_change_rate = 1.1
impedance_change_iterations = 40
solver = JuMP.optimizer_with_attributes(Ipopt.Optimizer, "print_level" => 3, "sb" => "yes")

result = PowerModels.solve_ac_pf(network_data, solver)
PowerModels.update_data!(network_data, result["solution"])
PowerModels.set_ac_pf_start_values!(network_data)

for iter in 1:impedance_change_iterations
    println("Impedance ramp step $iter / $impedance_change_iterations")
    for branch_id in branch_ids
        network_data["branch"][branch_id]["br_r"] *= impedance_change_rate
        network_data["branch"][branch_id]["br_x"] *= impedance_change_rate
    end

    result = PowerModels.solve_ac_pf(network_data, solver)
    if result["termination_status"] != LOCALLY_SOLVED
        println("Stopped at iteration $iter, total impedance increased by $(impedance_change_rate^iter)")
        error("Solver terminated with status $(result["termination_status"])")
    end

    PowerModels.update_data!(network_data, result["solution"])
    PowerModels.set_ac_pf_start_values!(network_data)
end

for branch_id in branch_ids
    network_data["branch"][branch_id]["br_status"] = 0
end

result = PowerModels.solve_ac_pf(network_data, solver)
PowerModels.update_data!(network_data, result["solution"])
PowerModels.set_ac_pf_start_values!(network_data)
# PowerModels.print_summary(result["solution"])

output_path = "results/psse/ACTIVSG500_flow_shed/tmp"
mkpath(output_path)
excel_file = "$output_path/pm_pf.xlsx"
create_excel_report(result, network_data, excel_file, powerworld=false)
println("Excel file created successfully!")
