# GUI plan

A local GUI for running islanding scenarios without editing code. It sets the run (case, boundary, objective, penalties, security options, network modifications), runs it in a Julia session that stays warm, shows which stage is running, and shows the information the console reports print (generation, load shedding, boundary flows, frequency and voltage security) as tables. The Plotly report still opens in the browser as it does today.

## How to use this plan (for the implementing agent)

- Implement **one phase per session**. Do not start the next phase.
- Before starting, read `CLAUDE.md`, then the sections **Decisions**, **Architecture** and **Contracts** below, then your phase. The phase lists the files to read first.
- Follow the code style in `CLAUDE.md`. Use the same principles for Python: settings as constants at the top, small single-purpose functions, descriptive names, a short docstring on each non-trivial function, plain control flow.
- Every new file goes under `runners/gui/`. A phase may touch a file outside it only when the phase says so.
- Python is the **system Python 3.14 with no venv**, the same interpreter that runs PSS®E and ANDES. Do not create a venv. Do not add a Python dependency the phase does not name.
- Anything not covered by the phase, or any change to the workflow or the Julia ↔ Python contract beyond what the phase states, is a question for the user, not a decision.
- Verify the phase as its **Done when** says, on `cases/psse/savnw` and `cases/psse/ACTIVSg500`. No unit tests unless the user asks for them.
- **Do not edit the user's runners for testing.** To run an `islanding.jl` variant (for example with `run_dynamic_sim = false`), write a temporary copy into `runners/` so its `include`s still resolve, run it, and delete it.
- **Keep test runs out of the real results folders.** Results go to `results/psse/<case>_<objective>[_<tag>]`, so an untagged run overwrites the user's `run_info.json` and other files there.
  - Every verification run uses an `output_tag` that starts with `gui_test`.
  - When a phase compares against `islanding.jl`, give the temporary copy `output_tag="gui_test_ref"` in its `run_islanding` call.
  - List the test folders you left in the phase notes.
- At the end, set the phase's row in the status table to done and add two or three sentences under **Phase notes**: what changed, how it was verified, and anything the next phase should know.
- Do not commit unless the user asks.

## Status

| Phase | Title | Depends on | Status |
|---|---|---|---|
| 1 | Julia worker | none | done (2026-11-20) |
| 2 | Areas as well as zones | 1 | not started |
| 3 | Run hooks: stages and per-run settings file | 1 | not started |
| 4a | Report data: calc/print split | 2 | not started |
| 4b | Result summary from the worker | 3, 4a | not started |
| 5 | GUI shell and worker client | 1 | not started |
| 6 | Run page: settings form | 2, 5 | not started |
| 7 | Run page: status strip | 3, 6 | not started |
| 8 | Run page: results panel | 4b, 7 | not started |
| 9 | Advanced settings dialog | 6 | not started |
| 10 | History page | 3, 6 | not started |
| 11 | Network page | 2, 6 | not started |
| 12 | Presets (optional, ask the user first) | 6 | not started |

Phases 2, 3 and 5 can run in any order once phase 1 is done. The GUI is usable for real runs after phase 6.

## Decisions

These were made by the user. Do not reopen them.

1. **Python app in a browser tab.** The GUI is a Python app built with NiceGUI. It serves a page on the local machine only (`http://localhost:8080`), which opens in a browser tab; nothing leaves the machine. `app.py` keeps a constant `NATIVE_WINDOW = False`. A desktop window would need `pywebview`, so it is not pursued unless the user asks.
2. **One warm Julia worker.** The GUI starts one Julia process when it opens and keeps it. Stop kills that process with its `dynamic.py` child and starts a fresh one. The user accepted that the next run then pays the compile time again.
3. **Files.** All GUI files live in `runners/gui/`. There is no limit on their number.
4. **Run page layout.** The settings are on top and can be folded. Results are in the middle. The status strip is at the bottom. This may be revisited once the status strip exists.
5. **Information, not a console.** The run page does not show a scrolling raw console. Instead it has:
   - a bottom **status strip** that shows the stage running, the elapsed time and the latest activity line;
   - a **results panel** that shows the report information as tables;
   - a **Full log** button that opens the raw log, for errors and details.
6. **Advanced settings.** Load scaling, generator settings, load overrides and later additions go in an **Advanced settings dialog with tabs**, not on the main form.
7. **Per-run settings file.** Each run writes `settings_<timestamp>.json` next to its report in the results folder. `run_islanding` writes it, so runs from `islanding.jl` get one too. There is no separate GUI log. Deleting a results folder deletes its settings.
8. **Network page.** Start with the easiest clean drawing: an automatic force layout, with no bus coordinates.
9. **Zones and areas.** Some cases group buses by area rather than by zone. Wherever a group of buses is chosen, the choice is `{kind: "zone" | "area", name}`. That covers the boundary, penalties, load scaling, generator settings, results grouping and network colouring.
10. **Voltage security details as tables, behind a button.** The results panel shows only the main voltage results (verified, rounds, worst indicator). A Details button opens a dialog with tables, one block per round:
    - each island's state;
    - its largest indicators;
    - its generators at a reactive limit;
    - the sheds that were sized.

    To get these as data, `voltage.jl` returns them in `result["voltage_security"]["details"]` (phase 4a). That is a change inside the PowerModels module, so it triggers a recompile.

## Architecture

```
browser tab (NiceGUI page)
   │  websocket (NiceGUI)
runners/gui/app.py            Python 3.14: pages, worker client, results rendering
   │  stdin: one JSON job per line       stdout+stderr: log lines and @@ control lines
runners/gui/worker.jl         one long-lived Julia (julia --project=.), cwd = repo root
   │  run_islanding (runners/islanding_core.jl)
   └─ python runners/<simulator>_scripts/dynamic.py   (child of Julia, unchanged)
         └─ results/psse/<case>_<objective>[_<tag>]/   (raw, dyr, xlsx, run_info.json,
                                                         settings_<ts>.json, report html)
```

Planned files:

```
runners/gui/
  gui_plan.md            this plan
  worker.jl              Julia side: job loop, handlers, settings → run
  app.py                 entry point: python runners/gui/app.py
  julia_worker.py        Python client for worker.jl
  settings.py            settings schema v1: defaults, validation, (de)serialisation
  results_index.py       scans results/psse for the History page
  components/            reusable UI pieces (status_strip.py, results_view.py)
  pages/                 one file per page: run.py, history.py, network.py
  advanced/              one file per advanced-settings tab
  dev/send_jobs.py       command-line client for testing the worker without the GUI
```

**Extension rules:**
- **A new page** is one file in `pages/` that exposes `TITLE` and `build(ctx)`, plus one entry in `PAGES` in `app.py`.
- **A page that needs Julia** also gets one handler in `HANDLERS` in `worker.jl`.
- **A new advanced tab** is one file in `advanced/` plus one modification handler in `MODIFICATIONS` in `worker.jl`.
- **Pages pass values to each other** through `ctx.state`. For example, History's "Load into Run" and Network's "Use as target" both fill the Run form.

## Contracts

### Worker protocol

The GUI writes **one JSON object per line** to the worker's stdin:

```json
{"id": 7, "type": "run", "settings": { ... }}
```

| type | payload | reply |
|---|---|---|
| `ping` | none | `@@data {"id", "pong": true, "julia": "<version>"}` |
| `list_cases` | none | `@@data {"id", "cases": ["cases/psse/savnw", ...]}` (folders with a `.raw`) |
| `case_info` | `"case"` | `@@data {"id", "zones": [...], "areas": [...], "loads": [...], "gens": [...], "has_dyr"}` |
| `run` | `"settings"` | `@@stage` lines, then `@@result`, then `@@done` |
| `network` (phase 11) | `"case"` | `@@data {"id", "buses": [...], "branches": [...]}` |

The worker writes ordinary log lines (its own prints, Ipopt and `dynamic.py`) plus **control lines** that start with `@@`. Each control line has a kind and one-line JSON:

| kind | payload |
|---|---|
| `ready` | `{"julia": "<version>"}`, once after startup |
| `start` | `{"id", "type"}` |
| `stage` | `{"id", "stage", "label"}`, see the stage table |
| `data` | `{"id", ...}`, the reply of `ping`, `list_cases`, `case_info` and `network` |
| `result` | `{"id", "summary": {...}}`, see the result summary |
| `error` | `{"id", "message"}`; the stack trace goes to the log just before it |
| `done` | `{"id", "ok": true/false, "seconds"}` |

Rules on the worker side:
- **Writing a control line.** Ipopt and Julia share the output, so a control line has to start on a fresh line. First call `Libc.flush_cstdio()` and print `"\n"`. Then print `@@<kind> <json>` on one line and call `flush(stdout)`.
- **Errors.** Every handler runs inside `try`/`catch`. An error prints its stack trace, then sends `@@error` and `@@done ok=false`. The worker never exits on a job error.
- **Reloading runner files.** Before each `run`, the worker re-includes the runner files: `calc_line_flow.jl`, `excel_generator.jl`, `utils.jl` and `islanding_core.jl`. Edits to them then apply without a restart. After re-including, call their functions through `Base.invokelatest`; otherwise Julia's world age runs the old methods. Edits to `src/`, `frequency.jl` or `voltage.jl` need Restart Julia.

Rules on the GUI side:
- **Starting the worker.** Start it with `cwd` set to the repo root and with `PYTHONUNBUFFERED=1` and `PYTHONIOENCODING=utf-8` in its environment. `dynamic.py` inherits both, so its output streams and decodes correctly.
- **Reading the output.** Merge stderr into stdout, decode as UTF-8 with replacement, and read continuously so the pipe never fills.
- **Long lines.** asyncio's `readline` fails on lines longer than its 64 KiB default, and the `@@result`, `case_info` and `network` lines for ACTIVSg500 can be longer. Pass a large `limit` (for example 16 MiB) when creating the subprocess.
- **Stop.** Run `taskkill /T /F /PID <pid>` so the `dynamic.py` child dies too, then restart the worker.

### Stages

| stage | emitted by | when |
|---|---|---|
| `load_case` | worker | before parsing the case (parses are cached by path and file time) |
| `prepare` | worker | modifications, boundary lines, penalties |
| `frequency_limits` | `run_islanding` | only with frequency security |
| `solve` | `run_islanding` | before the solve; the voltage security loop runs inside this stage |
| `reports` | `run_islanding` | console reports |
| `excel` | `run_islanding` | Excel report |
| `export` | `run_islanding` | raw, line outage and dyr files, only with the dynamic simulation |
| `dynamic_sim` | `run_islanding` | before calling `dynamic.py` |
| `summary` | worker | building `@@result` |

### Settings schema v1

The GUI sends this to the worker, and `run_islanding` stores it verbatim as `gui_settings` in the per-run settings file:

```json
{
  "schema": 1,
  "case": "cases/psse/ACTIVSg500",
  "objective": "flow_shed",
  "opf_model": "AC",
  "flow_model": "squared",
  "lambda": 500,
  "boundary": {"kind": "zone", "name": "SPARTANB", "bus_pairs": []},
  "penalties": {
    "uniform": null,
    "groups": [{"kind": "zone", "name": "SPARTANB", "times_lambda": 2.5}],
    "buses": {"205": 5.8},
    "others": null
  },
  "frequency_security": false,
  "voltage_security": false,
  "run_dynamic_sim": true,
  "simulator": "andes",
  "output_tag": "spartanb_2.5",
  "modifications": {}
}
```

| field | meaning |
|---|---|
| `objective` | `opf`, `flow`, `flow_shed`, `opf_shed` |
| `opf_model` | `AC`, `DC`; voltage security needs `AC` |
| `flow_model` | `squared`, `abs_sum`, `combined` |
| `boundary.kind` | `zone` or `area`: the lines are that group's boundary lines and its buses orient the flows. `bus_pairs`: the lines come from `find_branches_by_bus_pairs` and nothing is oriented |
| `penalties` | All values are multiples of λ. `uniform` (if not null) applies to every load and ignores the rest. Otherwise the precedence is `buses` over `groups` over `others`. `others: null` keeps today's default of 1e4 absolute for loads that are not listed (`add_load_shedding_penalty!`) |
| `output_tag` | suffix of the results folder; empty means none |
| `modifications` | filled by the advanced dialog (phase 9); `{}` means none |

The worker turns penalties into the absolute per-bus dictionary that `add_load_shedding_penalty!` expects (bus string to `times_lambda * lambda`), exactly as `runners/islanding.jl` does by hand today.

### Per-run settings file

`run_islanding` writes `results/psse/<case>_<objective>[_<tag>]/settings_<timestamp>.json`. The timestamp is the same one used in the Excel file name and comes from `get_timestamp()`, called once at the start of the run.
- **At the start of the run** it writes `"status": "started"`.
- **At the end** it rewrites the file with `"status": "finished"`, the file names and a short summary.

A run that throws leaves `"started"`, and History shows that as incomplete.

```json
{
  "status": "finished",
  "started": "2026-11-21T10:15:02", "finished": "2026-11-21T10:16:40",
  "case_name": "ACTIVSg500",
  "objective": "flow_shed", "lambda": 500, "opf_model": "AC", "flow_model": "squared",
  "target_lines": [{"id": 12, "from": 154, "to": 3008, "ckt": "1"}],
  "target_zone": "spartanb",
  "load_shedding_penalties": {"3005": 1250.0},
  "uniform_shedding": false, "uniform_penalty": 0.0,
  "frequency_security": false, "voltage_security": false,
  "run_dynamic_sim": true, "simulator": "andes", "output_tag": "spartanb_2.5",
  "gui_settings": null,
  "files": {"excel": "pm_res_flow_shed_<ts>.xlsx", "raw": "...", "report": "dynamic_channels_<ts>.html"},
  "summary": {"termination_status": "LOCALLY_SOLVED", "objective": 0.0, "preemptive_shed_mw": 0.0, "voltage_security": null},
  "seconds": {"solve": 0.0, "dynamic_sim": 0.0}
}
```

The report name is `dynamic.py`'s own `dynamic_channels_<ts>.html`. `run_islanding` finds it after the simulation as the newest such file modified after the run started. `run_info.json` stays exactly as it is, because the Python report reads it.

### Result summary (`@@result`)

The summary is in MW and Mvar, rounded as the console reports round. Keys whose feature was off are `null`:
- `termination_status`, `objective`, `seconds` (`solve`, `dynamic_sim`, `total`)
- `generation`:
  - `group_kind`
  - `groups`: name, `pg_mw`, `pmax_mw`, `qg_mvar`, `qmax_mvar`
  - `total`
- `load_shed`:
  - `total_load_mw`, `total_shed_mw`
  - `groups`
  - `buses`: bus, `pd_mw`, `shed_mw`, `shed_pct`
- `boundary_flows`:
  - `lines`: id, from, to, `p_mw`, `q_mvar`, oriented into the target group when there is one
  - `net`, `abs_sum`
- `frequency`, one entry per island:
  - `island_bus`, `n_buses`, `H`, `K`, `D`
  - `limits_mw` (`rocof`, `qss`, `nadir`), `binding`
  - `scheduled_import_mw`
- `voltage`, from `result["voltage_security"]`:
  - `verified`, `rounds`, `worst_indicator`;
  - `details`, one entry per round:
    - `round` and the optimization status;
    - `islands`: for each island, its bus, bus count, buses with generation, buses holding voltage, generators at the upper and at the lower reactive limit, slack P and Q, and the largest indicators (value, bus, V, load MW). It also has a `status` of `checked`, `no_generator` or `power_flow_failed`;
    - `sheds`: bus, shed MW, of MW, and the indicator left after the shed.
- `files`: `output_path`, `excel`, `raw`, `report`

### Run page layout (target after phase 8)

```
┌ Islanding GUI ─────────────────────────────── [● Julia: ready] [Restart Julia] ┐
│ Run | History | Network                                                        │
├────────────────────────────────────────────────────────────────────────────────┤
│ [Case and model] [Boundary] [Load shedding penalties] [Security and simulation]│ ▴ fold
│ [Advanced settings… (2 active)]                             [▶ Run] [■ Stop]   │
├────────────────────────────────────────────────────────────────────────────────┤
│ Results of run 3 ▾   Summary | Generation | Load shed | Boundary | Frequency | Voltage | Files │
│   tables and summary cards                                                     │
├────────────────────────────────────────────────────────────────────────────────┤
│ ✓ load case  ✓ prepare  ✓ solve  ✓ reports  ✓ excel  ✓ export  ● dynamic sim  │
│ now: -- Solving power flow...          01:42     2 warnings     [Full log]     │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Julia worker

**Goal.** Run a scenario from a settings dictionary through a long-lived Julia process driven over stdin and stdout, with no GUI yet.

**Read first:**
- `runners/islanding.jl`: its hardcoded block is what `run_from_settings` reproduces.
- `runners/islanding_core.jl`: the `run_islanding` keyword arguments.
- `runners/utils.jl`: `find_case_files`, `find_branches_by_zone`, `find_buses_by_zone`, `find_branches_by_bus_pairs`, `add_load_shedding_penalty!`.

**Files:**
- `runners/gui/worker.jl` (new)
- `runners/gui/dev/send_jobs.py` (new)

**Steps:**
1. **Startup.** In `worker.jl`, check that the working directory is the repo root (`Project.toml` present). Load the same packages as `islanding.jl`, call `PowerModels.silence()`, include the runner files, and send `@@ready`.
2. **Job loop.** Read stdin line by line and parse each line as JSON. Look up `HANDLERS[type]` and send `@@start`. Run the handler under `try`/`catch` through `Base.invokelatest`, then send `@@done`. Follow the protocol rules above.
3. **Simple handlers.** Implement `ping`, `list_cases` and `case_info`. In this phase `case_info` returns zones (index, name, bus count, load MW), loads (id, bus, pd MW), gens (id, bus, pmax MW) and `has_dyr`. Areas come in phase 2.
4. **`handle_run`.** Re-include the runner files, then call `run_from_settings(settings)` through `Base.invokelatest`. `run_from_settings` does the following:
   - Validate the fields and give clear messages.
   - Find the case files.
   - Take a `deepcopy` of a cached parse (`parse_file(...; import_all=true)`, cached by path and file modification time).
   - Build the target lines and selected buses from `boundary`. It is an error when no line is found.
   - Build the absolute penalty dictionary from `penalties`.
   - Call `add_load_shedding_penalty!`.
   - Call `run_islanding` with `case_name = basename(case)`, `target_zone` (the zone name for zone boundaries), `selected_buses`, `output_tag` and `simulator`.
5. **Test client.** `dev/send_jobs.py` starts the worker as the GUI will (repo root, environment variables, merged output). It sends the jobs from a JSON file given on the command line, prints every line, and exits after the last `@@done`. Put two example job files next to it:
   - `dev/job_savnw.json`: the "north south separation" bus pairs from the notes in `islanding.jl`.
   - `dev/job_activsg500_spartanb.json`: zone SPARTANB with 2.5 λ in the zone and λ = 500.
   - Both use `flow_shed`, `run_dynamic_sim: false` and an `output_tag` that starts with `gui_test`.

**Done when:**
- **savnw job.** It prints the usual reports and ends with `@@done ok=true`.
- **ACTIVSg500 SPARTANB job.** It gives the same objective value and the same `preemptive_shed_mw` in `run_info.json` as `islanding.jl`'s current hardcoded block run with `run_dynamic_sim = false`, from a temporary copy.
- **Warm session.** Sending the same job twice in one session makes the second run clearly faster than the first. Report both times.
- **Errors.** A job with an unknown zone name gives a readable `@@error`, `@@done ok=false`, and the next job in the same file still runs.

**Out of scope:** areas, stages, the per-run settings file, the result summary, any GUI.

## Phase 2: Areas as well as zones

**Goal.** Allow every group choice to be a zone or an area. Zone runs must behave exactly as before.

**Read first:**
- `runners/utils.jl`: the zone helpers, `scale_loads!` and `print_branch_flows`.
- `runners/islanding_core.jl`: how `target_zone` is used. It feeds `print_branch_flows` and `run_info.json`.
- `src/io/pti.jl`: area records are parsed into `network_data["area interchange"]`, with fields `i` and `arname`, when `import_all=true`. Confirm this on the cases.

**Files:**
- `runners/utils.jl`
- `runners/islanding_core.jl` (only if needed for area boundaries)
- `runners/gui/worker.jl`

**Steps:**
1. **Area helpers.** Add `get_area_index_by_name`, `find_buses_by_area` and `find_branches_by_area` to `utils.jl`, mirroring the zone helpers in style. When a case has no area or zone records, use the index as the name (for example `"1"`). Do this for both kinds.
2. **Worker helpers.** In the worker, add `find_group_buses(data, kind, name)` and `find_group_branches(data, kind, name)`, and use them for the boundary and penalty groups.
3. **`case_info`.** It now also returns areas (index, name, bus count, load MW). It returns an empty list for a kind that has only one group or no records, so the GUI can hide it.
4. **Area boundaries.** Make them work with the smallest change. Today `print_branch_flows` looks up `target_zone` with `find_buses_by_zone`, which fails for an area name. One option is to give it the bus set; another is to pass the area buses as `selected_buses` without a zone name.
   - Keep the console output of zone runs identical.
   - Keep `run_info.json` compatible with the Python report: check what `psse_scripts/dynamic.py` and `andes_scripts/report.py` read from it.
   - Record an area target in a way the report does not misread, and say in the phase notes what you chose.

**Done when:**
- **Zone runs unchanged.** The ACTIVSg500 SPARTANB job gives the same console output (timestamps aside) and the same `run_info.json` as before.
- **Area run.** An area boundary run works on a case with at least two areas. List the areas of every case under `cases/psse` in the phase notes and say which case you used. If no case has two or more areas, say so and test the helpers on the case with the most areas.

**Out of scope:** load scaling by area (phase 9), the GUI.

## Phase 3: Run hooks: stages and per-run settings file

**Goal.**
- `run_islanding` reports its stages to a caller-supplied callback.
- `run_islanding` writes the per-run settings file described in **Contracts**.

**Read first:**
- `runners/islanding_core.jl`: all of `run_islanding`.
- **Contracts:** "Stages" and "Per-run settings file".

**Files:**
- `runners/islanding_core.jl`
- `runners/gui/worker.jl`
- `CLAUDE.md`

**Steps:**
1. **New keyword arguments.** Add `progress=nothing` and `run_settings=nothing` to `run_islanding`.
   - `progress` is a function taking a stage name; call it at the stage boundaries in the stage table. With `nothing`, nothing is printed, so terminal runs look as before.
   - `run_settings` is stored as `gui_settings`.
2. **One timestamp.** Compute the output path and one timestamp at the start. Use that timestamp for both the Excel file name and the settings file. The Excel name then carries the start time of the run, which is fine.
3. **The settings file.**
   - Write it with `"status": "started"` before the solve.
   - Rewrite it at the end with `"status": "finished"`, the file names, the report name found after `dynamic.py` (see Contracts), the short summary and the durations.
   - Take `target_lines` from/to/ckt from each branch's `source_id`, as the line outage file does.
4. **Worker.** Pass `progress` (sends `@@stage`) and `run_settings` (the settings). Also send the worker stages `load_case` and `prepare`.
5. **`CLAUDE.md`.**
   - Add the settings file to the "Julia ↔ Python contract" list and say that the Python report does not read it.
   - Add `runners/gui/` to the runner pipeline section with a one-line pointer to this plan.

**Done when:**
- **A run from `islanding.jl`** (no GUI, dynamic simulation on, savnw) leaves a `settings_<ts>.json` with `finished`, the right report name, and the same timestamp as the Excel file. Its console output is unchanged apart from the timestamp.
- **A worker run** sends the stages in table order, and skips `export` and `dynamic_sim` when the dynamic simulation is off.
- **A failed run.** A run forced to fail after the solve leaves the file with `"status": "started"`. For example, temporarily add `error("test")` right after the Excel step, then revert it.

**Out of scope:** the result summary, the GUI.

## Phase 4a: Report data: calc/print split

**Goal.** Make the numbers that the console reports print available as data, without changing the console output. This refactors shared runner code, so it gets its own checkpoint.

**Read first:**
- `runners/utils.jl`: `print_generation_status`, `print_load_shedding_status`, `print_branch_flows`, `analyze_load_shedding_results`.
- `runners/frequency.jl`: `print_frequency_security`.
- `runners/voltage.jl`: `print_island_voltage`, `print_island_shed`, `solve_voltage_secure_opf`.

**Files:**
- `runners/utils.jl`
- `runners/frequency.jl`
- `runners/voltage.jl`

**Steps:**
1. **Capture the logs first.** Before any edit, save the full console logs of the three runs listed under **Done when**.
2. **Split the report functions.** Split `print_generation_status`, `print_load_shedding_status` and `print_branch_flows` into:
   - a `calc_*` function that returns the numbers as a plain `Dict`;
   - the existing `print_*` function, which prints from that `Dict`.

   The printed text must stay byte-identical. The `calc_*` functions take a group kind (`"zone"` by default, `"area"` with the phase 2 helpers) so the GUI can group like the boundary.
3. **Frequency.** In `frequency.jl`, move the scheduled import into `calc_scheduled_import(network_data, result, island)` and use it in `print_frequency_security`. That file is included into the PowerModels module, so the name is exported. Check that it clashes with nothing in the runners. Editing it needs a recompile.
4. **Voltage details (decision 10).** In `voltage.jl`:
   - Split `print_island_voltage` and `print_island_shed` into `calc_*` and `print_*` in the same way.
   - In `solve_voltage_secure_opf`, collect each round's data (see `voltage` → `details` in **Contracts: Result summary**) in a local vector, because `result` is replaced every round. Attach it to the final `result["voltage_security"]["details"]`.
   - Keep the values in per unit, with `baseMVA`, as the file does internally.
   - The same rules as `frequency.jl` apply: the names are exported, and editing triggers a recompile.

**Done when:**
- **Identical console logs.** The full console log is identical before and after this phase, apart from timestamps and timings, for:
  - savnw `flow_shed`;
  - ACTIVSg500 SPARTANB `flow_shed` with `frequency_security = true`;
  - savnw with `voltage_security = true`.

  All three run with `run_dynamic_sim = false` and a `gui_test` output tag. Show the diff command and its empty result in the phase notes.

**Out of scope:** the worker, the GUI.

## Phase 4b: Result summary from the worker

**Goal.** The worker sends the report information to the GUI as `@@result`.

**Read first:**
- **Contracts:** "Result summary".
- **Decisions:** 10.
- `runners/voltage.jl`: what `result["voltage_security"]` holds.
- The `calc_*` functions from phase 4a.

**Files:**
- `runners/gui/worker.jl`

**Steps:**
1. **Build the summary.** After `run_islanding` returns:
   - send the stage `summary`;
   - build the summary from the `calc_*` results, the embedded `frequency_islands`, `result["voltage_security"]` and the file names;
   - send `@@result`.

   Convert to MW and Mvar here when the `calc_*` functions return per unit.
2. **Voltage.** Copy `result["voltage_security"]` into `voltage`, including `details`, converted to MW and Mvar (decision 10).

**Done when:**
- **Summary matches the log.** The numbers in `@@result` match the printed numbers in the same run's log, for the three runs of phase 4a. Spot-check totals, one generator group, one shed bus, one boundary line and one island.

**Out of scope:** the GUI.

## Phase 5: GUI shell and worker client

**Goal.** An app that starts, starts the Julia worker, shows its state, and can restart it. The pages are placeholders.

**Read first:** **Architecture** and **Contracts: Worker protocol**.

**Files:**
- `runners/gui/app.py`, `runners/gui/julia_worker.py`, `runners/gui/pages/run.py` (all new)
- `CLAUDE.md` (the start command under Environment & Commands)

**Steps:**
1. **Install NiceGUI.** Run `pip install nicegui` on the system Python 3.14 and check `python -c "import nicegui"`. If it does not install or import on 3.14, stop and report to the user. Do not try other libraries.
   - Run the app with `reload=False`.
   - Confirm that `asyncio.create_subprocess_exec` works inside NiceGUI's event loop on Windows. If it does not, use `subprocess.Popen` with a reader thread that hands lines to the UI loop, and say so in the phase notes.
2. **`julia_worker.py`.** Write a class `JuliaWorker` around `asyncio.create_subprocess_exec("julia", "--project=.", "runners/gui/worker.jl")`, following the GUI-side protocol rules. It provides:
   - **States:** `starting`, `ready`, `busy`, `stopped`, `crashed`.
   - **Methods:** `start`, `send(job)` (assigns and returns the id), `stop` (process tree kill), `restart`.
   - **Listeners:** for log lines, control messages and state changes.
   - **A per-job log** kept in memory.
3. **`app.py`.**
   - **Constants at the top:** `PORT = 8080`, `NATIVE_WINDOW = False`.
   - **Registry:** `PAGES = [run]`, plus a `ctx` object holding the worker, a shared `state` dict and the repo root.
   - **Header:** title, a Julia state pill and a Restart Julia button.
   - **Navigation:** tabs for the pages.
   - **Worker lifecycle:** start the worker on app start and stop it on app shutdown.
4. **`pages/run.py`.** A placeholder: `TITLE`, and `build(ctx)` with a Ping button that shows the reply.

**Done when:**
- **Start.** `python runners/gui/app.py` opens the page, and the pill goes from starting to ready.
- **Ping** answers.
- **Restart Julia** works.
- **External kill.** Killing `julia.exe` from Task Manager shows `crashed`, and Restart recovers.
- **Clean exit.** Closing the app leaves no `julia.exe` running (`tasklist | findstr julia`).

**Out of scope:** the settings form.

## Phase 6: Run page: settings form

**Goal.** Run real scenarios from the GUI.

**Read first:**
- **Contracts:** "Settings schema v1".
- `runners/gui/worker.jl`: the handlers.
- **Decisions:** 4 and 9.

**Files:**
- `runners/gui/settings.py` (new)
- `runners/gui/pages/run.py`

**Steps:**
1. **`settings.py`.** It holds:
   - `DEFAULT_SETTINGS` (schema v1);
   - `validate(settings)`, which returns a list of readable problems;
   - bus-pair text parsing (`"154-3008, 154-153"`);
   - JSON load and save.
2. **The four foldable cards:**
   - **Case and model:** case from `list_cases`, objective, OPF model, flow model, λ.
   - **Boundary:** kind (zone, area or bus pairs; zone and area appear only when `case_info` lists them), group name from `case_info`, bus-pairs text.
   - **Load shedding penalties:** a uniform switch and value; rows of group or bus with a × λ value, which can be added and removed; and "all other loads", blank by default, with the hint "default: 1e4, absolute".
   - **Security and simulation:** frequency security, voltage security (disabled under DC), dynamic simulation, simulator, output tag.
3. **Case changes.** Changing the case calls `case_info` and refreshes the group lists.
4. **Buttons.**
   - **Run** validates the settings and sends the job. It is disabled while the worker is busy.
   - **Stop** kills and restarts the worker.
   - **Advanced settings…** is visible but disabled until phase 9.
5. **Runs in this session.** A list showing id, case, objective, tag and status. Each run has the buttons Open report (server-side `webbrowser.open`), Open folder (`os.startfile`) and Load settings (puts the run's settings back in the form).
6. **Temporary log.** Until phase 7, add a temporary collapsed raw log under the form (`ui.log`), so the page is usable.

**Done when:**
- **Same results as phase 1.** The phase 1 savnw and ACTIVSg500 jobs run from the form and give the same results as their phase 1 runs.
- **An area run** works if phase 2 found a suitable case.
- **Case switching** refreshes the zone list.
- **DC** disables voltage security.
- **Bad input** (malformed bus pairs, an empty boundary) is reported before anything is sent.
- **Load settings** brings back a past run's settings exactly.

**Out of scope:** stages, result tables, the advanced dialog.

## Phase 7: Run page: status strip

**Goal.** Replace the raw log with the bottom status strip.

**Read first:**
- **Decisions:** 5.
- **Contracts:** "Stages".
- The run page layout sketch.

**Files:**
- `runners/gui/components/status_strip.py` (new)
- `runners/gui/pages/run.py`

**Steps:**
1. **The strip.** It sticks to the bottom of the page and shows:
   - **The stage stepper**, driven by `@@stage`: done, current and not applicable (greyed, for example `dynamic_sim` when it is off).
   - **Elapsed time** for the current stage and the whole run.
   - **"now:"** with the latest non-empty log line that is not a control line, cut to one line. This shows the voltage security rounds and the `dynamic.py` progress without parsing them.
   - **A warning count:** lines containing "warning" in any case. Clicking it lists them.
   - **A Full log button** that opens a dialog with the run's raw log, a search box and a copy button.
2. **Errors.** On `@@error`, mark the current stage red and show the message in the strip.
3. **Clean-up.** Remove the temporary raw log from phase 6.

**Done when:**
- **A normal run.** During an ACTIVSg500 run with the dynamic simulation, the stages advance in order and "now:" follows the `dynamic.py` lines.
- **A failing run** (unknown zone) shows a red stage and the message.
- **Full log** shows the whole output of each run, including the Ipopt and `dynamic.py` lines.

**Out of scope:** result tables.

## Phase 8: Run page: results panel

**Goal.** Show the report information as tables.

**Read first:**
- **Contracts:** "Result summary".
- The run page layout sketch.

**Files:**
- `runners/gui/components/results_view.py` (new)
- `runners/gui/components/voltage_details.py` (new)
- `runners/gui/pages/run.py`

**Steps:**
1. **Panel and tabs.** Build a results panel driven by `@@result`, with these tabs:
   - **Summary:** termination status, objective, total load, shed MW, boundary net P and Q, frequency verdict per island (import against the binding limit), voltage verified, rounds and worst indicator, durations, and the output folder with Open report and Open folder.
   - **Generation**, by group.
   - **Load shedding:** by group, and by bus showing only buses with shed by default.
   - **Boundary flows:** per line, net, and sum of absolute flows.
   - **Frequency:** per island.
   - **Voltage:** only the main results (verified, rounds, worst indicator). A Details button opens a dialog with the per-round tables from `voltage` → `details` (decision 10). Keep the dialog in its own component file, `components/voltage_details.py`.
   - **Files**.
2. **Visibility and units.** Hide a tab whose part is `null`. Use MW and Mvar with the console's rounding.
3. **Run selector.** "Results of run N" switches between this session's runs.

**Done when:**
- **Numbers match.** The panel's numbers match the printed reports in the Full log for:
  - a savnw run;
  - an ACTIVSg500 run with frequency security;
  - a savnw run with voltage security, including the Details dialog against the "Voltage viability, round N" lines.

**Out of scope:** the History page.

## Phase 9: Advanced settings dialog

**Goal.** Network modifications that are used rarely, in a dialog with tabs, built to grow.

**Read first:**
- `runners/islanding.jl`: the commented scenario notes (`scale_loads!`, load `pd` overrides, generator `pmin = 0` in a zone).
- `runners/utils.jl`: `scale_loads!`.
- **Decisions:** 6 and 9.

**Files:**
- `runners/gui/advanced/__init__.py`, `load_scaling.py`, `loads.py`, `generators.py` (all new)
- `runners/gui/pages/run.py`
- `runners/gui/settings.py`
- `runners/gui/worker.jl`

**Steps:**
1. **Tab registry.** `ADVANCED_TABS` holds the tab modules. Each module exposes `TITLE`, `KEY` (its entry in `settings["modifications"]`) and `build(ctx, modifications)`.
2. **The three tabs:**
   - **Load scaling:** rows of a group or a bus list, and a factor.
   - **Loads:** pick a load from `case_info`, then set its `pd` in MW (and `qd` in Mvar if given).
   - **Generators:** rows of a group, with "set pmin to 0" (the case in the notes). The tab is built so later fields can be added, for example a per-generator `pmax` or status.
3. **Worker.** Add `MODIFICATIONS = Dict("load_scaling" => ..., "loads" => ..., "generators" => ...)`. Apply them in that fixed order in the `prepare` stage, before the boundary and penalties.
   - Group scaling uses `scale_loads!(data, factor, buses)` with the group's buses.
   - Loads: MW to per unit with `baseMVA`.
4. **Run page.** The Advanced settings button opens the dialog and shows "(n active)". A short line under the buttons lists the active modifications. Reset clears them.

**Done when:**
- **savnw "island on top".** That scenario from the notes (load 6 `pd = 4.0` pu, with the five bus pairs) gives the same results from the GUI as from `islanding.jl`.
- **ACTIVSg500 scaling.** Scaling SPARTANB by 0.7 gives the same results as `scale_loads!(data, 0.7, "SPARTANB")` in `islanding.jl`.
- **Saved settings.** The modifications are stored in `gui_settings` and restored by Load settings.

**Out of scope:** new kinds of modification beyond these three. Ask the user.

## Phase 10: History page

**Goal.** Filter past runs and open their reports.

**Read first:**
- **Contracts:** "Per-run settings file".
- **Decisions:** 7.
- The current contents of a few `results/psse/*` folders.

**Files:**
- `runners/gui/results_index.py` (new)
- `runners/gui/pages/history.py` (new)
- `runners/gui/app.py` (registry)

**Steps:**
1. **`results_index.py`.** Scan `results/psse/*/settings_*.json` into rows: time, folder, case, objective, boundary (kind and name, or "bus pairs"), λ, penalty summary, shed MW, simulator, frequency and voltage flags, status and report.
   - **Older runs.** Report files without a settings file (from before phase 3) become rows with the time from `dynamic_channels_<ts>.html` and "no settings".
   - **The newest older row** of a folder may also show `run_info.json` values, marked "latest only".
2. **The page.**
   - **Filters:** text (folder or tag), case, objective, group name, simulator, date range, status, and "only with a report".
   - **Table and details:** a sortable table, and a detail panel for the selected row.
   - **Buttons:** Open report, Open folder, and Load into Run (`gui_settings` when present; otherwise fill the fields that `run_islanding` recorded).
   - **Refresh:** a Refresh button. There is no delete, because the user deletes folders by hand.

**Done when:**
- **New runs appear.** After two GUI runs and one `islanding.jl` run, all three appear with the right settings.
- **Older folders** appear as "no settings" rows.
- **The filters** narrow the table correctly.
- **Open report** opens the right file.
- **Load into Run** fills the form.

**Out of scope:** comparing runs side by side. Ask the user if wanted.

## Phase 11: Network page

**Goal.** See the network, coloured by zone or area, and pick a group as the target from it.

**Read first:**
- **Decisions:** 8 and 9.
- `runners/utils.jl`: `build_network_graph` may already help.
- NiceGUI's `ui.echart`. It is ECharts, whose graph series has a force layout.

**Files:**
- `runners/gui/pages/network.py` (new)
- `runners/gui/worker.jl` (`network` handler)
- `runners/gui/app.py` (registry)

**Steps:**
1. **The `network` handler.** It returns:
   - buses: id, zone, area, has generator, load MW;
   - in-service branches: id, from bus, to bus;
   - the zone and area names.
2. **The page.**
   - **Controls:** a case selector, and colour by zone or by area.
   - **The graph:** a force layout. Click a bus to select its group, and highlight that group's boundary branches, the same set `find_branches_by_zone` or `find_branches_by_area` returns.
   - **Actions:** "Use as target" and "Set penalty for this group" fill the Run form through `ctx.state`.
3. **Optional.** If it is easy, shift-clicking branches builds a bus-pair boundary.

**Done when:**
- **Render time.** savnw and ACTIVSg500 render within a few seconds.
- **Highlighting.** Selecting SPARTANB highlights exactly the lines `find_branches_by_zone` returns.
- **Use as target** fills the Run form.

**Out of scope:** geographic coordinates. Ask the user later.

## Phase 12: Presets (optional, ask the user before starting)

**Goal.** Named settings files, like the commented scenario blocks in `islanding.jl`.

**Steps:**
- **Storage.** Presets live in `runners/gui/presets/*.json` (settings schema v1).
- **Run page.** It gets a preset selector, Save as and Delete.
- **Starter presets.** Optionally add starter presets transcribed from the notes in `islanding.jl`:
  - savnw top, left and bottom islands, and the north-south separation;
  - ACTIVSg500 SPARTANB.

**Done when:** a saved preset reloads exactly, and the starter presets reproduce their `islanding.jl` scenarios.

---

## Phase notes

(Each phase adds two or three sentences here: what changed, how it was verified, and anything the next phase should know.)

**Phase 1 (2026-11-20).**

*What changed.* `runners/gui/worker.jl` implements the job loop, the control lines (`send_control` flushes Julia's and C's stdout first) and the handlers `ping`, `list_cases`, `case_info` and `run`. `run_from_settings` reproduces the hardcoded block of `islanding.jl`. `runners/gui/dev/send_jobs.py` and two job files are there for testing without the GUI. Nothing outside `runners/gui/` changed.

*How it was verified.* The ACTIVSg500 SPARTANB job (2.5 λ, λ = 500, `flow_shed`, squared, AC) matched a run of a temporary copy of `islanding.jl` (dynamic simulation off, tag `gui_test_ref`):
- objective 12140.983057017995;
- 407.43 MW shed;
- net boundary flow P = -1.058, Q = 0.042;
- identical `run_info.json`.

Other checks:
- **Timings.** In one session, the first ACTIVSg500 run took 40.0 s and the second 4.75 s. The worker was ready after 25 s on its first start and after 3.4 s later on.
- **savnw.** The bus-pair job ran fine.
- **Errors.** An unknown zone gave `@@error "Zone 'atlantis' not found in network data"`, and the next job (a ping) still ran.
- **`case_info` for savnw** returned zone loads FIRST 1200, SECOND 1500, FIFTH 500 and PLANT 0 MW (the same as its load shedding report), 8 loads, 6 generators, and `has_dyr` true.
- **Penalty forms,** checked against `run_info.json`:
  - `buses` {3008: 2, 153: 0.5} gave `shed_penalty_rel` [0.5, 2.0];
  - `others` 1.6 gave `shed_penalty_rel` 1.6;
  - `uniform` 0.2 gave `uniform_shedding` true and `uniform_penalty_rel` 0.2.
- **Validation.** DC with voltage security was rejected with "invalid settings: voltage security needs the AC model".
- **Dynamic simulation through the pipe.** A savnw run with the dynamic simulation (ANDES) streamed every `dynamic.py` line, in order, through the worker's output before `@@done`.

Not exercised: editing a runner file while the worker runs (the re-include path).

Test folders left in `results/psse`:
- `savnw_flow_shed_gui_test`, `_gui_test_buses`, `_gui_test_others`, `_gui_test_uniform`, `_gui_test_dyn`;
- `ACTIVSg500_flow_shed_gui_test`, `_gui_test_ref`.

`dev/send_jobs.py --full` prints control lines without cutting them (useful for checking `@@result` in phase 4b).

*For the next phases:*
- **Phase 2.** The extension points are `BOUNDARY_KINDS`, `GROUP_KINDS` and `find_group_buses` in `worker.jl`. `find_target` and `case_info` (`calc_zone_table`) need the area cases.
- **Target zone name.** `target_zone` is passed exactly as given, so `run_info.json` shows the name as the GUI sends it ("SPARTANB" from `case_info`, where `islanding.jl` writes "spartanb").
- **Not yet supported.** Settings with a non-empty `modifications` are rejected until phase 9.
