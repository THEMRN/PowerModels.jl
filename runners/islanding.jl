using PowerModels
using Ipopt
using JuMP
using JSON3
using XLSX
using LinearAlgebra  # matrix solves/inverses for Jacobian sensitivities
include("excel_generator.jl")
include("calc_line_flow.jl")
include("utils.jl")
include("islanding_core.jl")


# ==================== Configuration Mode =====================
# Set to true to read all settings from an external JSON config file.
# Set to false to use the hardcoded values defined below.
use_config_file = false
config_file_path = joinpath(@__DIR__, "config.json")
dynamic_simulator = "andes"    # "psse", "andes"; used in both modes (not read from the config file)
# =============================================================

function load_config(path::String)
    raw = read(path, String)
    return JSON3.read(raw, Dict{String,Any})
end

if use_config_file
    println("Loading configuration from: $config_file_path")
    cfg = load_config(config_file_path)

    # load the network data
    src_case_path = cfg["src_case_path"]
    run_dynamic_sim = get(cfg, "run_psse", true)
    case_files = find_case_files(src_case_path; require_dyr=run_dynamic_sim)
    case_name = basename(src_case_path)
    network_data = PowerModels.parse_file(case_files.raw, import_all=true)

    # settings
    objective = get(cfg, "objective", "flow")
    bus_pairs = [(Int(p[1]), Int(p[2])) for p in cfg["target_bus_pairs"]]
    target_lines = find_branches_by_bus_pairs(network_data, bus_pairs)
    lambda = get(cfg, "lambda", 50000.0)
    uniform_shedding = get(cfg, "uniform_shedding", false)
    uniform_penalty = get(cfg, "uniform_penalty", lambda / 10)
    opf_model = get(cfg, "opf_model", "AC")
    flow_model = get(cfg, "p_model", "squared")
    frequency_security = get(cfg, "frequency_security", false)

    # load shedding penalties
    raw_penalties = get(cfg, "load_shedding_penalties", Dict())
    load_shedding_penalties = Dict{String,Float64}(string(k) => Float64(v) for (k, v) in raw_penalties)

    # network modifications
    add_load_shedding_penalty!(
        network_data;
        uniform=uniform_shedding,
        uniform_penalty=uniform_penalty,
        penalties=load_shedding_penalties
    )

    # apply load modifications from config  (load_id => {field => value})
    # raw_load_mods = get(cfg, "load_modifications", Dict())
    # for (load_id, mods) in raw_load_mods
    #     for (field, value) in mods
    #         modified_network_data["load"][string(load_id)][string(field)] = Float64(value)
    #     end
    # end

else
    # ------------------- Hardcoded settings ----------------------

    # Load the network data ------------------------
    src_case_path = "cases/psse/ACTIVSg500"
    run_dynamic_sim = true
    case_files = find_case_files(src_case_path; require_dyr=run_dynamic_sim)
    case_name = basename(src_case_path)
    PowerModels.silence()
    network_data = PowerModels.parse_file(case_files.raw, import_all=true)
    modified_network_data = deepcopy(network_data) # make a copy of the network data for modifications, keeping the original

    # settings ------------------------------------
    objective = "flow_shed"    # "opf", "flow", "flow_shed", "opf_shed"
    lambda = 500       # for the flow minimization weight
    opf_model = "AC"
    flow_model = "squared"  # "abs_sum", "squared", "combined"
    frequency_security = false   # RoCoF, QSS and nadir limits on each island's import (frequency.jl)
    uniform_shedding = false
    uniform_penalty = 0 * lambda
    load_shedding_penalties = Dict()

    # ======================================================================
    # ACTIVSg500 case targets --------------------
    # zone names:  CLEMSON, GREENVIL, SPARTANB, YORK, MIDLANDS, COLUMBIA
    target_zone = "spartanb"  # case insensitive
    target_lines = find_branches_by_zone(modified_network_data, target_zone)
    selected_buses = find_buses_by_zone(modified_network_data, target_zone)

    for bus in keys(network_data["bus"])
        if parse(Int, bus) in selected_buses        # bus inside the target zone
            # spartanb: 2.5, midlands: 0.95
            load_shedding_penalties[bus] = 2.5 * lambda
        else                                        # bus outside the target zone
            # clemson: 1.6, york: 2.5
            # load_shedding_penalties[bus] = 1.6 * lambda
        end
    end

    # set the gen pmin to 0 for selected buses
    # for (_, gen) in modified_network_data["gen"]
    #     if gen["gen_bus"] in selected_buses
    #         gen["pmin"] = 0.0
    #     end
    # end


    # CLEMSON ------------------------
    # GREENVIL -----------------------
    # scale_loads!(modified_network_data, 0.1, "GREENVIL")
    # SPARTANB -----------------------
    # scale_loads!(modified_network_data, 0.7, "SPARTANB")
    # YORK ---------------------------
    # MIDLANDS -----------------------
    # COLUMBIA -----------------------
    # --------------------------------------------

    # ======================================================================
    # SAVNW case ----------------------
    # load_shedding_penalties = Dict(
    # "3005" => 10000.0,        # top, only load in case c, 100MW
    #------
    # "3007" => 0.2 * lambda,   # 200MW
    # "3008" => 2 * lambda,     # 200MW
    # "153" => 0.5 * lambda,    # 200MW
    #------------------------------
    # "205" => 5.8 * lambda,      # huge load center, 1200
    # "203" => 0.9 * lambda,      # 300 MW
    #------
    # "154" => 4.9 * lambda,   # it has 2 loads 600 + 400      
    # )
    # savnw test case targets --------------------
    # bus-gen map: bus_id => [gen_id, pmax, qmax] 
    # {101: [1, 8.1, 6], 102: [2, 8.1, 6],  206: [3, 9, 6], 211: [4, 6.16, 4], 3011: [5, 9, 6], 3018: [6, 1.17, 0.8]}
    # bus-load map: bus_id => [load_id, pd, qd]
    # {153: [1, 2, 1], 154: [[2, 6, 4.5], [3, 4, 3.5]], 203: [4, 3, 1.5], 205: [5, 12, 7], 3005: [6, 1, 0.5], 3007: [7, 2, 0.75], 3008: [8, 2, 0.75]}

    # target_lines = find_branches_by_bus_pairs(network_data, [(202, 152), (202, 201), (202, 203)])  # bus 202
    # target_lines = find_branches_by_bus_pairs(network_data, [(3004, 152), (3004, 3002), (3004, 3005)]) # bus 3004

    # island on top ------------------------------------
    # modified_network_data["load"]["6"]["pd"] = 4.0    # for the top island case make it more stable       load default: 1.0, pmax: 9.0 
    # target_lines = find_branches_by_bus_pairs(network_data, [(3001, 3002), (3005, 3004), (3005, 3006), (3005, 3008), (3005, 3007)]) # island on top
    # island on left -----------------------------------
    # modified_network_data["load"]["8"]["pd"] = 1.0      # for the left side case, so the gen can supply   load default: 2.0, pmax: 1.17
    # target_lines = find_branches_by_bus_pairs(network_data, [(3007, 3008), (154, 3008), (3005, 3008)]) # island on left
    # island on bottom (one load) ----------------------
    # modified_network_data["load"]["5"]["pd"] = 5.0    # for the bottom side case                          load default: 12.0, pmax: 15.16
    # target_lines = find_branches_by_bus_pairs(network_data, [(201, 151), (201, 202), (205, 203), (205, 154)]) # island on bottom
    # island on bottom (two loads) ---------------------
    # modified_network_data["load"]["5"]["pd"] = 8.0    # for the bottom side second case                     load default: 12.0, pmax: 15.16
    # modified_network_data["load"]["4"]["pd"] = 2.5    # for the bottom side second case                     load default: 3.0, pmax: 15.16
    # target_lines = find_branches_by_bus_pairs(network_data, [(201, 151), (202, 152), (203, 154), (205, 154)]) # another island on bottom with 2 loads
    # north south seperation --------------------------
    # scaling_buses = [3005, 3007, 3008, 153]
    # scale_loads!(modified_network_data, 1.6, scaling_buses)
    # target_lines = find_branches_by_bus_pairs(network_data, [(154, 3008), (154, 153), (152, 153), (152, 3004)]) # north-south seperation    

    # add load shedding penalties ------------------------
    add_load_shedding_penalty!(
        modified_network_data;
        uniform=uniform_shedding,
        uniform_penalty=uniform_penalty,
        penalties=load_shedding_penalties
    )

end


# run the shared pipeline (solve, reports, voltage prediction, psse export)
data_for_run = @isdefined(modified_network_data) ? modified_network_data : network_data
result = run_islanding(
    data_for_run;
    case_name=case_name,
    case_files=case_files,
    objective=objective,
    lambda=lambda,
    opf_model=opf_model,
    flow_model=flow_model,
    target_lines=target_lines,
    run_dynamic_sim=run_dynamic_sim,
    uniform_shedding=uniform_shedding,
    uniform_penalty=uniform_penalty,
    load_shedding_penalties=load_shedding_penalties,
    target_zone=(@isdefined(target_zone) ? target_zone : nothing),
    selected_buses=(@isdefined(selected_buses) ? selected_buses : nothing),
    frequency_security=frequency_security,
    simulator=dynamic_simulator,
)
