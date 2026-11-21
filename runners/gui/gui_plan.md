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
| 2 | Areas as well as zones | 1 | done (2026-11-20) |
| 3 | Run hooks: stages and per-run settings file | 1 | done (2026-11-20) |
| 4a | Report data: calc/print split | 2 | done (2026-11-20) |
| 4b | Result summary from the worker | 3, 4a | done (2026-11-20) |
| 5 | GUI shell and worker client | 1 | done (2026-11-20) |
| 6 | Run page: settings form | 2, 5 | done (2026-11-20) |
| 7 | Run page: status strip | 3, 6 | done (2026-11-20) |
| 8 | Run page: results panel | 4b, 7 | done (2026-11-20) |
| 9 | Advanced settings dialog | 6 | done (2026-11-21) |
| 10 | History page | 3, 6 | not started |
| 11 | Network page | 2, 6 | done (2026-11-21) |
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
8. **Network page.** The network is drawn as a clean graph without bus coordinates: the buses of a zone or an area stand together in a circle, a bus whose zone number sits among another zone's buses keeps its colour and does not pull the picture apart, and the page zooms and pans without becoming slow. Buses, lines and circles can be coloured by what the case holds or a run found. (The first decision was "the easiest clean drawing, an automatic force layout"; the user replaced it on 2026-11-21, when phase 11 was started.)
9. **Zones and areas.** Some cases group buses by area rather than by zone. Wherever a group of buses is chosen, the choice is `{kind: "zone" | "area", name}`. That covers the boundary, penalties, load scaling, generator settings, results grouping and network colouring.
10. **Voltage security details as tables, behind a button.** The results panel shows only the main voltage results (verified, rounds, worst indicator). A Details button opens a dialog with tables, one block per round:
    - each island's state;
    - its largest indicators;
    - its generators at a reactive limit;
    - the sheds that were sized.

    To get these as data, `voltage.jl` returns them in `result["voltage_security"]["details"]` (phase 4a). That is a change inside the PowerModels module, so it triggers a recompile.
11. **An area study is reported by area, a zone study by zone, never mixed.** `find_group_kind` (`utils.jl`) picks the kind:
    - the target's own kind;
    - for bus pairs, zones when the case has more than one zone, otherwise areas.

    The console, `@@result`, `run_info.json` (`group_kind`), the Excel bus sheet and the ANDES report all follow it. A new report that groups buses uses it too.
12. **A load belongs to its bus's zone and area**, never to the zone or area on its own RAW record.
13. **The PSS®E script (`psse_scripts/dynamic.py`) is no longer updated.** New report features go into the ANDES side only (`andes_scripts/dynamic.py`, `report.py`).
14. **The look: simple, elegant, compact, and not Material Design.** The user rejected the first look of phases 5 and 6 (NiceGUI's default, which is Quasar's Material Design): wasted space, poor colours, no taste. Every page follows the rules under "Look" below.

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
  network_layout.jl      Julia side: where the buses of a case stand on the Network page (no PowerModels in it)
  app.py                 entry point: python runners/gui/app.py [--port N] [--no-browser]
  start_gui.bat          double-click launcher for app.py (passes its arguments on)
  julia_worker.py        Python client for worker.jl
  session_runs.py        the runs of this app session (settings, status, result), shared by all tabs
  settings.py            settings schema v1: defaults, form values <-> settings, validation, JSON files
  network_view.py        what the Network page shows, as plain data: values, colours, selection, boundary
  theme.py               the look: element defaults, icons, building blocks (panel, sheet, Section, fields, button, State, FoldButton)
  theme.css              the look: colours and sizes as variables, the building blocks, Quasar without the Material look
  results_index.py       scans results/psse for the History page
  components/            reusable UI pieces: status_strip.py (where a run is), log_dialog.py (log lines as text),
                         results_view.py (a run's report numbers as tables), voltage_details.py (the voltage rounds),
                         row_list.py (rows to edit, with Add row and remove),
                         network_canvas.py with network_canvas.js (the network drawing: a canvas with zoom and pan)
  pages/                 one file per page: run.py, history.py, network.py
  advanced/              the advanced settings: __init__.py (the tab list, the dialog, what the modifications say),
                         one file per tab (load_scaling.py, loads.py, generators.py) and where.py (a row's zone,
                         area or bus list, shared by load scaling and the generators)
  dev/send_jobs.py       command-line client for testing the worker without the GUI
  dev/check_results_tables.py  compares the results panel's tables with the printed reports in a send_jobs log
  dev/jobs_results_check.json  the five runs that check is made for
```

**NiceGUI version.** The installed version is NiceGUI 4.0.0 (with uvicorn 0.54 and FastAPI 0.165), newer than most examples in memory or online. Check the installed API before using an idiom, for example with `inspect.signature` or the package source. For instance, `ui.run` has a `root` parameter since 3.0, and `Client.on_delete` exists since 3.0. `ui.page` still works and is what `app.py` uses.

**Extension rules:**
- **A new page** is one file in `pages/` that exposes `TITLE` and `build(ctx)`, plus one entry in `PAGES` in `app.py`.
- **A page that needs Julia** also gets one handler in `HANDLERS` in `worker.jl`.
- **A new advanced tab** is one file in `advanced/`, listed in `ADVANCED_TABS`, plus one function in `MODIFICATIONS` in `worker.jl` under the same key. The file exposes:
  - `TITLE` and `KEY` (its key in `settings["modifications"]`);
  - `describe(entries)`, one short text per entry, and `find_problems(entries, study)`, what keeps them from running. Both draw nothing;
  - `find_rows(entries, study)` and `read_rows(rows, study)`, between the entries and the dialog's rows;
  - `build(study, rows, on_change)`, the tab's content. A tab of rows builds them with `components/row_list.RowList` and a grid class of its own in `theme.css`.

  `study` (`advanced.Study`) holds the case, its `case_info` and the study's kind of group. A tab whose rows name a zone, an area or a list of buses takes that part from `advanced/where.py`, and its Julia function takes the buses from `find_entry_buses`.
- **Pages pass values to each other** through `ctx.client_state()`, the dict of the browser tab. The Run page puts its form there (`"run_form"`), `app.py` the function that shows a page (`"show_page"`), and the Network page's "Use as target" calls `RunForm.take` and shows the Run page. History's "Load into Run" goes the same way. `ctx.state` is shared by every open browser tab, so it only holds what was read from Julia.
- **What `ctx` holds** (since phase 6):
  - `ctx.worker`, the `JuliaWorker`;
  - `ctx.runs`, the `SessionRuns`: one record per run of this session, with its settings, status, the stages it reached with their times, its latest log line, its warnings and its `@@result` summary (the fields are listed in the class's docstring);
  - `ctx.state`, which caches what was read from Julia: `"cases"` (the case list), `"case_infos"` (case path to its `case_info`, or to the error that reading it gave) and `"networks"` (the same for the `network` reply). The worker answers one job at a time, so a question asked during a run would wait for the run to end.

### Look

Decision 14. The look lives in `theme.py` and `theme.css` and nowhere else, so every page gets it.

**What it is:**
- **Light and quiet.** A grey page, white panels with a hairline border, no shadows.
- **One accent colour** (blue) for the main action, the chosen option and the focus ring. Green, amber and red only show a state.
- **Compact.** Text is 13 px in the system font (Segoe UI). Fields and buttons are 28 px high. A label stands left of its control, not above it and not floating inside it.
- **Nothing leaves the machine.** No web font, no CDN.
- **One bar on top:** the mark, the title, the page tabs, the Julia state pill and Restart Julia.

**Rules for a page:**
- **Build with the blocks of `theme.py`:** `panel`, `toolbar`, `sheet` and `Section`, `fields` with `label`, `stack`, `line`, `hint`, `eyebrow`, `button`, `State`, `FoldButton`, `dialog` (a dialog and its white box), `offstage` (a holder for timers, so they take no room), `data_table` (a table of numbers, as one element) and `facts` with `fact` (a name and its value). Plain `ui.select`, `ui.number`, `ui.input`, `ui.textarea`, `ui.checkbox` and `ui.toggle` get the look from the defaults set in `theme.setup()`. Give them no label argument; put a `theme.label` beside them.
- **Buttons** come from `theme.button`: `primary` for the one main action of a page, `default`, `ghost` for secondary actions, `danger`.
- **No Quasar colours or spacing classes** (`color=...`, `text-grey`, `q-mt-md`, `bg-primary`): they are Material's palette and they carry `!important`. Use the variables and classes of `theme.css`, and add to that file when something is missing.
- **Not used:** `ui.card`, `ui.expansion`, `ui.switch`, `ui.badge`, `ui.table` (Quasar's Material table; use `theme.data_table`), Material icon names. Use a panel, a `FoldButton`, a checkbox, a `State`, and the icons in `theme.ICONS` (add a path there for a new icon).
- **A choice of two or three** is a `ui.toggle` (drawn as a segmented control); more options are a `ui.select`.
- **Rows to edit** (a list the user adds to and removes from) are a `components/row_list.RowList`.
- **A dialog that changes something** edits a copy and ends with a row of the class `dialog-foot`: what clears on the left, then Cancel and the dialog's own primary button. A click beside it does not close it (`no-backdrop-dismiss`). Its problems show above that row, in the class `problems`.
- **Colours that show data** (the Network page) are in `network_view.py`, not in the stylesheet, and follow three rules. Groups get the eight colours of `GROUP_COLORS` in a fixed order, a ninth group and later ones share one grey, and a group is always named as well (on its circle, in the legend, in the tooltip). An amount is one hue from light to dark. A value around a middle (a voltage around 1 pu) is two hues with grey in the middle. What is selected is marked by shape (a ring, a dashed line with a white edge), because the colours are already taken.
- **Class names:** before adding a class to `theme.css`, check that Quasar and Tailwind do not use the name (`inline` and `row` are taken).
- **A Quasar part used for the first time** (a dialog, a table, a chart) still has its Material look. Add its rules to `theme.css`, section "Quasar, without the Material look", and check a screenshot. Popups are where Material comes back most easily.

**How the stylesheet wins.** NiceGUI loads Quasar's rules in CSS layers. `theme.css` is loaded outside any layer, so its rules win over Quasar's whatever the selector. Only Quasar's `!important` rules need the block `@layer overrides` at the end of the file. The stylesheet is read once, when the app starts, so a change to it needs a restart of the app.

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
| `network` | `"case"` | `@@data {"id", "case", "buses": [...], "lines": [...], "zones", "areas", "group_names", "layouts"}`, see "Network reply" |

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
- **Own process group.** Start the worker with `CREATE_NEW_PROCESS_GROUP`. Ctrl+Break in the app's console then reaches only the app, whose shutdown stops the worker tree. A keyboard Ctrl+C still reaches Julia, which handles it itself even in its own group (phase 6 test); the app shuts down at the same time and stops whatever is left.

### Network reply (`network`)

The case as the Network page draws it. Values are in MW, Mvar and pu, rounded as in `@@result`.

- `buses`, sorted by number: `bus`, `name`, `kv`, `zone` and `area` (numbers), `vm`, and what is in service at the bus: `pd_mw`, `qd_mvar`, `pg_mw`, `qg_mvar`, `pmax_mw`, `qmax_mvar` and `gens` (how many generators).
- `lines`, **one per pair of buses** with `from` < `to`, sorted:
  - `ids`, the branch ids of every circuit between the two buses, in service or not; `in_service`, how many are; `transformer`, true when all are transformers;
  - `p_mw` and `q_mvar`, the power that enters the pair's circuits at `from`, and `p_to_mw` and `q_to_mvar`, the power that enters at `to`. The case's values come from its own voltages (`calc_branch_flow_ac`), so they are a power flow only if the RAW holds a solved case.
- `zones` and `areas`, as in `case_info`; `group_names`, `{"zone": {"<number>": name}, "area": {...}}` for every record.
- `layouts`, one per kind of group the case has more than one of (`"zone"`, `"area"`), or `"none"` alone for a case without groups. Each has `x` and `y` for the buses in their order (line lengths), `circles` (`group`, `x`, `y`, `radius`, `buses`) and `circle_of_bus` (1 is the first circle). `network_layout.jl` makes them; the same case gives the same layout every time.

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

The GUI keeps the same list, in this order, as `STAGES` in `components/status_strip.py`, because it shows the stages a run has not reached yet. A new stage goes in three places: this table, `STAGE_LABELS` in `worker.jl` and `STAGES`. A stage that only some runs reach also goes in `STAGE_SETTINGS` there, with the setting that turns it on.

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
| `modifications` | changes to the network made before the boundary and the penalties, filled by the advanced dialog; `{}` means none. See below |

`modifications` holds a list of entries per kind. A kind without entries is left out. The worker applies the kinds in this order (`MODIFICATIONS` in `worker.jl`), and the entries of a kind in the order of the list:

```json
"modifications": {
  "load_scaling": [
    {"kind": "zone", "name": "SPARTANB", "factor": 0.7},
    {"kind": "buses", "buses": [3005, 3007, 3008, 153], "factor": 1.6}
  ],
  "loads": [{"id": 6, "bus": 3005, "pd_mw": 400, "qd_mvar": null}],
  "generators": [
    {"kind": "zone", "name": "SPARTANB", "pmin_mw": 0, "pmax_mw": null},
    {"kind": "buses", "buses": [101, 102], "pmin_mw": null, "pmax_mw": 500}
  ]
}
```

| kind | entry | what the worker does |
|---|---|---|
| `load_scaling` | `kind` `zone` or `area` with `name`, or `kind` `buses` with `buses`; `factor` zero or more | multiplies the pd and qd of every load at those buses, with `scale_loads!(data, factor, buses)`. A bus list is required, because without one that function scales every load |
| `loads` | `id` (the load's number as PowerModels reads the case), `bus`, `pd_mw` and `qd_mvar` (`null` keeps the case's value; one of the two is needed) | sets pd and qd from MW and Mvar with `baseMVA`. When `bus` is given and the load is at another bus, the run fails: the settings were made for another version of the case |
| `generators` | `kind` `zone` or `area` with `name`, or `kind` `buses` with `buses`; `pmin_mw` and `pmax_mw` (`null` keeps the case's value; one of the two is needed) | sets the pmin and the pmax of each generator at those buses from MW with `baseMVA`, in service or not: every generator gets the value, it is not shared among them. A generator in service that would end with its pmin above its pmax fails the run |

The loads come after the scaling, so a load's own pd and qd are final. A kind the worker does not know, a missing factor and a load that is not in the case fail the run in the stage `prepare`, with a message. A scaling that meets no load and a group without generators only print a note.

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
  "case_files": {"raw": "cases/psse/ACTIVSg500\\ACTIVSg500.raw", "dyr": "cases/psse/ACTIVSg500\\ACTIVSg500.dyr"},
  "objective": "flow_shed", "lambda": 500, "opf_model": "AC", "flow_model": "squared",
  "target_lines": [{"id": 12, "from": 154, "to": 3008, "ckt": "1"}],
  "target_zone": "spartanb", "target_area": null,
  "load_shedding_penalties": {"3005": 1250.0},
  "uniform_shedding": false, "uniform_penalty": 0.0,
  "frequency_security": false, "voltage_security": false,
  "run_dynamic_sim": true, "simulator": "andes", "output_tag": "spartanb_2.5",
  "gui_settings": null,
  "files": {"excel": "pm_res_flow_shed_<ts>.xlsx", "raw": "...", "report": "dynamic_channels_<ts>.html"},
  "summary": {"termination_status": "LOCALLY_SOLVED", "objective": 0.0, "preemptive_shed_mw": 0.0, "voltage_security": null},
  "seconds": {"solve": 0.0, "dynamic_sim": 0.0, "total": 0.0}
}
```

The report name is `dynamic.py`'s own `dynamic_channels_<ts>.html`. `run_islanding` finds it after the simulation as the newest such file modified after the run started. `run_info.json` keeps its keys, because the Python report reads them. It gained `target_area` in phase 2 and `group_kind` in phase 4b; the ANDES report uses both.

### Result summary (`@@result`)

The worker sends it at the end of a run, after the stage `summary`. A run that fails sends `@@error` and no `@@result`.

**Units and rounding.** The summary is in MW and Mvar, rounded as the console prints:
- MW, Mvar and % to 2 decimals;
- H, K, D, voltages (pu) and voltage indicators to 3 decimals. The GUI shows these as they are and does not round them again.

A number that is not finite is `null`. Keys whose feature was off are `null`.

**Source.** The numbers come from a copy of the network data taken just before `run_islanding`. The export step writes the solution into the network data, which turns each load's `pd` into its served load.

**Groups.** The summary groups exactly like the console reports, by `find_group_kind` in `utils.jl`:
- an area boundary groups by area;
- a zone boundary groups by zone;
- a bus-pair boundary groups by the kind the case divides its buses into: zones when there is more than one zone, otherwise areas when there is more than one area.

A group's name is its record name, or its number when it has no record, as in `case_info`.

- `termination_status`, `objective`
- `seconds` (`solve`, `dynamic_sim`, `total`), from the per-run settings file
- `generation`:
  - `group_kind`
  - `groups`, one per zone or area record (none when the case has no such records): `index`, `name`, `pg_mw`, `pmax_mw`, `qg_mvar`, `qmax_mvar`, `p_used_pct`, `q_used_pct`
  - `total`: the same fields without `index` and `name`
- `load_shed`, for objectives with shedding only:
  - `group_kind`, `total_load_mw`, `total_shed_mw`
  - `groups`, one per group with load: `index`, `name`, `load_mw`, `shed_mw`, `shed_pct`
  - `buses`, every load bus, with the loads at that bus added up: `bus`, `pd_mw`, `shed_mw`, `shed_pct`. Solver noise rounds to 0, so "only buses with shed" means `shed_mw > 0`.
- `boundary_flows`:
  - `oriented`: true with a target zone or area. Each line is then measured at its end inside the group (`from`) and is positive leaving the group. With bus pairs, each line is measured at its RAW from end.
  - `lines`: `id`, `from`, `to`, `p_mw`, `q_mvar`
  - `net` and `abs_sum`: `p_mw`, `q_mvar`, and `total` (P + Q, as the console prints it)
- `frequency`, one entry per island that has frequency limits (an empty list when no island has inertia):
  - `island_bus`, `n_buses`, `gens`, `governors`
  - `H` (s), and `K` and `D` (pu on the system base)
  - `limits_mw` (`rocof`, `qss`, `nadir`), `binding`
  - `scheduled_import_mw`, positive into the island, which is the opposite sign of the boundary flows. The limits hold in both directions, so an island is within them when the import's magnitude is at most the binding limit (for example −342.15 MW against 592.4 MW).
- `voltage`, from `result["voltage_security"]`:
  - `verified`, `rounds`, `worst_indicator`;
  - `details`, one entry per round:
    - `round`, `termination_status` and `indicator_threshold`;
    - `islands`, one entry per island. Each has a `status` of `checked`, `no_generator` or `power_flow_failed` and its `bus` and `n_buses`. A checked island also has:
      - `n_with_generation`, `n_holding_voltage`;
      - `at_upper_limit`, `at_lower_limit` (bus numbers);
      - `slack_bus`, `slack_pg_mw`, `slack_qg_mvar`;
      - `largest_indicators` (`value`, `bus`, `vm`, `pd_mw`);
      - `worst_indicator`;
      - `shed`: `null`, or `sheds` (`bus`, `shed_mw`, `of_mw`) with `indicator_after` and `indicator_after_bus`.
  - `voltage.jl` keeps these in per unit (`slack_pg`, `pd`, `shed`, `of`). The worker converts them and adds the unit to the key.
- `network`, for the Network page: `buses` (`bus`, `vm`, `pd_mw`, `qd_mvar`, `pg_mw`, `qg_mvar`, `pmax_mw`, `qmax_mvar`, `gens`) and `lines` (`from`, `to`, `p_mw`, `q_mvar`, `p_to_mw`, `q_to_mvar`), as in the `network` reply but with the run's solution: its voltages, its dispatch and its flows, on the run's network (after its modifications, before its shed). A value the solution does not have (a voltage or a reactive flow of a DC run) is `null`. The shed per bus is in `load_shed.buses`.
- `files`, from the per-run settings file:
  - `output_path`, the absolute results folder;
  - the file names in that folder: `settings`, `excel`, `raw`, `report` (`null` when not written).

### Run page layout (since phase 9)

```
┌ ◉ Islanding GUI   Run | History | Network          [● Julia ready]  ↻ Restart Julia ┐
├────────────────────────────────────────────────────────────────────────────────────┤
│ ▾ Settings   (folded: the settings on one line)      Advanced (2)  [■ Stop] [▶ Run] │
│ NETWORK MODIFICATIONS   loads of zone SPARTANB × 0.7 · load 6 at bus 3005: P 400 MW   Reset │
│ CASE AND MODEL    │ BOUNDARY    │ LOAD SHEDDING PENALTIES   │ SECURITY AND SIMULATION │ ▴ fold
├────────────────────────────────────────────────────────────────────────────────────┤
│ RESULTS OF [run 3 · savnw · flow_shed · 4 bus pairs · 22:09:03 ▾]                   │
│ Summary | Generation | Load shedding | Boundary flows | Frequency | Voltage | Files │
│   facts and tables of that run                                                     │
├────────────────────────────────────────────────────────────────────────────────────┤
│ RUNS IN THIS SESSION   run, started, case, ...   Report  Folder  Log  Load settings │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Run 3 ● finished   ✓ Load case — ✓ Prepare — ✓ Solve — ... — ✓ Summary              │
│ now: latest log line, or the error          total 1:42    2 warnings   [Full log]  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

The page tabs are in the top bar. Run and Stop are in the toolbar of the settings panel, above the sheet, so they stay in the same place when the sheet is folded or a penalty row is added. The problems that keep the settings from running show between the toolbar and the sheet. Under them, the line of the network modifications shows while there are any, also while the sheet is folded. The results panel is hidden until a run has results, and the last two rows are the status strip, fixed to the bottom of the window.

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
   - `run_islanding` copies `result["voltage_security"]` into the per-run settings file's `summary`. Keep only `verified`, `rounds` and `worst_indicator` there, without `details`, so the settings files stay small. The details go to the GUI through `@@result` only (phase 4b).

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
3. **Case changes.** Changing the case calls `case_info` and refreshes the group lists. `list_cases` also returns folders whose `.raw` does not parse (`savnw_orig`, `simple`, `simple3`). For those, show the `@@error` message next to the case selector and keep the form usable.
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
   - **Incomplete runs.** A run that failed, even before the solve, leaves a settings file with `"status": "started"` and no report. Show it as incomplete.
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

**Goal (as the user set it on 2026-11-21, replacing the first text of this phase).** Get a good sense of the network of a case, and ideas for scenarios: a clean graph that fits the window, with zoom and pan that stay fast; zones or areas (whichever the case has), buses and lines (bus pairs) to select and see; and colours for buses, lines and circles.

**Files:**
- `runners/gui/network_layout.jl` (new), `runners/gui/worker.jl` (`network` handler, `network` part of `@@result`)
- `runners/gui/network_view.py` (new), `runners/gui/components/network_canvas.py` and `.js` (new), `runners/gui/pages/network.py` (new)
- `runners/gui/app.py` (registry, `client_state`), `runners/gui/pages/run.py` (`RunForm.take`), `runners/gui/theme.css`

**What it has:**
1. **The layout,** made in Julia from the buses, the bus pairs and the zone or area of each bus (the steps are at the top of `network_layout.jl`): one circle per connected part of a group, strays laid out with the cluster they are wired to, the circles arranged so that the lines between them cross least, and the buses spread evenly inside.
2. **The drawing,** a canvas of its own: wheel to zoom, drag to move, double click or Fit for the whole network, a tooltip on every bus, line and circle, bus numbers when zoomed in.
3. **Colours,** each with its legend:
   - buses by zone or area, voltage, load (P or Q), generation (P or Q), capacity (P or Q) or load shed;
   - lines plain, or by flow (P or Q) with an arrow in the direction of the power and a width that follows it;
   - circles by their group, or by the group's total load, generation, capacity or shed, with the number under the name.
4. **Values of** the case as read, or of a run of the session on that case.
5. **Selection** by clicking or typing: a zone or an area, single buses (also by a box, with shift), or lines. Its boundary is drawn dashed in red, and the side panel says what it holds, what leaves it, and which islands opening the boundary leaves.
6. **To the Run form:** "Use as target" (the group, or the bus pairs of the boundary) and "Set penalty" (the group, or each selected bus with a load).

**Done when:**
- **Render time.** savnw and ACTIVSg500 show within a few seconds, and zooming ACTIVSg500 is smooth.
- **Highlighting.** Selecting a zone or an area marks exactly the lines `find_branches_by_zone` or `find_branches_by_area` returns.
- **Use as target** fills the Run form, and a run from it gives the result of the same settings typed by hand.
- **A run's values** on the page agree with its own tables.

**Out of scope:** geographic coordinates; moving buses by hand; values of runs of earlier sessions (phase 10 would bring them). Ask the user.

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
- **Target zone name.** `target_zone` is passed exactly as given, so `run_info.json` shows the name as the GUI sends it. That is the record name from `case_info`, for example "Spartanb" for ACTIVSg500 and "SPARTANB" for ACTIVSg500z, where `islanding.jl` writes "spartanb".
- **Not yet supported.** Settings with a non-empty `modifications` are rejected until phase 9.

**Phase 2 (2026-11-20).**

*What changed:*
- **`utils.jl`.** New `get_area_index_by_name`, `find_buses_by_area` and `find_branches_by_area`. The zone and area lookups now fall back to the group number (`find_group_index_by_number`) when a name matches no record, for cases such as case9 that have no records at all.
- **`print_branch_flows`.** It accepts either a zone name or the target buses themselves as its fifth argument.
- **`run_islanding`.** It has a new keyword, `target_area`. An area target is written to `run_info.json` as `"target_area"`, so the Python report does not label it "Zone". The penalty scope reads "inside area" or "outside area". Zone runs take exactly the old path.
- **Worker.** It takes `area` boundaries and penalty groups (`find_group_buses`, `find_group_branches`). `case_info` returns `zones` and `areas` built from the buses, with record names or the number as the name, and an empty list when a case has fewer than two such groups.

*How it was verified:*
- **Area helpers.** Checked against a direct count from each bus's `area` field on savnw (FLAPCO 6 buses and 7 lines, LIGHTCO 7 and 4, WORLD 10 and 3) and AU14GenModel (areas "1", "3", "5").
- **Number fallback.** On case9, zone and area "1" gave 9 buses each, and "2" or "x" gave a readable error.
- **Zone runs unchanged.** The ACTIVSg500 SPARTANB job gave a console output identical, line for line (66 lines), to phase 1, and a `run_info.json` identical to the `islanding.jl` reference.
- **Area runs.**
  - savnw LIGHTCO: 25.88 MW shed, net P = 0.191.
  - AU14GenModel area "3": 183.82 MW shed, net P = -0.09.
- **Errors.** An unknown area gave "Area 'NOWHERE' not found in network data".
- **Area path equals zone path.** In savnw, zone SECOND and area LIGHTCO hold the same buses and boundary lines. A zone SECOND run and an area LIGHTCO run gave identical console output (51 lines, apart from the once-per-process Ipopt banner): objective 9097.028165220057, 25.88 MW shed, P = 0.191. Their `run_info.json` files differ only in `target_zone`/`target_area` and the scope word.

Not exercised:
- an area run with the dynamic simulation (that the report ignores `target_area` rests on reading `report.py` and `dynamic.py`);
- a penalty list that mixes zone and area groups.

Groups in the cases:

| case | zones | areas |
|---|---|---|
| savnw | 4: FIRST, SECOND, FIFTH, PLANT | 3: FLAPCO, LIGHTCO, WORLD |
| AU14GenModel | 1 | 5, named "1" to "5" |
| ACTIVSg200 | 6 (7 records, zone 1 has no buses) | 1 |
| ACTIVSg500, ACTIVSg500z | 6 | 1 |
| IEEE39, Hawaii40_20231026 | 1 | 1 |
| case9, case9_edited_dyr | no records | no records |
| savnw_orig, simple, simple3 | not parsed | not parsed |

The last three fail to parse ("'@!IC' for IC is not of type Int64"), an issue that predates this phase; `case_info` on them gives an error.

New test folders: `savnw_flow_shed_gui_test_area`, `savnw_flow_shed_gui_test_zone_second` and `AU14GenModel_flow_shed_gui_test_area`.

*For the next phases:*
- **Phase 3.** Its `CLAUDE.md` update should mention the new `run_info.json` key `target_area`.
- **Ask the user.** An "Area" row in the Python report header would be a change to the report, so ask before adding one.

**Phase 3 (2026-11-20).**

*What changed:*
- **`islanding_core.jl` helpers:**
  - `calc_branch_source`: bus pair and circuit from `source_id`. The line outage file now uses it too.
  - `write_run_record`: indented JSON through `JSON3.pretty(...; allow_inf=true)`, so a NaN objective does not break it.
  - `find_new_report`: the newest `dynamic_channels_*.html` modified after the run started.
- **`run_islanding`:**
  - New keywords `progress` and `run_settings`.
  - The results folder and one timestamp are made at the start. The Excel name now carries the start time of the run instead of the time after the solve.
  - `settings_<timestamp>.json` is written as `"started"` before the solve and rewritten as `"finished"` at the end.
- **Worker:** `STAGE_LABELS` and `send_stage`, its own stages `load_case` and `prepare`, and the settings passed as `run_settings`.
- **`CLAUDE.md`:** documents the settings file, `target_area`, the new keywords and `runners/gui/`.

*How it was verified:*
- **Stage order** in three savnw worker runs:
  - dynamic simulation off: load_case > prepare > solve > reports > excel;
  - with frequency security: frequency_limits comes before solve;
  - dynamic simulation on: export > dynamic_sim come after excel.
- **A temporary copy of `islanding.jl`** (ACTIVSg500 SPARTANB, ANDES on, tag `gui_test_ref`) left a `"finished"` settings file with:
  - the same timestamp as its Excel file;
  - the report it created (`dynamic_channels_20261120_161441.html`);
  - `gui_settings` null;
  - objective 12140.983057017995 and 407.43 MW shed.

  Its Julia report block was identical to before (36 lines), and its `line_outage.json` was byte-identical to the user's October SPARTANB run. The plan asked for this check on savnw, but `islanding.jl`'s hardcoded block is ACTIVSg500, so that case was used; savnw was covered by the worker runs.
- **Voltage summary.** A savnw worker run with voltage security filled `summary.voltage_security`: verified in round 1, worst indicator 0.396.
- **Other callers.** `batch_islanding.jl` and `frequency_tests/3_dynamic.jl` pass `find_case_files` results, which always have `.raw`. They were read, not run.
- **Failure test.** A failure injected through `progress` at the `export` stage (scratch script, no file edited) left `"status": "started"` with `files` null.

*Watch out for:*
- **Captured logs scramble the order.** When Julia's output is redirected to a file, Julia buffers its own lines and the `dynamic.py` lines land first. The worker reads a pipe and its output stays in order.
- **`gui_settings` keys** come out in arbitrary order (a `Dict`).
- **`load_shedding_penalties`** lists every penalized bus (85 entries for a SPARTANB run).

- **Before the solve.** The results folder and its `"started"` record now appear before the solve, so a run that fails early leaves both.
- **Hand edits are not recorded.** For `islanding.jl` runs the record holds only what `run_islanding` receives. Edits made by hand before the call (`scale_loads!`, `pd` overrides, `pmin`) are not in it.

Not exercised:
- report detection after a PSS®E run (only ANDES was run);
- the batch runner;
- editing a runner file while the worker runs.

Test folders added or reused: `savnw_flow_shed_gui_test_stages`, `_gui_test_freq`, `_gui_test_dyn`, `_gui_test_fail`, `_gui_test_volt`, and `ACTIVSg500_flow_shed_gui_test_ref`.

**Phase 4a (2026-11-20).**

*What changed:*
- **`utils.jl`.** New `find_group_names`, `calc_generation_shares`, `calc_generation_status`, `calc_load_shedding_status` and `calc_branch_flows`. All return plain `Dict`s in per unit, and the first two take `group_kind` (`"zone"` or `"area"`). `print_generation_status`, `print_load_shedding_status` and `print_branch_flows` keep their signatures, which the archived `islanding2.jl` and `helpers/` still use, and now print from the `calc_*` data.
  - **Bug fixed:** `print_branch_flows(...; detailed=true)` referred to an undefined `total_flow`. It now prints P + Q.
- **`frequency.jl`.** New `calc_scheduled_import`.
- **`voltage.jl`.** New `calc_island_voltage` and `calc_island_shed`. `print_island_voltage` and `print_island_shed` now take that data. `solve_voltage_secure_opf` collects each round in `result["voltage_security"]["details"]`.
- **`islanding_core.jl`.** The settings file's summary keeps only `verified`, `rounds` and `worst_indicator`.
- **`dev/send_jobs.py`.** It now prints UTF-8. It crashed on the ✓ in Julia's "Precompiling" output when its own output was redirected (cp1252).

*How it was verified.* The console logs were captured before any edit and again after, with the dynamic simulation off and `gui_test_4a*` tags. They are identical apart from control lines and Ipopt's timing line:

| run | lines |
|---|---|
| savnw `flow_shed` | 66 |
| ACTIVSg500 SPARTANB with frequency security | 88 |
| savnw with voltage security (verified in round 1) | 74 |
| ACTIVSg500 SPARTANB with voltage security (5 rounds with sheds at 383, 469, 252 and 28 twice) | 334 |

Other checks, in a scratch script:
- **Voltage details.** They match the printed rounds: worst indicators, top buses and every shed with its MW.
- **Area grouping on savnw.** Generation by area (FLAPCO = zones FIRST + PLANT, and so on) and load by area (1200, 1500, 500 MW) agree with the zone sums and with `case_info`.
- **Settings file.** Its voltage summary has the three keys only.
- **Old against new.** The committed `utils.jl` (`git show HEAD`) and the new one, loaded side by side on the same solved results, printed identical text:
  - the whole-network generation block (case9, no zone records);
  - `print_load_shedding_status`, with and without `detailed` (savnw, uniform 0.2 λ, 1594.31 MW shed);
  - `print_branch_flows`.
- **Other readers.** Nothing else reads `result["voltage_security"]` except `run_info` and the settings summary, which take named keys.

*Load grouping.* In this phase a load's zone was its RAW record's own zone and its area was its bus's area. savnw's two loads at bus 154 carry area 2 while bus 154 is in area 1, which would put 1000 MW of load outside the LIGHTCO boundary into LIGHTCO. The user then decided that a load belongs to its bus's zone and area, and phase 4b made zones follow the bus too.

*For phase 4b:*
- **Units.** Every `calc_*` value is per unit:
  - generation `pg`, `pmax`, `qg`, `qmax`;
  - load `load`, `shed`, `pd`;
  - flows `p`, `q`;
  - voltage `slack_pg`, `slack_qg`, `pd`, `shed`, `of`.

  Convert with `baseMVA`. Shares and indicators are already unitless.
- **Generation groups.** These exist only for cases with zone or area records; otherwise use `"total"`.
- **Flow sign.** Each branch flow is measured at the end inside the target and is positive leaving it. In the SPARTANB frequency run the net flow was -104.5 MW, the main island inside imported +32.03 MW, and the other small islands have no generation. That is consistent. It matches the console, not the objective's "into the target zone" wording in `CLAUDE.md`, so state the sign in the GUI.

Not exercised: the planned/forced split shedding output; no objective produces it today.

Test folders added: `savnw_flow_shed_gui_test_4a`, `savnw_flow_shed_gui_test_4a_volt`, `ACTIVSg500_flow_shed_gui_test_4a_freq`, `ACTIVSg500_flow_shed_gui_test_4a_volt` and `ACTIVSg500_flow_shed_gui_test_4a_check`.

**Phase 4b (2026-11-20).**

*What changed:*
- **`run_from_settings`.** It now returns what the summary needs:
  - the result;
  - a copy of the network data taken before `run_islanding`, with the embedded `frequency_islands` added back;
  - the settings and the target;
  - the results folder and the start time.
- **`handle_run`.** It sends the stage `summary` and then `@@result`.
- **`calc_result_summary` and its helpers** build the summary as **Contracts: Result summary** now describes it, from:
  - the phase 4a `calc_*` functions;
  - `calc_scheduled_import`;
  - `result["voltage_security"]`;
  - the per-run settings file, for the files and durations. It is found as the newest finished `settings_*.json` written since the run started.
- **`send_control`** writes NaN and Infinity, which Python's `json` reads, instead of failing.
- **Load grouping (the user's decision).** A load belongs to its bus's zone and area everywhere. `calc_load_shedding_status`, `scale_loads!(data, scale, zone_name)` and `print_network_summary` no longer read the load record's own zone.
- **Study grouping (the user's decision).** An area study is reported by area throughout and a zone study by zone, in the console as well as in `@@result`. There is no mixing of the two kinds.
  - `find_group_kind` in `utils.jl` picks the kind:
    - the target's own kind;
    - for bus pairs, zones when the buses are in more than one zone, otherwise areas when they are in more than one area.
  - `run_islanding` passes it to `print_generation_status` and `print_load_shedding_status`, which have a new `group_kind` keyword (default `"zone"`). It also uses it for the penalty scope word in `run_info.json`.
  - The worker uses the same function for the summary.
  - `calc_generation_status` also lists a group that has no record when the buses are in more than one group. No current case has such a group, but a future case could.
  - The rest of the pipeline follows the same kind:
    - `run_info.json` carries `group_kind`;
    - the Excel bus sheet's group column is the area or the zone;
    - the ANDES report puts the target area in its header and title, and totals the UFLS shed by area or zone in the console and the header. Each event line names its group.
  - The PSS®E script is no longer updated, by the user's decision, so it keeps its zone totals.
- **`islanding.jl` targets an area too.** `target_kind` (`"zone"` or `"area"`) and `target_name` replace the hardcoded zone. Both `target_zone` and `target_area` are reset to `nothing` first, so a group left from an earlier `include` in the same session is not passed. `run_islanding` now refuses a zone and an area together.
  - Checked with temporary copies run in one session. The default ACTIVSg500 SPARTANB zone setting gave the phase 1 objective 12140.983057017995 and 407.43 MW. savnw area LIGHTCO, run after it, gave 9097.028165220057 and 25.88 MW, reported by area like the worker's area run.
  - Test folders: `ACTIVSg500_flow_shed_gui_test_ref` (reused) and `savnw_flow_shed_gui_test_ref_area`.
- **Export fix in `src/io/pti.jl`.** `export_pti` wrote zone and owner records with their positions (savnw zones 1 to 4) instead of their numbers (1, 2, 5, 77). It now writes `"i"`, as the area records already did. ANDES reads the zone names from those records.
- **Contract.** **Contracts: Result summary** was rewritten to the final keys. The flow line now gives the measured sign; it used to say "oriented into the target group".

*How it was verified:*
- **The four 4a jobs, rerun with `--full` on the final worker.** Their logs are identical to phase 4a's, apart from the blank line printed before each new control line.
- **Lines and buses.** The console does not print single lines or shed buses at `detailed=false`. They were checked through the sums they add up to, and through bus 203 against the zone and area totals.
- **`@@result` against the printed reports:**
  - **savnw:**
    - SECOND generation 14.0334 pu became 1403.34 MW;
    - net P 6.287 pu became 628.67 MW;
    - 0 MW shed of 3200 MW.
  - **ACTIVSg500 with frequency security:**
    - generation by zone matches;
    - Spartanb shed 408.68 MW of 1115.53 MW (36.64 %);
    - net P −1.045 pu became −104.51 MW;
    - island 23 has H 29.664, K 145.505, limits 49.44, 72.75 and 32.03 MW with nadir binding, and an import of 32.03 MW;
    - island 1 imports −342.15 MW.
  - **Voltage.** A scratch script rebuilt the console's voltage lines from `details` and got them identical:
    - savnw: 13 lines, verified in round 1, worst indicator 0.396;
    - ACTIVSg500: 95 lines over 5 rounds.
- **savnw area LIGHTCO with the ANDES simulation:**
  - 25.88 MW shed of 3200 MW, with bus 203 at its original 300 MW, so the copy taken before the export works;
  - the area groups equal the zone sums;
  - `files` names the raw, the Excel file and `dynamic_channels_20261120_181931.html`, and the durations are there.
- **AU14GenModel area "3":** groups "1" to "5", 183.82 MW shed.
- **case9 with bus pairs 4-5 and 8-9 (no zone records).** There are no generation groups, and the total of 2.7466 pu matches as 274.66 MW. The one load group is named "1" (the console prints "Zone 1").
- **Study grouping**, after `find_group_kind` was added:
  - **Zone runs unchanged.** The four 4a jobs (zone and bus-pair runs on zone cases) still print exactly the phase 4a console.
  - **savnw area LIGHTCO.** The console now prints "Generation status by area" and "Load Shed by Area" (FLAPCO, LIGHTCO, WORLD; 25.88 MW shed in LIGHTCO). `@@result` matches, and `run_info.json` has "inside area".
  - **AU14GenModel with area 3's boundary as bus pairs (309-102, 315-509).** It picked areas by itself: 1 zone and 5 areas, 198.76 MW shed in area "3".
  - **case9** still prints the whole-network block.
  - **ANDES with UFLS** (`opf_shed`, so the islands import and the relays act):
    - savnw area LIGHTCO and zone SECOND shed the same 73.51 MW (buses 205 and 203). The area study shows "LIGHTCO", "UFLS shed by area" and "Area: LIGHTCO" in the header, and an `area` column in Excel. The zone study shows "SECOND" and "by zone".
    - ACTIVSg500 zone SPARTANB: 102 events, 164.75 MW in Spartanb.
    - The exported savnw RAW has zone records 1, 2, 5, 77 and owner records 1, 2, 5, 11, 22, 55, 100.
    - `read_group_names` and `calc_ufls_by_group`, run on exported savnw RAWs with events in four zones: before the fix zones 5 and 77 had no name; after it they are FIFTH and PLANT. The area totals add up over several groups (FLAPCO 2 events).
    - The `export_pti` round trip of `test/pti.jl` passes on case3 and case30. On savnw, its zones and owners now come back unchanged.
- **Errors.** An unknown zone sent `@@error` and no `@@result`, and the next ping answered.
- **Old against new.** The committed `scale_loads!` and `print_network_summary` were compared with the new ones on every zone of savnw and ACTIVSg500: identical text and loads.
  - `print_network_summary` throws for zones without generators or loads (savnw FIRST and PLANT), both before and after this phase.

*For the next phases:*
- **Line length.** The largest `@@result` was 23 KB (ACTIVSg500 with 5 voltage rounds). That is below asyncio's 64 KiB default, but phase 5 still sets the large `limit`.
- **Results folder.** The worker builds the folder name the way `run_islanding` does (`calc_output_path`). Keep the two in step.
- **Generation groups** exist only for cases with records of that kind. Otherwise show `total` alone.
- **Summary errors.** An error while building the summary fails the job at the `summary` stage, although the run's files exist.
- **Left out.** `@@result` leaves out the planned and forced split of shedding (`planned_shed`, `forced_shed`), because no objective produces it today. Add it if one does.

Test folders added:
- `savnw_flow_shed_gui_test_4b_area_dyn`, `case9_flow_shed_gui_test_4b` and `AU14GenModel_flow_shed_gui_test_pairs`;
- `savnw_opf_shed_gui_test_area_ufls`, `_zone_ufls` and `_pairs_ufls`;
- `ACTIVSg500_opf_shed_gui_test_zone_ufls`.

Reused: `savnw_flow_shed_gui_test_area`, `savnw_flow_shed_gui_test_4a`, `savnw_flow_shed_gui_test_4a_volt`, `ACTIVSg500_flow_shed_gui_test_4a_freq`, `ACTIVSg500_flow_shed_gui_test_4a_volt` and `AU14GenModel_flow_shed_gui_test_area`.

**Phase 5 (2026-11-20).**

*What changed:*
- **NiceGUI 4.0.0** was installed on the system Python 3.14 (`pip install nicegui`). It imports and runs.
- **`julia_worker.py`.** `JuliaWorker` is built on `asyncio.create_subprocess_exec`, which works inside NiceGUI's event loop on Windows: with `reload=False`, uvicorn uses a ProactorEventLoop. No reader thread was needed.
  - **States:** `starting`, `ready`, `busy`, `stopped`, `crashed`, with a `message` saying why.
  - **Methods:** `start`, `stop`, `restart` (one at a time, under a lock), `send(job)` (returns the id) and `request(job)` (returns the `@@data` payload, or raises `WorkerError` on `@@error`, a crash or a stop).
  - **Listeners:** `on_log`, `on_control` and `on_state`. Each returns its remover. A listener that throws is reported on the console and never stops the reader.
  - **Logs:** `job_logs` (per job) and `worker_log` (outside jobs).
  - **Exit watching.** A separate task waits for the process to exit, so a crash shows even when a `dynamic.py` child still holds the output pipe.
  - **Robustness:** job ids keep counting across restarts, `starting` has no timeout (a recompile can take minutes), and a missing `julia` gives `crashed` with a message.
  - **Process group.** The worker runs in its own process group (see the GUI-side rules).
- **`app.py`:**
  - `PORT`, `NATIVE_WINDOW = False` and `PAGES = [run]`, with `ctx` holding `worker`, `state` and `repo_root`;
  - a header with the title, a Julia state pill (its tooltip gives the version, PID and reason) and Restart Julia;
  - a tab per page;
  - the worker started in `on_startup` and stopped in `on_shutdown`, with its state changes printed on the console.
- **`pages/run.py`** is a placeholder with Ping.
- **`CLAUDE.md`** has the install and start commands.

*How it was verified:*
- **Headless lifecycle script** (`JuliaWorker` alone):
  - ready after 5.3 s (precompiled), ping answered, and a failing `case_info` raised the Julia message;
  - restart left no old process;
  - a kill by PID with a request pending failed that request and gave `crashed` (exit code 1), and new requests were refused;
  - restart recovered, and two concurrent restarts left exactly one Julia;
  - stop left none;
  - listeners that threw on every event (45 times) did not stop replies.
- **In the browser** (Chrome, the app started from outside the repo root):
  - the pill showed ready, and Ping answered "pong from Julia 1.11.3 in 0.90 s";
  - with two tabs open, a Restart in one turned both pills to starting and then ready;
  - killing the worker's `julia.exe` by PID (as Task Manager does) turned the pill red, "crashed", without a click; its tooltip gave "Julia exited by itself (code 4294967295)", the 32-bit form of −1 that Windows reports for a forced kill;
  - Restart recovered.
  - The busy pill first used `primary`, the header's own colour, and was invisible; it is now `deep-purple`.
- **Exit, by the worker's PID only.** The user's own `julia.exe` (PID 11896) was never touched.
  - **Graceful (Ctrl+Break sent to the app's process group, as Ctrl+C would be):** the console printed "Julia worker: stopped" from `on_shutdown`, the app exited within 0.5 s, port 8080 was free and no worker was left. The exit code 3 comes from uvicorn raising the signal again after a completed shutdown. Before the worker had its own process group, the signal reached Julia directly and killed it (code 143) before `on_shutdown` ran.
  - **App killed outright** (`on_shutdown` does not run): an idle worker exited 0.3 s later, because its stdin closed. A worker killed in the middle of an ACTIVSg500 solve exited 6.1 s later, at its next write to the closed output.

*For the next phases:*
- **Requests vs. runs.** Use `ctx.worker.request(...)` for `list_cases` and `case_info`, and `send(...)` plus the listeners for `run`. Register listeners per browser tab and remove them in `ui.context.client.on_delete`, as the header does.
- **Updating elements.** Listeners run on the event loop outside any page context. Updating existing elements there works; creating elements or calling `ui.notify` needs `with <element or client>:`.
- **Transient busy state.** The `@@data` reply resolves a request before `@@done` arrives, so the state is briefly still `busy` after the reply.
- **Not handled.** After an external kill of `julia.exe` during the dynamic simulation, the orphaned `dynamic.py` keeps running until it finishes, because Restart's `taskkill /T` only reaches the new worker's tree.
- **First ping.** The first ping of a fresh worker takes about 1 s, while its handler compiles.

Test folder added: `ACTIVSg500_flow_shed_gui_test_hard_kill` (a run killed mid-solve; its settings file stays `"started"`).

**Phase 6 (2026-11-20).**

*What changed:*
- **`settings.py`.** Pure functions, no GUI:
  - `DEFAULT_SETTINGS` and `default_settings()` (simulator `andes`, decision 13);
  - `parse_bus_pairs` and `format_bus_pairs`;
  - `build_settings(form)` and its inverse `form_values(settings)`, between the form's flat values and schema v1;
  - `validate(settings)`, which returns readable problems;
  - `save_settings` and `load_settings` (JSON files, not used by a page yet).
- **`session_runs.py`.** `SessionRuns` (`ctx.runs`) keeps one record per run of the app session: `number` (1, 2, 3, as shown), `id` (the worker's job id), `settings`, `status` (`running`, `finished`, `failed`, `stopped`), `started`, `stage`, `summary`, `error`, `seconds`.
  - It follows the control lines.
  - A run that Julia never finishes (Stop, Restart Julia, a crash) gets no `@@done`, so its status comes from the worker's state change.
- **`pages/run.py`:**
  - **The form (`RunForm`).** Four cards inside one foldable "Run settings" section. `read()` gives the settings and the problems, `write(settings)` fills the form, and `update_view()` keeps it consistent.
  - **Case information.** Zones, areas and load buses come from `case_info`, cached in `ctx.state`. A refresh button next to the case selector reads them again.
  - **Buttons.** Run is enabled only when Julia is ready. Stop is enabled only while a run is in progress; it restarts the worker. Advanced settings is visible and disabled.
  - **Runs in this session.** Newest first, with Report, Folder and Load settings. A new or reloaded tab starts from the last run's settings, or from the defaults.
  - **Temporary raw log** (`ui.log`), until phase 7.
- **Decision 11 in the form.** Penalty rows offer the boundary's kind and buses, never the other kind. With bus pairs they offer the kind the case uses (zones before areas). `validate` refuses a mix.
- **Uniform shedding** sends empty penalty rows and no `others`, so the settings file does not record penalties the run ignored.
- **`JuliaWorker.send` is now synchronous.** The run's record exists before any of its output can arrive. `JobError` (a `WorkerError`) marks a job that failed in Julia, as opposed to Julia not running.
- **`app.py`:**
  - `--port N` and `--no-browser`;
  - started while the port is in use, it opens the running page and exits, instead of failing to bind.
- **`start_gui.bat`** starts the GUI with a double click from any folder and passes its arguments on. It keeps its window open when the start fails.

*How it was verified.* In Chrome, on a test instance on port 8090 (the user's own GUI was running on 8080 and was left alone). All runs used `gui_test_form*` tags.
- **Same results as phase 1, from the form:**

  | run | objective | shed |
  |---|---|---|
  | ACTIVSg500 zone Spartanb, 2.5 λ in the zone | 12140.983057017995 | 407.43 MW |
  | savnw, four bus pairs | 30642.40499516773 | 0 MW |
  | savnw area LIGHTCO, 2.5 λ in the area | 9097.028165220057 | 25.88 MW |
  | savnw, uniform 0.2 λ | | 1594.31 MW |
  | savnw, buses 3008 at 2 λ and 153 at 0.5 λ | | 200 MW |

  The area run is recorded as an area study ("inside area", `group_kind` area).
- **Case switching.** savnw brought 4 zones and 3 areas and the Area kind. ACTIVSg500z (no `.dyr`) dropped Area, cleared the boundary and the penalty rows, and disabled the dynamic simulation and frequency security with a note. savnw_orig showed its parse error in red under the selector and left the form usable.
- **DC** turned voltage security off and disabled it.
- **Bad input,** each refused before anything was sent, with the reason under the buttons: a zone boundary with no zone, an empty bus-pair list, and "154 3008" as a bus pair (one message, naming the text).
- **A run that fails in Julia.** savnw with the bus pair 154-3001, which has no line: the row turned red, "failed", with Julia's message "no boundary line found for bus pairs 154-3001". The stack trace was in the log and Run was available again.
- **Load settings.** With savnw_orig in the form, loading the LIGHTCO run restored every field. Running it again stored `gui_settings` identical to the first run's.
- **Stop during an ANDES simulation, after a page reload mid-run.**
  - The reloaded page showed the running run, its settings, Run disabled and Stop enabled.
  - Stop left no `dynamic.py`, marked the run "stopped", and a fresh worker came up.
  - The next Run finished (79.9 s with the cold worker), with Report and Folder enabled. Both buttons opened without errors.
- **The form's rule for penalty kinds:** an area boundary offered Area and Bus; bus pairs on savnw offered Zone and Bus.
- **Launcher.** `start_gui.bat` from another folder, through `cmd /c`:
  - with the port taken, it reported the running GUI and exited with 0;
  - with a bad argument, it kept the window open;
  - on a free port, it served the page (HTTP 200) and started its worker. After the app was killed, the worker exited by itself.
- **Ctrl+C in a real console window** (sent through the console API to `python app.py` in its own console): the app exited with 3221225786, Windows' "ended by Ctrl+C" code, and within 2 s no worker was left and the port was free. The launcher treats that code and 3 (Ctrl+Break) as normal ends.
  - A process started from a tool shell inherits "ignore Ctrl+C". In a first try the app therefore ignored it while Julia, which sets its own handler, exited.
- **Not tested: the window's close button.** Two ways of imitating it from a script did nothing (a close message to the console window, and ending the console's host process). By Windows' rules, closing a console window ends every process attached to it, and the app, Julia and `dynamic.py` are all attached to it.
- **`settings.py`** passed 27 plain checks, including the exact round trip of both `dev/job_*.json` files through `form_values` and `build_settings`.

*Choices the user can reverse:*
- **One fold, not four.** The phase text says "four foldable cards". The page has one foldable "Run settings" section holding four cards, which is what decision 4 needs to give the results room.
- **Switches stay off.** A case without a `.dyr` turns the dynamic simulation and frequency security off. They stay off after switching back to a case that has one.

*For the next phases:*
- **Starting a run.** Use `ctx.runs.start(settings)`, which sends the job and keeps its record. Don't call `ctx.worker.send` for runs.
- **Phase 7.** Each record of `ctx.runs` already carries the latest `stage`. The run's log lines are in `ctx.worker.job_logs[record["id"]]` (the job id, not the run number). Remove the temporary log.
- **Phase 8.** `record["summary"]` is the `@@result` summary. The settings sheet folds with `settings_fold` (a `theme.FoldButton`: `set_opened(False)`), so it can fold when results arrive.
- **Phases 10 and 11.** `RunForm.write(settings)` fills the form from any schema v1 settings and matches group names without regard to case. Pass settings between pages through `ctx.state`.
- **Updating from listeners works** in NiceGUI 4: `refreshable.refresh()` and `ui.log.push()` called from worker listeners reach the page. `ui.notify` still needs a page context.
- **`ui.toggle.set_options`** rebuilds the toggle's buttons.
- **Setting a value from code** calls the element's `on_change` at once. `RunForm` guards its handlers with `writing` and `updating`, and its case handler does nothing when the case is already loaded.
- **Run numbers.** Runs are numbered 1, 2, 3 for the user. The worker's job ids also count the form's queries.
- **Failed runs** show the first line of the `@@error` message in the list, with the whole message as a tooltip. Their Folder button stays disabled, because the folder path arrives only with `@@result`.
- **Not exercised through the form:** frequency and voltage security runs (the switches only pass a flag the worker already handles), the PSS®E simulator, "all other loads", two tabs watching the same run, and a crash of Julia during a run.

Test folders added: `ACTIVSg500_flow_shed_gui_test_form`, `ACTIVSg500_flow_shed_gui_test_form_stop`, `savnw_flow_shed_gui_test_form`, `savnw_flow_shed_gui_test_form_area`, `savnw_flow_shed_gui_test_form_uniform` and `savnw_flow_shed_gui_test_form_buses`. The failed run (tag `gui_test_form_fail`) left no folder, because it failed before `run_islanding`.

**Look (2026-11-20, after phase 6).**

*What changed.* The user rejected the look of phases 5 and 6 (decision 14). No phase was started; the Run page does what it did.
- **`theme.css` and `theme.py` (new)** hold the look and the rules under "Look".
- **`app.py`.** One light bar on top holds the mark, the title, the page tabs, the Julia state pill and Restart Julia. While a run is in progress the pill reads "Julia running · run N". The mark is also the browser tab's icon.
- **`pages/run.py`, layout only.** `RunForm.read`, `write`, `update_view` and the handlers are as they were.
  - One panel: a toolbar (the Settings fold, Advanced, Stop, Run), then the sheet with the four sections side by side, divided by hairlines. They stand two by two under 1240 px of page width, and in one column under 680 px.
  - Labels stand left of the controls. OPF model, the boundary kind and the simulator are segmented controls, and the switches became checkboxes.
  - Penalties are a small table: where, × λ, remove. "uniform" is a checkbox in the section's title row.
  - While the sheet is folded, the toolbar shows the settings on one line (case, objective, model, boundary, λ, tag).
  - Problems show under the toolbar. Pressing Run with problems also unfolds the sheet.
  - The runs are a table with a coloured dot for the status and text buttons at the right. The log folds with the same kind of button.

*How it was verified.* In Chrome on a test instance on port 8090 (the user's GUI on 8080 was left alone), at 1490 px of page width, with tags `gui_test_look*`.
- **Same results as before, through the new form:**
  - savnw with four bus pairs and the ANDES simulation: objective 30642.40499516773, 0 MW shed, Report and Folder enabled;
  - savnw area LIGHTCO with a penalty row of 2.5 λ in the area, no simulation: objective 9097.028165220057, 25.88 MW shed, recorded as an area study;
  - ACTIVSg500 zone Spartanb with a penalty row of 2.5 λ in the zone, no simulation: objective 12140.983057017995, 407.43 MW shed.
- **Looked at, each in a screenshot:** before the case is read; zone, area and bus pairs; penalty rows of kind zone, area and bus, and uniform; DC (voltage security off, with its tooltip); the option lists; the problems list; the folded bar; a notification; running, finished, failed and stopped rows; the open log; savnw_orig (its parse error in red under the selector, the form still usable); ACTIVSg500z (no `.dyr`: the dynamic simulation and frequency security greyed out, with the note); the sheet two by two (forced with a style rule, because the test window could not be made narrower, so not seen in a real narrow window).
- **Stop** during a run marked it "stopped" and brought up a fresh worker. **Load settings** filled the form from a row.

*Choices the user can reverse.* The user's reference was the concept picture; these differ from it by choice:
- **Run and Stop are above the sheet,** in the settings toolbar, not under the cards. They keep their place when the sheet folds or a penalty row is added. Under the sheet is a move of the toolbar's three buttons.
- **Section titles are small grey capitals,** not bold titles (`.eyebrow` in `theme.css`).
- **Segmented controls and checkboxes,** where the concept has radio buttons.
- **No notification for settings that cannot run.** The list under the toolbar says it.
- **Not built, because they belong to later phases or are undecided:** Preset and Save as (phase 12), the History and Network tabs (phases 10 and 11), Clear console (the log goes in phase 7), Network modifications (the Advanced dialog of phase 9).

*For the next phases:*
- **Follow "Look".** The first dialog (phases 7 to 9), the first table (phase 8) and the first chart (phase 11) need their rules in `theme.css`.
- **Tabs inside a page** (the results panel of phase 8) get the page tabs' look. If they should look different, scope the rules of `.q-tab` in `theme.css` to the header.
- **Advanced** is a ghost button in the toolbar. Phase 9 enables it and adds the count to its text.
- **Presets** (phase 12) fit in the settings toolbar, right of the Settings fold.

Test folders added: `savnw_flow_shed_gui_test_look`, `savnw_flow_shed_gui_test_look_area` and `ACTIVSg500_flow_shed_gui_test_look_zone`. The failed and the stopped run (tag `gui_test_look_fail`) left no folder.

**Phase 7 (2026-11-20).**

*What changed:*
- **`session_runs.py`.** A run's record now also carries what the strip shows, so every tab shows the same and a reloaded page picks a run up where it is:
  - `started_at` and `ended_at` (the end is also set when Julia is stopped or crashes, which send no `@@done`);
  - `stages`, every stage reached with its label and the time it started;
  - `last_line`, the latest log line with a letter or a digit in it, cut to 300 characters;
  - `warnings`, the log lines that warn.

  The log-derived fields change without calling the change listeners, which rebuild the runs table.
- **`components/status_strip.py` (new).** `StatusStrip`, a bar fixed to the bottom of the window. It shows the run in progress, and otherwise the latest run:
  - **Row 1:** the run number, its status, and the stages as steps. A step is done, current (with its clock), failed, stopped, not reached, or not part of this run (struck through). Each step has a tooltip with its time.
  - **Row 2:** "now" with the latest log line; for a failed run the `@@error` message in red; for a finished or stopped run the time it ended. Then the run's total time, the warning count when there is one, and Full log.
  - A timer of 0.5 s reads the clocks, "now" and the warnings, only while a run is in progress.
- **`components/log_dialog.py` (new).** `LogDialog`, one dialog for any list of lines. It shows them as plain text, follows the list while open, shows only the lines containing a text, and copies what it shows. It serves three things:
  - Full log on the strip, and a Log button in each row of the runs table (so the log of each run of the session);
  - the warning count on the strip (the warning lines);
  - a click on the Julia state pill: what Julia printed outside the runs, which the removed raw log used to show.
- **`pages/run.py`.** The temporary raw log is gone. "Run N started" is gone too (the strip says it), and the remaining notifications show at the top, clear of the strip.
- **`theme.py` and `theme.css`.** `dialog` and `offstage`, and the rules for the strip, the steps, the first dialog and the log view.

*How it was verified.* In Chrome on a test instance on port 8090 (the user's GUI on 8080 was left alone), tags `gui_test_strip*`.
- **A normal run** (ACTIVSg500 zone Spartanb, 2.5 λ, ANDES): the steps went Load case, Prepare, Solve, Reports, Excel report, Export, Dynamic simulation, Summary, with the clock on the current one. "now" followed the lines of `run_islanding` and `dynamic.py`. The result was the reference one (objective 12140.983057017995, 407.43 MW shed).
- **Full log during that run** opened at the end of the log and showed `dynamic.py`'s lines, with `<LDSHBL>` as text. Searching "relay" left 2 of 126 lines.
- **Full log following a run** (savnw, four bus pairs, voltage security, opened right after Run on a fresh worker): the dialog went from 3 to 62 lines while open and stayed at the end, with the lines "Voltage viability, round 1" and "Voltage verified in round 1" in it. The run gave objective 30642.40499516773, as without voltage security.
- **A failing run.** The form cannot name an unknown zone, so a bus pair with no line was used (savnw, 1-2), which fails in the same stage: Prepare turned red and the strip showed "no boundary line found for bus pairs 1-2". Its Log button showed the stack trace.
- **Frequency security** (savnw, four bus pairs): Frequency limits was a normal step and was reached. Without it the step is struck through.
- **Reload during that run:** the page came back with the strip on the same run and stage.
- **Stop during the dynamic simulation:** the step got the stopped mark, Summary stayed not reached, and the clock stopped at 0:45.
- **A real warning** (ACTIVSg500, `opf_shed`, zone Spartanb, ANDES): "1 warning", and a click listed "-- Warning: dynamic simulation stopped early, see the ANDES log." The PowerModels notice was not counted in any run.
- **Without the dynamic simulation:** Export and Dynamic simulation were struck through and the run ended after Summary.
- **Copy** reported the number of lines, and pasting into the search field gave the log's text, so the clipboard was written. **The Julia state pill** opened the lines Julia printed outside the runs.
- **The dialog's height:** a long log fills it and scrolls; a list of one line gets a short dialog.
- **Fixed position.** The bar's box was the full window width at the bottom. No element above it has a transform, a filter or a containment that would break `position: fixed`.
- **A narrow window** was forced with a style rule, as in the look change: only the marks of the steps stay, with their names as tooltips.

*Choices the user can reverse:*
- **Warnings.** The plan counts every line containing "warning". `PowerModels.silence()` prints "Suppressing information and warning messages" once per Julia worker, so that line is left out (`IGNORED_WARNINGS` in `session_runs.py`).
- **"now" skips lines without a letter or a digit,** such as the rules of dashes between the report blocks.
- **Search shows only the lines that contain the text.** It does not highlight matches inside the whole log.
- **The strip shows the run in progress or the latest run.** The log of an older run is behind its Log button, but its steps are not shown again.
- **The strip is hidden until the first run** of the session.
- **A fixed bar built by the Run page,** not NiceGUI's footer: `ui.footer` cannot be made inside a tab panel. The page ends with an empty block of the bar's height (`.strip-room`), so the bar covers nothing.

*For the next phases:*
- **Phase 8.** The results panel goes between the runs table and the strip. If it gets a run selector, `StatusStrip.find_record` is the one place that decides which run the strip shows.
- **Dialogs** (phases 8 and 9) start from `theme.dialog()`. Its box is 1100 px wide at most; give a smaller dialog its own width.
- **Timers** go inside `theme.offstage()`. A timer is an element, and in a panel or a toolbar it would take a gap of the layout.
- **Elements that are replaced** (the runs table, the steps) lose their browser references on every change. A test that clicks in them has to find the element again after each change.
- **Not exercised:** a crash of Julia during a run (the code path is the one of Stop, with status "failed"), a voltage security run that needs more than one round, the PSS®E simulator, and a log of many thousands of lines (the largest seen had a few hundred).

Test folders added: `ACTIVSg500_flow_shed_gui_test_strip`, `ACTIVSg500_flow_shed_gui_test_strip_nosim`, `ACTIVSg500_opf_shed_gui_test_strip_nosim`, `ACTIVSg500_opf_shed_gui_test_strip_warn2`, `savnw_flow_shed_gui_test_strip_freq` (stopped), `savnw_flow_shed_gui_test_strip_volt` and `savnw_opf_shed_gui_test_strip_warn`. The failed run (tag `gui_test_strip_fail`) left no folder.

**Phase 8 (2026-11-20).**

*What changed:*
- **`components/results_view.py` (new).** `ResultsView`, the results panel, between the settings and the runs table:
  - **"Results of"** lists the runs of the session that have results, newest first, with their case, objective, boundary, tag and start time.
  - **Summary:** four sections side by side, like the settings sheet. Solution (termination status with a green or red dot, the objective as printed, the solve and simulation times, and the whole run's time), Load and boundary (total load, load shed, net P and Q, the sums of |P| and |Q|, and where the flows are measured), Security (per island the scheduled import against the limit that binds; voltage verified or not, with rounds and worst indicator), and Output (folder, report, Open report, Open folder).
  - **Generation, Load shedding, Boundary flows, Frequency:** tables. Load shedding has the groups and the buses side by side; the buses are filtered to those with shed by a checkbox that starts ticked, and stand in a box of their own that scrolls.
  - **Voltage:** verified, rounds, worst indicator, the threshold, and Details.
  - **Files:** the folder and the four files, each with Open.
  - A tab whose part is null is left out: Load shedding for `opf` and `flow`, Frequency and Voltage when the check was off.
- **`components/voltage_details.py` (new).** `VoltageDetailsDialog`: one block per round with four tables (islands, largest indicators, sheds sized, generators at a reactive limit), decision 10.
- **`theme.py` and `theme.css`.** `data_table` builds a table as one HTML element, with the values escaped as text; `facts` and `fact`; the rules for tables, facts, the tabs inside a page (the page tabs' rules are now scoped to the top bar) and the two new blocks.
- **`pages/run.py`.** The panel is built after the settings and refreshed with the runs. The openers of a run's report and folder moved to `results_view.py` and the runs table uses them. They now say so in a notification when the file is gone or Windows cannot open it.
- **The whole run's time** in the Summary is the record's `seconds` (Julia's time for the job, from `@@done`), the number the runs table shows. It arrives after the results, so the Summary shows "..." for a moment. The summary's own `seconds.total` is not shown: it is the time inside `run_islanding`, without loading the case, preparing and Julia's compiling, and it read up to 17 s less than the strip and the runs table.
- **`dev/check_results_tables.py` and `dev/jobs_results_check.json` (new):** the check described below, and its five runs.

*How it was verified.*
- **Against the printed reports, by script.** The `find_*` functions that build each table's rows draw nothing, so `dev/check_results_tables.py` compares their cells, formatted as the panel formats them, with the console text of the same runs in a log made with `dev/send_jobs.py --full`. It was run on two logs of the five runs in `dev/jobs_results_check.json` (savnw, ACTIVSg500 with frequency security, savnw and ACTIVSg500 with voltage security, and case9): the phase 4b log, and a fresh one made with the command in the script's first lines. Both times 606 comparisons, none failed.
  - Printed and compared directly: the objective, load and shed by group and in total, every frequency line, every line of the voltage rounds.
  - Printed in per unit and compared at the console's precision after ×100: generation (4 decimals, so 0.01 MW) and the net and absolute flow sums (3 decimals, so 0.1 MW; the panel is finer there).
  - Not printed by the console, so checked against the totals instead: the flow of each boundary line (they add up to the net flow), the load and shed of each bus (they add up to the totals), and the generation total (the sum of the groups; for case9 the console's one "Network" line).
- **In Chrome,** on a test instance on port 8090, tags `gui_test_results*`, the three runs of "Done when" through the form:
  - **ACTIVSg500 zone Spartanb, 2.5 λ, frequency security, against its own Full log.** A script in the page read the tables on screen and the text of that run's Full log: the six generation rows, the six shed rows and the total, the two flow sums and the two islands' frequency rows agreed (18 comparisons, at the console's precision).
  - **savnw, four bus pairs, with ANDES:** objective 30642.40499516773, the simulation time and the report in the Summary, no Frequency or Voltage tab. Its Full log was not opened.
  - **savnw with voltage security:** the Details dialog read the same as the "Voltage viability, round 1" lines (both islands, six indicators, the generators at a limit, no shed). Those lines were read in the log of the same settings from phase 7, not in this run's own Full log; the script above makes that comparison on logs of the same run.
- **Also looked at:**
  - ACTIVSg500 with voltage security: five rounds in the dialog, with the sheds sized and bus lists of 20 and more. That dialog scrolled sideways, because of a long text in the State column. The text was shortened, and the dialog of the next run (both checks, six rounds, 517.91 MW shed) did not;
  - the unfiltered bus list of 200 rows in its own box, the page staying short;
  - an `opf` run: no Load shedding tab, a red LOCALLY_INFEASIBLE status and a red "not verified" voltage result;
  - switching runs in the selector (a tab the other run does not have falls back to Summary), and a reload (the newest results come back);
  - the selector's list open during a run: it stayed open through five stage changes and was rebuilt only when the run delivered its results;
  - a failed run after results: the results stayed on show;
  - the whole run's time: 33.45 s in the Summary, 0:33 on the strip;
  - the moment a run finishes, at 1490 × 790 with the settings open: the whole Summary is in view above the strip;
  - a narrow window, forced with a style rule: the Summary stands two by two, a wide table scrolls inside its tab and not the page, and the runs table's buttons fit at 960 px.
- **The Open buttons.** Clicked once each in the Files tab: the folder, the report and the run record. None gave an error. The Excel report and the RAW file were not clicked, so as not to start Excel or Windows' "open with" on the desktop; a script with a stand-in for Windows' call confirmed that each button passes a file that exists, and that a file that is gone or refused gives a message.

*Choices the user can reverse:*
- **The order of the page:** settings, results, runs. The results are what a run is for, and the runs table is a list to come back to.
- **A run that finishes takes over the panel,** with the tab that was open. An older run stays reachable in the selector. A failed or stopped run leaves the panel alone.
- **The settings do not fold when results arrive.** The Summary fits under the open settings; the other tabs may need the page scrolled.
- **The objective is shown with all its digits,** as the console prints it.
- **A group without a record** is named by its number ("1"), as the summary has it, where the console prints "Zone 1".
- **P + Q** (the console's "Total") is shown for the net flow and the sum of absolute flows only, as printed, not per line.
- **The frequency verdict** treats an import up to 0.006 MW over its limit as on the limit, because both numbers are rounded to 0.01 MW and an island whose limit binds sits exactly on it.
- **Files** has an Open button for every file. A file other than the report opens in the program Windows has for it. This machine has no program set for `.raw` and `.json` in the system's list, so Windows may ask which one to use.
- **The check script and its jobs file in `dev/`** are close to a test, which the project's rules ask for only on request. They are there because "the numbers match the printed reports" is 600 comparisons. Deleting the two files changes nothing else.

*For the next phases:*
- **Tables** come from `theme.data_table(columns, rows, footers)`: one element, values as text. A long one goes in a `div` with the class `table-scroll`.
- **Tabs inside a page** are small; the top bar's are scoped under `.q-header`.
- **Phase 10.** The History page can show an old run the same way if it has a summary: `ResultsView` reads `record["summary"]` and `record["settings"]` only, and the `find_*` functions take the summary alone. A run from disk has no `@@result`, so it would need the summary rebuilt or saved; the per-run settings file keeps only a short one.
- **Not exercised:** a frequency run in which no island has inertia (the tab then says so), a voltage island whose power flow fails, and the PSS®E simulator's report.
- **Seen once and not explained:** after a run finished, the zone list of a penalty row was open, its text selected, although nothing had clicked it. Before that the "Results of" list had been opened and closed with Escape during the run. The browser tools went away before it could be tried again, so it is not known whether a user can cause it.

Test folders added: `savnw_flow_shed_gui_test_results`, `savnw_flow_shed_gui_test_results_volt`, `ACTIVSg500_flow_shed_gui_test_results_freq`, `ACTIVSg500_flow_shed_gui_test_results_volt5`, `ACTIVSg500_flow_shed_gui_test_results_both` and `ACTIVSg500_opf_gui_test_results_opf`; and from the check's jobs `savnw_flow_shed_gui_test_check`, `savnw_flow_shed_gui_test_check_volt`, `ACTIVSg500_flow_shed_gui_test_check_freq`, `ACTIVSg500_flow_shed_gui_test_check_volt` and `case9_flow_shed_gui_test_check`.

**Phase 9 (2026-11-21).**

*What changed:*
- **`worker.jl`.** `MODIFICATIONS` lists the three kinds in the order they are applied (a list of pairs, because a Julia `Dict` keeps no order): `apply_load_scaling!`, `apply_load_overrides!`, `apply_generator_settings!`. `apply_modifications!` runs them in the stage `prepare`, before the boundary lines and the penalties. `find_settings_problems` refuses a kind it does not know. The shape of the entries and what the worker refuses are under "Settings schema v1".
- **`settings.py`.** The modifications go through `build_settings` and `form_values` (`clean_modifications` drops a kind without entries, so `{}` still means none). `validate` checks their shape only; the entries are checked by the tabs.
- **`advanced/` (new):**
  - `__init__.py`: `ADVANCED_TABS`; `Study` (the case, its `case_info` and the study's kind of group, with the lookups the tabs share); `count_entries`, `describe` and `find_problems` over all tabs; and `AdvancedDialog`.
  - `load_scaling.py`, `loads.py`, `generators.py`: one tab each, with what "Extension rules" lists.
- **The dialog.** It edits a copy of the modifications as rows, one tab per kind, with the number of rows in each tab's name.
  - **Load scaling:** a zone or an area, or a list of buses, and a factor.
  - **Loads:** a load picked by its number, bus and MW (typing filters the list), then P and Q. A field left empty keeps the case's value, which shows in grey.
  - **Generators:** a zone or an area, or a list of buses, then Pmin and Pmax (see "Generators tab like load scaling" below; at first it was a group and a "Pmin to 0" tick).
  - **Apply** reads the rows, shows what is wrong in the dialog and closes only when nothing is. **Cancel**, the close button and Escape leave the modifications as they were. **Clear all** empties the rows of every tab.
- **`components/row_list.py` (new).** `RowList`: column titles, one grid line of fields per row with a remove button, and Add row.
- **`pages/run.py`:**
  - **Advanced** opens the dialog and counts the modifications: "Advanced (2)".
  - **A line under the toolbar** lists them, with **Reset**, which removes them all at once. It stays while the sheet is folded.
  - **The problems list** is read again after Apply and Reset, so it does not go on naming modifications that were just mended or removed.
  - **`RunForm`** keeps `modifications` and carries them through `read` and `write`, so a run records them in `gui_settings` and Load settings brings them back.
  - **The runs table** marks a run whose network was changed with "modified" after the case; the tooltip lists the changes.
- **`components/results_view.py`.** Beside "Results of", the panel says "network modified:" with the changes of the run on show.
- **`theme.css`.** The rows to edit (`edit-row` and one grid class per tab), the modifications line, a dialog's foot, a dialog of medium width and its tabs.
- **`app.py`, outside this phase.** The app now listens on `127.0.0.1` only (`HOST`). NiceGUI's default is every network address, so the page could be opened from other machines on the network, against decision 1.

*How it was verified.*
- **The worker against `islanding.jl`.** Four temporary copies of `islanding.jl`, each with scenario lines of its notes switched on, no dynamic simulation and a tag `gui_test_ref_*`, were run each in its own Julia process and then deleted. The same four scenarios went to the worker as jobs (`dev/send_jobs.py`, tags `gui_test_mods_*`). The console reports of each pair, from the objective to the flow sums, are the same line for line:

  | scenario | modification | objective | shed |
  |---|---|---|---|
  | savnw, island on top (five bus pairs) | load 6 at 400 MW (4.0 pu) | 9431.510209057029 | 0 of 3500 MW |
  | savnw, north-south separation (four bus pairs) | loads at buses 3005, 3007, 3008, 153 × 1.6 | 45070.19441721722 | 0 of 3620 MW |
  | ACTIVSg500, zone Spartanb at 2.5 λ | loads of the zone × 0.7 | 8519.135912744756 | 152.66 of 7416.06 MW |
  | ACTIVSg500, zone Spartanb at 2.5 λ | pmin 0 for the zone's 15 generators | 12140.983056999981 | 407.43 of 7750.72 MW |

  The first and the third are the two of "Done when".
- **Jobs the worker has to refuse,** eight of them, each failed in `prepare` with its reason: an unknown kind, an empty bus list, a zone that is not there, `true` as a factor, a load recorded at another bus, a load that is not in the case, a load entry without values, and "bus" as a generator group.
- **The functions that draw nothing,** 67 plain checks in the session's scratch folder: the four jobs through `form_values` and `build_settings` and back, each tab's entries to rows and back, the descriptions, and each problem text.
- **Through the form,** on a test instance on port 8090, tags `gui_test_adv*`. The Chrome extension was not connected in this session, so the page was driven and looked at in a headless Chrome of its own (own profile folder, real mouse and key events through its debugging port), with screenshots:
  - **The two runs of "Done when", set up by hand in the form and the dialog:** the same objectives as above, and the `gui_settings` each run saved in its `settings_*.json` equal the settings of the matching job file (apart from the tag).
  - **Load settings** of the savnw run brought the case, the five bus pairs and "load 6 at bus 3005: P 400 MW" back. Run again with the ANDES simulation, it saved the same settings, gave the same objective, and its exported RAW has 400 MW at bus 3005.
  - **Cancel, Escape, a click beside the dialog:** a value typed and cancelled was gone at the next opening; the click beside left the dialog open; Escape on an open option list closed the list only.
  - **The study changes its kind.** With zone rows in place (savnw by bus pairs), choosing an area boundary put a red note on the line, and Run refused with "Advanced, load scaling: zone FIRST: this study is by area, so choose an area or buses". The dialog opened with the same problems and with those rows asking for an area, and Apply refused them until they were filled.
  - **Another case** removed the modifications, with a notification.
  - **A reload** came back with the last run's modifications. **Clear all** followed by Cancel changed nothing. **Reset** emptied the line and the count.
  - **Refused by Apply, with the reason in the dialog:** buses without a load, a row without a group, a generator row that sets nothing.
  - **case9** (no zones or areas): load scaling and the generators offer buses only.
  - **The order on one load:** bus 3005 scaled by 2 and its load 6 set to 400 MW in the same run gave 3500 MW of total load, so the load's own P came last (3900 MW the other way round).
  - **The problems list under the toolbar** was empty right after an Apply that mended the rows it named, and right after Reset.
  - **The refresh button beside the case** kept a modification (the Q of a load alone, its P left as the case has it). **A case that cannot be read** (savnw_orig): Advanced says to choose a case that can be read.
  - **Looks:** eight modifications (the line wraps to two lines), the folded sheet, the dialog and the page at 720 px of width (no sideways scrolling), the load list of ACTIVSg500 filtered by typing.
- **`dev/check_results_tables.py`** still passes its 606 comparisons.

*Choices the user can reverse:*
- **Groups follow the study's kind** (decision 11): a scaling row and a generator row offer the study's zones, or its areas, and a bus list. So in an area study a zone's loads and generators are reached through their buses.
- **A modification that stops fitting is kept and blocks Run.** It is not dropped, because the rows are out of sight. Only another case removes them, since they name its loads and groups.
- **Apply and Cancel,** not changes that take effect as they are typed. A click beside the dialog does not close it.
- **Every row counts as active,** a factor of 1 too.
- **A load is named by its number, with its bus recorded.** Julia refuses the entry when the load is at another bus.
- **Names are stored as the case writes them** ("Spartanb"), as the form's lists show them.
- **P, Q or both** can be set for a load; the phase text has P, and Q when given.
- **Two things the phase text does not ask for:** "modified" in the runs table, and "network modified:" in the results panel.
- **The app listens on this machine only.** To reach it from another machine, `HOST` in `app.py` would be `"0.0.0.0"` again.
- **A tab's functions** differ from the phase text's `build(ctx, modifications)`: see "Extension rules".

*For the next phases:*
- **Phase 10.** `advanced.describe(modifications)` describes the modifications of any run without its case, so History can show them from `gui_settings`. Load into Run brings them back through `RunForm.write`; if the case has changed since, `find_problems` says what no longer fits.
- **Phase 12.** A preset is the settings, so it carries the modifications.
- **Not possible in the dialog, and not in the plan:** scaling every load, or setting every generator, of the network in one row. In a case without zones or areas both go by bus list.
- **Without the Chrome extension,** a page can still be driven and looked at in a headless Chrome over its debugging port, with `websockets`, which NiceGUI installs. The script of this phase is `p9/cdp.py` in the session's scratch folder, not in the repo.
- **Not exercised:** the PSS®E simulator, a load out of service in the load list, and area rows in ACTIVSg500 (it has one area).
- **Phase 8's unexplained option list:** tried once more (the "Results of" list opened and closed with Escape during a run with a penalty row): no list was open after the run.

Test folders added: `savnw_flow_shed_gui_test_ref_top`, `savnw_flow_shed_gui_test_ref_ns`, `ACTIVSg500_flow_shed_gui_test_ref_scale`, `ACTIVSg500_flow_shed_gui_test_ref_pmin`; `savnw_flow_shed_gui_test_mods_top`, `savnw_flow_shed_gui_test_mods_ns`, `ACTIVSg500_flow_shed_gui_test_mods_scale`, `ACTIVSg500_flow_shed_gui_test_mods_pmin`; `savnw_flow_shed_gui_test_adv_top`, `savnw_flow_shed_gui_test_adv_top_sim`, `savnw_flow_shed_gui_test_adv_kinds`, `savnw_flow_shed_gui_test_adv_final`, `savnw_flow_shed_gui_test_adv_final2`, `savnw_flow_shed_gui_test_adv_order` and `ACTIVSg500_flow_shed_gui_test_adv_scale`. The refused jobs (tag `gui_test_mods_bad`) left no folder.

**Generators tab like load scaling (2026-11-21, after phase 9, on the user's request).**

*What changed:*
- **The tab.** A row is "Generators of" a zone or an area (the study's kind) or a list of buses, then **Pmin (MW)** and **Pmax (MW)** where load scaling has its factor. A new row starts with both empty (at first Pmin started at 0; the user asked for empty the same day). An empty field leaves that limit as the case has it, and a row needs one of the two. Every generator named gets the value; the hint says so, because a Pmax typed for a zone could be read as the zone's total.
- **The entry** is `{kind, name | buses, pmin_mw, pmax_mw}` (see "Settings schema v1"). `pmin_zero` of the first version is gone: such an entry sets nothing, so the form and the worker both refuse it. No settings file outside the `gui_test` folders has one (searched in `results/psse`).
- **`advanced/where.py` (new)** has what load scaling and the generators share: the zone, area or bus list of an entry, its words, its problems and its two fields in a row. `load_scaling.py` and `generators.py` are built on it; the load scaling entries are as they were.
- **`worker.jl`.** `apply_generator_settings!` sets the limits that are given, from MW. It refuses an entry without a limit, and a generator in service that would end with its pmin above its pmax, naming the generator. `find_entry_buses` and `describe_where` serve both load scaling and the generators.
- **A half-filled row** is told only what it still needs ("row 1 needs a factor"), in both tabs.

*How it was verified.*
- **The worker.** The four scenarios of phase 9 again, against the saved logs of their `islanding.jl` copies: the reports are the same line for line, with "pmin 0 for the zone's generators" now sent as `pmin_mw: 0` (objective 12140.983056999981). Then, on savnw with four bus pairs, where zone PLANT has the two generators at buses 101 and 102 (810 MW each, pmin 0):

  | entry | PLANT, Pg of Pmax (MW) | what it shows |
  |---|---|---|
  | none | 833.68 of 1620 | |
  | buses 101 and 102, Pmax 500 | 833.68 of 1000 | each of the two got 500 MW; the log names pmax alone |
  | zone PLANT, Pmin 600 and Pmax 700 | 1200 of 1400 | both are held at their new pmin |
  | bus 101, Pmin 300 | 837.18 of 1620 | Pmax is as the case has it |

  The third of these again with the ANDES simulation (tag `gui_test_gen_both_sim`): the report was written, and the exported RAW has 700 MW and 600 MW as the limits of the generators at buses 101 and 102, each at 600 MW, with the generator at bus 206 as before. ANDES stopped at 6.15 s there ("Time step reduced to zero"), and it does the same for this boundary without any modification (tag `gui_test_gen_none_sim`), so that belongs to the scenario and not to the limits.

  Seven jobs were refused with their reason: the entry of the first version, Pmin above Pmax, a Pmin above a unit's own pmax of 810 MW, an empty bus list (for the generators and for load scaling), "bus" as a kind, and text for a number.
- **The functions that draw nothing:** 85 plain checks in the session's scratch folder, with the new rows in them. Among them: 0 is a value and not "empty", and an entry with a Pmax alone comes back from the dialog's rows without a Pmin.
- **Through the form,** headless Chrome as in phase 9, tags `gui_test_genform*`:
  - **A new row** showed Zone, no group yet, Pmin 0 and an empty Pmax that reads "unchanged". Pmin now starts empty too, which was checked on the row's values only, not in the browser.
  - **Pmax alone** (buses 101 and 102, 500 MW, the Pmin field emptied): the Generation tab went from 1620 to 1000 MW for PLANT, with the other rows as before. Opened again the row had no Pmin, and Apply as it was, and later Load settings, left the entry the same. The settings saved on disk equal the job file's.
  - **Pmin 0 alone** (then the value of a new row), for zone PLANT and for zone Spartanb of ACTIVSg500: the saved entry has `"pmin_mw": 0` and `"pmax_mw": null`, the Pmax totals did not change, and the ACTIVSg500 run gave 12140.983056999981.
  - **Both limits** for zone PLANT: 1200 of 1400 MW, as from the worker job.
  - **Refused by Apply:** a bus without a generator, Pmin above Pmax, a row without a limit, a row without its zone.
  - **The study changing to area** kept the zone row's limits and asked for an area or buses.
  - **case9:** the Generators tab offers buses only and takes them.
  - **Load scaling again,** since its code moved: the bus list of the north-south separation (45070.19441721722) and zone Spartanb by 0.7 (8519.135912744756), each with saved settings equal to its job file's.
  - **Both tabs in one run** (zone FIFTH by 1.1, the generator at bus 3018 between 50 and 100 MW): 3250 MW of load, 1000 MW of Pmax in FIFTH, and both lines in the Full log.

*Choices the user can reverse:*
- **MW, and the same value for every generator named.** A limit as a share of each unit's own Pmax would be a different field.
- **Generators out of service get the limits too,** as the loop in the notes of `islanding.jl` sets them; only those in service are checked for pmin above pmax.
- **A unit left with its pmin above the new Pmax fails the run in `prepare`,** with the generator named. The dialog cannot see it for a zone, because `case_info` does not say which zone a generator is in.
- **Two rows on the same zone are refused;** bus lists may overlap, and the later row wins.
- **Pmin above Pmax is checked after each row,** so a later row cannot mend a generator that an earlier row left with its pmin above its pmax: the earlier row fails first.

Test folders added: `savnw_flow_shed_gui_test_gen_top`, `savnw_flow_shed_gui_test_gen_ns`, `savnw_flow_shed_gui_test_gen_none`, `savnw_flow_shed_gui_test_gen_pmax`, `savnw_flow_shed_gui_test_gen_both`, `savnw_flow_shed_gui_test_gen_both_sim`, `savnw_flow_shed_gui_test_gen_none_sim`, `savnw_flow_shed_gui_test_gen_pmin`, `ACTIVSg500_flow_shed_gui_test_gen_scale`, `ACTIVSg500_flow_shed_gui_test_gen_pmin`; `savnw_flow_shed_gui_test_genform_none`, `savnw_flow_shed_gui_test_genform_pmax`, `savnw_flow_shed_gui_test_genform_pmax2`, `savnw_flow_shed_gui_test_genform_pmin0`, `savnw_flow_shed_gui_test_genform_both`, `savnw_flow_shed_gui_test_genform_ns`, `savnw_flow_shed_gui_test_genform_last`, `ACTIVSg500_flow_shed_gui_test_genform_scale` and `ACTIVSg500_flow_shed_gui_test_genform_zpmin`. The refused jobs (tag `gui_test_gen_bad`) left no folder.

**Phase 11 (2026-11-21). The user asked for it before phase 10 and widened it; decision 8 and the phase text were rewritten to what was asked.**

*What changed:*
- **`network_layout.jl` (new).** `calc_network_layout` takes plain arrays and gives positions and circles, the same every time. Its steps:
  - **clusters:** a group's connected parts; a part with less than a quarter of the buses of the group's largest part is a stray and joins the cluster most of its lines go to;
  - **leaves** (buses with one line, half the buses of ACTIVSg500) are set aside and put beside their bus at the end;
  - **first positions** by stress majorization over the rest, with lines between clusters long;
  - **circles** with an area that follows the number of buses, arranged by stress majorization on the clusters from 81 starts, keeping the arrangement where the bundles of lines between clusters cross least;
  - **each cluster** scaled into its circle and turned or mirrored towards its neighbours, its buses spread until the circle is filled evenly, and single buses moved where that uncrosses lines.
- **`worker.jl`.** The `network` job (see "Network reply") and the `network` part of `@@result`.
- **`network_view.py` (new)** works out everything the page shows as plain data: the values of the case or of a run, group totals, colours and sizes, tooltips, the boundary of a selection, the islands it leaves. **`components/network_canvas`** draws what it is given. **`pages/network.py`** holds the controls and the selection.
- **`app.py`:** `ctx.client_state()`. **`pages/run.py`:** `RunForm.take(case, boundary=..., penalty_rows=...)`, which goes through `read` and `write`, so the form's own rules apply (a change of case drops what named the other case; penalty rows of the other kind of group go).

*Is a clean graph possible without coordinates?* Yes, with limits that are worth knowing:
- **savnw, IEEE39 and case9** are drawn without a single crossing.
- **ACTIVSg500** has 128 crossings among its 584 lines, and ACTIVSg200 about 26 among 245. The six zones are six separate circles filled evenly, so the whole case reads at a glance; single lines are followed after zooming in. The untidiest place is where three zones meet (Clemson, Greenvil, Spartanb).
- **What the first tries taught:** stress majorization alone piles the buses in the middle of each circle; pushes between all buses line them up along the circle's edge; short pushes between buses that are too near fill the circle evenly.

*How it was verified.*
- **The layout** on savnw (by zone and by area), ACTIVSg500, ACTIVSg200, AU14GenModel, IEEE39, Hawaii40 and case9, as pictures of the size of the page's canvas, with the crossings counted. In the checks: no two circles overlap and every bus is inside its circle.
- **The worker:** `network` jobs for savnw (9 KiB), ACTIVSg500 (165 KiB, 0.23 s once Julia is warm, 12 s for the first job of a worker), case9 and `simple`, which cannot be read and answers `@@error`. A run of the four savnw bus pairs gave 30642.40499516773 as before.
- **Boundaries:** for every zone and area of savnw and ACTIVSg500, the buses and the branch ids of the selection equal those of `find_buses_by_zone`, `find_branches_by_zone` and the area functions (Spartanb: 85 buses, 18 branches), and the four bus pairs give the branches of `find_branches_by_bus_pairs`.
- **A run's values against its own tables:**
  - **savnw:** generation and capacity per zone equal the Generation tab; the shed per bus adds up to the total shed; the flow of a bus pair equals the sum of its boundary lines; and for a run with zone FIFTH as the target the selection's "Leaving it" (1.7 MW, 8.9 Mvar) equals the net flow of the Boundary flows tab (1.72, 8.93).
  - **ACTIVSg500,** zone Spartanb as the target at 2.5 λ with its loads at 0.7, from the form: 8519.135912744756 as in phase 9. On the page, with that run's values, Spartanb has 780.9 MW of load (the case has 1 115.5) and 152.7 MW of shed, "Leaving it" is -25.1 MW and 12.6 Mvar over its 18 lines against -25.10 and 12.62 in the Boundary flows tab, and the circles by generation show the Generation tab's numbers.
  - **A DC run** (savnw, by the worker): its voltages are 1, its reactive values are missing, and the page's functions show "–" for them, also in the totals, without an error.
- **In a headless Chrome,** on a test instance on another port:
  - a redraw of ACTIVSg500 takes 2 to 3 ms, with flows and arrows on, and a click on a bus takes 52 ms from the mouse to the new picture (the look of all 500 buses goes through Python);
  - the zoom is kept by a click, by a change of colouring or mode, and by going to the Run page and back;
  - Julia is asked for nothing until the Network page is shown: with the page closed the worker stays ready and Run stays enabled. The first network of a worker then takes 9 to 15 s, because Julia compiles the layout, and the next ones well under a second;
  - AU14GenModel (areas only, 138 branches on 74 bus pairs): five circles in a row, 44 lines of more than one circuit;
  - by zone and by area on savnw; every colouring with its legend; the three kinds of selection by click, by box and by typing; a bus pair that is not there is refused with its reason;
  - "Use as target" with four bus pairs filled the Run form, and the run gave 30642.40499516773; a zone as target and a zone penalty arrived too;
  - a run with shedding (zone FIFTH, uniform penalty 0.01): its shed of 582.9 MW at bus 154 shows on the bus and on the circle of zone FIRST;
  - case9 (no groups: no circles, selection by buses or lines only), `simple` (the reason it cannot be read), a 1100 x 700 window, and the Run tab and back.

*What the page showed about ACTIVSg500,* which is the kind of thing it was asked for: opening the boundary of Spartanb (18 lines) leaves six islands of 405, 79, 7, 4, 3 and 2 buses, because the zone has small pockets inside its neighbours and pockets of York inside it. Every zone of that case has such strays.

*Found by the review before the handover, and fixed:*
- **The first click after opening the page threw the zoom away,** because the canvas did not remember which graph it had fitted.
- **The network was asked for when the app started,** which kept Julia busy for up to 15 s although nobody had opened the page. The page is built with the others and only shown later, so the canvas now reports when it first has a size on the screen (`ready`), and the page reads then.
- **"Leaving it" was measured at the far end of each line,** which is wrong for Q by the line charging (263 Mvar where the results tab had 8.9). The worker now sends both ends of every line.
- **A total over buses of which one has no value is "–",** not the sum of the others.
- **The Run page's refresh** now also drops the networks read from Julia.

*Choices the user can reverse:*
- **One drawn line per pair of buses.** Parallel circuits are one line with their branches in the tooltip, and a bus-pair boundary opens them all, as `find_branches_by_bus_pairs` does.
- **A stray keeps its group's colour and stands in the neighbour's circle.** When its group is selected it gets a ring, and its lines are part of the red boundary, because they are.
- **A group in two large parts has two circles** with the same name (PLANT in savnw), and each shows the group's whole total.
- **An amount is coloured by its size,** so a negative reactive value looks like a positive one; the tooltip has the sign, and the legend says so when it happens.
- **"Leaving it" is measured at each line's end inside the selection,** as the boundary flows of a run with a target zone are.
- **A click on nothing clears a group selection;** buses and lines are only cleared by Clear.
- **Bus numbers show** from a zoom where they have room, and for the ringed buses.
- **`@@result` grew by the `network` part** (about 95 KiB for ACTIVSg500), which every run now carries in the session's memory.

*Not done, and not asked:* moving a bus by hand, line loading in % (the reply has no ratings yet), the values of runs of earlier sessions, a picture to save. The layout knows nothing of geography or voltage levels.

*For the next phase:*
- A page of a browser tab reaches another through `ctx.client_state()`; History's "Load into Run" should use `client_state()["run_form"]` and `["show_page"]`.
- `ui.tab_panels` keeps hidden pages alive (`keep_alive` is on by default), so the canvas keeps its zoom while another page shows.
- The colours of data follow the rule under "Look"; a new chart should take its colours from `network_view.py`.

Not looked at: the PSS®E simulator and any dynamic simulation (the page reads the solution of the optimization only), a case with a line out of service or a bus without a line (the code paths are there, the cases have none), a case with more than eight groups, and the page in the user's own browser (it was seen in a headless Chrome).

Test folders added: `savnw_flow_shed_gui_test_net` and `savnw_flow_shed_gui_test_net_dc` (worker jobs), `savnw_flow_shed_gui_test_net_form`, `savnw_flow_shed_gui_test_net_shed` and `ACTIVSg500_flow_shed_gui_test_net_spartanb` (runs from the form).
