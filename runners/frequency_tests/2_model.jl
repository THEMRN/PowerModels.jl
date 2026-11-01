# Test 2: the frequency constraint in the optimization (constraint_island_frequency_security).
# Each test solves a scenario twice, frequency security off and on, and checks the expected
# outcome:
#   "binds"       off: some island's import exceeds its limit; on: every import within its
#                 limit and at least one at it (within BINDING_TOLERANCE)
#   "within"      as "binds", without requiring an import at its limit (flat objective: any
#                 dispatch inside the limits is optimal)
#   "unchanged"   off: every import already within its limit; on: the same solution
#   "infeasible"  on: no solution, and the hand check agrees the limits cannot be met
#                 without shedding (check_limits_feasible_by_hand)
#
#     julia --project=. runners/frequency_tests/2_model.jl

include("common.jl")

const OUTPUT_DIR = joinpath(TEST_RESULTS, "model")
const SAME_OBJECTIVE = 1e-6         # relative, "unchanged" solutions
const SAME_IMPORT = 1e-3            # MW, "unchanged" solutions

# user's penalties from islanding.jl: 2.5 lambda inside SPARTANB (lambda = 500), the default elsewhere
spartanb_user_penalties!(data) = add_load_shedding_penalty!(data;
    penalties=Dict(string(bus) => 2.5 * 500 for bus in find_buses_by_zone(data, "SPARTANB")))

# ==================== Tests ====================
const TESTS = [
    # savnw: the constraint in both directions, infeasibility, shedding, DC ------------
    (scenario="savnw_top", objective="opf", opf_model="AC", expect="binds", penalties=nothing,
        purpose="exporting island: the export is cut to the RoCoF limit"),
    (scenario="savnw_top_heavy", objective="opf", opf_model="AC", expect="binds", penalties=nothing,
        purpose="the same island with 400 MW at 3005 (islanding.jl): its unit stays above its governor minimum"),
    (scenario="savnw_north", objective="opf", opf_model="AC", expect="binds", penalties=nothing,
        purpose="importing island: the import is cut to the RoCoF limit by redispatch"),
    (scenario="savnw_bottom", objective="opf", opf_model="AC", expect="unchanged", penalties=nothing,
        purpose="imports already within the limits: the solution must not change"),
    (scenario="savnw_north_heavy", objective="opf", opf_model="AC", expect="infeasible", penalties=nothing,
        purpose="north units (1017 MW) cannot cover 1120 MW minus the 56.5 MW limit without shedding"),
    (scenario="savnw_north_heavy", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="same island with shedding allowed: the deficit is shed preemptively"),
    (scenario="savnw_left", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="island without governor (K = 0): the QSS limit is only D x 0.3/60"),
    (scenario="savnw_north", objective="flow_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="flow objective (sum of squared branch flows) still leaves a net import above the limit"),
    (scenario="savnw_north_heavy", objective="opf_shed", opf_model="DC", expect="binds", penalties=nothing,
        purpose="DC model: flow expressions at the island end of each arc"),
    (scenario="savnw_top", objective="opf", opf_model="DC", expect="within", penalties=nothing,
        purpose="DC model with equal costs and no losses: flat objective, the limit must still hold"),
    # savnw: edge cases -----------------------------------------------------------------
    (scenario="savnw_gen_only", objective="opf", opf_model="AC", expect="binds", penalties=nothing,
        purpose="island with no load and no governor: QSS limit 0, the unit must be scheduled at zero"),
    (scenario="savnw_dead_bus", objective="opf", opf_model="AC", expect="unchanged", penalties=nothing,
        purpose="island without generation is skipped, the rest of the system keeps its constraint"),
    (scenario="savnw_north_line_out", objective="opf", opf_model="AC", expect="binds", penalties=nothing,
        purpose="a target line already out of service"),
    # ACTIVSg500 --------------------------------------------------------------------------
    (scenario="activsg_spartanb", objective="opf", opf_model="AC", expect="infeasible", penalties=nothing,
        purpose="zone units (608 MW) cannot cover 1043 MW minus the 49.4 MW limit"),
    (scenario="activsg_spartanb", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="importing zone with shedding allowed"),
    (scenario="activsg_spartanb", objective="opf_shed", opf_model="DC", expect="binds", penalties=nothing,
        purpose="DC model on the large case"),
    (scenario="activsg_midlands", objective="opf", opf_model="AC", expect="infeasible", penalties=nothing,
        purpose="zone units (1023 MW) cannot cover 1196 MW minus the 101.8 MW limit"),
    (scenario="activsg_midlands", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="importing zone with mixed hydro, gas and steam units"),
    (scenario="activsg_york", objective="opf", opf_model="AC", expect="infeasible", penalties=nothing,
        purpose="exporting zone: the rest of the system cannot cover its own load without York's export"),
    (scenario="activsg_york", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="exporting zone with shedding allowed: the shedding happens outside the zone"),
    (scenario="activsg_columbia", objective="opf", opf_model="AC", expect="unchanged", penalties=nothing,
        purpose="small exchange, within the limits"),
    (scenario="activsg_greenvil", objective="opf_shed", opf_model="AC", expect="binds", penalties=nothing,
        purpose="zone with almost no generation: limits of about 1 MW"),
    (scenario="activsg_spartanb", objective="flow_shed", opf_model="AC", expect="unchanged", penalties=spartanb_user_penalties!,
        purpose="the islanding.jl setup (flow_shed, lambda 500, 2.5 lambda in the zone)"),
]

"Outcome of one test: both solves, the imports and the check of its expectation."
function run_model_test(test)
    network_data, target_lines, case_files = load_scenario(test.scenario)
    test.penalties === nothing || redirect_stdout(devnull) do
        test.penalties(network_data)
    end
    islands = find_test_islands(network_data, target_lines, case_files.dyr)
    dead_islands = find_dead_islands(network_data, target_lines, islands)
    feasible_by_hand, import_ranges, dead_load = check_limits_feasible_by_hand(network_data, islands, dead_islands)

    # frequency security off and on
    data_off = deepcopy(network_data)
    result_off = solve_scenario!(data_off, target_lines, case_files.dyr; objective=test.objective, opf_model=test.opf_model)
    data_on = deepcopy(network_data)
    result_on = nothing
    error_message = nothing
    try
        result_on = solve_scenario!(data_on, target_lines, case_files.dyr;
            objective=test.objective, opf_model=test.opf_model, frequency_security=true)
    catch err
        error_message = sprint(showerror, err)
    end
    solved_off = is_solved(result_off)
    solved_on = result_on !== nothing && is_solved(result_on)

    # per island: limit, imports off/on, and the import range the hand check allows
    island_rows = Dict{String,Any}[]
    imports_off = solved_off ? calc_island_imports(network_data, islands, result_off) : fill(NaN, length(islands))
    imports_on = solved_on ? calc_island_imports(network_data, islands, result_on) : fill(NaN, length(islands))
    for (k, island) in enumerate(islands)
        limits_mw, binding = calc_limits_mw(network_data, island)
        balance = calc_island_balance(network_data, island["buses"])
        push!(island_rows, Dict(
            "island" => k,
            "n_buses" => length(island["buses"]),
            "limit_mw" => limits_mw[binding],
            "binding" => binding,
            "import_off_mw" => imports_off[k],
            "import_on_mw" => imports_on[k],
            "load_mw" => balance["load_mw"],
            "pmax_mw" => balance["pmax_mw"],
            "pmin_mw" => balance["pmin_mw"],
            "hand_import_range_mw" => import_ranges[k],
        ))
    end
    over_limit_off = any(abs(row["import_off_mw"]) > row["limit_mw"] + BINDING_TOLERANCE for row in island_rows)
    within_on = solved_on && all(abs(row["import_on_mw"]) <= row["limit_mw"] + BINDING_TOLERANCE for row in island_rows)
    at_limit_on = solved_on && any(abs(abs(row["import_on_mw"]) - row["limit_mw"]) <= BINDING_TOLERANCE for row in island_rows)

    # check the expectation
    if test.expect == "binds"
        passed = solved_off && over_limit_off && within_on && at_limit_on
    elseif test.expect == "within"
        passed = solved_off && over_limit_off && within_on
    elseif test.expect == "unchanged"
        same_objective = solved_on && abs(result_on["objective"] - result_off["objective"]) <= SAME_OBJECTIVE * abs(result_off["objective"])
        same_imports = solved_on && all(abs(row["import_on_mw"] - row["import_off_mw"]) <= SAME_IMPORT for row in island_rows)
        passed = solved_off && !over_limit_off && same_objective && same_imports
    elseif test.expect == "infeasible"
        passed = solved_off && !solved_on && !feasible_by_hand
    end

    shed_off = solved_off ? calc_total_shed(network_data, result_off) : NaN
    shed_on = solved_on ? calc_total_shed(network_data, result_on) : NaN
    row = Dict(
        "scenario" => test.scenario,
        "description" => SCENARIOS[test.scenario].description,
        "objective" => test.objective,
        "opf_model" => test.opf_model,
        "expect" => test.expect,
        "purpose" => test.purpose,
        "passed" => error_message === nothing && passed,
        "error" => error_message,
        "status_off" => string(result_off["termination_status"]),
        "status_on" => result_on === nothing ? "ERROR" : string(result_on["termination_status"]),
        "objective_off" => solved_off ? result_off["objective"] : NaN,
        "objective_on" => solved_on ? result_on["objective"] : NaN,
        "solve_time_off_s" => result_off["solve_time"],
        "solve_time_on_s" => result_on === nothing ? NaN : result_on["solve_time"],
        "shed_off_mw" => shed_off,
        "shed_on_mw" => shed_on,
        "feasible_by_hand" => feasible_by_hand,
        "dead_island_load_mw" => dead_load,
        "islands" => island_rows,
    )

    println("---------------------------")
    println("$(test.scenario)  $(test.objective) $(test.opf_model)  expect $(test.expect): ", row["passed"] ? "PASS" : "FAIL")
    println("  ", test.purpose)
    println("  status off $(row["status_off"]), on $(row["status_on"]);  feasible by hand without shedding: $feasible_by_hand",
        error_message === nothing ? "" : "\n  error: $(first(error_message, 200))")
    for island in island_rows
        println("  island $(island["island"]) ($(island["n_buses"]) buses): limit $(round(island["limit_mw"], digits=2)) MW ($(island["binding"])), ",
            "import off $(round(island["import_off_mw"], digits=2)) MW, on $(round(island["import_on_mw"], digits=2)) MW")
    end
    println("  shed off $(round(shed_off, digits=1)) MW, on $(round(shed_on, digits=1)) MW;  solve time off $(round(row["solve_time_off_s"], digits=2)) s, on $(round(row["solve_time_on_s"], digits=2)) s")
    return row
end

# warm-up solve, so the first test's solve time does not include compilation
let (network_data, target_lines, case_files) = load_scenario("savnw_north")
    solve_scenario!(network_data, target_lines, case_files.dyr; frequency_security=true)
end

rows = [run_model_test(test) for test in TESTS]
write_json(joinpath(OUTPUT_DIR, "model_tests.json"), rows)
println("===========================")
println("$(count(row -> row["passed"], rows)) of $(length(rows)) model tests passed, results in $OUTPUT_DIR")
