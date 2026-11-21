# GUI worker: one long-lived Julia session that runs the jobs the GUI sends.
#
# Start it from the repo root:   julia --project=. runners/gui/worker.jl
#
# It reads one JSON job per line on stdin, for example
#   {"id": 7, "type": "run", "settings": {...}}
# prints its log as the runners always do, and marks job events with control lines
# that start with "@@" (@@ready, @@start, @@stage, @@data, @@result, @@error, @@done). A run
# ends with @@result, the report information in MW. The protocol, the settings schema and the
# result summary are in runners/gui/gui_plan.md ("Contracts").
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
const MW_DIGITS = 2                               # MW, Mvar and % in @@result, as the console prints them
const PU_DIGITS = 3                               # H, K, D, voltages (pu) and voltage indicators in @@result, as the console prints them
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
    JSON3.write(stdout, payload; allow_inf=true)      # NaN and Infinity, which Python's json reads
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

    known_modifications = [first(modification) for modification in MODIFICATIONS]
    for (key, entries) in find_modifications(settings)
        key in known_modifications || push!(problems, "unknown network modification \"$key\"")
        entries isa AbstractVector || push!(problems, "network modification \"$key\" must be a list")
    end
    return problems
end

"The settings' network modifications (modification => its entries); empty when there are none."
function find_modifications(settings)
    modifications = get(settings, "modifications", nothing)
    modifications === nothing && return Dict{String,Any}()
    return modifications
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

"A JSON number (`true` and `false` are not numbers here, though Julia counts them as Real)."
is_number(value) = value isa Real && !(value isa Bool)

"Whose loads or generators a modification entry names, in a few words: \"zone SPARTANB\", or \"buses 3005, 3007\"."
function describe_where(entry)
    kind = string(get(entry, "kind", ""))
    kind == "buses" && return "buses " * join(get(entry, "buses", []), ", ")
    return "$kind $(get(entry, "name", ""))"
end

"""
Buses a modification entry names: the buses of its group (`kind` "zone" or "area", `name`), or
its own list (`kind` "buses"). A list is required, because without one scale_loads! scales every load.
"""
function find_entry_buses(network_data, entry)
    kind = string(get(entry, "kind", ""))
    if kind == "buses"
        buses = [Int(bus) for bus in get(entry, "buses", [])]
        isempty(buses) && error("a modification by buses needs at least one bus")
        return Set(buses)
    end
    kind in GROUP_KINDS || error("the kind of a modification must be one of $(join(GROUP_KINDS, ", ")) or buses, not \"$kind\"")
    return Set(find_group_buses(network_data, kind, string(get(entry, "name", ""))))
end

"""
Scale the loads (pd and qd) at each entry's buses by its factor, with scale_loads!.
Entries: `{kind, name, factor}` for a zone or an area, `{kind: "buses", buses, factor}` for a bus list.
"""
function apply_load_scaling!(network_data, entries)
    for entry in entries
        factor = get(entry, "factor", nothing)
        is_number(factor) && factor >= 0 || error("load scaling of $(describe_where(entry)) needs a factor of zero or more")
        buses = find_entry_buses(network_data, entry)
        println("Load scaling: $(describe_where(entry)) × $factor")
        if !any(load -> Int(load["load_bus"]) in buses, values(network_data["load"]))
            println("  no load there, nothing scaled")
            continue
        end
        scale_loads!(network_data, factor, buses)
    end
end

"""
Set the pd (MW) and the qd (Mvar) of single loads, each when given.
Entries: `{id, bus, pd_mw, qd_mvar}`; `bus`, when given, has to be the load's bus, so settings
made for another version of the case do not change a different load.
"""
function apply_load_overrides!(network_data, entries)
    base_mva = network_data["baseMVA"]
    for entry in entries
        id = string(get(entry, "id", ""))
        haskey(network_data["load"], id) || error("load $id is not in the case")
        load = network_data["load"][id]
        load_bus = Int(load["load_bus"])
        bus = get(entry, "bus", nothing)
        bus === nothing || bus == load_bus || error("load $id is at bus $load_bus, not at bus $bus as the settings say")

        pd_mw = get(entry, "pd_mw", nothing)
        qd_mvar = get(entry, "qd_mvar", nothing)
        pd_mw === nothing && qd_mvar === nothing && error("load $id needs a pd or a qd")
        if pd_mw !== nothing
            is_number(pd_mw) || error("the pd of load $id must be a number (MW)")
            println("Load $id at bus $load_bus: pd $(round(load["pd"] * base_mva, digits=2)) MW set to $pd_mw MW")
            load["pd"] = pd_mw / base_mva
        end
        if qd_mvar !== nothing
            is_number(qd_mvar) || error("the qd of load $id must be a number (Mvar)")
            println("Load $id at bus $load_bus: qd $(round(load["qd"] * base_mva, digits=2)) Mvar set to $qd_mvar Mvar")
            load["qd"] = qd_mvar / base_mva
        end
    end
end

"""
Set the pmin and the pmax (MW) of every generator at each entry's buses, each when given; a
limit that is not given stays as the case has it. Entries: `{kind, name, pmin_mw, pmax_mw}` for
a zone or an area, `{kind: "buses", buses, pmin_mw, pmax_mw}` for a bus list. The limits are set
on generators in service or not; one in service that would get a pmin above its pmax is refused.
"""
function apply_generator_settings!(network_data, entries)
    base_mva = network_data["baseMVA"]
    for entry in entries
        place = describe_where(entry)
        pmin_mw = get(entry, "pmin_mw", nothing)
        pmax_mw = get(entry, "pmax_mw", nothing)
        pmin_mw === nothing && pmax_mw === nothing && error("the generators of $place need a pmin or a pmax")
        pmin_mw === nothing || is_number(pmin_mw) || error("the pmin of the generators of $place must be a number (MW)")
        pmax_mw === nothing || is_number(pmax_mw) || error("the pmax of the generators of $place must be a number (MW)")
        buses = find_entry_buses(network_data, entry)

        gens_set = 0
        for (id, gen) in network_data["gen"]
            Int(gen["gen_bus"]) in buses || continue
            pmin_mw === nothing || (gen["pmin"] = pmin_mw / base_mva)
            pmax_mw === nothing || (gen["pmax"] = pmax_mw / base_mva)
            if get(gen, "gen_status", 1) != 0 && gen["pmin"] > gen["pmax"]
                pmin_text = round(gen["pmin"] * base_mva, digits=2)
                pmax_text = round(gen["pmax"] * base_mva, digits=2)
                error("generator $id at bus $(gen["gen_bus"]): its pmin, $pmin_text MW, would be above its pmax, $pmax_text MW")
            end
            gens_set += 1
        end

        limits = String[]
        pmin_mw === nothing || push!(limits, "pmin $pmin_mw MW")
        pmax_mw === nothing || push!(limits, "pmax $pmax_mw MW")
        println("Generators of $place: $(join(limits, ", ")) set for $gens_set generator$(gens_set == 1 ? "" : "s")")
    end
end

# network modifications: key in the settings' `modifications` => the function that applies its
# entries. They are applied in this order, so a load's own pd and qd come after the scaling.
const MODIFICATIONS = [
    "load_scaling" => apply_load_scaling!,
    "loads" => apply_load_overrides!,
    "generators" => apply_generator_settings!,
]

"Apply the network modifications of the settings to `network_data`, in the order of MODIFICATIONS."
function apply_modifications!(network_data, modifications)
    for (key, apply_entries!) in MODIFICATIONS
        entries = get(modifications, key, nothing)
        entries === nothing && continue
        isempty(entries) && continue
        apply_entries!(network_data, entries)
        println("---------------------------")
    end
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

"Results folder of a run, named as run_islanding names it: results/psse/<case>_<objective>[_<tag>]."
function calc_output_path(case_name::AbstractString, objective::AbstractString, output_tag)
    output_path = "results/psse/$(case_name)_$(objective)"
    if output_tag !== nothing
        output_path *= "_$(output_tag)"
    end
    return output_path
end

"""
Run one islanding scenario from settings (schema v1), the way islanding.jl's hardcoded block does.
`progress` is called with each stage name (gui_plan.md, "Stages"). Returns what the result summary
needs: the solve `result`, the network data as the console reports read it (with the embedded
`frequency_islands`), the settings, the target, the results folder and the start time (Unix).
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

    # network modifications, then the boundary lines
    progress("prepare")
    apply_modifications!(network_data, find_modifications(settings))
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

    # the network as the console reports read it: before the export, run_islanding writes the
    # solution into network_data, which replaces each load's pd by its served load
    report_data = deepcopy(network_data)

    # run the shared pipeline (solve, reports, export, dynamic simulation)
    output_tag = isempty(strip(settings["output_tag"])) ? nothing : strip(settings["output_tag"])
    case_name = case_name_of(case_path)
    run_started = time()
    result = run_islanding(
        network_data;
        case_name=case_name,
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
    if haskey(network_data, "frequency_islands")
        report_data["frequency_islands"] = network_data["frequency_islands"]     # embedded by run_islanding
    end

    return (
        result=result,
        network_data=report_data,
        settings=settings,
        target=target,
        output_path=calc_output_path(case_name, settings["objective"], output_tag),
        started=run_started,
    )
end


# ==================== Result summary ====================
"`value` rounded to `digits`, or `nothing` when it is not a finite number (JSON has no NaN)."
function round_value(value::Real, digits::Integer)
    isfinite(value) || return nothing
    return round(value, digits=digits)
end

"A per-unit power in MW (or Mvar), rounded for @@result."
to_mw(value_pu::Real, base_mva::Real) = round_value(value_pu * base_mva, MW_DIGITS)

"`part` as a share of `whole` (%), `nothing` when the whole is 0."
function calc_share(part::Real, whole::Real)
    whole == 0 && return nothing
    return round_value(100 * part / whole, MW_DIGITS)
end

"""
The finished settings record that run_islanding wrote into `output_path` at or after `since`
(Unix time), as `(file, record)`; `nothing` when there is none.
"""
function find_run_record(output_path::AbstractString, since::Real)
    isdir(output_path) || return nothing
    newest_file = nothing
    newest_time = since
    for file in readdir(output_path)
        startswith(file, "settings_") && endswith(file, ".json") || continue
        modified = mtime(joinpath(output_path, file))
        modified >= newest_time || continue
        newest_file = file
        newest_time = modified
    end
    newest_file === nothing && return nothing

    record = JSON3.read(read(joinpath(output_path, newest_file), String), Dict{String,Any}; allow_inf=true)
    get(record, "status", "") == "finished" || return nothing
    return (file=newest_file, record=record)
end

"P and Q of generators (MW, Mvar) with the used shares of Pmax and Qmax (%), from calc_generation_status sums."
function calc_generation_row(sums, base_mva::Real)
    return Dict{String,Any}(
        "pg_mw" => to_mw(sums["pg"], base_mva),
        "pmax_mw" => to_mw(sums["pmax"], base_mva),
        "qg_mvar" => to_mw(sums["qg"], base_mva),
        "qmax_mvar" => to_mw(sums["qmax"], base_mva),
        "p_used_pct" => round_value(sums["p_used_pct"], MW_DIGITS),
        "q_used_pct" => round_value(sums["q_used_pct"], MW_DIGITS),
    )
end

"Generation by zone or area (one row per record of the case, none without records) and in total."
function calc_generation_summary(network_data, result, group_kind::AbstractString)
    base_mva = network_data["baseMVA"]
    status = calc_generation_status(network_data, result; group_kind=group_kind)

    groups = Dict{String,Any}[]
    for group in status["groups"]
        row = calc_generation_row(group, base_mva)
        row["index"] = group["index"]
        row["name"] = group["name"]
        push!(groups, row)
    end
    return Dict{String,Any}(
        "group_kind" => group_kind,
        "groups" => groups,
        "total" => calc_generation_row(status["total"], base_mva),
    )
end

"""
Load and shed (MW) in total, by zone or area, and at every load bus (the loads at a bus added
up). Group names are the record names, or the group number as in case_info.
"""
function calc_load_shed_summary(network_data, result, group_kind::AbstractString)
    base_mva = network_data["baseMVA"]
    status = calc_load_shedding_status(result, network_data; group_kind=group_kind)
    group_names = find_group_names(network_data, group_kind)

    groups = Dict{String,Any}[]
    for group in status["groups"]
        push!(groups, Dict{String,Any}(
            "index" => group["index"],
            "name" => get(group_names, group["index"], string(group["index"])),
            "load_mw" => to_mw(group["load"], base_mva),
            "shed_mw" => to_mw(group["shed"], base_mva),
            "shed_pct" => calc_share(group["shed"], group["load"]),
        ))
    end

    # every load bus, the shed loads from the status
    load_by_bus = Dict{Int,Float64}()
    for (_, load) in network_data["load"]
        bus = Int(load["load_bus"])
        load_by_bus[bus] = get(load_by_bus, bus, 0.0) + load["pd"]
    end
    shed_by_bus = Dict{Int,Float64}()
    for load in status["loads"]
        shed_by_bus[load["bus"]] = get(shed_by_bus, load["bus"], 0.0) + load["shed"]
    end
    buses = Dict{String,Any}[]
    for bus in sort(collect(keys(load_by_bus)))
        bus_load = load_by_bus[bus]
        bus_shed = get(shed_by_bus, bus, 0.0)
        push!(buses, Dict{String,Any}(
            "bus" => bus,
            "pd_mw" => to_mw(bus_load, base_mva),
            "shed_mw" => to_mw(bus_shed, base_mva),
            "shed_pct" => calc_share(bus_shed, bus_load),
        ))
    end

    return Dict{String,Any}(
        "group_kind" => group_kind,
        "total_load_mw" => to_mw(status["total_load"], base_mva),
        "total_shed_mw" => to_mw(status["total_shed"], base_mva),
        "groups" => groups,
        "buses" => buses,
    )
end

"P and Q (MW, Mvar) of a flow sum from calc_branch_flows; `total` is P + Q, as the console prints it."
function calc_flow_sums(sums, base_mva::Real)
    return Dict{String,Any}(
        "p_mw" => to_mw(sums["p"], base_mva),
        "q_mvar" => to_mw(sums["q"], base_mva),
        "total" => to_mw(sums["total"], base_mva),
    )
end

"""
Flows on the boundary lines (MW, Mvar). With a target zone or area (`"oriented"`), each line is
measured at its end inside the group (`from`) and is positive leaving it; with bus pairs, at its
RAW from end.
"""
function calc_flow_summary(network_data, result, target)
    base_mva = network_data["baseMVA"]
    flows = calc_branch_flows(result, network_data, target.lines, target.buses)

    lines = Dict{String,Any}[]
    for line in flows["lines"]
        push!(lines, Dict{String,Any}(
            "id" => line["id"],
            "from" => line["from"],
            "to" => line["to"],
            "p_mw" => to_mw(line["p"], base_mva),
            "q_mvar" => to_mw(line["q"], base_mva),
        ))
    end
    return Dict{String,Any}(
        "oriented" => target.buses !== nothing,
        "lines" => lines,
        "net" => calc_flow_sums(flows["net"], base_mva),
        "abs_sum" => calc_flow_sums(flows["abs_sum"], base_mva),
    )
end

"""
Each island's frequency response (H in s, K and D in pu on the system base), its import limits
(MW) with the binding one, and its solved scheduled import (MW, positive into the island).
"""
function calc_frequency_summary(network_data, result)
    base_mva = network_data["baseMVA"]
    islands = Dict{String,Any}[]
    for island in network_data["frequency_islands"]
        limits = island["limits"]
        limits_mw = Dict{String,Any}()
        for (name, limit) in limits
            limits_mw[name] = to_mw(limit, base_mva)
        end
        scheduled_import = calc_scheduled_import(network_data, result, island)

        push!(islands, Dict{String,Any}(
            "island_bus" => first(island["buses"]),
            "n_buses" => length(island["buses"]),
            "gens" => island["gens"],
            "governors" => island["governors"],
            "H" => round_value(island["inertia"], PU_DIGITS),
            "K" => round_value(island["governor_gain"], PU_DIGITS),
            "D" => round_value(island["damping"], PU_DIGITS),
            "limits_mw" => limits_mw,
            "binding" => argmin(limits),
            "scheduled_import_mw" => to_mw(scheduled_import, base_mva),
        ))
    end
    return islands
end

"A shed sized in a voltage round: each bus's shed and the load it was taken from (MW), and the worst indicator it leaves."
function calc_voltage_shed_summary(island_shed, base_mva::Real)
    sheds = Dict{String,Any}[]
    for shed in island_shed["sheds"]
        push!(sheds, Dict{String,Any}(
            "bus" => shed["bus"],
            "shed_mw" => to_mw(shed["shed"], base_mva),
            "of_mw" => to_mw(shed["of"], base_mva),
        ))
    end
    indicator_after = island_shed["indicator_after"]
    if indicator_after !== nothing
        indicator_after = round_value(indicator_after, PU_DIGITS)
    end
    return Dict{String,Any}(
        "sheds" => sheds,
        "indicator_after" => indicator_after,
        "indicator_after_bus" => island_shed["indicator_after_bus"],
    )
end

"One island of a voltage round with P and Q in MW and Mvar; an island that was not checked has only its status, bus and size."
function calc_island_voltage_summary(island, base_mva::Real)
    summary = Dict{String,Any}(
        "status" => island["status"],
        "bus" => island["bus"],
        "n_buses" => island["n_buses"],
    )
    island["status"] == "checked" || return summary

    largest_indicators = Dict{String,Any}[]
    for indicator in island["largest_indicators"]
        push!(largest_indicators, Dict{String,Any}(
            "value" => round_value(indicator["value"], PU_DIGITS),
            "bus" => indicator["bus"],
            "vm" => round_value(indicator["vm"], PU_DIGITS),
            "pd_mw" => to_mw(indicator["pd"], base_mva),
        ))
    end
    shed = nothing
    if island["shed"] !== nothing
        shed = calc_voltage_shed_summary(island["shed"], base_mva)
    end

    summary["n_with_generation"] = island["n_with_generation"]
    summary["n_holding_voltage"] = island["n_holding_voltage"]
    summary["at_upper_limit"] = island["at_upper_limit"]
    summary["at_lower_limit"] = island["at_lower_limit"]
    summary["slack_bus"] = island["slack_bus"]
    summary["slack_pg_mw"] = to_mw(island["slack_pg"], base_mva)
    summary["slack_qg_mvar"] = to_mw(island["slack_qg"], base_mva)
    summary["largest_indicators"] = largest_indicators
    summary["worst_indicator"] = round_value(island["worst_indicator"], PU_DIGITS)
    summary["shed"] = shed
    return summary
end

"The voltage security results (`result[\"voltage_security\"]`) with each round's details, P and Q in MW and Mvar."
function calc_voltage_summary(voltage_security, base_mva::Real)
    details = Dict{String,Any}[]
    for round_detail in voltage_security["details"]
        islands = Dict{String,Any}[]
        for island in round_detail["islands"]
            push!(islands, calc_island_voltage_summary(island, base_mva))
        end
        push!(details, Dict{String,Any}(
            "round" => round_detail["round"],
            "termination_status" => round_detail["termination_status"],
            "indicator_threshold" => round_detail["indicator_threshold"],
            "islands" => islands,
        ))
    end
    return Dict{String,Any}(
        "verified" => voltage_security["verified"],
        "rounds" => voltage_security["rounds"],
        "worst_indicator" => round_value(voltage_security["worst_indicator"], PU_DIGITS),
        "details" => details,
    )
end

"The results folder (absolute) and the names of the files the run wrote, from its settings record."
function calc_files_summary(output_path::AbstractString, run_record)
    files = Dict{String,Any}(
        "output_path" => abspath(output_path),
        "settings" => nothing,
        "excel" => nothing,
        "raw" => nothing,
        "report" => nothing,
    )
    run_record === nothing && return files

    files["settings"] = run_record.file
    for name in ("excel", "raw", "report")
        files[name] = run_record.record["files"][name]
    end
    return files
end

"""
The report information of a finished run, sent as @@result (gui_plan.md, "Result summary"), in
MW and Mvar. Grouped like the console reports (`find_group_kind`); parts whose feature was off
are `nothing`.
"""
function calc_result_summary(finished_run)
    result = finished_run.result
    network_data = finished_run.network_data
    settings = finished_run.settings
    target = finished_run.target
    base_mva = network_data["baseMVA"]
    group_kind = find_group_kind(network_data, target.zone, target.area)
    run_record = find_run_record(finished_run.output_path, finished_run.started)

    objective = result["objective"]
    isfinite(objective) || (objective = nothing)
    seconds = nothing
    if run_record !== nothing
        seconds = run_record.record["seconds"]
    end
    load_shed = nothing
    if occursin("shed", settings["objective"])
        load_shed = calc_load_shed_summary(network_data, result, group_kind)
    end
    frequency = nothing
    if haskey(network_data, "frequency_islands")
        frequency = calc_frequency_summary(network_data, result)
    end
    voltage = nothing
    if haskey(result, "voltage_security")
        voltage = calc_voltage_summary(result["voltage_security"], base_mva)
    end

    return Dict{String,Any}(
        "termination_status" => string(result["termination_status"]),
        "objective" => objective,
        "seconds" => seconds,
        "generation" => calc_generation_summary(network_data, result, group_kind),
        "load_shed" => load_shed,
        "boundary_flows" => calc_flow_summary(network_data, result, target),
        "frequency" => frequency,
        "voltage" => voltage,
        "files" => calc_files_summary(finished_run.output_path, run_record),
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

"""
Run a scenario: re-include the runner files so edits apply, run the settings reporting each
stage, then send the report information as @@result. Both calls go through invokelatest, so they
see the re-included runner functions.
"""
function handle_run(job)
    include_runner_files()
    progress = stage -> send_stage(job, stage)
    finished_run = Base.invokelatest(run_from_settings, job["settings"]; progress=progress)

    send_stage(job, "summary")
    summary = Base.invokelatest(calc_result_summary, finished_run)
    send_control("result", Dict("id" => get(job, "id", nothing), "summary" => summary))
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
