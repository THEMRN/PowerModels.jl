
using PowerModels
using Ipopt
include("../utils.jl")


casefile = "cases/psse/ACTIVSg500/ACTIVSg500.raw"
network_data = PowerModels.parse_file("$(casefile)", import_all=true);

modified_network_data = deepcopy(network_data)

# any modifications to the network data here
target_lines = find_branches_by_zone(network_data, "clumabia")
scale_loads!(modified_network_data, 0.01, "GREENVIL")
for line in target_lines
    modified_network_data["branch"]["$(line)"]["br_status"] = 0
end
# ---------------------------------------------

result = PowerModels.solve_pf(modified_network_data, ACPPowerModel, Ipopt.Optimizer)
