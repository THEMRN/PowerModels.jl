# Test 3: the frequency limits against ANDES dynamic simulations.
#   A. calibration sweeps: the scheduled import of the first island is fixed at a range of values
#      (a test-only equality constraint), each solution is simulated in ANDES with the relays
#      removed from the .dyr, and every island's simulated RoCoF, nadir and settling frequency
#      are compared with the SFR model behind the limits
#   B. pass/fail runs through run_islanding (the real pipeline, relays kept): frequency security
#      off and on, and what UFLS and the generator frequency relays do after the split
#
#     julia --project=. runners/frequency_tests/3_dynamic.jl              # both parts
#     julia --project=. runners/frequency_tests/3_dynamic.jl sweeps       # part A only
#     julia --project=. runners/frequency_tests/3_dynamic.jl passfail     # part B only

include("common.jl")

const OUTPUT_DIR = joinpath(TEST_RESULTS, "dynamic")
const KEEP_SWEEP_REPORTS = false        # dynamic.py's HTML report of each sweep point (60 MB each on ACTIVSg500)
const PARTS = isempty(ARGS) ? ["sweeps", "passfail"] : ARGS

# ==================== Runs ====================
# imports (MW) into the first island of the scenario; the island's units must be able to cover them
const SWEEPS = [
    (scenario="savnw_north", imports=[-300, -200, -150, -100, -50, 0, 25, 50, 75, 100, 125, 150, 200, 300]),
    (scenario="activsg_midlands_light", imports=[-150, -100, -50, 0, 50, 100, 150, 200, 300, 400]),
    (scenario="activsg_spartanb_light", imports=[-75, -50, -25, 0, 25, 50, 75, 100, 150, 200, 300]),
]
const PASS_FAIL_RUNS = [
    (scenario="savnw_north_heavy", objective="opf_shed"),
    (scenario="savnw_top", objective="opf"),
    (scenario="savnw_top_heavy", objective="opf"),
    (scenario="savnw_left", objective="opf_shed"),
    (scenario="activsg_spartanb", objective="opf_shed"),
    (scenario="activsg_midlands", objective="opf_shed"),
    (scenario="activsg_york", objective="opf_shed"),
]


# ==================== A. Calibration sweeps ====================
if "sweeps" in PARTS
    println("==================== A. Calibration sweeps ====================")
    for sweep in SWEEPS
        network_data, target_lines, case_files = load_scenario(sweep.scenario)
        islands = find_test_islands(network_data, target_lines, case_files.dyr)
        dyr_without_relays = write_dyr_without_relays(case_files.dyr, joinpath(OUTPUT_DIR, "dyr", basename(case_files.dyr)))
        sweep_dir = joinpath(OUTPUT_DIR, "sweep_$(sweep.scenario)")
        rm(sweep_dir; force=true, recursive=true)

        points = Dict{String,Any}[]
        for forced_import in sweep.imports
            run_dir = joinpath(sweep_dir, "import_$(forced_import)MW")
            data = deepcopy(network_data)
            result = solve_scenario!(data, target_lines, case_files.dyr; objective="opf", forced_import=forced_import, islands=islands)
            point = Dict{String,Any}("forced_import_mw" => forced_import, "folder" => basename(run_dir), "status" => string(result["termination_status"]))
            push!(points, point)
            if !is_solved(result)
                println("$(sweep.scenario) import $forced_import MW: no solution ($(point["status"])), skipped")
                continue
            end

            run_info = Dict("scenario" => sweep.scenario, "forced_import_mw" => forced_import)
            export_for_andes(data, result, target_lines, islands, dyr_without_relays, run_dir; run_info=run_info)
            simulation_seconds = @elapsed simulated = run_andes(run_dir)
            point["simulated"] = simulated
            if !simulated
                println("$(sweep.scenario) import $forced_import MW: ANDES failed, see $(joinpath(run_dir, "console.txt"))")
                continue
            end
            print("$(sweep.scenario) import $forced_import MW (ANDES $(round(simulation_seconds, digits=1)) s): ")
            run_analysis(run_dir)
            KEEP_SWEEP_REPORTS || foreach(rm, filter(f -> startswith(basename(f), "dynamic_channels_"), readdir(run_dir; join=true)))
        end
        write_json(joinpath(sweep_dir, "sweep.json"), Dict(
            "scenario" => sweep.scenario,
            "description" => SCENARIOS[sweep.scenario].description,
            "dyr" => dyr_without_relays,
            "points" => points,
        ))
    end
end


# ==================== B. Pass/fail runs through run_islanding ====================
if "passfail" in PARTS
    println("==================== B. Pass/fail runs ====================")
    passfail_dir = joinpath(OUTPUT_DIR, "passfail")
    runs = Dict{String,Any}[]
    for test_run in PASS_FAIL_RUNS, frequency_security in (false, true)
        scenario = SCENARIOS[test_run.scenario]
        network_data, target_lines, case_files = load_scenario(test_run.scenario)
        islands = find_test_islands(network_data, target_lines, case_files.dyr)
        uniform_shedding = contains(test_run.objective, "shed")
        uniform_shedding && redirect_stdout(devnull) do
            add_load_shedding_penalty!(network_data; uniform=true, uniform_penalty=SHED_PENALTY)
        end

        # run_islanding writes into results/psse/<case>_<objective>_<tag>; the folder is moved afterwards
        switch = frequency_security ? "on" : "off"
        case_name = basename(scenario.case_path)
        tag = "freqtest_$(test_run.scenario)_$(switch)"
        pipeline_dir = "results/psse/$(case_name)_$(test_run.objective)_$(tag)"
        run_dir = joinpath(passfail_dir, "$(test_run.scenario)_$(switch)")
        rm(pipeline_dir; force=true, recursive=true)
        mkpath(pipeline_dir)

        # console output of run_islanding and of the ANDES script to console.txt
        selected_buses = scenario.zone === nothing ? nothing : find_buses_by_zone(network_data, scenario.zone)
        run_seconds = @elapsed result = open(joinpath(pipeline_dir, "console.txt"), "w") do io
            redirect_stdout(io) do
                withenv("BROWSER" => NO_BROWSER) do
                    run_islanding(network_data;
                        case_name=case_name,
                        case_files=case_files,
                        objective=test_run.objective,
                        lambda=500,
                        opf_model="AC",
                        flow_model="squared",
                        target_lines=target_lines,
                        run_dynamic_sim=true,
                        uniform_shedding=uniform_shedding,
                        uniform_penalty=SHED_PENALTY,
                        target_zone=scenario.zone,
                        selected_buses=selected_buses,
                        output_tag=tag,
                        frequency_security=frequency_security,
                        simulator="andes",
                    )
                end
            end
        end
        rm(run_dir; force=true, recursive=true)
        mkpath(dirname(run_dir))
        mv(pipeline_dir, run_dir)

        run_info = Dict(
            "scenario" => test_run.scenario,
            "description" => scenario.description,
            "objective" => test_run.objective,
            "frequency_security" => frequency_security,
            "status" => string(result["termination_status"]),
        )
        write_islands_json(network_data, result, islands, case_files.dyr, run_dir; run_info=run_info)
        print("$(test_run.scenario) frequency security $switch ($(round(run_seconds, digits=1)) s): ")
        run_analysis(run_dir)
        push!(runs, merge(run_info, Dict("folder" => basename(run_dir))))
    end
    write_json(joinpath(passfail_dir, "passfail.json"), runs)
end
println("Dynamic results written to $OUTPUT_DIR")
