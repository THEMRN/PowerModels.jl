using PowerModels
using Ipopt
include("../utils.jl")


casefile = "cases/psse/ACTIVSg500/ACTIVSg500.raw"
network_data = PowerModels.parse_file("$(casefile)", import_all=true);
uniform = false;
penalty = 1;
load_shedding_penalties = Dict();
target_buses = find_buses_by_zone(network_data, "clemson")
for bus in target_buses
    load_shedding_penalties[string(bus)] = 0
end
add_load_shedding_penalty!(network_data, uniform=uniform, uniform_penalty=penalty, penalties=load_shedding_penalties)
result = PowerModels.solve_load_shedding_opf(network_data, ACPPowerModel, Ipopt.Optimizer)
print_load_shedding_status(result, network_data)