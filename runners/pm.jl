using PowerModels
using Ipopt
using JuMP
using JSON3

# disabling constants based on matpower data types
const LINE_DISABLED_STATUS = 0
const BUS_DISABLED_STATUS = 4

# function to get brances connected to the buses in the bus sets
function get_connected_branches(network_model::Dict, bus_sets::Dict)
    branches = network_model["branch"]
    result = Dict()

    for (set_id, set_data) in bus_sets
        buses = set_data["buses"]
        connected_branches = Set()

        for (branch_id, branch_data) in branches
            if branch_data["f_bus"] in buses || branch_data["t_bus"] in buses
                push!(connected_branches, branch_id)
            end
        end

        result[set_id] = Dict("buses" => buses, "branches" => collect(connected_branches))
    end

    return result
end

# contingency bus sets
bus_sets = Dict(
    1 => Dict("buses" => [404]),
    2 => Dict("buses" => [5207, 5209, 5210, 5211, 5212, 5213, 5214]),
    3 => Dict("buses" => [5236, 5238, 5239]),
    4 => Dict("buses" => [5854, 5856]),
    5 => Dict("buses" => [5863, 5865])
);

solver_modles = Dict(
    "ACR" => ACRPowerModel,          # AC power flow in rectangular coordinates
    "IVR" => IVRPowerModel,          # Current-Voltage Rectangular Power Model
    "SDP" => SDPWRMPowerModel,       # SDP relaxation
    "SOC" => SOCWRPowerModel,        # SOC relaxation of the W (voltage outer product) rank-constrained formulation.
    "QCA" => LPACCPowerModel,        # Linearized power flow with a convex quadratic cost approximation
    "QCA2" => DCPLLPowerModel        # Linearized power flow with a convex quadratic cost approximation
)

# control -------------------------------------------------
selected_model = "QCA"              # choose from: ACR, IVR, SDP, SOCP, QCQP
impedance_increase_mode = true      # true or false
selected_set = 5;                   # choose from: 1, 2, 3, 4, 5
iterations = 11;
impedance_increase_rate = 1.6
#-----------------------------------------------------------

orig_network_model = PowerModels.parse_file("Texas7k2.m");
network = deepcopy(orig_network_model)
contingency_sets = get_connected_branches(network, bus_sets)

if !impedance_increase_mode
    impodance_increase_rate = 1.0
    iterations = 2
end

# solving the OPF
nlp_ws_solver = JuMP.optimizer_with_attributes(Ipopt.Optimizer, "tol" => 1e-6, "mu_init" => 1e-4, "mu_strategy" => "adaptive")
opf_model = solver_modles[selected_model]
begin_time = time()
result = 0
for i in range(1, iterations)
    tst = time()
    println("=================================================Iteration: ", i)
    # global result = solve_opf(network, opf_model, nlp_ws_solver, solution_processors=[sol_data_model!])
    global result = solve_opf(network, opf_model, nlp_ws_solver)

    # update network with the solution of the previous iteration
    PowerModels.update_data!(network, result["solution"])
    set_ac_pf_start_values!(network)

    if (!impedance_increase_mode && i == 1) || (impedance_increase_mode && i == iterations - 1)
        # Disable the buses in the selected contingency set
        println("######################## Disabling buses in contingency set: ", selected_set)
        for bus in contingency_sets[selected_set]["buses"]
            network["bus"][string(bus)]["bus_type"] = BUS_DISABLED_STATUS
        end
    end

    if impedance_increase_mode
        # Increase the resistance of the branches in the selected contingency set
        for branch in contingency_sets[selected_set]["branches"]
            network["branch"][branch]["br_r"] *= impedance_increase_rate
        end
    end
    println("========= Iteration $i, Time: ", time() - tst)
end

total_time = time() - begin_time
println("========= Total Time: $total_time")

# Check for voltage violations
solution = result["solution"]
violations = Vector{Dict{String,Any}}();
for (bus_number, bus_data) in solution["bus"]
    if (haskey(bus_data, "vr") && haskey(bus_data, "vi"))
        v = sqrt(bus_data["vr"]^2 + bus_data["vi"]^2)
    elseif haskey(bus_data, "va")
        v = bus_data["va"]
    else
        continue
    end
    if v > network["bus"][bus_number]["vmax"] + 0.005
        push!(violations, Dict("bus" => bus_number, "type" => "over", "value" => v))
    elseif v < network["bus"][bus_number]["vmin"] - 0.005
        push!(violations, Dict("bus" => bus_number, "type" => "under", "value" => v))
    end
end

println("num of violations: ", length(violations))
# for viol in violations
#     println("Bus: ", viol["bus"], ", ", viol["type"], " voltage with value: ", viol["value"])
# end

# Exporting results to JSON and MATPOWER format
_file_name = "case_set$(selected_set)_$(iterations)i_$selected_model"
res = Dict(
    "time" => total_time,
    "objective" => result["objective"],
    "solution" => solution,
    "violations" => violations
)

open("res/$_file_name.json", "w") do f
    JSON3.write(f, res)
end

PowerModels.update_data!(network, solution);
PowerModels.export_matpower("res/$_file_name.m", network)