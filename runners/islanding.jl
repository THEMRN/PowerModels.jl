using PowerModels
using Ipopt
using JuMP
using JSON3
using Plots
plotly()
# gr()
using Dates
using XLSX
include("excel_generator.jl")
include("line_flow.jl")

# settings ------------------------------------
casefile = "case9.m"
opf_model = "AC"
objective = "flow"  # "opf", "flow", "opf_flow"
target_lines = [2, 5]
range = 0:50:5000
range = 1:1:1
p_model = "squared"         # "normal", "squared"
# ----------------------------------------------

network_data = PowerModels.parse_file("test/data/matpower/$(casefile)");
# network modifications
network_data["gen"]["1"]["pmax"] = 5
network_data["gen"]["2"]["pmax"] = 5
network_data["gen"]["3"]["pmax"] = 5
network_data["load"]["1"]["pd"] = 0.5
network_data["load"]["2"]["pd"] = 3
network_data["load"]["3"]["pd"] = 0.5
network_data["load"]["1"]["qd"] = 0.4
network_data["load"]["2"]["qd"] = 0.4
network_data["load"]["3"]["qd"] = 0.4
# ----------------------------------------------

const ObjectiveType = Dict(
    "opf" => "opf",
    "flow" => "flow",
    "opf_flow" => "opf_flow",
)

const PowerModelType = Dict(
    "DC" => DCPPowerModel,
    "AC" => ACPPowerModel,
)

network_data["objective"] = ObjectiveType[objective]
network_data["target_ids"] = target_lines
network_data["opf_model"] = opf_model
network_data["p_model"] = p_model
power_model = PowerModelType[opf_model]


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

plt1 = plot(range, objectives, ylabel="Objective", label="obj", legend=:outerright)
plt2 = plot(ylabel="Branch Flow", legend=:outerright, ylims=(-0.2, 2.5))
plt3 = plot(xlabel="Lambda", ylabel="Generation", legend=:outerright, ylims=(-1, 5))
for (j, bid) in enumerate(branch_ids)
    plot!(plt2, range, all_flows[j], label="Branch $bid")
end
for (j, bid) in enumerate(gen_ids)
    plot!(plt3, range, all_generations[j], label="Generator $bid")
end

# plot(plt1, plt2, plt3, layout=(3, 1))

# println("---------------------------")
# println("objective:", result["objective"])
# PowerModels.print_summary(result["solution"])

# pm = instantiate_model(network_data, DCPPowerModel, PowerModels.build_opf)

# Generate the Excel file
create_excel_report(result, network_data, "power_analysis_results.xlsx", powerworld=true)

