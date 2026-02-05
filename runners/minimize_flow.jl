
using PowerModels
using Ipopt
using JuMP
using JSON3
using Plots
include("utils.jl")
plotly()
# gr()


# settings ------------------------------------
casefile = "cases/psse/savnw/savnw.raw"
network_data = PowerModels.parse_file("$(casefile)");
opf_model = "AC"
objective = "flow"  # "opf", "flow", "opf_flow", "opf_flow_shedd"
# target_lines = find_branches_by_bus_pairs(network_data, [(3001, 3002), (3005, 3004), (3005, 3006), (3005, 3008), (3005, 3007)]) # island on top
# target_lines = find_branches_by_bus_pairs(network_data, [(3007, 3008), (154, 3008), (3005, 3008)]) # island on left
# target_lines = find_branches_by_bus_pairs(network_data, [(201, 151), (201, 202), (205, 203), (205, 154)]) # island on bottom
target_lines = find_branches_by_bus_pairs(network_data, [(154, 3008), (154, 153), (152, 153), (152, 3004)]) # north-south seperation    
max_lambda = 500000
step = 5000
range = 0:step:max_lambda
p_model = "squared"         # "normal", "squared"
uniform_penalty = 10
uniform_shedding = true
# ----------------------------------------------
modified_network_data = deepcopy(network_data)
# modified_network_data = add_load_shedding_penalty(
#     network_data;
#     uniform=uniform_shedding,
#     uniform_penalty=uniform_penalty,
#     # penalties=load_shedding_penalties
# )
# network modifications
# modified_network_data["load"]["6"]["pd"] = 4.0    # for the top island case make it more stable       load default: 1.0, pmax: 9.0 
# modified_network_data["load"]["8"]["pd"] = 1.0      # for the left side case, so the gen can supply     load default: 2.0, pmax: 1.17
# modified_network_data["load"]["5"]["pd"] = 10.0    # for the bottom side case                         load default: 12.0, pmax: 15:16
# modified_network_data["load"]["5"]["qd"] = 1.0    # for the bottom side case                          load default: 12.0, pmax: 15:16
# ----------------------------------------------

const ObjectiveType = Dict(
    "opf" => "opf",
    "flow" => "flow",
    "opf_flow" => "opf_flow",
    "opf_flow_shedd" => "opf_flow_shedd",
)

const PowerModelType = Dict(
    "DC" => DCPPowerModel,
    "AC" => ACPPowerModel,
)

modified_network_data["objective"] = ObjectiveType[objective]
modified_network_data["target_ids"] = target_lines
modified_network_data["opf_model"] = opf_model
modified_network_data["p_model"] = p_model
power_model = PowerModelType[opf_model]

objectives = []
branch_ids = sort(collect(keys(modified_network_data["branch"])))    # get all branch ids as strings
gen_ids = sort(collect(keys(modified_network_data["gen"])))          # get all generator ids as strings
all_flows = [Float64[] for _ in branch_ids]                 # one array per branch
all_generations = [Float64[] for _ in gen_ids]              # one array per branch
result = nothing

for l in range
    modified_network_data["lambda"] = l
    global result = PowerModels.solve_custom_opf(modified_network_data, power_model, Ipopt.Optimizer)

    obj = result["objective"]
    push!(objectives, obj)

    for (j, bid) in enumerate(branch_ids)
        sf = get(result["solution"]["branch"], bid, Dict())["pf"]
        if opf_model == "AC"
            qf = get(result["solution"]["branch"], bid, Dict())["qf"]
            sf = (sf^2 + qf^2)^0.5
        end
        push!(all_flows[j], abs(sf))
    end

    for (j, gid) in enumerate(gen_ids)
        pg = get(result["solution"]["gen"], gid, Dict())["pg"]
        push!(all_generations[j], abs(pg))
    end
end

println("---------------------------")
println("target lines: ", target_lines)

plt1 = plot(range, objectives, ylabel="Objective", label="obj", legend=:outerright)
plt2 = plot(ylabel="Branch Flow", legend=:outerright)
plt3 = plot(xlabel="Lambda", ylabel="Generation", legend=:outerright)
for (j, bid) in enumerate(branch_ids)
    plot!(plt2, range, all_flows[j], label="Branch $bid")
end
for (j, bid) in enumerate(gen_ids)
    plot!(plt3, range, all_generations[j], label="Generator $bid")
end
plot(plt1, plt2, plt3, layout=(3, 1))

