# GUI worker: one long-lived Julia session that runs the jobs the GUI sends.
#
# Start it from the repo root:   julia --project=. runners/gui/worker.jl
#
# It reads one JSON job per line on stdin, for example
#   {"id": 7, "type": "run", "settings": {...}}
# prints its log as the runners always do, and marks job events with control lines
# that start with "@@" (@@ready, @@start, @@data, @@error, @@done). The protocol and
# the settings schema are in runners/gui/gui_plan.md ("Contracts").
#
# Packages load once; the runner files are re-included before every run, so edits to
# them apply without a restart. Edits to src/, frequency.jl or voltage.jl need a restart.

using PowerModels
using Ipopt
using JuMP
using JSON3
using XLSX
using LinearAlgebra  # matrix solves/inverses for Jacobian sensitivities


# ==================== Settings ====================
const RUNNERS_DIR = normpath(joinpath(@__DIR__, ".."))
const RUNNER_FILES = ["calc_line_flow.jl", "excel_generator.jl", "utils.jl", "islanding_core.jl"]   # same as islanding.jl
const CASES_DIR = "cases/psse"                    # list_cases looks here, relative to the repo root
const OBJECTIVES = ["opf", "flow", "flow_shed", "opf_shed"]
const OPF_MODELS = ["AC", "DC"]
const FLOW_MODELS = ["squared", "abs_sum", "combined"]
const SIMULATORS = ["psse", "andes"]
const BOUNDARY_KINDS = ["zone", "area", "bus_pairs"]
const GROUP_KINDS = ["zone", "area"]              # kinds a group of buses may be (bus field of the same name)
const GROUP_RECORDS = Dict(                       # kind => (network data key of its records, name field)
    "zone" => ("zone", "zoname"),
    "area" => ("area interchange", "arname"),
)
const MAX_ERROR_MESSAGE = 2000                    # characters of an error message sent in @@error
const STAGE_LABELS = Dict(                        # stage => label shown by the GUI (gui_plan.md, "Stages")
    "load_case" => "Load case",
    "prepare" => "Prepare",
    "frequency_limits" => "Frequency limits",
    "solve" => "Solve",
    "reports" => "Reports",
    "excel" => "Excel report",
    "export" => "Export",
    "dynamic_sim" => "Dynamic simulation",
    "summary" => "Summary",
)


# ==================== Protocol ====================
"""
Write a control line `@@<kind> <json>` on a fresh line of stdout.
Ipopt writes through C stdio into the same output, so that is flushed first.
"""
function send_control(kind::AbstractString, payload::AbstractDict)
    flush(stdout)
    Libc.flush_cstdio()
    print(stdout, "\n@@", kind, " ")
    JSON3.write(stdout, payload)
    println(stdout)
    flush(stdout)
end

"Send the reply of a query job (`@@data`), tagged with the job id."
function send_data(job, payload::AbstractDict)
    reply = Dict{String,Any}("id" => get(job, "id", nothing))
    merge!(reply, payload)
    send_control("data", reply)
end

"Send the start of a run stage (`@@stage`) for a job."
function send_stage(job, stage::AbstractString)
    send_control("stage", Dict(
        "id" => get(job, "id", nothing),
        "stage" => stage,
        "label" => get(STAGE_LABELS, stage, stage),
    ))
end


# ==================== Runner files and cases ====================
"Include the runner files into Main, as islanding.jl does; called at startup and before every run."
function include_runner_files()
    for file in RUNNER_FILES
        Base.include(Main, joinpath(RUNNERS_DIR, file))
    end
end

# parsed cases, by .raw path: (modification time, network data)
const PARSED_CASES = Dict{String,Any}()

"The parsed network of `raw_file`, parsed once and kept until the file changes. Do not mutate it."
function find_parsed_case(raw_file::AbstractString)
    modified = mtime(raw_file)
    cached = get(PARSED_CASES, raw_file, nothing)
    if cached === nothing || cached.modified != modified
        network_data = PowerModels.parse_file(raw_file, import_all=true)
        cached = (modified=modified, network_data=network_data)
        PARSED_CASES[raw_file] = cached
    end
    return cached.network_data
end

"A fresh copy of the parsed network of `raw_file`, safe to modify."
load_case(raw_file::AbstractString) = deepcopy(find_parsed_case(raw_file))

"Case folders under CASES_DIR that hold a .raw file, as paths relative to the repo root."
function find_cases()
    cases = String[]
    isdir(CASES_DIR) || return cases
    for name in readdir(CASES_DIR)
        folder = joinpath(CASES_DIR, name)
        isdir(folder) || continue
        any(file -> endswith(lowercase(file), ".raw"), readdir(folder)) || continue
        push!(cases, "$CASES_DIR/$name")
    end
    return sort(cases)
end

"Case name used in the results folder: the last part of the case path."
case_name_of(case_path::AbstractString) = basename(rstrip(case_path, ['/', '\\']))


# ==================== Case information ====================
"""
Groups of kind `kind` ("zone" or "area") that the buses belong to: index, name, bus count and
in-service load (MW), sorted by index. Names come from the case's records, or are the index when
a group has no record. Empty when the case has fewer than two such groups (nothing to choose).
"""
function calc_group_table(network_data, kind::AbstractString)
    base_mva = network_data["baseMVA"]
    records_key, name_field = GROUP_RECORDS[kind]

    group_by_bus = Dict{Int,Int}()
    bus_count = Dict{Int,Int}()
    for (_, bus) in network_data["bus"]
        group = Int(bus[kind])
        group_by_bus[Int(bus["bus_i"])] = group
        bus_count[group] = get(bus_count, group, 0) + 1
    end
    length(bus_count) < 2 && return Dict{String,Any}[]

    load_mw = Dict{Int,Float64}()
    for (_, load) in network_data["load"]
        get(load, "status", 1) == 0 && continue
        group = group_by_bus[Int(load["load_bus"])]
        load_mw[group] = get(load_mw, group, 0.0) + load["pd"] * base_mva
    end

    name_by_index = Dict{Int,String}()
    for (_, record) in get(network_data, records_key, Dict())
        name_by_index[Int(record["i"])] = strip(string(record[name_field]))
    end

    groups = Dict{String,Any}[]
    for (index, buses) in bus_count
        name = get(name_by_index, index, "")
        isempty(name) && (name = string(index))
        push!(groups, Dict{String,Any}(
            "index" => index,
            "name" => name,
            "buses" => buses,
            "load_mw" => round(get(load_mw, index, 0.0), digits=2),
        ))
    end
    return sort(groups, by=group -> group["index"])
end

"Loads of the case: id, bus, pd (MW), qd (Mvar) and status, sorted by id."
function calc_load_table(network_data)
    base_mva = network_data["baseMVA"]
    loads = Dict{String,Any}[]
    for (id, load) in network_data["load"]
        push!(loads, Dict{String,Any}(
            "id" => parse(Int, id),
            "bus" => Int(load["load_bus"]),
            "pd_mw" => round(load["pd"] * base_mva, digits=2),
            "qd_mvar" => round(load["qd"] * base_mva, digits=2),
            "status" => Int(get(load, "status", 1)),
        ))
    end
    return sort(loads, by=load -> load["id"])
end

"Generators of the case: id, bus, pmin and pmax (MW) and status, sorted by id."
function calc_gen_table(network_data)
    base_mva = network_data["baseMVA"]
    gens = Dict{String,Any}[]
    for (id, gen) in network_data["gen"]
        push!(gens, Dict{String,Any}(
            "id" => parse(Int, id),
            "bus" => Int(gen["gen_bus"]),
            "pmin_mw" => round(gen["pmin"] * base_mva, digits=2),
            "pmax_mw" => round(gen["pmax"] * base_mva, digits=2),
            "status" => Int(get(gen, "gen_status", 1)),
        ))
    end
    return sort(gens, by=gen -> gen["id"])
end


# ==================== Settings → run ====================
"Readable problems with a run's settings (schema v1); empty when the settings are usable."
function find_settings_problems(settings)
    problems = String[]
    required = ["case", "objective", "opf_model", "flow_model", "lambda", "boundary", "penalties",
        "frequency_security", "voltage_security", "run_dynamic_sim", "simulator", "output_tag"]
    for key in required
        haskey(settings, key) || push!(problems, "missing setting \"$key\"")
    end
    isempty(problems) || return problems

    get(settings, "schema", 1) == 1 || push!(problems, "settings schema $(settings["schema"]) is not supported, expected 1")
    isdir(settings["case"]) || push!(problems, "case folder not found: $(settings["case"])")
    settings["objective"] in OBJECTIVES || push!(problems, "objective must be one of $(join(OBJECTIVES, ", "))")
    settings["opf_model"] in OPF_MODELS || push!(problems, "opf_model must be AC or DC")
    settings["flow_model"] in FLOW_MODELS || push!(problems, "flow_model must be one of $(join(FLOW_MODELS, ", "))")
    settings["simulator"] in SIMULATORS || push!(problems, "simulator must be psse or andes")
    settings["lambda"] isa Real && settings["lambda"] > 0 || push!(problems, "lambda must be a positive number")
    settings["output_tag"] isa AbstractString || push!(problems, "output_tag must be text (empty for none)")
    if settings["voltage_security"] == true && settings["opf_model"] != "AC"
        push!(problems, "voltage security needs the AC model")
    end

    boundary = settings["boundary"]
    boundary_kind = get(boundary, "kind", "")
    if !(boundary_kind in BOUNDARY_KINDS)
        push!(problems, "boundary kind must be one of $(join(BOUNDARY_KINDS, ", "))")
    elseif boundary_kind == "bus_pairs" && isempty(get(boundary, "bus_pairs", []))
        push!(problems, "boundary by bus pairs needs at least one pair")
    elseif boundary_kind != "bus_pairs" && isempty(strip(string(get(boundary, "name", ""))))
        push!(problems, "boundary $boundary_kind needs a name")
    end

    penalties = settings["penalties"]
    for group in get(penalties, "groups", [])
        get(group, "kind", "") in GROUP_KINDS || push!(problems, "penalty group kind must be one of $(join(GROUP_KINDS, ", "))")
        get(group, "times_lambda", nothing) isa Real || push!(problems, "penalty group $(get(group, "name", "?")) needs a number times lambda")
    end
    for (bus, times_lambda) in get(penalties, "buses", Dict())
        times_lambda isa Real || push!(problems, "penalty of bus $bus must be a number times lambda")
    end

    isempty(get(settings, "modifications", Dict())) || push!(problems, "network modifications are not supported yet (phase 9)")
    return problems
end

"Buses of the group of kind `kind` (\"zone\" or \"area\") named `name`, sorted."
function find_group_buses(network_data, kind::AbstractString, name::AbstractString)
    kind == "zone" && return find_buses_by_zone(network_data, name)
    kind == "area" && return find_buses_by_area(network_data, name)
    error("unknown group kind \"$kind\"")
end

"Boundary branches (exactly one end inside) of the group of kind `kind` named `name`, sorted ids."
function find_group_branches(network_data, kind::AbstractString, name::AbstractString)
    kind == "zone" && return find_branches_by_zone(network_data, name)
    kind == "area" && return find_branches_by_area(network_data, name)
    error("unknown group kind \"$kind\"")
end

"""
Boundary lines, the buses of the target group (to orient the flows) and the target zone or
area name, from the settings' `boundary`. Bus-pair boundaries have no target group.
"""
function find_target(network_data, boundary)
    kind = boundary["kind"]
    if kind == "bus_pairs"
        bus_pairs = [(Int(pair[1]), Int(pair[2])) for pair in boundary["bus_pairs"]]
        target_lines = find_branches_by_bus_pairs(network_data, bus_pairs)
        pair_text = join(["$(pair[1])-$(pair[2])" for pair in bus_pairs], ", ")
        isempty(target_lines) && error("no boundary line found for bus pairs $pair_text")
        return (lines=target_lines, buses=nothing, zone=nothing, area=nothing)
    end

    name = string(boundary["name"])
    target_lines = find_group_branches(network_data, kind, name)
    isempty(target_lines) && error("no boundary line found for $kind $name")
    return (
        lines=target_lines,
        buses=find_group_buses(network_data, kind, name),
        zone=(kind == "zone" ? name : nothing),
        area=(kind == "area" ? name : nothing),
    )
end

"""
Absolute load shedding penalty per bus (bus string => penalty), as add_load_shedding_penalty!
expects, from penalties given in multiples of lambda. Buses override groups, groups override
`others`. Loads left out keep that function's default (1e4, absolute).
"""
function calc_shed_penalties(network_data, penalties, lambda::Real)
    bus_penalty = Dict{String,Float64}()

    others = get(penalties, "others", nothing)
    if others !== nothing
        for (_, load) in network_data["load"]
            bus_penalty[string(load["load_bus"])] = others * lambda
        end
    end
    for group in get(penalties, "groups", [])
        for bus in find_group_buses(network_data, group["kind"], string(group["name"]))
            bus_penalty[string(bus)] = group["times_lambda"] * lambda
        end
    end
    for (bus, times_lambda) in get(penalties, "buses", Dict())
        bus_penalty[string(bus)] = times_lambda * lambda
    end
    return bus_penalty
end

"""
Run one islanding scenario from settings (schema v1), the way islanding.jl's hardcoded block does.
`progress` is called with each stage name (gui_plan.md, "Stages"). Returns the solve result.
"""
function run_from_settings(settings; progress=stage -> nothing)
    problems = find_settings_problems(settings)
    isempty(problems) || error("invalid settings:\n  " * join(problems, "\n  "))

    # load the network data
    progress("load_case")
    case_path = string(settings["case"])
    run_dynamic_sim = settings["run_dynamic_sim"] == true
    case_files = find_case_files(case_path; require_dyr=run_dynamic_sim)
    network_data = load_case(case_files.raw)

    # boundary lines
    progress("prepare")
    target = find_target(network_data, settings["boundary"])

    # load shedding penalties
    lambda = settings["lambda"]
    penalties = settings["penalties"]
    uniform_value = get(penalties, "uniform", nothing)
    uniform_shedding = uniform_value !== nothing
    uniform_penalty = uniform_shedding ? uniform_value * lambda : 0.0
    load_shedding_penalties = calc_shed_penalties(network_data, penalties, lambda)
    add_load_shedding_penalty!(
        network_data;
        uniform=uniform_shedding,
        uniform_penalty=uniform_penalty,
        penalties=load_shedding_penalties
    )

    # run the shared pipeline (solve, reports, export, dynamic simulation)
    output_tag = isempty(strip(settings["output_tag"])) ? nothing : strip(settings["output_tag"])
    return run_islanding(
        network_data;
        case_name=case_name_of(case_path),
        case_files=case_files,
        objective=settings["objective"],
        lambda=lambda,
        opf_model=settings["opf_model"],
        flow_model=settings["flow_model"],
        target_lines=target.lines,
        run_dynamic_sim=run_dynamic_sim,
        uniform_shedding=uniform_shedding,
        uniform_penalty=uniform_penalty,
        load_shedding_penalties=load_shedding_penalties,
        target_zone=target.zone,
        target_area=target.area,
        selected_buses=target.buses,
        output_tag=output_tag,
        frequency_security=settings["frequency_security"] == true,
        voltage_security=settings["voltage_security"] == true,
        simulator=settings["simulator"],
        progress=progress,
        run_settings=settings,
    )
end


# ==================== Handlers ====================
"Reply that the worker is alive, with the Julia version."
handle_ping(job) = send_data(job, Dict("pong" => true, "julia" => string(VERSION)))

"Reply with the case folders that hold a .raw file."
handle_list_cases(job) = send_data(job, Dict("cases" => find_cases()))

"Reply with the zones, areas, loads and generators of a case, and whether it has a .dyr file."
function handle_case_info(job)
    case_path = string(job["case"])
    case_files = find_case_files(case_path)
    network_data = find_parsed_case(case_files.raw)
    send_data(job, Dict(
        "case" => case_path,
        "zones" => calc_group_table(network_data, "zone"),
        "areas" => calc_group_table(network_data, "area"),
        "loads" => calc_load_table(network_data),
        "gens" => calc_gen_table(network_data),
        "has_dyr" => case_files.dyr !== nothing,
    ))
end

"Run a scenario: re-include the runner files so edits apply, then run the settings, reporting each stage."
function handle_run(job)
    include_runner_files()
    progress = stage -> send_stage(job, stage)
    Base.invokelatest(run_from_settings, job["settings"]; progress=progress)
    return nothing
end

const HANDLERS = Dict{String,Function}(
    "ping" => handle_ping,
    "list_cases" => handle_list_cases,
    "case_info" => handle_case_info,
    "run" => handle_run,
)


# ==================== Job loop ====================
"Run one job line: @@start, the handler (errors go to the log and @@error), then @@done."
function run_job(line::AbstractString)
    job = Dict{String,Any}()
    job_id = nothing
    started = time()
    ok = try
        job = JSON3.read(line, Dict{String,Any})
        job_id = get(job, "id", nothing)
        job_type = string(get(job, "type", ""))
        send_control("start", Dict("id" => job_id, "type" => job_type))
        handler = get(HANDLERS, job_type, nothing)
        handler === nothing && error("unknown job type \"$job_type\"")
        Base.invokelatest(handler, job)
        true
    catch err
        println()
        showerror(stdout, err, catch_backtrace())
        println()
        message = sprint(showerror, err)
        length(message) > MAX_ERROR_MESSAGE && (message = first(message, MAX_ERROR_MESSAGE) * " …")
        send_control("error", Dict("id" => job_id, "message" => message))
        false
    end
    send_control("done", Dict("id" => job_id, "ok" => ok, "seconds" => round(time() - started, digits=2)))
end

isfile("Project.toml") || error("start the worker from the repo root: julia --project=. runners/gui/worker.jl")
PowerModels.silence()
include_runner_files()
send_control("ready", Dict("julia" => string(VERSION)))

for line in eachline(stdin)
    isempty(strip(line)) && continue
    run_job(line)
end
