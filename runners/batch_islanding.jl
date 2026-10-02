# Batch runner for the islanding study.
#
# Define the runs in the `scenarios` vector below and run this file once; every
# run executes in this Julia session (packages/case are loaded only once).
#
# Each scenario dict supports:
#   "src_case_path"          : String (required), e.g. "cases/psse/ACTIVSg500"
#   "run_psse"               : Bool (default true)
#   "objective"              : String or Vector{String} (sweep), default "flow"
#   "lambda"                 : Number or Vector (sweep), default 500
#   "flow_model"             : String or Vector{String} (sweep), default "squared"
#   "opf_model"              : String or Vector{String} (sweep), default "AC"
#   "frequency_security"     : Bool (default false), RoCoF/QSS/nadir limits on
#                              each island's import (frequency.jl), needs .dyr
#   "target_lines"           : Vector of (from_bus, to_bus) tuples. Takes
#                              precedence over target_zones for line selection.
#   "target_zones"           : zone name(s). A String is a single zone; a
#                              Vector sweeps over its elements, so
#                              ["spartanb", "york"] = 2 runs, while
#                              [["spartanb", "york"]] = 1 run targeting both.
#                              When target_lines is absent, the run's lines are
#                              the zone boundary branches.
#   "load_shedding_penalties": penalty spec Dict, or Vector of specs (sweep).
#       Penalty numbers are multiples of lambda (2.5 means 2.5 * lambda).
#       Supported forms:
#         Dict("custom" => Dict("205" => 5.8, "203" => 0.9))
#             explicit bus => penalty entries
#         Dict("zone" => "spartanb", "penalty" => 2.5)
#             one penalty for every bus in the zone
#         Dict("zones" => [Dict("zone" => "spartanb", "penalty" => 2.5),
#                          Dict("zone" => "midlands", "penalty" => 0.95)])
#             per-zone penalties
#         Dict("!zones" => ["spartanb", "york"], "penalty" => 1.6)
#             penalty for all buses EXCEPT those in the listed zones
#
# Any field given as a Vector is swept, and the cross product of all swept
# fields within a scenario becomes individual runs.

using PowerModels
using Ipopt
using JuMP
using JSON3
using XLSX
using LinearAlgebra
include("excel_generator.jl")
include("calc_line_flow.jl")
include("utils.jl")
include("islanding_core.jl")

# ==================== Batch Configuration =====================
scenarios = [
    Dict(
        "src_case_path" => "cases/psse/ACTIVSg500",
        "run_psse" => false,
        "objective" => ["flow_shed", "opf_shed"],
        "lambda" => 500,
        "flow_model" => ["squared", "abs_sum"],
        "opf_model" => "AC",
        "target_zones" => "spartanb",
        "load_shedding_penalties" => Dict("zone" => "spartanb", "penalty" => 2.5),
    ),
    # Dict(
    #     "src_case_path" => "cases/psse/ACTIVSg500",
    #     "run_psse" => false,
    #     "objective" => "flow_shed",
    #     "lambda" => 500,
    #     "flow_model" => "squared",
    #     "target_zones" => ["spartanb", "midlands"],   # sweep: one run per zone
    #     "load_shedding_penalties" => [                # swept together with zones (cross product)
    #         Dict("zone" => "spartanb", "penalty" => 2.5),
    #         Dict("!zones" => ["spartanb"], "penalty" => 1.6),
    #     ],
    # ),
    # Dict(
    #     "src_case_path" => "cases/psse/savnw",
    #     "run_psse" => true,
    #     "objective" => "flow_shed",
    #     "lambda" => 500,
    #     "flow_model" => "squared",
    #     "target_lines" => [(3007, 3008), (154, 3008), (3005, 3008)],
    #     "load_shedding_penalties" => Dict("custom" => Dict("3005" => 10.0, "153" => 0.5)),
    # ),
]
# ==============================================================

const SWEEP_FIELDS = ["objective", "flow_model", "opf_model", "lambda", "target_zones", "load_shedding_penalties"]

# Expand a scenario dict into individual run dicts (cross product of all
# fields given as vectors). Returns the runs and the names of swept fields.
function expand_scenario(scenario::AbstractDict)
    base = Dict{String,Any}(k => v for (k, v) in scenario if !(k in SWEEP_FIELDS))
    runs = [base]
    swept = String[]
    for field in SWEEP_FIELDS
        haskey(scenario, field) || continue
        value = scenario[field]
        options = value isa AbstractVector ? collect(value) : [value]
        length(options) > 1 && push!(swept, field)
        runs = [merge(run, Dict{String,Any}(field => opt)) for run in runs for opt in options]
    end
    return runs, swept
end

# Resolve a load_shedding_penalties spec into a bus => penalty dict.
# Penalty numbers in the spec are multiples of lambda.
function resolve_penalties(network_data, spec, lambda)
    penalties = Dict{String,Float64}()
    spec === nothing && return penalties
    if haskey(spec, "custom")
        for (bus, p) in spec["custom"]
            penalties[string(bus)] = Float64(p) * lambda
        end
    elseif haskey(spec, "zone")
        p = Float64(spec["penalty"]) * lambda
        for bus in find_buses_by_zone(network_data, spec["zone"])
            penalties[string(bus)] = p
        end
    elseif haskey(spec, "zones")
        for zone_spec in spec["zones"]
            p = Float64(zone_spec["penalty"]) * lambda
            for bus in find_buses_by_zone(network_data, zone_spec["zone"])
                penalties[string(bus)] = p
            end
        end
    elseif haskey(spec, "!zones")
        zones = spec["!zones"] isa AbstractString ? [spec["!zones"]] : spec["!zones"]
        excluded = Set{Int}()
        for zone in zones
            union!(excluded, find_buses_by_zone(network_data, zone))
        end
        p = Float64(spec["penalty"]) * lambda
        for (_, bus) in network_data["bus"]
            bus_id = Int(bus["bus_i"])
            bus_id in excluded && continue
            penalties[string(bus_id)] = p
        end
    else
        error("Unrecognized load_shedding_penalties spec: $spec")
    end
    return penalties
end

# Short human-readable tag for a swept field value (used in output folder names).
function tag_component(field::String, value)
    if field == "load_shedding_penalties"
        haskey(value, "custom") && return "custom"
        haskey(value, "zone") && return "pen_$(lowercase(value["zone"]))"
        haskey(value, "zones") && return "pen_" * join((lowercase(z["zone"]) for z in value["zones"]), "-")
        haskey(value, "!zones") && begin
            zones = value["!zones"] isa AbstractString ? [value["!zones"]] : value["!zones"]
            return "pen_not_" * join(lowercase.(zones), "-")
        end
        return "pen"
    elseif field == "target_zones"
        return value isa AbstractString ? lowercase(value) : join(lowercase.(value), "-")
    else
        return string(value)
    end
end

# ---------------------------------------------------------------------------

PowerModels.silence()

# parse each case only once, runs work on deepcopies
network_cache = Dict{String,Any}()

# expand all scenarios into a flat run list
all_runs = Tuple{Int,Dict{String,Any},Vector{String}}[]
for (scenario_idx, scenario) in enumerate(scenarios)
    runs, swept = expand_scenario(scenario)
    for run in runs
        push!(all_runs, (scenario_idx, run, swept))
    end
end
println("Batch: $(length(scenarios)) scenario(s) expanded into $(length(all_runs)) run(s)")

summary_rows = Vector{Dict{String,Any}}()
for (run_idx, (scenario_idx, run, swept)) in enumerate(all_runs)
    # resolve run settings (same defaults as islanding.jl)
    src_case_path = run["src_case_path"]
    run_psse = get(run, "run_psse", true)
    objective = get(run, "objective", "flow")
    lambda = get(run, "lambda", 500)
    opf_model = get(run, "opf_model", "AC")
    flow_model = get(run, "flow_model", "squared")
    frequency_security = get(run, "frequency_security", false)

    # output tag from swept fields (plus scenario index when several scenarios)
    tag_parts = String[]
    length(scenarios) > 1 && push!(tag_parts, "s$(scenario_idx)")
    append!(tag_parts, [tag_component(f, run[f]) for f in swept if f != "objective"])
    output_tag = join(tag_parts, "_")

    println()
    println("===========================================================")
    println("Run $run_idx/$(length(all_runs))  (scenario $scenario_idx)")
    println("  case:       $src_case_path")
    println("  objective:  $objective   lambda: $lambda")
    println("  opf_model:  $opf_model   flow_model: $flow_model")
    haskey(run, "target_zones") && println("  zones:      $(run["target_zones"])")
    haskey(run, "target_lines") && println("  lines:      $(run["target_lines"])")
    haskey(run, "load_shedding_penalties") && println("  penalties:  $(run["load_shedding_penalties"])")
    isempty(output_tag) || println("  output tag: $output_tag")
    println("===========================================================")

    row = Dict{String,Any}(
        "run" => run_idx,
        "objective" => objective,
        "tag" => output_tag,
    )
    try
        case_files = find_case_files(src_case_path; require_dyr=run_psse)
        case_name = basename(src_case_path)
        base_network = get!(network_cache, src_case_path) do
            PowerModels.parse_file(case_files.raw, import_all=true)
        end
        network_data = deepcopy(base_network)

        # zones for this run (nothing, one zone, or several combined)
        zones = String[]
        if haskey(run, "target_zones")
            tz = run["target_zones"]
            zones = tz isa AbstractString ? [String(tz)] : String.(collect(tz))
        end

        # target lines: explicit bus pairs win, otherwise zone boundary branches
        if haskey(run, "target_lines")
            bus_pairs = [(Int(p[1]), Int(p[2])) for p in run["target_lines"]]
            target_lines = find_branches_by_bus_pairs(network_data, bus_pairs)
        elseif !isempty(zones)
            target_lines = sort(unique(vcat((find_branches_by_zone(network_data, z) for z in zones)...)))
        else
            error("Run has neither target_lines nor target_zones")
        end
        isempty(target_lines) && error("No target lines found for this run")

        # zone bus info for reporting
        target_zone = isempty(zones) ? nothing : join(zones, "+")
        selected_buses = isempty(zones) ? nothing :
                         sort(unique(vcat((find_buses_by_zone(network_data, z) for z in zones)...)))

        # load shedding penalties
        load_shedding_penalties = resolve_penalties(
            network_data, get(run, "load_shedding_penalties", nothing), lambda)
        add_load_shedding_penalty!(
            network_data;
            uniform=false,
            uniform_penalty=0.0,
            penalties=load_shedding_penalties,
        )

        result = run_islanding(
            network_data;
            case_name=case_name,
            case_files=case_files,
            objective=objective,
            lambda=lambda,
            opf_model=opf_model,
            flow_model=flow_model,
            target_lines=target_lines,
            run_psse=run_psse,
            load_shedding_penalties=load_shedding_penalties,
            target_zone=target_zone,
            selected_buses=selected_buses,
            output_tag=output_tag,
            frequency_security=frequency_security,
        )
        row["status"] = string(result["termination_status"])
        row["objective_value"] = result["objective"]
    catch err
        @error "Run $run_idx failed" exception = (err, catch_backtrace())
        row["status"] = "ERROR"
        row["error"] = sprint(showerror, err)
    end
    push!(summary_rows, row)
end

# ------------------------------- summary -----------------------------------
println()
println("======================= Batch Summary =======================")
println(@sprintf("%-5s %-16s %-28s %-14s %s", "Run", "Objective", "Tag", "Status", "Objective value / error"))
for row in summary_rows
    detail = haskey(row, "objective_value") ? string(round(row["objective_value"], digits=4)) : get(row, "error", "")
    println(@sprintf("%-5d %-16s %-28s %-14s %s", row["run"], row["objective"], row["tag"], row["status"], detail))
end
println("=============================================================")
