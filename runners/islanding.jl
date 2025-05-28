using PowerModels
using Ipopt
using JuMP
using JSON3
using Plots
# gr()
plotly()


casefile = "case9.m"
opf_model = "AC"
objective = "opf_flow"  # "opf", "flow", "opf_flow"
target_lines = [8, 2, 5]
range = 0:50:5000
# range = 0:50:50

const ObjectiveType = Dict(
    "opf" => "opf",
    "flow" => "flow",
    "opf_flow" => "opf_flow",
)

const PowerModelType = Dict(
    "DC" => DCPPowerModel,
    "AC" => ACPPowerModel,
)

network_data = PowerModels.parse_file("test/data/matpower/$(casefile)");
network_data["objective"] = ObjectiveType[objective]
network_data["target_ids"] = target_lines
network_data["opf_model"] = opf_model
power_model = PowerModelType[opf_model]

# network_data["lambda"] = 159.9262466    # for bus 6
# network_data["lambda"] = 159.926246645    # for bus 5
# network_data["lambda"] = 488   # for bus 2

objectives = []
branch_ids = sort(collect(keys(network_data["branch"])))    # get all branch ids as strings
gen_ids = sort(collect(keys(network_data["gen"])))          # get all generator ids as strings
all_flows = [Float64[] for _ in branch_ids]                 # one array per branch
all_generations = [Float64[] for _ in gen_ids]                 # one array per branch
result = nothing

for l in range
    network_data["lambda"] = l
    global result = PowerModels.solve_custom_opf(network_data, power_model, Ipopt.Optimizer)

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

plt1 = plot(range, objectives, ylabel="Objective", label="cost", legend=:outerright)
plt2 = plot(ylabel="Branch Flow", legend=:outerright)
plt3 = plot(xlabel="Lambda", ylabel="Generation", legend=:outerright, ylims=(-1, 3))
for (j, bid) in enumerate(branch_ids)
    plot!(plt2, range, all_flows[j], label="Branch $bid")
end
for (j, bid) in enumerate(gen_ids)
    plot!(plt3, range, all_generations[j], label="Generator $bid")
end

plot(plt1, plt2, plt3, layout=(3, 1))

# println("---------------------------")
# println("objective:", result["objective"])
# PowerModels.print_summary(result["solution"])

# pm = instantiate_model(network_data, DCPPowerModel, PowerModels.build_opf)
