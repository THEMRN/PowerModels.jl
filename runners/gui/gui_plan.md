# GUI plan

A local GUI for running islanding scenarios without editing code. It sets the run (case, boundary, objective, penalties, security options, network modifications), runs it in a Julia session that stays warm, shows which stage is running, and shows the information the console reports print (generation, load shedding, boundary flows, frequency and voltage security) as tables. Phase 13 brings the dynamic simulation's curves into the app and makes the Plotly report optional.

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
| 10 | History page | 3, 6 | done (2026-11-21) |
| 11 | Network page | 2, 6 | done (2026-11-21) |
| 12 | Presets (optional, ask the user first) | 6 | done (2026-11-21) |
| 13 | Dynamic simulation in the app | 8, 10 | done (2026-11-23) |
| 14 | Compare: curves of several runs | 13 | done (2026-11-23) |

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
15. **The dynamic simulation in the app (2026-11-23).** The results panel shows the simulation's curves and statistics, read from the channel file the ANDES script already writes (`output_andes_<stamp>.csv.gz`). Time series do not go into Excel; the Excel files keep the steady state. The Plotly HTML report is written only when the Run form's "HTML file" box is ticked, and the box is unticked by default. Script runs (`islanding.jl`, `batch_islanding.jl`) keep writing it, and the PSS®E script, which is frozen, always writes its own.

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
  run_queue.py           the runs that wait for the run in progress (RunQueue, ctx.queue): add, cancel, reorder, pause
  batch.py               a batch of runs as plain data: lists of values, every combination a run with its own tag
  comparison.py          the runs on the Compare page (CompareList, ctx.compare) and what it says of them, without drawing; which runs its dynamic response draws (phase 14)
  settings.py            settings schema v1: defaults, form values <-> settings, validation, JSON files
  network_view.py        what the Network page shows, as plain data: values, colours, selection, boundary
  dynamics.py            a run's channel file: reading it, its statistics, its curves as chart options, without drawing (phase 13); one curve per run for the Compare page (phase 14)
  theme.py               the look: element defaults, icons, building blocks (panel, sheet, Section, fields, button, State, FoldButton)
  theme.css              the look: colours and sizes as variables, the building blocks, Quasar without the Material look
  results_index.py       scans results/psse for the History page: rows, filters, settings from a script's record
  presets.py             the presets: files in presets/, their names, saving and deleting (PresetStore, ctx.presets)
  presets/               one JSON file per preset (git-ignored by the user: the presets stay on this machine)
  components/            reusable UI pieces: status_strip.py (where a run is), log_dialog.py (log lines as text),
                         results_view.py (a run's report numbers as tables), voltage_details.py (the voltage rounds),
                         row_list.py (rows to edit, with Add row and remove),
                         network_canvas.py with network_canvas.js (the network drawing: a canvas with zoom and pan),
                         sortable_table.py with sortable_table.js (a table of rows to choose from, sorted in the browser),
                         preset_bar.py (the presets in the Run page's settings toolbar, with Save as and Delete),
                         queue_dialog.py (the run queue: the runs that wait, with cancel, reorder, pause and resume),
                         batch_dialog.py (a batch: the form's settings with lists of values, and the runs they make),
                         dynamics_view.py (the Dynamics tab of the results panel: curves and statistics, phase 13)
  pages/                 one file per page, in the order of the tabs: run.py, network.py, compare.py, history.py
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
- **Pages pass values to each other** through `ctx.client_state()`, the dict of the browser tab. The Run page puts its form there (`"run_form"`), `app.py` the function that shows a page (`"show_page"`), and the Network page's "Use as target" calls `RunForm.take` and shows the Run page. The Run page also puts there `"load_settings"`, which writes settings into its form, unfolds the sheet and says so, and shows the results of the run they came from in the results panel when it has them; History's "Load into Run" calls it and shows the Run page. `ctx.state` is shared by every open browser tab, so it only holds what was read from Julia.
- **What `ctx` holds** (since phase 6):
  - `ctx.worker`, the `JuliaWorker`;
  - `ctx.presets`, the `PresetStore`: the presets of the app, read from `presets/`, whose listeners keep every open tab's list the same;
  - `ctx.runs`, the `SessionRuns`: one record per run of this session, with its settings, status, the stages it reached with their times, its latest log line, its warnings and its `@@result` summary (the fields are listed in the class's docstring);
  - `ctx.queue`, the `RunQueue` (since 2026-11-23): the runs that wait for the run in progress. It is kept in Python, and Julia gets one run at a time, so a run that waits can be cancelled or moved and a page's question is answered between two runs;
  - `ctx.compare`, the `CompareList` (since 2026-11-23): the runs on the Compare page, each a record as the results panel shows one;
  - `ctx.state`, which caches what was read from Julia: `"cases"` (the case list), `"case_infos"` (case path to its `case_info`, or to the error that reading it gave) and `"networks"` (the same for the `network` reply). The worker answers one job at a time, so a question asked during a run would wait for the run to end.

### Look

Decision 14. The look lives in `theme.py` and `theme.css` and nowhere else, so every page gets it.

**What it is:**
- **Light and quiet.** A grey page, white panels with a hairline border, no shadows.
- **One accent colour** (blue) for the main action, the chosen option (a tab, a segment) and the focus ring, and its **soft tints** (a pale fill with dark text of the same hue) for the other actions of a panel or a toolbar and for a line that informs. Two more soft tones, violet and teal, only on buttons, tell the Run toolbar's tools apart. Green, amber and red only show a state, also as soft tints (the Julia pill, the problems line, a danger button). Colour stays a little: soft, never saturated, and not on row actions or crosses.
- **Compact.** Text is 13 px in the system font (Segoe UI). Fields and buttons are 28 px high. A label stands left of its control, not above it and not floating inside it.
- **Nothing leaves the machine.** No web font, no CDN.
- **One bar on top:** the mark, the title, the page tabs, the Julia state pill, Restart Julia and Quit.

**Rules for a page:**
- **Build with the blocks of `theme.py`:** `panel`, `toolbar`, `sheet` and `Section`, `fields` with `label`, `stack`, `line`, `hint`, `eyebrow`, `button`, `State`, `FoldButton`, `dialog` (a dialog and its white box), `offstage` (a holder for timers, so they take no room), `data_table` (a table of numbers, as one element), `facts` with `fact` (a name and its value), `help_mark` (a "?" whose tooltip says how to use a page), `dim_unused` (settings the current choice does not read: dimmed, still editable), and for waiting `Cover`, `grey_out` and `show_hint(..., waiting=True)`. Plain `ui.select`, `ui.number`, `ui.input`, `ui.textarea`, `ui.checkbox` and `ui.toggle` get the look from the defaults set in `theme.setup()`. Give them no label argument; put a `theme.label` beside them.
- **Buttons** come from `theme.button`: `primary` for the one main action of a page; `soft` (the accent's tint, or with `tone="violet"` or `"teal"`) for the other actions of a panel or a toolbar; `default` (plain, outlined) for Cancel and Pause beside a dialog's primary, where a tint would read as a second action; `ghost` for small and row actions and crosses (a soft blue on hover); `danger` (soft red). A soft or danger button has its colour only while it can be clicked; off, it is a plain button, faded. The results panel's Clear keeps its own soft yellow.
- **No Quasar colours or spacing classes** (`color=...`, `text-grey`, `q-mt-md`, `bg-primary`): they are Material's palette and they carry `!important`. Use the variables and classes of `theme.css`, and add to that file when something is missing.
- **Not used:** `ui.card`, `ui.expansion`, `ui.switch`, `ui.badge`, `ui.table` (Quasar's Material table; use `theme.data_table`), Material icon names. Use a panel, a `FoldButton`, a checkbox, a `State`, and the icons in `theme.ICONS` (add a path there for a new icon).
- **No tooltip that explains a control** (the user, 2026-11-23: "you add a lot of useless tooltips, don't do that"). A button or a field with a label says what it is, and a plain close or remove cross needs no words. A tooltip is only for what the page does not show: why a control is off, or the whole of a text that is cut with "...". What needs explaining goes where it is read without hovering (a hint line), or is left out.
- **A choice of two or three** is a `ui.toggle` (drawn as a segmented control); more options are a `ui.select`.
- **Rows to edit** (a list the user adds to and removes from) are a `components/row_list.RowList`.
- **A dialog that changes something** edits a copy and ends with a row of the class `dialog-foot`: what clears on the left, then Cancel and the dialog's own primary button. A click beside it does not close it (`no-backdrop-dismiss`). Its problems show above that row, in the class `problems`.
- **Colours that show data** (the Network page) are in `network_view.py`, not in the stylesheet, and follow three rules. Groups get the eight colours of `GROUP_COLORS` in a fixed order, a ninth group and later ones share one grey, and a group is always named as well (on its circle, in the legend, in the tooltip). A bus with a generator (a square) has its group's colour a shade darker (`GEN_SHADE` of the way to `DARK_COLOR`), to stand apart from the group's other buses. An amount is one hue from light to dark. A value around a middle (a voltage around 1 pu) is two hues with grey in the middle. What is selected is marked by shape (a ring, a dashed line with a white edge), because the colours are already taken.
- **Class names:** before adding a class to `theme.css`, check that Quasar and Tailwind do not use the name (`inline`, `row` and `dimmed` are taken).
- **Anything that waits shows it, and says for what.** Julia answers one job at a time, so a question can wait for a whole run.
  - **A part of a page that waits** (a drawing, a table) gets a `theme.Cover` with a sentence saying what it waits for: Julia starting, run N to end, or the read itself.
  - **A field that waits** gets its hint with `waiting=True` (a turning ring), in one short line, so the fields below it do not move.
  - **Controls that would act on what is not there yet** are greyed with `theme.grey_out`; a button that cannot be used says why in its tooltip.
  - **A button whose click waits, on a page that stays where it is**, is made with `busy=True`. It turns into a ring and ignores clicks until it is done; Quasar ignores clicks on a button with its ring anyway. A button that goes to another page which shows the wait gets no ring, and its newest click wins.
  - **Quick waits show nothing:** the ring, the cover and the greying appear after 0.2 s (`BUSY_DELAY`), so a quick wait does not flash.
  - **A question Julia did not answer** because it stopped (Stop, Restart Julia) is asked again once Julia is ready, rather than left as an error.
  - **A view that is read again** (at every stage of a run) keeps what did not change instead of building it again, so it does not flicker or lose a click.
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
| `run` | `"settings"` | `@@stage` and `@@activity` lines, then `@@result`, then `@@done`; a run with the dynamic simulation also sends a first `@@result` with `"partial": true` once it is solved, before the Excel report and the simulation |
| `network` | `"case"` | `@@data {"id", "case", "buses": [...], "lines": [...], "zones", "areas", "group_names", "layouts"}`, see "Network reply" |

The worker writes ordinary log lines (its own prints, Ipopt and `dynamic.py`) plus **control lines** that start with `@@`. Each control line has a kind and one-line JSON:

| kind | payload |
|---|---|
| `ready` | `{"julia": "<version>"}`, once after startup |
| `start` | `{"id", "type"}` |
| `stage` | `{"id", "stage", "label"}`, see the stage table |
| `activity` | `{"id", "text"}`, a note on what the run is doing inside the solve stage, see "Stages" |
| `data` | `{"id", ...}`, the reply of `ping`, `list_cases`, `case_info` and `network` |
| `result` | `{"id", "summary": {...}}`, see the result summary; `"partial": true` on the first of two, sent before the dynamic simulation |
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
- **The empty line before a control line.** The `"\n"` that starts a control line leaves an empty line whenever the output was already at the start of a line. `julia_worker.py` holds an empty line until the next line comes and drops it when that is a control line, so a run's log does not fill with empty lines (Ipopt's notes come twice a second).
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

The GUI keeps the same list, in this order, as `STAGES` in `components/status_strip.py`, because it shows the stages a run has not reached yet. A new stage goes in three places: this table, `STAGE_LABELS` in `worker.jl` and `STAGES`. A stage that only some runs reach also goes in `STAGE_SETTINGS` there, with the setting that turns it on. What the strip's "now" says for a stage is in `STAGE_ACTIVITIES` there.

**Notes inside the solve stage (`@@activity`).** The solve stage prints nothing while it builds the model and while Ipopt works, so `run_islanding` reports each of its steps through its `activity` callback, and the worker sends each note as `@@activity`. A note holds until the next note or the next stage; the GUI drops it at each `@@stage`.

| note | sent by | when |
|---|---|---|
| `building the optimization model` | `run_islanding` | before the solve |
| `solving with Ipopt, iteration 37, constraint violation 3.2e-5` | Ipopt's intermediate callback, set by `build_ipopt_reporter` through `solve_custom_opf(...; before_solve)` | iteration 0 of each solve at once, then at most every `IPOPT_REPORT_SECONDS` (0.5 s) |
| `voltage round 2: building the optimization model` | `solve_voltage_secure_opf` | before each round's solve; Ipopt's notes then start with the round too |
| `voltage round 2: checking the islands' voltage` | `solve_voltage_secure_opf` | after the solve |
| `voltage round 2: power flow and voltage indicators of the island at bus 3001` | `solve_voltage_secure_opf` | for each island |
| `voltage round 2: sizing a shed in the island at bus 3001` | `solve_voltage_secure_opf` | before sizing a shed |

Runs without `activity` (`islanding.jl`, `batch_islanding.jl`) set no callback and solve as before.

### Settings schema v1

Version 2 since 2026-11-21 (the heading keeps its name, as the phases refer to it). The GUI sends this to the worker, and `run_islanding` stores it verbatim as `gui_settings` in the per-run settings file:

```json
{
  "schema": 2,
  "case": "cases/psse/ACTIVSg500",
  "objective": "flow_shed",
  "opf_model": "AC",
  "flow_model": "squared",
  "lambda": 500,
  "boundary": {"kind": "zone", "name": "SPARTANB", "bus_pairs": []},
  "penalties": {
    "uniform": null,
    "rows": [
      {"kind": "zone", "name": "SPARTANB", "except": false, "times_lambda": 2.5},
      {"kind": "zone", "name": "SPARTANB", "except": true, "times_lambda": 1.6},
      {"kind": "bus", "name": 205, "except": false, "times_lambda": 5.8}
    ],
    "others": null
  },
  "frequency_security": false,
  "voltage_security": false,
  "run_dynamic_sim": true,
  "simulator": "andes",
  "open_report": true,
  "html_report": false,
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
| `penalties` | All values are multiples of λ. `uniform` (if not null) applies to every load and ignores the rest. Otherwise the `rows` apply in their order, a later row over an earlier one where they reach the same bus, and `others` goes to the loads no row reaches; `others: null` keeps today's default of 1e4 absolute for them (`add_load_shedding_penalty!`). A row is a `zone` or an `area` (of the study's kind only) or a `bus` (`name` its number); `except: true` on a zone or area row means every bus outside it. Two rows for the same place are allowed: the lower one counts |
| `open_report` | since 2026-11-21, optional (missing means `true`): `false` makes `run_islanding` pass `--no-open` to the simulation script, so the ANDES report is written but not opened in the browser. The PSS®E script ignores it and always opens its report, so the form greys the box for PSS®E |
| `html_report` | since 2026-11-23 (phase 13), optional (missing means `false`, the GUI's default, so older settings and presets come in unticked): `false` makes `run_islanding` pass `--no-html` to the ANDES script, which then writes no HTML report (the Dynamics tab draws the channels). The PSS®E script never gets the flag and always writes its report, so the form greys the box for PSS®E and sends `true` |
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

The worker turns penalties into the absolute per-bus dictionary that `add_load_shedding_penalty!` expects (bus string to `times_lambda * lambda`), exactly as `runners/islanding.jl` does by hand today: `others` on every load first, then each row on its buses in order (`calc_shed_penalties`). An "all but" row reaches every bus outside its zone or area, as the loop of `islanding.jl` over the buses outside the target does, and a name the case does not have fails the run, so such a row never reaches every load by mistake.

**Schema 1** (until 2026-11-21) had `"groups": [{kind, name, times_lambda}]` and `"buses": {"205": 5.8}` instead of `rows`, with buses over groups whatever their order. It is still read everywhere: by the worker (`find_penalty_rows`), and on the Python side by `settings.upgrade_settings`, which `form_values`, `load_settings`, the presets and History use. Its groups become rows first and its buses after, which gives every load the same penalty as before. Settings written now are schema 2.

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
  "run_dynamic_sim": true, "simulator": "andes", "open_report": true, "html_report": true, "output_tag": "spartanb_2.5",
  "gui_settings": null,
  "files": {"excel": "pm_res_flow_shed_<ts>.xlsx", "raw": "...", "report": "dynamic_channels_<now>.html", "channels": "output_andes_<now>.csv.gz"},
  "summary": {"termination_status": "LOCALLY_SOLVED", "objective": 0.0, "preemptive_shed_mw": 0.0, "voltage_security": null},
  "seconds": {"solve": 0.0, "dynamic_sim": 0.0, "total": 0.0}
}
```

The report name is `dynamic.py`'s own `dynamic_channels_<now>.html`, whose stamp is the script's, not the run's. `run_islanding` finds it after the simulation as the newest such file modified after the run started (`find_new_file`), and finds the ANDES channel file `output_andes_<now>.csv.gz` the same way as `files.channels` (since 2026-11-23; `null` for PSS®E and without a simulation). `html_report` is recorded since 2026-11-23; with it `false` the report is `null`. `run_info.json` keeps its keys, because the Python report reads them. It gained `target_area` in phase 2 and `group_kind` in phase 4b; the ANDES report uses both.

### Preset file

A preset is one file in `runners/gui/presets/`, the settings at their top level (schema 2; a schema 1 file is read and upgraded) with two more keys, written by `presets.write_preset`:

```json
{"preset": "savnw – island on top", "note": "a line about the scenario, or empty", "schema": 2, "case": "cases/psse/savnw", ...}
```

The name is what the Run page lists; the file name is made from it (`savnw_island_on_top.json`), with `_2`, `_3`, ... when another preset has that file. Names are compared ignoring case, so two presets cannot differ by case only, and they cannot hold `\/:*?"<>|`. A file that cannot be read, or holds no schema 1, is listed as "(cannot be read)" and cannot be chosen. The form reads only the settings' own keys, so `preset` and `note` never reach the worker.

### Result summary (`@@result`)

The worker sends it at the end of a run, after the stage `summary`. A run that fails sends `@@error` and no final `@@result`.

**The results before the simulation (since 2026-11-21).** A run with the dynamic simulation also sends a first summary with `"partial": true`, as soon as it is solved and its console reports are printed. `run_islanding` calls its `on_solved(result, solve_seconds)` there, before the Excel report and the export. In that first summary:
- `ufls` and `frequency_simulation` are `{"status": "pending"}`;
- `seconds` has only `solve`;
- `files` has only `output_path`.

Everything else is final. The final `@@result` replaces it, and only the final one is kept in the results folder. A first summary that cannot be made leaves a warning in the log, and the run goes on.

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
- `target`, since 2026-11-21: the target zone or area, `kind`, `name` and its `buses` (sorted), by which the GUI names the islands of the frequency and voltage parts ("zone SECOND", "outside zone SECOND", numbered by size as "zone SECOND island 1" when a side has more than one; `voltage_details.name_islands`); `null` for a bus-pair boundary, and missing in results kept before, whose islands are "island 1", "island 2", ... (since 2026-11-22; before, "island at bus N")
- `generation`:
  - `group_kind`
  - `groups`, one per zone or area record (none when the case has no such records): `index`, `name`, `pg_mw`, `pmax_mw`, `qg_mvar`, `qmax_mvar`, `p_used_pct`, `q_used_pct`
  - `total`: the same fields without `index` and `name`
- `load_shed`, for objectives with shedding only:
  - `group_kind`, `total_load_mw`, `total_shed_mw`
  - `groups`, one per group with load: `index`, `name`, `load_mw`, `shed_mw`, `shed_pct`
  - `buses`, every load bus, with the loads at that bus added up: `bus`, `pd_mw`, `shed_mw`, `shed_pct`. Solver noise rounds to 0, so "only buses with shed" means `shed_mw > 0`.
- `ufls`, the UFLS relays' shed in the dynamic simulation; `null` when the simulation was off. `status` is one of:
  - `pending`: the first summary, sent before the simulation;
  - `not_reported`: the simulator was PSS®E, whose script writes no record (its report has the shed);
  - `no_record`: ANDES left no `ufls_shed.json` in the results folder at or after the run's start;
  - `no_relays`: the `.dyr` has no LDSHBL records;
  - `simulated`, which adds `relays`, `end_time_s` (how far the simulation ran), `stopped_early`, `group_kind`, `total_load_mw`, `total_shed_mw`, `total_shed_mvar`, `total_shed_pct`, `stages` (relay stages that acted, 0 when none did), `groups` (`index`, `name`, `load_mw`, `shed_mw`, `shed_pct`, `stages`, one per group with load) and `buses` (`bus`, `pd_mw`, `shed_mw`, `shed_pct`, `stages`, every load bus). Groups and names are those of `load_shed`. The load is what is in service when the lines open (the case's load less the preemptive shed). The shed is in MW at 1 pu voltage, as the relays and the simulation report give it (P0/V0 of a constant current load, so a 5 % stage at a bus above 1 pu is under 5 % of its MW load). The `shed_pct` is therefore the share of the load the stages tripped (each stage's `percent` times its load's power flow P), not the MW over the load.
  - The worker reads it from `ufls_shed.json`, which `andes_scripts/dynamic.py` writes into the results folder: `relays`, `end_time` (s), `stopped_early`, and `events`, one per relay stage that acted (`time`, `bus`, `load_id`, `stage`, `percent`, `load_mw` (the load's power flow P), `MW`, `Mvar`, `voltage`, `frequency`).
- `boundary_flows`:
  - `oriented`: true with a target zone or area. Each line is then measured at its end inside the group (`from`) and is positive leaving the group. With bus pairs, each line is measured at its RAW from end.
  - `lines`: `id`, `from`, `to`, `p_mw`, `q_mvar`
  - `net` and `abs_sum`: `p_mw`, `q_mvar`, and `total` (P + Q, as the console prints it)
- `frequency`, one entry per island that has frequency limits (an empty list when no island has inertia):
  - `island_bus`, `n_buses`, `gens`, `governors`
  - `H` (s), and `K` and `D` (pu on the system base)
  - `limits_mw` (`rocof`, `qss`, `nadir`), `binding`
  - `scheduled_import_mw`, positive into the island, which is the opposite sign of the boundary flows. The limits hold in both directions, so an island is within them when the import's magnitude is at most the binding limit (for example −342.15 MW against 592.4 MW).
  - since 2026-11-21, the frequency once the lines open, in Hz to 3 decimals:
    - `extreme`: `nadir` for an island that imports (it loses power and its frequency falls), or `peak` for one that exports;
    - `limit_hz`: what the nadir limit keeps it from passing (`MIN_NADIR_FREQUENCY`, 59.5 Hz, or as far above f0 for a peak);
    - `predicted_hz`: `simulate_frequency_nadir` of `frequency.jl` at the scheduled import (for a peak, mirrored about f0);
    - `simulated_hz`, `simulated_bus` and `simulated_time_s` (absolute, s): the lowest (for a peak, the highest) bus frequency of the island's buses after the trip, from `frequency_stats.json`. All `null` without that record.
- `frequency_simulation`, since 2026-11-21, where the simulated frequency stands: `null` when the simulation was off, otherwise `status` `pending` (the first summary), `not_reported` (PSS®E), `no_record`, or `simulated` with `event_time_s`, `end_time_s` and `stopped_early`.
  - The worker reads `frequency_stats.json`, which `andes_scripts/dynamic.py` writes into the results folder: `event_time`, `end_time`, `stopped_early`, and `buses` (bus number as a string, each with `min_hz`, `min_time`, `max_hz`, `max_time`). The extremes are taken after the trip only, because a case not quite at steady state can swing before it.
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
  - the file names in that folder: `settings`, `excel`, `raw`, `report`, `channels` (since 2026-11-23, the ANDES channel file the Dynamics tab reads), `result` (`null` when not written).

### Kept results (`result_<timestamp>.json`)

Since 2026-11-21 the worker keeps the summary of every run that finishes, beside the run's settings file and with its timestamp: `settings_2026_11_21_10_15_02.json` gets `result_2026_11_21_10_15_02.json` (`write_result_file!`, just before `@@result`). The file is the `@@result` summary as sent, with `files.result` naming itself. A run without a settings file keeps nothing, and a file that cannot be written leaves `files.result` at `null` and a warning in the log.

History's Load into Run reads it (`results_index.read_result`, never while scanning) and shows it in the results panel, with `files.output_path` set to where the folder is now. Script runs, runs that did not finish and runs from before 2026-11-21 have no such file; the Load note says why there are no results. Nothing else reads the file.

### Run page layout (since phase 9)

```
┌ ◉ Islanding GUI   Run | Network | Compare | History   [● Julia ready]  ↻ Restart Julia  ⏻ Quit ┐
├────────────────────────────────────────────────────────────────────────────────────┤
│ ▾ Settings  Preset [savnw – island on top ▾] Save as Delete  (note) Advanced (2) Batch Queue (3) [■ Stop] [▶ Run] │
│ NETWORK MODIFICATIONS   loads of zone SPARTANB × 0.7 · load 6 at bus 3005: P 400 MW   Reset │
│ CASE AND MODEL    │ BOUNDARY    │ LOAD SHEDDING PENALTIES   │ SECURITY AND SIMULATION │ ▴ fold
├────────────────────────────────────────────────────────────────────────────────────┤
│ RESULTS OF [run 3 · savnw · flow_shed · 4 bus pairs · 22:09:03 ▾]                   │
│ Summary | Generation | Load shedding | Boundary flows | Frequency | Voltage | Dynamics | Files │
│   facts and tables of that run                                                     │
├────────────────────────────────────────────────────────────────────────────────────┤
│ RUNS IN THIS SESSION   run, started, case, ...   Report  Folder  Log  Load          │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Run 3 ● finished   ✓ Load case — ✓ Prepare — ✓ Solve — ... — ✓ Summary              │
│ now: Julia's note or the stage's sentence, or the error   total 1:42  2 warnings  [Full log] │
└────────────────────────────────────────────────────────────────────────────────────┘
```

The page tabs are in the top bar. The presets come right of the Settings fold (since phase 12), with "changed" and Reload while the form differs from the chosen preset; the toolbar's text is the preset's note while the sheet is open and the settings on one line while it is folded. Run and Stop are in the toolbar of the settings panel, above the sheet, so they stay in the same place when the sheet is folded or a penalty row is added. Since 2026-11-23, Run reads "Add to queue" while a run is in progress (the same button, at the same width), Queue shows how many runs wait and turns amber while the queue is paused, and Batch opens the batch dialog on the form's settings. The problems that keep the settings from running show between the toolbar and the sheet. Under them, the line of the network modifications shows while there are any, also while the sheet is folded. The results panel is hidden until a run has results, and the last two rows are the status strip, fixed to the bottom of the window.

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
7. **Picked:** a right click on a line adds its bus pair, and on a bus its number, to two fields of their own, each with Copy: Bus pairs in the text of the Run form's bus pairs field, Buses in the text of the bus lists (Advanced, the Buses field of the selection). The selection does not change. Another case empties them.

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

## Phase 13: Dynamic simulation in the app

**Goal (decision 15).** See the dynamic simulation's curves and statistics in a Dynamics tab of the results panel, read from the channel file the ANDES script already writes, and write the Plotly HTML report only when the Run form's "HTML file" box is ticked (unticked by default).

**Read first:**
- **Decisions:** 13 and 15, and "Look".
- `runners/andes_scripts/dynamic.py`: the command line (`NO_OPEN_FLAG`, `file_arguments`), the channel DataFrame and its file `output_andes_<now>.csv.gz`, `write_frequency_stats_json`, and what follows "Stability metrics and report".
- `runners/andes_scripts/report.py`: `write_html_report` (what the report plots, its frequency lines), `build_voltage_stats_json` with `calculate_wtvsi`, and `build_frequency_stats_html` with `build_voltage_stats_html` (what its statistics show).
- `runners/islanding_core.jl`: `open_report`, `find_new_report` and the `files` of the settings file.
- `runners/gui/worker.jl`: `find_settings_problems`, `run_from_settings`, `calc_files_summary`.
- `runners/gui/settings.py`, `pages/run.py` (the Report line and its greying in `_changed`), `components/batch_dialog.py` ("open its report"), `components/results_view.py` (`TAB_LABELS`, `_build_summary`, `_build_files`), `results_index.py` (`build_settings_from_record`), and `pages/compare.py` (`build_frequency_chart`, the one `ui.echart` so far).

**Facts measured on 2026-11-23,** to size the steps:
- **Size.** The ANDES channel file has 3003 samples of every channel (25 s at 1/120 s). ACTIVSg500 has 1522 channels: 500 FREQ, 500 VOLT, 56 POWR, 56 VARS, 205 PLOD and 205 QLOD. Its `csv.gz` is 8.8 MB, against 61 MB for its HTML report; savnw's is 303 KB, against 8.4 MB.
- **Speed.** pandas reads the whole ACTIVSg500 file in 0.44 s.
- **Units.** FREQ is the deviation from 60 Hz in pu, and VOLT is in pu. POWR, VARS, PLOD and QLOD are in pu on the system base: a 772 MW unit reads 7.718. The HTML report plots those four as they are under titles in MW, so its P and Q axes are really in pu.
- **PSS®E** writes its channels as a binary `output_psse_<now>.out`, which the GUI does not read. Its script reads only its three paths and always writes and opens its report (decision 13).
- **Which file is whose.** `output_andes_<now>.csv.gz` and `dynamic_channels_<now>.html` share the script's own stamp `<now>`, which is not the stamp of the run's settings file. The folder is reused by later runs, so `voltage_stats.json` and `frequency_stats.json` only hold its latest run, and the tab cannot take its statistics from them.

**Files:**
- `runners/andes_scripts/dynamic.py`, `runners/islanding_core.jl`
- `runners/gui/worker.jl`, `settings.py`, `results_index.py`, `pages/run.py`, `components/batch_dialog.py`, `components/results_view.py`, `theme.css`
- `runners/gui/dynamics.py` (new): reads a run's channel file and works out what the tab shows, without drawing
- `runners/gui/components/dynamics_view.py` (new): the Dynamics tab
- `CLAUDE.md`

**Steps:**
1. **`--no-html` in the ANDES script.** `dynamic.py` takes `--no-html` beside `--no-open` (`NO_HTML_FLAG`, filtered out of `file_arguments` the same way). With it, the script writes the channel file, `voltage_stats.json`, `frequency_stats.json` and `ufls_shed.json` as before, skips `write_html_report` and the opening, and says so in its output. `--no-html` implies `--no-open`. Without the flag nothing changes.
2. **`run_islanding`.**
   - A keyword `html_report::Bool=true`, so `islanding.jl` and `batch_islanding.jl` keep their report.
   - With `false` and the ANDES simulator, it adds `--no-html` to the command. The PSS®E script never gets the flag.
   - It records `html_report` in the settings file beside `open_report`.
   - It finds the channel file as it finds the report, the newest `output_andes_*.csv.gz` modified at or after the run's start, and records it as `files.channels` (`nothing` for PSS®E and without a simulation). Give `find_new_report` a prefix and a suffix instead of copying it.
3. **Worker.** `html_report` is an optional setting, a Bool when present, and a missing key means `false`, the GUI's default (step 4). The worker passes it to `run_islanding`. `calc_files_summary` adds `channels` from the settings file, so `@@result` and the kept result name it.
4. **Settings and the form.**
   - **`settings.py`:** `"html_report": False` in `DEFAULT_SETTINGS`, and a missing key reads as `false` in `form_values`. So older settings, presets and History loads come in unticked. There is no schema bump: the key is optional, as `open_report` was.
   - **Run form,** Security and simulation, the Report line: two checkboxes, "HTML file" (unticked) and "open when done". "open when done" is off while "HTML file" is unticked, with the tooltip "No HTML report". Both are off without a simulation, and both are off for PSS®E, which always writes and opens its report; the form then sends `true` for both, as it does for `open_report` now.
   - **Batch dialog:** the runs keep the form's `html_report`. "open its report" is off with the same tooltip while it is `false`.
   - **`results_index.build_settings_from_record`** copies `html_report` from a script's record when the record has it.
5. **A run's channel file** (`dynamics.find_channel_file(files)`): `files.channels` when it is there. For results kept before this phase, the name comes from `files.report` (`dynamic_channels_<now>.html` gives `output_andes_<now>.csv.gz`). The file must be in `files.output_path`; otherwise the tab says it is gone.
6. **`dynamics.py`,** which draws nothing:
   - **Reading.** `read_channels(path, kinds)` reads only the columns of the quantities asked for (`usecols`) with pandas. The tab calls it through `nicegui.run.io_bound` under a `theme.Cover` ("Reading the simulation's channels …"), so the event loop is never blocked. Nothing large is kept between reads: a read is fast, and a later view reads again. pandas and numpy are installed for the simulation scripts; they are the phase's only new imports.
   - **Units.** Frequency in Hz (`60 · (1 + FREQ)`), voltage in pu, and P and Q in MW and Mvar. The base MVA is SBASE in the first record of the run's RAW (`files.raw`), or 100 MVA when the RAW is gone.
   - **Channels.** The bus number, name and kV come from each channel's name (`FREQ 3005 [NAME 138.000]`, `POWR 9[NAME 13.800]1`). A bus whose voltage is 0 after the trip was de-energized: the script sets its voltage and its frequency deviation to 0 then. It is left out of the curves and the statistics, and the tab says how many buses that is.
   - **Statistics.**
     - Frequency, from the trip on as in `frequency_stats.json`: the nadir and the peak (Hz, bus, time), how many buses go below 59 and 57 Hz and above 60.5 and 61.8 Hz (the report's thresholds), and the five buses with the largest deviation from 60 Hz. The report takes these over the whole run, so a case that swings before the trip can differ there; the tab follows `frequency_stats.json`.
     - Voltage: `report.build_voltage_stats_json`, imported from `runners/andes_scripts/report.py` by its path, so the tab and `voltage_stats.json` never disagree. It gives the minimum and the maximum (pu, bus, time), the buses outside 0.9–1.1 pu, the five with the largest violation, and WTVSI with its top buses. Give it the PLOD channels' buses as `load_buses` (it returns zeros without any), the trip time as `t0` (`frequency_simulation.event_time_s`, or 5 s for results kept before it), and the last sample's time as `t_end`. The script passes `SIM_END_TIME` there, so the two WTVSI agree only for a simulation that did not stop early.
   - **Thinning.** At most `MAX_POINTS` points per curve (about 600). They are chosen so that each stretch of time keeps its lowest and its highest value, so a nadir or a peak is never cut off. At most `MAX_CURVES` curves are drawn at once (about 60). Check whether ECharts' own `sampling` thins before or after the data crosses the websocket; if after, it does not replace this.
   - **Chart options** (`build_chart`), built as `compare.py` builds its charts:
     - time on x, with a line at the trip;
     - on the frequency chart, the report's lines: 57 and 61.8 Hz in red, 59 and 60.5 Hz in amber, and the UFLS stages 59.5, 59.3 and 59.1 Hz dotted;
     - on the voltage chart, the 0.9–1.1 pu band;
     - no legend: a curve's tooltip names its bus and the bus's name, and the hovered curve comes forward.
7. **The Dynamics tab** (`components/dynamics_view.py`), after Voltage in `TAB_LABELS`:
   - **Controls on one line:**
     - Quantity, a `ui.select` of frequency, voltage, generator P, generator Q, load P and load Q;
     - Where: all buses, or, with a target zone or area, "zone X" and "outside zone X" from `summary["target"]`;
     - Buses, a text field read by `advanced.where.parse_buses`, in the format the Network page's Picked Buses gives.
   - **Which curves.**
     - Without Buses: the curves of the chosen side, those that move most first, up to `MAX_CURVES`, with a line saying how many are not drawn.
     - Voltage shows only the buses that leave 0.9–1.1 pu, as the report does, unless the checkbox "all buses" is ticked.
     - With Buses: exactly those buses. A number with no channel of that quantity is named in a line.
   - **Statistics.** Beside the frequency and the voltage charts, as `theme.facts` and a `theme.data_table`, as the report shows them under its charts. The P and Q charts have none.
   - **A sentence in place of the chart** when:
     - the simulation is still running (the run's first `@@result`), with the turning ring;
     - the run used PSS®E, with Open report;
     - a run kept before this phase has no report to take the name from, or the channel file is gone, with Open report when there is a report.

     The tab is hidden when the run had no simulation.
   - **Keeping state.** The tab reads again when it shows another run, and keeps the controls' choices across runs. It keeps what did not change when it is read again ("Look").
8. **Where a report was taken for granted.** With `files.report` null on an ANDES run whose `html_report` was `false`:
   - the Summary's Report fact says "not written (HTML file unticked)";
   - the line shown during the simulation does not say the report comes when it ends;
   - Open report stays off in the results panel, the runs table and History, as it already does for a null report;
   - History's "Only with a report" leaves the run out.

   The Files tab lists the channel file as "Channels".
9. **Contracts and `CLAUDE.md`.**
   - **Contracts:** `html_report` goes into "Settings schema v1", `html_report` and `files.channels` into "Per-run settings file", and `files.channels` into "Result summary". The Run page layout sketch gets the Dynamics tab.
   - **`CLAUDE.md`:** the Julia ↔ Python contract gets `--no-html` and `files.channels`, and the GUI paragraph gets the Dynamics tab and the HTML box.

**Done when:**
- **Numbers.** On fresh ANDES runs of savnw and ACTIVSg500 with frequency and voltage security, the tab's voltage statistics and WTVSI equal that run's `voltage_stats.json`. Its frequency nadir and peak equal the extremes of `frequency_stats.json` over the same buses.
- **Curves.** One bus's curves in the tab match the same channels in the HTML report of a run with the box ticked: frequency in Hz, and P and Q at the report's values times the base MVA.
- **A reused folder.** In a folder with two runs, Load into Run of the older run shows its own curves, not the newer run's.
- **An older run.** A run kept before this phase shows its curves through the name of its report.
- **The box.**
  - A GUI run with the box unticked writes no HTML and records `html_report: false`. Its report buttons are off, and "Only with a report" leaves it out.
  - Ticked, the run writes and opens its report as before.
  - A preset from before this phase comes in unticked.
  - An `islanding.jl` run (temporary copy, `gui_test_ref`) still writes and opens its HTML.
- **Speed.** On ACTIVSg500 the tab draws within about two seconds of being shown, a change of quantity stays responsive, and the page does not lag with the curves on show.
- **PSS®E.** The tab shows its sentence, and Open report opens the PSS®E report.

**Out of scope:**
- the curves of several runs on the Compare page (phase 14);
- the HTML report's P and Q axes, which are in pu under MW titles (in `report.py`; ask the user);
- statistics the report does not show;
- PSS®E's `.out` channels.

## Phase 14: Compare: curves of several runs

**Goal.** The dynamic response of the runs on the Compare page on one chart, so the trade-off of "How much preparation is enough" shows in the curves and not only in the nadir.

**Read first:** phase 13's notes and `dynamics.py`; `comparison.py` and `pages/compare.py`.

**Files:** `runners/gui/comparison.py`, `pages/compare.py`, `dynamics.py`, `theme.css`.

**Steps:**
1. **A section "Dynamic response"** under the trade-off charts, with two controls:
   - Quantity, a toggle of frequency and voltage;
   - What: a bus number, or the extreme of a side when the runs share a target ("lowest in zone X", "lowest outside zone X"; for the frequency of a side that exports, the highest). The extreme is taken over the side's buses at each moment, so the lowest point of the "lowest in zone X" curve is that side's simulated nadir.
2. **One curve per run,** in the colours of `GROUP_COLORS`, named as the run's column and listed in a legend, for at most eight runs. Runs that cannot be drawn are listed under the chart with the reason: another case, no channel file (PSS®E, no simulation, an older run without a report), no channel for that bus, or a ninth run and later.
3. **Reading.** Each run's channel file is read through `dynamics.read_channels` in `run.io_bound`, one run after another, under a Cover that says which run it reads. It is read again when the runs or the choice change.

**Done when:**
- Four runs of an ACTIVSg500 batch (paired penalties) show their target side's frequency on one chart.
- The lowest point of each curve equals that run's simulated nadir in the Frequency rows.
- A PSS®E run and a run of another case are listed as not drawn.

**Out of scope:** the P and Q of generators and loads, and rows of statistics from the channels on the Compare page; ask the user.

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

**Phase 10 (2026-11-21), after phase 11 at the user's request; the History tab comes after Network, as the user asked.**

*What changed:*
- **`results_index.py` (new),** which draws nothing:
  - **Rows.** One per settings file, and one per report that no settings file of its folder names (an older run). Older rows take their case, objective and tag from the folder's name (the longest case folder under `cases/psse` that starts it), and their simulator from the files written beside the report with the same stamp (`output_andes_*`, `output_psse_*`); every one of the 159 reports has such a file. Their time is when the report was written.
  - **`run_info.json`** is rewritten by every run of a folder, before its simulation, so it is shown only with the newest older row, and only when it was written no more than 30 minutes before that report and no settings file of the folder is newer. Three older rows get it, and the details say where those values come from.
  - **`filter_rows`, `find_choices`, `find_group_choices`;** zone and area names are matched whatever their case ("spartanb" and "Spartanb" are one choice).
  - **`build_settings_from_record`** for a record without `gui_settings` (a script's run). The boundary is the target zone or area, or the bus pairs of the target lines (parallel circuits once). Penalties become bus rows in multiples of λ for the buses with a load only: a penalty on a bus without a load changes nothing, and the form offers only buses with a load, so such a row would have stayed empty and blocked Run. The note that comes with it says how many were left out, and that network changes made by a script are not recorded.
- **`components/sortable_table.py` and `.js` (new):** one element for the whole table, sorted in the browser by a click on a column title (again for the other way, rows without a value last), a row chosen by a click or the arrow keys. It has the look of `theme.data_table`, with the column titles staying in view. 270 rows as separate NiceGUI elements would have been some 3000 elements.
- **`pages/history.py` (new).**
  - **Filters:** folder or tag, case, objective, zone or area, simulation, status, a date range (the browser's own date fields, not Quasar's Material date picker) and "Only with a report", with Clear.
  - **The table:** time, case, objective, tag, boundary, λ, penalties, shed, simulation, security, status and report. The folder is in the details.
  - **The details** of the selected run: times, folder, case, objective, boundary with its branches, λ, penalties, modifications, security, simulation, solver, objective value, shed, voltage security, and the run's files. Buttons: Open report, Open folder, Load into Run (not for older rows).
  - **Statuses:** finished, incomplete (a settings file still "started": failed, stopped, or running outside this GUI), running (this session's run in progress, matched by its folder and start time), and no settings (older rows).
  - **When it reads the folder:** when the page is built (0.06 s for 270 runs, and Julia is not asked), on Refresh, and when a run of this session starts, reaches a stage or ends. So a run of the GUI appears by itself; a script's run needs Refresh.
- **`pages/run.py`:** `client_state()["load_settings"]`; `RunForm._find_case_info` is now `find_case_info`, because History reads the case's loads through it. **`app.py`:** `PAGES = [run, network, history]`.

*How it was verified.*
- **The records first:** all 112 GUI settings on disk go through `form_values` and `validate` without an error. Four hold the generators entry of the first version (`pmin_zero`).
- **Counts:** every filter against counts worked out from the files without `results_index` (270 runs: 124 finished, 5 incomplete, 141 older, 159 with a report, 87 on savnw, 130 with "gui_test", 46 on 2026-11-21). The zone filter "spartanb" shows 56 where that count gives 54: the two more are the older rows whose `run_info.json` names spartanb, which the separate count does not read.
- **The three runs of "Done when":**
  - **The script run:** a temporary copy of `islanding.jl` (tag `gui_test_hist_ref`, no simulation) gave 12140.983057017995 and appeared with zone spartanb, 85 buses at 2.5 λ and 407.43 MW of shed. The copy was deleted and `runners/` holds its own files only.
  - **GUI run 1:** Load into Run of the GUI run `gui_test_net_spartanb` (ACTIVSg500, zone Spartanb at 2.5 λ, loads × 0.7), then Run with a new tag. It gave 8519.135912744756, and its `gui_settings` equal the source's apart from the tag.
  - **GUI run 2:** Load into Run of the script run above gave 35 bus rows (50 buses without a load left out, said in the notification), the zone as the boundary, and after Run 12140.983057017995 with 407.43 MW of shed: the script's result. Its target lines are the script's, and its 35 penalties are the script's values for those buses.
  - **All three** appeared in History with the right settings, the two GUI runs without a Refresh.
- **On savnw:**
  - **A GUI run** (`gui_test_net_form`, four bus pairs) loaded and run again gave 30642.40499516773 with the same settings.
  - **A script run by bus pairs** (`gui_test_ref_ns`, whose script scaled four loads by 1.6) opened the same five branches (5, 6, 7, 11 and 26) and gave 30642.40499516773, the plain four-pair result instead of its own 45070.19441721722. The scaling was never recorded, as the details panel and the notification say.
- **Every script record** (13, by zone, area and bus pairs) converts and passes `validate`; no record has uniform shedding, so that conversion was checked on a made-up record (0.01 λ from 5 at λ 500).
- **Open report and Open folder:** the test instance was started through a wrapper that wrote down what would be opened instead of opening it. A new run's report, an older run's report and a folder gave the right paths.
- **States:** a run in progress showed as running in History one second after its row appeared and turned incomplete after Stop. A loaded record with `pmin_zero` was refused by Run with "Advanced, generators: the generators of area FLAPCO need a Pmin or a Pmax".
- **Filters by objective and simulation:** 12 opf runs and 39 ANDES runs, as counted from the files.
- **Table:** sorting both ways, values missing last, the sorting kept through Refresh, the arrow keys moving the selection with the details. At 1500 × 900 the table fits; at 1100 × 700 it scrolls sideways by 352 px.

*Choices the user can reverse:*
- **A script's penalties come back as one bus row each** (35 for Spartanb). One zone row would need the zone of each bus, which `case_info` does not give; with that added, the rows could be folded into a zone row when they are exactly the zone's load buses at one value.
- **Older runs are the reports only.** Runs from before the settings files that wrote no report (only an Excel file) do not show: the folders without settings files hold 334 PowerModels Excel files against 141 reports, so roughly 190 such runs.
- **The table shows the tag, not the folder,** since the folder is the case, the objective and the tag. The text filter searches both.
- **History reads the folder by itself** when a run of this session starts, reaches a stage or ends (the plan asked for a Refresh button only).

*Not done:* comparing runs side by side (out of scope), deleting runs (the user deletes folders by hand), the values of earlier sessions' runs on the Network page (it would need a run's `network` part, which only runs of the session have).

*For the user:* most rows are test runs: 130 of 270 have "gui_test" in their folder. The text filter finds them, and the folders can be deleted by hand.

Test folders added: `ACTIVSg500_flow_shed_gui_test_hist_ref` (the `islanding.jl` copy), `ACTIVSg500_flow_shed_gui_test_hist_gui`, `ACTIVSg500_flow_shed_gui_test_hist_script`, `ACTIVSg500_flow_shed_gui_test_hist_stop2` (stopped, so incomplete), `savnw_flow_shed_gui_test_hist_stop` (it finished before Stop) and `savnw_flow_shed_gui_test_hist_ns`.

**Polish (2026-11-21), at the user's request, between phases:** "make the gui more pleasant to use, no glitches, nowhere without waiting indicator". Not a numbered phase.

*What was wrong:* every question to Julia (the case list, a case's information, a network) waited without a sign, or with a small grey line, and a question asked during a run waited for the whole run. Timed on a fresh Julia: 6 s to start, about 9 s for the first case, 17 s for the first network. Meanwhile:
- the Network page kept drawing the old case under the new case's name, with its selection still active;
- the Run form offered the old case's zones under the new case, and what was typed during the first load was overwritten when the case came;
- a read that a Stop cut off ended as a red "Julia did not answer" that blocked Run until the case was chosen again;
- the "reading the case..." line could stay up for good after a refused Load into Run or Use as target;
- Run was off whenever Julia answered any question (17 s for a network), with no reason given.

*What changed:*
- **`theme.py` / `theme.css`:**
  - `button(..., busy=True)` (`busy_handler`): the button turns into a ring after 0.2 s and ignores clicks until its work is done;
  - `Cover`: a veil with a ring and a sentence;
  - `grey_out`: greyed controls that take no clicks;
  - `show_hint(..., waiting=True)`: a ring before the text;
  - the whole page greys out under NiceGUI's "Connection lost" note when the app is closed.
- **`julia_worker.py`:** each job's type (`job_types`, `current_type()`) and the types answered since Julia started (`answered_types`). With them, the Julia pill says what Julia is doing ("Julia busy · placing a network", "· reading a case"), and the Network cover warns that the first network after a start takes about 20 s.
- **Run page:**
  - While the form waits, the hint under the case says for what, in one line: "waiting for Julia to start...", "reading the case list...", "reading savnw...", "waiting for run 2 to end...". The rest of the form is greyed, and Run is off with the reason in its tooltip.
  - The case being read shows in the case field at once.
  - Run is no longer off while Julia answers a question of another page: the run waits behind it, and the status strip says so.
  - A read that a Stop or a Restart cut off is made again when Julia is ready (`RunForm.retry`), so the form fills itself.
  - `write` returns whether the settings went in.
  - The penalty rows are no longer rebuilt at every toggle (35 rows from a script record stayed in place through AC, DC and back).
  - Stop, Load settings and the case list's refresh are busy buttons.
  - The table of the session's runs is rebuilt only when what it shows of a run changes (status, error, time, files), not at each stage of a run, so a click on it is not lost.
- **Network page:**
  - A cover over the drawing while a network comes, saying what for. The choices of what to show and the selection are greyed; "How to use" stays readable.
  - Before the first network, only the field of the selection mode shows.
  - A network cut off by a Stop is asked again when Julia is back.
  - Use as target and Set penalty are busy buttons, with a note when the Run form will get the boundary only after a run.
- **History page:**
  - Load into Run shows the Run page first, so the form says what it waits for. It has no ring: a newer Load into Run replaces one that still waits for Julia (`load_request`).
  - Refresh is a busy button, and the count line says when the folders were read.
  - The details of the selected run are not rebuilt when a reading of the folders did not change them, so they no longer flicker at each stage of a run.
  - A settings file that cannot be read is counted in the singular or the plural, with its name and why in a tooltip. One was found: a run stopped by Stop while Julia was writing its first settings file left it empty (`ACTIVSg500_flow_shed_gui_test_polish_a`). That is how `run_islanding` writes the file, not new.

*How it was verified* (a test instance on port 8090 with `PYTHONASYNCIODEBUG=1`, a headless Chrome that recorded the page's errors, savnw and ACTIVSg500):
- **First load on a fresh Julia:** "waiting for Julia to start..." → "reading the case list..." → "reading ACTIVSg500..." with the rest greyed and Run off, then the form.
- **First Network page:** the cover with the 20 s note, then the drawing.
- **During a run** (the `gui_test_results_both` settings): the Run form on savnw said "waiting for run 1 to end...", the Network page on IEEE39 covered the old drawing with "Julia is busy with run 1...", and Run's tooltip gave the reason.
- **Stop during the run:** both reads were made again by themselves once Julia was back. savnw was in the form 12 s after Stop, and IEEE39 was drawn 10 s later.
- **Clicks during a run:** two Load into Run clicks during a run (a savnw script run, then a case9 GUI run, neither case read yet) gave the case9 settings in the end, with one note.
- **Run while Julia answers another page's question:** Run queued behind the Network page's first network and finished with 30642.40499516773 on savnw. The same on ACTIVSg500 gave 21778.720894025806, as the earlier runs with those settings did.
- **Run while Julia starts:** Run, pressed after a Stop while the pill said "Julia starting", queued and finished with 30642.40499516773.
- **Network to Run on savnw:** a zone and a set of buses as the target, and penalties for buses and for a zone, each arrived in the Run form.
- **The button ring:** during a run, Use as target on IEEE39 turned into a ring of the button's own width, with the note that the form gets it after the run.
- **Stop during a read:** a case9 Load into Run cut off by a Stop filled the form by itself once Julia was back.
- **Refresh:** History's Refresh kept the details element and changed the time read.
- **Runs:** two runs loaded from History ran to the end with the results of their sources: savnw `gui_test_hist_stop` → 30642.40499516773, and ACTIVSg500 `gui_test_net_spartanb` → 8519.135912744756, with equal settings apart from the tag.
- **Errors and stalls:** no Python traceback and no browser error in any scenario. Slow event-loop callbacks were at most 0.12 s (the worker's output reader when a run's result arrives, and the page build), so nothing was moved off the loop.

*Not changed:*
- **The first network takes about 17 s on a fresh Julia.** That is Julia compiling the layout and the cover now says so; precompiling it at the worker's start would be a change to `worker.jl`.
- **Open report and Open folder have no ring:** they return at once and the browser or the explorer shows the result.
- **Busy buttons stay locked for a run:** Use as target and Set penalty on a case not read yet wait for a run in progress to end. They show their ring and the note says why.

Test folders added:
- ACTIVSg500: `ACTIVSg500_flow_shed_gui_test_polish_long`, `_long2`, `_a` (stopped, with the empty settings file: History counts it as unreadable until the folder is deleted), `_500`, `_q1`, `_q7` and `_q8` (both stopped);
- savnw: `savnw_flow_shed_gui_test_polish_savnw`, `_q1`, `_q2`, `_q4`, `_q5` and `_q6`;
- IEEE39: `IEEE39_flow_shed_gui_test_polish_q3`.

**Phase 12 (2026-11-21), at the user's request ("go for the last phase and give me some presets").**

*What changed:*
- **`presets.py` (new),** which draws nothing: reading a preset file, the name rules, the file name of a name, writing, and `PresetStore` (`ctx.presets`), which reads the folder when the app starts and when a browser tab opens, and tells every tab after a save or a delete.
- **`components/preset_bar.py` (new),** in the settings toolbar, right of the fold:
  - **Preset:** a list of the presets. Choosing one puts its settings into the form, through `RunForm.write`, so the case is read as for any other load, and unfolds the sheet. A note says so, with the preset's note.
  - **Note:** while the sheet is open, the preset's note stands in the toolbar's text, which was empty there.
  - **"changed" with Reload:** shows while the form differs from what it held right after the preset went in. That is checked once a second while a preset is chosen, not while the form waits for Julia. Reload puts the preset back.
  - **Save as:** a dialog with the name and a note, starting from the chosen preset's. It becomes Replace for a name that exists. A name that cannot be used says why, and settings that cannot run say so and are not saved. It is off while the form waits for Julia.
  - **Delete:** a dialog that names the file to delete. It deletes only a listed preset's own file.
  - **Refused choices:** a preset that cannot be read, a preset whose case is not in `cases/psse`, and any choice before the case list is there are refused with a note.
- **`pages/run.py`:** the bar in the toolbar, its Save as following the form's wait (`update_buttons`), and the toolbar text showing the preset's note while the sheet is open. **`app.py`:** `ctx.presets`. **`theme.css`:** the bar, and `.dialog.narrow` and `.dialog-form` for small dialogs.
- **Notifications let clicks through** (`.q-notification`, `pointer-events: none`). Two notes stacked at the top covered the settings toolbar, and a click on Save as under them did nothing. That was there since phase 6, and more notes made it seen. They had no buttons of their own.
- **Eight starter presets in `presets/`,** transcribed from the notes in `islanding.jl` as phase 9 did (`make_refs.py`): the scenario's own lines (its bus pairs or zone, its load changes), without the commented penalty dictionary of the savnw notes, which no scenario names as its own.
  - savnw: island on top (load 6 at 400 MW), island on left (load 8 at 100 MW), island on bottom with one load (load 5 at 500 MW), island on bottom with two loads (load 5 at 800 MW, load 4 at 250 MW), north-south separation (loads at 3005, 3007, 3008 and 153 × 1.6);
  - ACTIVSg500: SPARTANB at 2.5 λ (`islanding.jl` as it is), SPARTANB with the zone's loads × 0.7, and SPARTANB with the zone's generators' Pmin at 0 MW.
  - Each has the dynamic simulation with ANDES, as `islanding.jl` does, and an output tag of its own (`top_island`, `left_island`, `bottom_island_one_load`, `bottom_island_two_loads`, `north_south`, `spartanb`, `spartanb_loads_0.7`, `spartanb_pmin_0`), so their results do not overwrite each other or the untagged folders.

*How it was verified* (a test instance on port 8090 in a headless Chrome):
- **Files:** all eight pass `validate`, and `build_settings(form_values(settings))` gives them back unchanged.
- **References:** three were made for this phase from temporary copies of `islanding.jl` (deleted after), with tags `gui_test_ref_left`, `gui_test_ref_bottom1` and `gui_test_ref_bottom2`. Phases 9 and 10 had made the other five.
- **Each preset run as shipped,** only its tag changed to `gui_test_preset_<file>` and read back before Run. Each gave its reference's objective to the last digit and the same opened lines, the run's `gui_settings` were the file's apart from the tag, and the ANDES simulation wrote its report:
  - savnw: top 9431.510209057029, left 642.2939110795945, bottom with one load 13419.06232523263, bottom with two loads 7486.733982225898, north-south 45070.19441721722;
  - ACTIVSg500: SPARTANB 12140.983057017995, loads × 0.7 8519.135912744756, Pmin 0 12140.983056999981.
- **A saved preset reloads exactly:**
  - A hand-made preset with every kind of setting (an area boundary, an area and a bus penalty, "All other loads", load scaling, a load and a generators row, a `gui_test` tag) went into the form and was saved with Save as under a new name. Its file held the same settings.
  - After another preset and back, it ran (3787.2016747635994), with `gui_settings` equal to the file, tag included.
  - Save as on the same name became Replace and wrote the same file. Delete removed both test presets through its dialog.
- **The rest:**
  - a bad name ("a/b") turned Save off with the reason;
  - an unreadable file was listed as such and refused;
  - "changed" showed after a change of the tag and went with Reload;
  - Save as was off while the form waited for a run to end;
  - at 1100 px the toolbar fits without scrolling, with a long name cut by "...", and folded it shows the settings' line;
  - under two stacked notes, Save as, Delete, Run and Stop each took the click (`elementFromPoint`), and Save as opened at the first click.

*Choices the user can reverse:*
- **Output tags in the starter presets;** an empty tag writes to the untagged folders, as `islanding.jl` does.
- **No penalties in the savnw presets;** the notes' dictionary (3005 at 1e4, 3007 at 0.2 λ, 3008 at 2 λ, 153 at 0.5 λ, 205 at 5.8 λ, 203 at 0.9 λ, 154 at 4.9 λ) can be added to any of them in the form and saved with Replace.
- **Left out of the notes:**
  - the single-bus islands at 202 and 3004;
  - the other ACTIVSg500 penalty values (MIDLANDS 0.95, CLEMSON 1.6, YORK 2.5);
  - GREENVIL × 0.1.

  Each is a preset away: set it in the form and Save as.

*Not done:*
- **Renaming a preset.** Save as under the new name, then Delete the old one.
- **An unreadable preset** cannot be chosen, so not deleted in the GUI; its file goes by hand.
- **Not seen:** a second browser tab hearing of a save. The same listener updates the list of the tab that saves, which was seen.

Test folders added:
- savnw: `savnw_flow_shed_gui_test_ref_left`, `_ref_bottom1`, `_ref_bottom2`, `savnw_flow_shed_gui_test_preset_savnw_island_on_top`, `_on_left`, `_on_bottom_one_load`, `_on_bottom_two_loads`, `_north_south_separation`, `savnw_flow_shed_gui_test_preset_saved` and `savnw_flow_shed_gui_test_preset_wait`;
- ACTIVSg500: `ACTIVSg500_flow_shed_gui_test_preset_activsg500_spartanb`, `_loads_0_7` and `_generators_pmin_0`.

**What the strip says during a run (2026-11-21), at the user's request, between phases.** The user saw "now" stay on "Adding Load Shedding Penalties" and then on "Adjusting branch 426 direction from 493 to 380" for many seconds each, and a user could think that adding penalties was what took long.

*What was wrong:* "now" showed the latest log line, and the slow steps print nothing while they work. The penalties line is printed in Prepare, and stayed while the Solve stage built the optimization model (with Julia compiling it on a fresh worker). The "Adjusting branch" lines were printed at the end of the build, one per boundary line read from its other end, and the last one stayed while Ipopt ran, because Ipopt at `print_level` 4 prints no line per iteration.

*What changed:*
- **Notes inside the solve stage** (`@@activity`, see "Stages"). `run_islanding` takes an `activity` callback and reports "building the optimization model" before the solve. `solve_voltage_secure_opf` reports each part of a round (its build, "checking the islands' voltage", each island's power flow and indicators, each shed it sizes), with the round in front: "voltage round 2: ...". The worker sends each note as `@@activity`.
- **Ipopt's iterations.** `build_ipopt_reporter` (`islanding_core.jl`) makes Ipopt's intermediate callback report "solving with Ipopt, iteration 37, constraint violation 3.2e-5", the first iteration of each solve at once and then at most every 0.5 s. It continues the latest step, so in a voltage round the round stays in front. The callback has to be set on the JuMP model once its optimizer is attached, because JuMP empties the optimizer before the solve and that clears a callback set earlier. That is why `solve_custom_opf` now takes an optional `before_solve(model)`. Without it, the function is still plain `solve_model`, so `islanding.jl` and `batch_islanding.jl` solve exactly as before and print as before.
- **The "Adjusting branch" line is gone** (`src/core/objective.jl`). It was debugging output, and it was misleading: nothing about the branch changes, the flow is only read at its end inside the target group. A comment in the code says so now.
- **The strip's second row** (`status_strip.py`):
  - "now" shows Julia's latest note for the stage, or else a sentence on what the stage does (`STAGE_ACTIVITIES`). Prepare's sentence names its parts, the results folder too, without putting the penalties first.
  - Once a note is 3 s old or more (`STALE_SECONDS`), its age follows it ("· 12 s").
  - On the first run since Julia started (no "run" in `worker.answered_types`), a note or sentence that is 3 s old also says "(first run: Julia compiles as it goes)". This is left out in the dynamic simulation, which runs outside Julia. On a fresh Julia, Prepare took 14 s, the first build 20 s, Ipopt's iteration 0 about 6 s, the first island power flow 4 s and the Excel report 4 s, all of it compiling. On a warm Julia the same run's Prepare is instant and its whole solve takes about 18 s.
  - The latest log line is no longer shown. It first came after "now" as "last output 12 s ago: ...", in grey, and the user had it removed: "now" says what the run does, and Full log has the lines. The record no longer keeps the latest line either (`last_line` is gone from `session_runs.py`), since nothing else read it.
  - A failed run shows its error in red across the row, as before, and a finished one its end time.
- **`session_runs.py`.** A record also keeps `activity` and `activity_at`, which are emptied at each `@@stage`. A note changes the record quietly, as a log line does, so the runs table and History are not refreshed twice a second.
- **`julia_worker.py`.** An empty line waits for the next line and is dropped when that line is a control line (see "Rules on the GUI side"). Without that, each of Ipopt's notes would have put an empty line into Full log.

*How it was verified:*
- **The worker** (`dev/send_jobs.py`): three runs gave their references to the last digit. These were savnw with four bus pairs (30642.40499516773), ACTIVSg500 SPARTANB (12140.983057017995) and ACTIVSg500 SPARTANB with voltage security (21729.825010181525, verified in 5 rounds, as `gui_test_results_volt5`). The notes came in order, and each round's Ipopt notes restarted at iteration 0. No "Adjusting branch" line was left.
- **The script path:** `run_islanding` called as `islanding.jl` calls it, without `activity`, gave 30642.40499516773 with Ipopt's console output as before and no notes.
- **DC:** savnw with four bus pairs gave 20879.980806582655 through the worker (with its notes) and through the script path.
- **The GUI** (a test instance on port 8090 in a headless Chrome, a temporary preset deleted afterwards, the voltage security run above, on a fresh Julia). The strip was read every second:
  - Prepare showed its sentence (with "last output 9 s ago: === Adding Load Shedding Penalties ===" beside it, before the log line was removed).
  - Solve showed "voltage round 1: building the optimization model · 12 s" while Julia compiled, then "voltage round 1: solving with Ipopt, iteration 0, constraint violation 2.7", iteration 22, the island checks and the sheds, and rounds 2 to 5 in the same way.
  - After that came Reports, "writing the Excel report", Summary and "at 13:41:17".
  - The run gave 21729.825010181525.
  - Full log had 295 lines, and its 32 empty lines were all Ipopt's own.
  - A failing run (savnw, bus pair 1-2) showed "no boundary line found for bus pairs 1-2" in red, across the row.
  - The same run again at 1100 px on a fresh Julia showed the first-run hint in each slow step listed above and none in the fast ones, and gave 21729.825010181525. The row fits; a note that is too long ends in "…", with the whole text in its tooltip. After that run, the Prepare sentence and the hint were shortened, so "first run" shows at that width. That last text change was not run again.

*Choices the user can reverse:*
- **0.5 s between Ipopt's notes and 3 s before an age shows** are `IPOPT_REPORT_SECONDS` in `islanding_core.jl` and `STALE_SECONDS` in `status_strip.py`.
- **Notes only in the solve stage.** On a warm Julia the other stages take a second or two, or print as they go (the dynamic simulation), and their sentences say what they do. On a fresh Julia each of them is slower once, which the first-run hint says.
- **The age of a note is its own:** Ipopt's note is renewed at each report, so its age stays small while Ipopt works, and the stage's clock gives the whole solve.

Test folders added: `savnw_flow_shed_gui_test_activity_savnw`, `_activity_script`, `_activity_dc`, `_activity_dc_script`, `ACTIVSg500_flow_shed_gui_test_activity_500`, `_activity_volt` and `_activity_gui` (the failing run stops before its folder is made).

**Penalty rows in order, and "all but" rows (2026-11-21), at the user's request, after phase 12:** "add shedding penalties to all loads except the selected zone in a row; the last row's rule should take effect if several rows reach a bus, zone or area".

*What it was:* bus rows always counted over zone and area rows whatever their order, two rows for the same zone or area were refused, and of two rows for the same bus the lower one counted. So "the last row counts" held only for one bus twice.

*What changed:*
- **Settings schema 2 (`settings.py`):** the penalties are one ordered list of `rows` (`{kind, name, except, times_lambda}`) instead of `groups` and `buses`.
  - `upgrade_settings` reads schema 1, its groups first and its buses after, which gives every load the same penalty as before.
  - `describe_penalty_row` describes a row; `validate` checks rows, now allowing two rows for the same place.
- **`worker.jl`:**
  - It takes schema 2 and still schema 1 (`find_penalty_rows`).
  - `calc_shed_penalties` applies `others`, then the rows in order (`find_penalty_row_buses`; an "all but" row reaches every bus outside its group).
- **Run form (`pages/run.py`):**
  - A row's kind is Zone, "All but zone" and Bus, or the same with area. Changing between a zone and all but it keeps the name.
  - A line under the rows says that the lower row counts. The kind column is wider for "All but zone".
- **`RunForm.take`** (the Network page's Set penalty) puts a row at the bottom, where it counts, and takes out an earlier row for the same place.
- **History (`results_index.py`):**
  - It describes rows ("zone Spartanb 2.5 λ, all but zone Spartanb 1.6 λ"), and its zone or area filter finds "all but" rows too.
  - A script run's record becomes bus rows. Schema 1 records are upgraded first, and the 307 runs show the same text as before.
- **Presets (`presets.py`):** schema 1 files are read and upgraded, and schema 2 is written. The eight starter files were rewritten in schema 2, each equal to its old file upgraded. A copy of the old ones is in the session's scratch folder (`p13/presets_before`).

*How it was verified* (test instance on port 8090, headless Chrome, ACTIVSg500 and savnw):
- **Pure:** the 148 GUI records on disk and the eight presets upgrade, pass `validate`, and come back unchanged through the form's values.
- **Order:** a zone row for SPARTANB at 2.5 λ and bus 109 (in the zone) at 5 λ, run in both orders.
  - Bus row last: bus 109 got 2500 (5 λ), objective 12151.983787625044.
  - Bus row first: it got 1250 (2.5 λ), objective 12140.983057017995, the plain SPARTANB result.
  - Before the change the bus row counted both times.
- **"All but":** SPARTANB at 2.5 λ and all but SPARTANB at 1.6 λ gave 9366.082934790202. The reference, a temporary copy of `islanding.jl` with its line for the buses outside the target switched on (deleted after), gave the same, with the same 500 recorded penalties.
- **Old settings:**
  - The schema 1 dev job `dev/job_activsg500_spartanb.json`, sent straight to the worker, gave 12140.983057017995 with the same penalties as the `islanding.jl` reference.
  - The schema 1 record `gui_test_preset_saved` (an area row, a bus row and "others"), loaded from History and run again, gave 3787.2016747635994, the same penalties as before.
- **The GUI:**
  - an "All but zone" row made by hand, saved as a preset (written as `except: true`) and loaded back without "changed";
  - Set penalty for the same zone twice from the Network page left one row, at the bottom;
  - the rows looked at in screenshots at 1500 and 1100 px.

*For the user:* the line of `islanding.jl` for the buses outside the target (`# load_shedding_penalties[bus] = 1.6 * lambda`) is now a row in the form: "All but zone" SPARTANB at 1.6.

Test folders added: `ACTIVSg500_flow_shed_gui_test_ref_except` (the `islanding.jl` copy), `ACTIVSg500_flow_shed_gui_test_rows_bus_last`, `_rows_bus_first`, `_rows_except`, `savnw_flow_shed_gui_test_rows_old`, and a new run in `ACTIVSg500_flow_shed_gui_test` (the dev job).

**UFLS shed beside the preemptive shed (2026-11-21), at the user's request:** "in load shedding tab ... I like to have UFLS sheds next to them (vertical line split the tab); if dynamic simulation is not going to run or there are no records or problems show the proper message at the place".

*What changed:*
- **`andes_scripts/dynamic.py`** writes `ufls_shed.json` into the results folder (`write_ufls_shed_json`): the relay count, how far the simulation ran, whether it stopped early, and each relay stage that acted with its load's power flow P. It is the first file that goes from Python to the GUI. The PSS®E script is frozen, so it writes none.
- **`worker.jl`:** `calc_ufls_summary` adds `ufls` to `@@result` (see **Contracts: Result summary**). It reads the file only for an ANDES run with the simulation on, and only when the file is newer than the run's start (`find_ufls_record`), because the folder is reused. It groups like `load_shed`.
- **Results panel (`results_view.py`):**
  - The Load shedding tab is always there, in two sides with a line between: "Before the event: optimization" and "After the event: UFLS relays".
  - Each side shows its tables, or a sentence in their place: the objective sheds no load; the simulation was off; PSS®E (with Open report); no record; no LDSHBL relays in the .dyr; no relay acted; or, in red above the tables, the simulation stopped early.
  - The Summary tab has a "UFLS shed" fact.
  - The classes `shed-sides`, `shed-side` and `shed-side-title` are in `theme.css`. Under 900 px the sides stack, with a line between them.
- **The % of the UFLS shed.** The relays report MW at 1 pu voltage (P0/V0 of the constant current load), so at savnw bus 205 a 5 % stage is 59.10 MW of 1200 MW. Shed (MW) keeps the reported value, which matches the console and the report. Shed (%) is the share the stages tripped (5.00 %).

*How it was verified* (savnw, area LIGHTCO, ANDES):
- **Through `send_jobs.py`:**
  - The `opf_shed` run shed 73.51 MW in LIGHTCO by UFLS, 59.10 MW at bus 205 and 14.41 MW at bus 203, as the console printed.
  - The `flow` run had 8 relays and no stage acted.
  - With the simulation off, `ufls` was `null`.
  - `flow_shed` with LIGHTCO at 2.5 λ shed 25.88 MW before the event at bus 203. Its UFLS side has 274.12 MW in service there and 3174.12 MW in total, the left side's load less its shed. No relay acted.
  - `opf_shed` at 0.5 λ still shed nothing before the event, so a run with both sides non-zero was not seen.
- **On a test instance (port 8090):** the same three runs, from History's Load into Run. Their tabs show the two sides, 5.00 % at both buses (2.34 % in total), and the sentences for the other cases.
- **Pure functions:** the sentences were checked on hand-made summaries for every status. PSS®E, no record, no relays and the stopped-early line were not seen drawn in the GUI.

Test folders added: `savnw_opf_shed_gui_test_ufls_area`, `savnw_flow_gui_test_ufls_flow`, `savnw_opf_shed_gui_test_ufls_nosim`, `savnw_flow_gui_test_ufls_area` (the GUI's flow run), `savnw_flow_shed_gui_test_ufls_both` and `savnw_opf_shed_gui_test_ufls_low`.

**Results kept and loaded with a run (2026-11-21), at the user's request:** "when we are loading into run (from run list in run page or from history) I want the results to be loaded as well ... we should keep the results as well and load them when loading a run".

*What changed:*
- **`worker.jl`:** `write_result_file!` keeps the `@@result` summary as `result_<timestamp>.json` beside the run's settings file, before sending it, and names it in `files.result` (see **Contracts: Kept results**).
- **`results_index.py`:** a settings row has `result` (the file's name when it is there), and `read_result` reads it on Load into Run only, or says in a sentence why there is none (a script run, a run that did not finish or is running, a run from before).
- **Results panel (`results_view.py`):**
  - `show(record)` shows a run's results. A run loaded from History is a record shaped like a session run (`build_loaded_record`: no `number`, its key `history:<row id>`), kept in the browser tab's `loaded` list, once each.
  - "Results of" lists the session's runs, then the loaded ones ("History · savnw · flow_shed · ... · 2026-11-21 17:31").
  - A session run that delivers results still takes over the panel. The panel shows as soon as there is any run to show, so a fresh app can show a History run.
  - The Files tab lists "Kept results". The voltage Details dialog takes the run's name ("the run of 2026-11-21 17:31").
- **Run page (`pages/run.py`):** the session list's "Load settings" is now "Load", which also shows the run's results. `load_settings` takes the run whose results go with the settings and shows them at once, without waiting for Julia.
- **History (`pages/history.py`):** Load into Run passes the results along, read after the check for a newer click. A run of this session is shown as its session record, not added twice (`find_session_record`). The details list the file and say whether Load into Run shows results.

*How it was verified* (savnw, four bus pairs, frequency and voltage security):
- **Worker:** a `send_jobs.py` run with ANDES (`gui_test_kept`) wrote `result_2026_11_21_17_31_16.json` (10 KB), with frequency, voltage, UFLS and network parts and `files.result` set.
- **Test instance (port 8090), fresh app with no session run:**
  - History → Load into Run of that run filled the form and showed its results: Summary, the Voltage Details dialog titled for that run, and Files with the folder where it is now.
  - A GUI run (`gui_test_kept_gui`, no simulation) kept its own file and took over the panel, with the History run still in the list.
  - The row's Load switched back to run 1. History's Load into Run of run 1's own row selected run 1, with no second entry.
  - An older run (`gui_test_ufls_both`) filled the form with the note that its results were not kept, and the panel stayed on run 1.
- **Pure:** of the 181 settings rows on disk before, none has a file; 155 get "ran before the GUI kept them", 19 "a run from a script", 7 "did not finish".

*Not exercised:* ACTIVSg500; Load into Run of a script run (its sentence was checked through `read_result` only); a results file that cannot be read, and one that cannot be written.

*Not done:* the Network page's "Values of" still offers only the session's runs, not those loaded from History. Script runs keep no results.

Test folders added: `savnw_flow_shed_gui_test_kept`, `savnw_flow_shed_gui_test_kept_gui`.

**UI/UX round (2026-11-21), at the user's request,** from a review of the GUI. The user chose these nine items; each is ticked once it is built and seen working.

- [x] 1. History: a Solver column with each run's solver status.
- [x] 2. History: the From and To dates typed and shown as yyyy-mm-dd.
- [x] 3. Run form: an "open the report when done" box, passed to the ANDES script (a workflow change: `run_islanding` and `andes_scripts/dynamic.py`).
- [x] 4. Header: a Quit button that stops the app and Julia.
- [x] 5. The browser tab's title shows the latest run ("Run 3 finished").
- [x] 6. Penalty rows move up and down.
- [x] 7. Network page: "How to use" behind a "?", and the two hints that repeat its buttons moved into the buttons' tooltips.
- [x] 8. The Run form follows the objective: what the objective does not read is greyed, and one formula line stands under Objective.
- [x] 9. Islands named by the target zone or area, with their size (Summary, Frequency, the voltage details).

*What changed:*
- **Solver column (History).** `results_index` gives each row its `solver` (the record's `termination_status`). History shows it short ("solved", "infeasible", "almost solved", other statuses in lower case), red when the solver did not solve and amber when almost. `sortable_table.js` takes a class per cell (`tones`) for that. To keep the table beside the details at about 1500 px, the wide columns are now 135 px at most (were 150) and the details 310 px (were 330).
- **Dates (History).** A date input shows the system's date form (mm/dd/yyyy here), so From and To are text fields with the mask `####-##-##` and a calendar (`ui.date`, minimal) behind an icon. A date counts once it is a whole day of the calendar (`read_date`), so a half-typed one filters nothing. The calendar is Quasar's: `theme.css` takes off its banner and its shadow.
- **Open the report when done (workflow, asked for).**
  - `run_islanding` has `open_report::Bool=true` and records it in the settings file. With `false` it adds `--no-open` to the `dynamic.py` command.
  - `andes_scripts/dynamic.py` takes `--no-open` after its three paths, writes the report and does not open it, and says so in the log.
  - The PSS®E script is not changed (decision 13): it reads only its three paths and always opens its report.
  - In the GUI the box is `open_report` in the settings, optional with `true` as the default, so older settings, presets and script records still open it. It is under Simulator ("Report: open when done"), greyed for PSS®E and without a simulation, with the reason in its tooltip. While it is greyed the form sends `true`, so a PSS®E run never records a report it did not open.
  - `islanding.jl` and `batch_islanding.jl` keep the default.
- **Quit (header).** A question first: it names a run in progress, which stops without results. Then every open page is replaced by a note ("The Islanding GUI has stopped ... double-click runners/gui/start_gui.bat"), and `app.shutdown()` stops the server, whose `on_shutdown` stops Julia with its children. The app exits with code 0, so `start_gui.bat` closes its window. A page left open reloads itself into the app when it is started again.
- **Tab title.** `app.py` follows the runs in each browser tab: "▶ Run 3 · Solve · Islanding GUI" during a run, then "✓ Run 3 finished", "✕ Run 3 failed" or "■ Run 3 stopped".
- **Penalty rows.** Two small arrows beside each row move it up or down. They are off at the ends, and the order is the order the rows apply in.
- **Network page.** "How to use" is a "?" at the end of the toolbar (`theme.help_mark`). What Use as target and Set penalty would do is in their tooltips. Only "Nothing is selected ..." stays a line, because it guides rather than repeats.
- **The form follows the objective.** A formula line stands under Objective, and its tooltip says what the symbols are. It changes with the flow penalty and the model: DC has no q. The formulas are:
  - `opf`: min generation cost;
  - `flow`: min Σp² + Σq²;
  - `flow_shed`: min λ·(Σp² + Σq²) + Σ c·Pd·(1 − z);
  - `opf_shed`: min generation cost + Σ c·Pd·(1 − z).

  What the objective does not read is dimmed (`OBJECTIVE_READS` in `run.py`, from `objective.jl`):
  - `opf`: λ, the flow penalty and the penalties;
  - `flow`: λ and the penalties;
  - `opf_shed`: the flow penalty. λ stays bright there, as the unit of the penalties.

  Dimmed fields stay editable and keep their values (`theme.dim_unused`, a class of its own, so the waiting grey does not undo it). They are still validated, because the worker still reads the penalties of every run.
- **Island names.** The worker adds `target` (kind, name, buses) to the result summary. `voltage_details.name_islands` names each island by its side: "zone SECOND", "outside zone SECOND", or with its bus when a side has more than one island. This shows in the Summary (with "(7 buses)"), the Frequency table (column "Island") and the four tables of the voltage details. A bus-pair run, and results kept before, keep "island at bus N". The rows keep the island's bus (`island_bus`, `island`), which `dev/check_results_tables.py` now compares directly.

*How it was verified* (a test instance on port 8090; the user's GUI on 8080 untouched):
- **Pure functions:** the formulas for each objective, flow penalty and model; names for one and two islands on a side and without a target; solver labels and tones; whole and half-typed dates; `open_report` missing from older settings.
- **One run:** savnw, `flow_shed`, zone SECOND, frequency and voltage security, ANDES, the box off, tag `gui_test_uiux`.
  - The log says "Interactive Plotly page written (not opened, --no-open)", and no report opened.
  - The settings file has `open_report: false` and the two penalty rows in the order they were moved to.
  - The kept result has `target` with the zone's seven buses.
  - The Summary, the Frequency table and every voltage table show "zone SECOND" and "outside zone SECOND".
  - The tab's title went "▶ Run 1 · starting", "▶ Run 1 · Load case", then "✓ Run 1 finished".
- **Form:** each objective dims what it should, and the formula follows the flow penalty and DC. The box greys for PSS®E with its tooltip. The arrows are off at the ends, and a row moves with its values.
- **History:** "solved" on every run, and "infeasible" in red on `ACTIVSg500_opf_gui_test_results_opf`. The table no longer scrolls sideways at about 1490 px, the one width measured (it overflowed by 45 px with the new column, and 50 px were freed). "20261121" typed becomes 2026-11-21 and filters to that day. A day picked in the calendar fills the field and closes it.
- **Network:** the "?" tooltip, and both button tooltips for zone SECOND.
- **Quit:** with two tabs open, both showed the note and "Islanding GUI (stopped)". The app exited with code 0, and its Julia worker was gone.

- **Console:** the test instances' output had no traceback; listeners and handlers that fail print there and not on the page.

*Not exercised:*
- `dev/check_results_tables.py` on a fresh `send_jobs.py --full` log (only its frequency part changed, and it was read, not run).
- ACTIVSg500, an area target, and a bus-pair run with frequency security.
- An island side with two islands, seen only in the pure check.
- Quit while a run is in progress (the question says the run stops too).
- A script run through `islanding.jl` on the default `open_report`.

*Left as it is:* the strip's notes during voltage rounds and the console reports still say "the island at bus 3001". They come from `voltage.jl` and `frequency.jl`, so naming them by the target would need the target passed in and a recompile; that was not asked.

*Seen once and not explained:* right after `flow` and DC were chosen, λ's field looked undimmed while its label was dimmed. On the next look both were dimmed. It may have been the 0.15 s fade.

**Results panel round (2026-11-21), at the user's request.** Each item is ticked once it is built and seen working.

- [x] 1. Results panel: a Clear button after the "Results of" list.
- [x] 2. Results panel: cleared when a new run starts.
- [x] 3. Results shown as soon as they are ready, before the dynamic simulation (the worker sends a first `@@result` before it).
- [x] 4. Boundary flows tab: the total rows at the top of the table.
- [x] 5. Frequency tab: the predicted nadir, and the actual nadir after the dynamic simulation (the ANDES script writes it).

*What changed:*
- **Clear.** A small button after the list. It empties the panel ("Cleared. Choose a run in the list to see its results again.") and is off while the panel is empty. The runs stay in the list. Choosing one, Load (runs table or History) or a new run brings the panel back.
- **A new run takes the panel.** The list now has every run of the session, not only those with results. A run that starts is put on show at once, so the results on show go. Until it is solved the panel says "Run N is running …". A run that ended without results says why ("failed before it was solved", with the error, or "was stopped"). The list names a run's status when it did not finish.
- **Results before the simulation.**
  - `run_islanding` has `on_solved(result, solve_seconds)`, called after the console reports. The worker (`run_from_settings`' `solved`, `send_partial_summary`) sends the summary from there with `"partial": true` (see "Result summary").
  - `session_runs` keeps `partial`. The panel draws a run again when its summary or its status changes (`find_version`), and keeps the tab on show.
  - While the run is in its simulation, a line over the tabs says the simulation's parts come when it ends. "Dynamic simulation" reads "running...", the UFLS shed "after the dynamic simulation", the Report "written when the simulation ends", and the UFLS side and the nadir table say the same with a turning ring.
  - A run that fails or is stopped during the simulation keeps the results of its solve, with a red line saying so.
- **Totals on top.** `theme.data_table(..., totals_on_top=True)` puts the totals under the column titles, with a firmer line under them. Only the boundary flows use it, as asked.
- **Nadir.** The Frequency tab has a second table, "Frequency when the lines open". It has a row per island: nadir or peak, the limit, the predicted and the simulated frequency, and the bus and time of the simulated one. Above it stands a line when there is no simulated value (off, running, PSS®E, no record, or a run kept before) or when the simulation stopped early. Under it, a hint says what each value is.
  - The prediction is the SFR model of the frequency limits (`simulate_frequency_nadir`) at the solved scheduled import.
  - The simulated value is the island's lowest (or highest) bus frequency after the trip. It comes from `frequency_stats.json`, a new file of the ANDES script (one minimum and one maximum per bus). The worker takes the extreme over the island's buses.
  - The PSS®E script is not changed (decision 13), so its runs show "not reported".

*How it was verified* (test instance on 8090; savnw, `flow_shed`, zone SECOND, frequency and voltage security, ANDES, report box off, tag `gui_test_results_panel`):
- **Clear:** after a History run was loaded, Clear emptied the panel and turned itself off, and choosing the run in the list brought it back.
- **New run:** on Run, the panel switched from the History run to "Run 1 is running …".
- **Before the simulation:** on the second, warm run, screenshots 4 and 8 s in showed the solve's results with the line over the tabs, "running...", "after the dynamic simulation" and "written when the simulation ends", while the strip was at Dynamic simulation. About 8 s later the final results replaced them on the same tab. The kept result file is the final one (`frequency_simulation` simulated).
- **Boundary flows:** "Net flow" and "Sum of absolute flows" stand above lines 3, 4, 9 and 10.
- **Nadir:** zone SECOND, nadir, limit 59.500, predicted 59.794, simulated 59.159 Hz at bus 211, t = 7.76 s; outside zone SECOND, peak, limit 60.500, predicted 60.049, simulated 61.841 Hz at bus 3001, t = 11.59 s. The simulation stopped early at 11.59 s, and the red line said so. A run kept earlier says "kept before the GUI predicted the nadir".
- **Found and fixed:** the first record took each bus's extremes over the whole run, and bus 211's highest frequency (60.73 Hz) came at t = 3.73 s, before the trip. The case is not quite at steady state then (the run's two warnings). The extremes are now taken after the trip only, from the first sample after t = 5 s, and the next run's earliest extreme was at 5.0001 s.
- **Console:** no traceback from the app. One asyncio `ConnectionResetError` came when the test tab was closed: Windows reporting the page's connection reset, in Python's own code.

- **Without the simulation** (tag `gui_test_results_nosim`): no first summary. The panel waited, then showed the final results. The Frequency tab had the predicted values, "–" for the simulated ones, and "The dynamic simulation was off …". The waiting sentence mentioned the simulation, and now it does so only when the run has one.
- **A failure before the solve** (bus pair 101-3008, which has no line): the run took the panel with "Run 2 failed before it was solved, so it has no results: no boundary line found …", and run 1 and the History run could still be chosen.

*Not exercised:* a run that fails or is stopped during its simulation (the red line was checked as a pure function only); PSS®E; ACTIVSg500.

*Behaviour to know:*
- The nadir table exists only with frequency security, since the islands and their model come from it.
- Clear is off during a run (since 2026-11-21, at the user's request), so a run's results always come to the panel. Its tooltip says which run is in progress.
- When the final results replace the first ones, the panel is drawn again: the tab stays, but a scrolled bus table goes back to its top.

*Worth knowing about this test's numbers:* the simulated nadir of zone SECOND (59.159 Hz) is well under the predicted one (59.794 Hz) and under the first UFLS stage, and the relays shed 183.92 MW. But this case is not at rest before the trip: its bus frequencies already range from 60.000 to 60.734 Hz before t = 5 s, and the run warns about it. So the simulated values start from a system already swinging. The prediction assumes it at rest at f0, and the simulation's value is the lowest bus frequency, with local swings. The "peak" of 61.841 Hz outside the zone is the last sample before the simulation broke off at 11.59 s, not a settled peak.

Test folder added: `savnw_flow_shed_gui_test_results_panel` (four runs).

Test folder added: `savnw_flow_shed_gui_test_uiux`.

**Voltage details tables (2026-11-22), at the user's request:** "don't need the dead buses rows ... at the beginning of the round say total number of dead buses or dead buses inside or outside the zone ... we don't need the state col ... remove the part 'at bus 23' ... zone spartanb at bus 383 ... and then remove the bus col ... do the same changes for shed table as well".

*What changed (`components/voltage_details.py` only; the summary and `voltage.jl` are unchanged, so kept results show the new tables too):*
- **Dead islands.** Islands without a generator that can hold their voltage (`no_generator`) have no rows. The round's title line says how many buses they hold, "dead buses: 6 inside zone Spartanb, 10 outside", or the total without a target (`describe_dead_buses`), with a tooltip saying what they are. Nothing is shown when there are none.
- **No State column.** The Islands table has the checked islands only. An island whose power flow did not solve gets a red line under the title instead, since it leaves the round not verified (`describe_failed_islands`).
- **Island names.** Names count only the islands that get rows, so the four dead islands of a Spartanb run no longer force "at bus N" onto the two live ones. The tag was the island's lowest-numbered bus, which says nothing about the island. When one side does have two live islands, they are numbered by size, largest first: "zone SECOND island 1". Without a target they are "island 1", "island 2", ... ("island" when alone). The Summary and Frequency tab use the same `name_islands` and were already given only the live islands.
- **Buses in the first column.** Largest indicators and Sheds sized name each bus with its island, "zone Spartanb at bus 383", in a column "Where", and the Bus and "Shed at bus" columns are gone. The shed table's "Indicator after" and "At bus" are one column, "Worst indicator after" ("0.389 at bus 28"): the island's worst indicator once all its sheds of the round are applied, on the island's last shed row only.

*How it was verified:*
- **Pure functions** on the kept `ACTIVSg500_flow_shed_spartanb/result_2026_11_21_23_45_08.json`, round 1: two island rows, dead buses 6 inside and 10 outside (6 + 79 = the zone's 85 buses), indicators at 383, 382, 28 and 469, 252, 251, sheds at 383 (0.389 at bus 28) and 469 (0.391 at bus 252). Hand-made rounds for two live islands on a side, a failed power flow and no target.
- **`dev/check_results_tables.py`** (its voltage part rewritten for the new columns, and now checking the dead and failed islands against the console) on a fresh `send_jobs.py --full` log of the two voltage jobs of `jobs_results_check.json`: 426 checks, 0 failed.
- **Dialog** on a test instance on 8090, the ACTIVSg500 run loaded from History: as above, round by round.

*Left as it is:* the console and the strip's notes still say "Island at bus 23". They come from `voltage.jl`, inside the PowerModels module, and the checker reads those lines.

**Load into Run by double-click or Enter (2026-11-22), at the user's request:** "load a history record into run with double click or enter".

*What changed:* `components/sortable_table.js` emits `open` with a row's id on a double-click, and with the selected row's id on Enter while the table has the focus (the arrow keys already needed it); the word a double-click selects is cleared. `SortableTable` takes `on_open`. History's `_open_run` selects the run and does what Load into Run does; a run from before settings files gets a note instead, as the button is off for it. The Load into Run button's tooltip and the hint of an empty selection say so.

*How it was verified* (test instance on 8090): a double-click on the ACTIVSg500 run of 2026-11-21 23:45 showed the Run page with its settings and results; a click on the savnw run of 2026-11-22 14:17 then Enter did the same for it; a double-click on the oldest run (savnw, 2026-03-13, no settings file) stayed on History with the note.

**Queue, batch and compare round (2026-11-23), at the user's request:** "I'd like to have a compare page, to be able to add runs to it from the run page or history page ... a run queue [that] I should be able to see and handle in a convenient dialog (view, cancel, reorder, etc) ... a batch run button, where I can edit what I want (like lambda's ...) which leads to a queue". The user also kept the trade-off chart of the proposal ("How much preparation is enough") and asked that the batch offer what `batch_islanding.jl` sweeps. Each item is ticked once it is built and seen working.

- [x] 1. Run queue: Run adds to it while a run is in progress. It is kept in Python and Julia gets one run at a time. Stop ends the run and pauses the queue; a run that fails does not.
- [x] 2. Queue dialog: the runs that wait, with cancel, clear, up and down, pause and resume.
- [x] 3. Batch: a button and a dialog that give the form's settings lists of values (what `batch_islanding.jl` sweeps, and the load scaling factors). Every combination is one run in the queue, with its own tag.
- [x] 4. Compare page: runs as columns, quantities as rows. Runs are added from the runs table of the Run page and from History, and a batch adds its runs as they finish.
- [x] 5. Trade-off chart on the Compare page: the preemptive shed against the frequency margin and the voltage margin.

Nothing changed in Julia, in `worker.jl` or in the files a run writes. The round is Python only, and the app has to be restarted to get it.

*What changed:*
- **Queue (`run_queue.py`, `ctx.queue`).**
  - Run starts a run when nothing is running. While a run is in progress the same button reads "Add to queue" and puts the form's settings, as they are then, at the end of the queue. Its tooltip says which of the two a click does.
  - The queue is a list in Python. When a run ends, the next one is sent to Julia on the event loop's next turn (not from inside the runs' listeners, which a start would call again). So Julia holds one run at a time, a run that waits can be cancelled or moved, and a page's question (reading a case, placing a network) is answered between two runs.
  - It pauses by itself when a run does not end by itself and runs wait: Stop, Restart Julia (both leave the run "stopped") and a Julia crash. The runs then wait for Resume. A run that fails in Julia does not pause it. An empty queue is never paused.
  - While the queue is paused and nothing runs, Run starts its run at once and the queue stays paused.
  - Each started run takes the results panel, as before, so the panel follows the queue.
  - Quit's question says how many queued runs are dropped. The queue is not kept when the app stops.
- **Queue dialog (`components/queue_dialog.py`).** Queue in the settings toolbar shows how many runs wait and is amber while paused. The dialog lists them in the order they start (case, objective, boundary, tag, penalties, when added), with arrows to move a run, a cross to cancel it, Clear queue, and Pause or Resume. It follows the queue while open, in every browser tab.
- **Batch (`batch.py`, `components/batch_dialog.py`).**
  - Batch opens on the form's settings, which must be without problems. On the left, each field that may vary: objective, OPF model, flow penalty and target zone or area as checkboxes, and λ, each penalty (× λ: every row, the uniform value, all other loads) and each load scaling factor as a list. A list is numbers with commas, or a range `first:step:last`.
  - Every combination is one run, in the order `batch_islanding.jl` sweeps (`expand_batch`). On the right, the runs with what each has and its results folder.
  - Several targets change the boundary only: the penalty rows stay on the zones or areas they name, as the script's penalties do. A hint under the targets says so.
  - Each run's tag is the prefix ("Tag starts with", the form's output tag or "batch") and one part per field that varies: `lam500`, `pen2.5-1.6` (the penalty rows that vary, joined), `oth5`, `uni0.01`, `load0.7`, the flow penalty, `ac` or `dc`, the target's name. The objective is in the folder's name already.
  - Each run is checked with `validate` and the advanced tabs' `find_problems`, and two runs may not write to the same folder. A problem several runs share shows once, with the runs it is in. A batch has at most 200 runs (`MAX_RUNS`).
  - "Open its report" is off unless ticked (PSS®E always opens its own). "Add it to the Compare page" is on.
  - **λ.** In the form the penalties are multiples of λ, and `flow_shed` minimises λ·flow + Σ (k·λ)·Pd·(1 − z), so λ drops out when every load has a row or "All other loads" has a value. A list of λ alone then gives the same solution. The dialog says so under λ. What moves the trade-off is a penalty.
- **Compare page (`comparison.py`, `pages/compare.py`, `ctx.compare`).**
  - A run comes from Compare in the runs table, from Add to compare in History, or from a batch when it finishes. Only a run with final results is taken: status finished, not the first summary, with a settings file. It is known by `folder/settings file`, which is History's row id, so a run added from both pages is there once. The buttons' tooltips say why a run cannot be added.
  - **Side by side.** One column per run with its name, tag and a cross to take it off. First a line of the settings every run shares, then the settings that differ, then Solution, Load shedding (preemptive, UFLS, both), Boundary flows, Frequency per island (scheduled import, limit, predicted, simulated, margin), Voltage, and the preemptive and UFLS shed by zone or area when the runs are of one case and one kind of group. There is no table by bus. The rows are one block of HTML in a CSS grid; the names stay in view when many runs scroll sideways.
  - Results kept before a part existed (`ufls`, `frequency_simulation`, `target`, the predicted nadir) show "–" there.
- **Trade-off (`ui.echart`, bundled with NiceGUI, no new dependency).** Two charts, because the margins have different units.
  - Frequency margin per island: the simulated nadir above its limit, or the peak below it; a toggle switches to the SFR model's prediction. Islands are series in the first three group colours of `network_view.py` (checked with the dataviz validator), a fourth and later ones grey.
  - Voltage margin: the indicator threshold (`voltage.details[0].indicator_threshold`) minus the worst indicator. It is predicted, not simulated, and the chart says so.
  - A line at zero is the limit and the part below it is tinted when a point is in it. A hollow point is a run whose simulation stopped early (frequency) or whose voltage was not verified (voltage). Points are named when there are eight or fewer, and each has a tooltip. Runs without a margin are listed under the chart.

*How it was verified* (test instance on 8090, savnw; the user's GUI untouched):
- **Pure functions:** lists and ranges and their errors; a 48-run expansion with its tags and folders; a batch over a uniform penalty and a load scaling factor; the DC runs of a batch with voltage security named as problems; the comparison and the chart options on kept results, among them one from before `frequency_simulation` and `target`.
- **The queue without the app** (a stand-in for the worker and the runs, no event loop): a failed run lets the next start; Julia exiting during a run pauses the queue with its reason, and it stays paused when Julia is back until Resume; a stopped run pauses it; clearing unpauses it; a run added while Julia is stopped waits and starts when Julia is ready.
- **Queue:** Run during a run added to the queue. A batch of three started its first run and showed "Queue (2)". The second waiting run was moved up, the queue paused by hand held when the run ended, and Resume started the next. A run with bus pair 101-3008 (no such line) failed in the middle of the queue and the next run started by itself. Stop with a run waiting paused the queue, with the note and the amber button; cancelling the waiting run emptied and unpaused it.
- **A question between runs:** the Network page asked for savnw during run 3 ("Julia is busy with run 3 ...") and was drawn while run 4, the next in the queue, was running.
- **Batch:** objective flow_shed and opf_shed with "all but zone SECOND" at 1.6 and 0.8 gave four runs in four folders. They ran in order and appeared on the Compare page as each finished, in a second browser tab that showed the same queue.
- **Compare:** runs added from History; an unfinished run refused with its reason; the same run added twice refused; four columns side by side; both charts with tooltips, the toggle, hollow points and the note of the runs that are not on a chart.
- **Last pass:** Compare in the runs table put run 5 on the page ("Run 5 is on the Compare page, with 8 runs there now") and refused it the second time; eight runs stood side by side in the page's width; a column's cross took its run off and Clear emptied the page. A batch of twelve (three flow penalties, penalties `1:1:4`) started one run and left eleven waiting, and Clear queue removed them while the run in progress went on.
- **Console:** no traceback in the test instances' output.

*Seen twice and not explained:* a dialog was open that no action of the test had opened: once the batch dialog, some time after its runs were added, and once the queue dialog, right after Add in the batch dialog. With every click and key of the page logged, the same steps were repeated twice (Batch, tick a flow penalty, Add, with a run in progress): one click per action, the batch dialog closed and none opened. The test tabs were in the user's own Chrome window, and the user's GUI was restarted several times during the tests, so a click by hand is the likely cause, but that was not established.

*Behaviour to know:*
- The form's settings are copied when a run is queued. A later change to the form does not reach it.
- On savnw the simulation of the zone SECOND runs stops early (about t = 11.6 s), so their frequency points are hollow.
- The opf_shed runs of the test are "not verified" with a worst indicator of 0.193, under the threshold: an island could not be checked. Their voltage points are hollow for that reason.
- Runs that give the same result lie on one point, and only one of their names shows.

*Not done:* the queue and the Compare list are not kept when the app stops (History adds runs to Compare again); reordering the columns of Compare; adding several History runs at once; a field the objective does not read is still varied (an `opf` run for each penalty value is the same run several times, as in `batch_islanding.jl`).

*Not exercised in the app:* ACTIVSg500; an area study; a uniform penalty, load scaling and several targets in a batch (pure functions only); Restart Julia with runs waiting (it leaves the run "stopped", as Stop does); a Julia crash with runs waiting (its own branch, checked only without the app); PSS®E.

Test folders added: `savnw_flow_shed_gui_test_q1` to `_q6`, `savnw_flow_shed_gui_test_fail` (failed before the solve, so empty), `savnw_flow_shed_gui_test_batch_pen1`, `_pen2.5` (stopped) and `_pen4`, `savnw_flow_shed_gui_test_b2_pen0.8` and `_pen1.6`, `savnw_opf_shed_gui_test_b2_pen0.8` and `_pen1.6`, `savnw_flow_shed_gui_test_q6_squared`, `_q6_abs_sum`, `_q6_squared_pen1` and `_q6_squared_pen2`.

**Batch dialog and tooltips (2026-11-23), at the user's request, after trying the round above:** "if I click batch button it says choose the zone, then in the dialog I can change the zone, does not make sense ... there is no way to set shedding penalties in batch ... you add a lot of useless tooltips, don't do that".

*What changed:*
- **Batch opens without a zone.** The form may have a zone or area boundary without its zone or area: the Run page leaves that one problem out when it opens the dialog (`describe_missing_target` in `settings.py`). No target is ticked then, and the dialog asks for one. Every other problem of the form still keeps the dialog shut.
- **Penalties are set in the dialog.** They start as the form's and are edited there: "uniform" with one list for every load, or rows as in the Run form (zone or area, all but one, or a bus) that can be added and removed, each with a list of values, and a list for all other loads. Before, the dialog only had a list for each row the form already had, so a form without rows offered nothing but "All other loads". The rows have no arrows: they apply in the order they stand in, and a new row goes to the bottom.
- **The run list** says "target Spartanb", not "zone Spartanb", so a penalty row on the same zone reads apart from it.
- **Tooltips.** The rule is under "Look". Taken off, from the round above: what Run does while it can be clicked, Compare in the runs table and Add to compare in History while they can be clicked, Close, Clear queue, Pause and the cancel cross in the queue dialog, the close cross, the tag and the field labels in the batch dialog, Clear, the column crosses and the "?" on the Compare page. The user took off those of Batch and Queue. Kept: why a button is off (Run, Compare, Add to compare, "open its report"), and the whole of a tag or of penalties that are cut.

*How it was verified* (test instance on 8090): Batch on the default form (ACTIVSg500, no zone chosen) opened with "choose at least one target zone"; two targets and one added row with `1:1:3` gave six runs. On savnw the form's two rows came into the dialog, uniform swapped them for one list and back, and a batch of two values of the first row ran both runs to the end, the second with the same objective value as the same settings typed in the form. No tooltip showed on Run. The dialog's reading of targets, rows and uniform was also checked without a browser.

Test folders added: `savnw_flow_shed_gui_test_p_pen1.6` and `_pen0.8`.

**Paired penalties and rows on the target (2026-11-23), at the user's request:** "what if I want 2 instead of 4 runs, one with 2.5 and 0.7 and another with 2.4, 0.8", and, after the two ideas were explained, "do the things that makes my life easier".

*What changed:*
- **Paired.** A checkbox "paired" beside "uniform" in the batch dialog's penalties. With it, the lists of the penalty rows and of all other loads go together by position: the first values are one run, the second the next, so each run has one whole set of penalties, as an entry of `load_shedding_penalties` has in `batch_islanding.jl`. Every list has the same number of values, or one value that every run gets; lists of different lengths are a problem that names them, and Add stays off. A number written twice stays twice in a paired list, because its place says which run it is for (`parse_values(text, unique=False)`); elsewhere a list still keeps each value once. Only the penalties pair: every other field still multiplies, so two targets with two pairs are four runs. The checkbox is off when the dialog opens and hidden with uniform shedding. A hint line under the rows says what it does while it is ticked.
- **Rows on the target.** With a zone or area boundary, a penalty row's "Where" also offers "Target zone" and "All but target zone" (or area). Such a row has no zone to choose. In each run it is on that run's target, so "the island's loads at 2.5 λ, the rest at 1.6 λ" holds for every target of a sweep. `batch.py` writes it into each run's settings as an ordinary row that names the run's target (`penalty_follows` in the spec, `set_target`), so the worker, the settings schema, presets and Load into Run know nothing of it. A bus-pair boundary has no target and does not offer it. The Run form does not have these rows.
- **In `batch.py`,** fields with the same `pair` form one axis (`find_axes`, `calc_axis_length`, `find_combinations`); a run still gets one value per field, so tags and the run list work as before (`pen2.5-0.7`, `pen2.4-0.8`).

*How it was verified:*
- **Without the app:** a crossed batch of 16 runs gives the same settings, texts and folders as before the change; the user's example paired gives two runs tagged `pen2.5-0.7` and `pen2.4-0.8`; "2.5, 2.5, 2.4" with "0.7, 0.8, 0.8" gives three runs; lists of 3 and 2 values and a list without a value are refused; a pair written twice is named as two runs to one folder; rows on the target take each of three targets' names and pass `validate`, and the settings given are not changed.
- **In the app** (test instance on 8090, ACTIVSg500, no dynamic simulation): the user's two rows gave four runs, and two with "paired"; a third value in one list showed "paired lists need the same number of values, or one value: penalty row 1 (zone Spartanb) has 2, penalty row 2 (zone Midlands) has 3". With targets Spartanb and Midlands, "Target zone" at "2.5, 2.4" and "All but target zone" at "0.7, 0.8", paired, four runs ran to the end and reached the Compare page; their settings files have zone Spartanb or zone Midlands in both rows, by the run's target, with 2.5 beside 0.7 and 2.4 beside 0.8. Uniform hid "paired". A bus-pair boundary offered Zone, All but zone and Bus only.
- **Read, not run:** a named row and a row on the target may reach the same zone in one run; `calc_shed_penalties` in `worker.jl` applies rows in order, so the lower row counts, as the hint says.

*Not done:* the dialog starts from the form each time it opens, so its rows, targets and "paired" are not kept from one batch to the next; pairing other fields than the penalties; a cross on each run of the run list to leave it out.

Test folders added: `ACTIVSg500_flow_shed_gui_test_q_spartanb_pen2.5-0.7`, `_spartanb_pen2.4-0.8`, `_midlands_pen2.5-0.7` and `_midlands_pen2.4-0.8`.

**Network page: generator buses and right click (2026-11-23), at the user's request:** "in mode where buses are set to zone/area ... differentiate between their colors. keep the colors close though ... when I right click on a bus or on a line, it should add it's bus pair or bus number in a text box in copy paste ready format, in a format of bus pair input that run page accepts".

*What changed:*
- **Generator buses.** Coloured by zone or area (or with one colour, in a case without groups), a bus with a generator (a square) has its group's colour mixed a quarter of the way to `DARK_COLOR` (`GEN_SHADE` = 0.25 in `network_view.py`, the one number to change for more or less contrast). The square is ΔE 14 to 21 from its own group's colour, and at least 18.4 from every other group's colour, plain or darker. A first version kept hue and saturation and only lowered the lightness (to 0.72 of it): it was 14.5 to 30 from its own group (pink turned magenta) and 15.9 from the closest other group, so the mix is closer to its group and further from the others on both counts, at the price of slightly muted squares. The legend says what a square is, and so does "How to use".
- **Right click.** `network_canvas.js` sends `context` for a right click on a bus or a line; on a circle or on nothing the browser keeps its own menu. Under Picked in the side panel, a line adds its bus pair to Bus pairs ("297-440, 23-386", as the Run form's bus pairs field reads it) and a bus its number to Buses ("111, 202", as the bus lists of Advanced and the Buses field read it). There are two fields because one text with both would be read by neither. An item already in its field is not added again. Each field can be edited, has Copy, and Clear empties both. Choosing another case empties them, since the numbers belong to the case. The selection does not change.

*How it was verified* (test instance on 8090 after a hard reload, ACTIVSg500 fitted): the squares stand apart from their group's circles at the fitted view, with both shadings. In Zone mode with a zone selected, with the canvas's mouse events logged, a right click on bus 111 gave "111", on line 297-440 twice gave it once, on line 23-386 then gave "297-440, 23-386", and on the Midlands circle gave nothing; the selection stayed. Copy then Ctrl+V in the Run form's bus pairs field was taken without a problem. `parse_buses` and `parse_bus_pairs` read the two fields. No traceback in the app's output.

*Not exercised:* choosing another case to empty the fields; savnw and a case without groups; pasting Buses into a bus list of Advanced in the app (the parser only); whether the browser's menu stays shut on a bus or a line (the extension's right click does not show it either way).

*Seen and not explained:* during the first test, the test tab's Bus pairs field held "183-274" before any right click of the test; a right click where the tooltip had just shown line 220-471 added bus 202 instead; then zone Spartanb was selected and the Buses field emptied, none of it by the test. The log then showed mouse moves that were not the test's. Someone was likely using the test tab by hand, as in the queue round. The logged right clicks above are the evidence. Between the two test instances, `network_view.py` was reformatted on disk (a formatter, it seems) and the legend note shortened to "a square is a bus with a generator"; both were kept. The user's GUI on 8080 was running after the first test instance quit and was gone after the second; Quit stops only its own server and its own Julia, and both Quit clicks were in the 8090 tab.

**Phase 13 (2026-11-23), with the HTML report's units fixed at the user's request:** "go for phase 13, and fix the html units too".

*What changed:*
- **ANDES script.** `andes_scripts/dynamic.py` takes `--no-html` (`NO_HTML_FLAG`) beside `--no-open`. With it the script writes everything as before except the HTML report, opens nothing, and says so: "HTML report not written (--no-html): the channels are in ...".
- **The HTML report's units.** `report.py`'s `write_html_report` takes `base_mva` and plots POWR, VARS and PLOD times it (`POWER_UNITS`), so generator and load P are in MW and Q in MVar, as the titles always said. Before, those axes were in pu on the system base. The PSS®E script is frozen and keeps its own copy of the function.
- **`run_islanding`.** It takes `html_report::Bool=true`, so script runs keep their report, and passes `--no-html` with `false` to the ANDES script only. `find_new_report` became `find_new_file(output_path, since, prefix, suffix)`, which finds both the report and the channel file. The settings file records `html_report` and `files.channels`.
- **Worker.** `html_report` is an optional setting, and a missing key means `false`. `calc_files_summary` adds `channels`.
- **Settings and forms.**
  - `settings.py` has `"html_report": False`, and a missing key reads as `false`.
  - The Run form's Report line has "HTML file" (unticked) and "open when done". "open when done" is off while "HTML file" is unticked. Both are off for PSS®E, which always writes and opens its report, so the form sends `true` for both, and both are off without a simulation. Each says why in its tooltip.
  - The batch dialog's "open its report" is off while the form's `html_report` is `false`.
  - `results_index.build_settings_from_record` copies `html_report` from a script's record.
- **`dynamics.py`** (new, draws nothing):
  - `find_channel_file` takes `files.channels`, or for results kept before, the name of the report, since both carry the script's stamp.
  - `load_dynamics` reads one quantity and VOLT with `usecols`. It converts the units, with the base MVA from the RAW's first record, and finds the buses that lost power (`report.is_valid_voltage_profile`).
  - `find_curves` chooses the curves to draw, `thin_curve` thins them, `calc_frequency_stats` and `calc_voltage_stats` compute the statistics (the voltage ones through `report.build_voltage_stats_json`, report.py loaded by its path), and `build_chart` and `build_view` make the chart.
- **`components/dynamics_view.py`** (new) is the tab. It reads the file through `run.io_bound` under a Cover, and only once the tab is shown. A newer read or drawing drops an older one, and a tab the panel has rebuilt drops its own.
- **`results_view.py`.**
  - `TAB_LABELS` has Dynamics.
  - `find_tabs` shows it when the summary's `frequency_simulation` or `ufls` is not null.
  - `describe_report` gives the Summary's Report fact ("not written: HTML file unticked", "not written: no dynamic simulation", "written when the simulation ends").
  - `describe_partial` names the curves, and the report only when one is written.
  - The Files tab lists "Simulation channels", found through the report's name for older results. `open_file` takes the name.
  - The panel keeps the tab's choices from run to run (`dynamics_choice`).
- **`theme.css`** has the `dyn-*` classes. **`CLAUDE.md`** and **Contracts** (settings schema, per-run settings file, result summary, the layout sketch) say what is new.

*Where it differs from the phase text:*
- **Hover.** ECharts shows no item tooltip for a hovered line, and its `mouseover` event fires only when the pointer is within about a pixel of a 1.2 px line. A real pointer 2 px off named nothing. So a small script in the browser (`NAME_NEAREST_CURVE_JS` in `dynamics_view.py`, run with `ui.run_javascript` for each new chart) names the nearest curve. At each move of the pointer it finds the curve nearest the cursor at the cursor's time, within `NEAREST_CURVE_PX` (8 px), highlights it, and writes its name in bold above the chart's top right. A plain label has no Vue component, so the script finds it by its DOM id `ng-<id>`. A cross-hair gives the time and the value at the cursor in labels on the two axes.
- **A sentence about the report.** The UFLS side's "no record" sentence adds "The simulation report may have it." only when the run has a report.
- **plotly at start.** Importing `report.py` loads plotly when the app starts, about 2 s more. pandas and numpy were the only imports the phase named.
- **Zoom.** Ctrl + wheel zooms the time and a drag moves it; a plain wheel scrolls the page. A "Whole time" button shows the whole simulation again. The phase text had neither.
- **Size.** `MAX_POINTS` is 1000, not 600, so a zoomed curve keeps more detail. 60 ACTIVSg500 curves are about 0.9 MB.
- **Statistics** follow Where (the side), not Buses.
- **Dead buses.** The load P and Q curves of buses that lost power are kept, because their drop to 0 is the load the dead island loses. Only frequency and voltage leave those buses out.
- **`parse_buses`** is in `advanced/where.py`; the phase text said `settings.py`.
- **ECharts' own `sampling`.** NiceGUI's `echart.js` passes the whole options to `setOption` in the browser, so ECharts would thin the data only after it crossed the websocket. The thinning is in Python.
- **A new chart at each change.** NiceGUI's `update_chart` merges new options into the old ones when the number of series stays the same, so old curves could linger.
- **Table width.** The statistics tables put the bus and its name in one column so they fit the 480 px column beside the chart.

*How it was verified:*
- **Pure functions.** These were checked on the savnw run of 16:07 (kept with a report, before this phase), on `ACTIVSg500_flow_shed_spartanb` of 2026-11-21, and on the new runs below.
  - The tab's minimum, maximum, buses outside the band and WTVSI equal each run's `voltage_stats.json`, and its nadir and peak equal `frequency_stats.json`. For example, on ACTIVSg500: 0.949 pu at bus 142, 1.103 pu at bus 410, 5 of 484, WTVSI 0.000005, nadir 59.537 Hz at bus 438, peak 60.327 Hz at bus 144.
  - On the GUI run they also equal the Frequency tab's simulated island values: 59.615 Hz at bus 206 and 60.223 Hz at bus 3018.
  - ACTIVSg500 reads in 0.47 s and its frequency view takes 0.11 s.
- **Worker** (`send_jobs.py`, three jobs):
  - savnw with HTML off and "open when done" on wrote no report and opened nothing. Its record has `html_report: false` and `files.channels`.
  - savnw with HTML on and "open when done" off wrote the report without opening it, in the same folder. Each of the two runs names its own channel file.
  - ACTIVSg500 with HTML off wrote no report.
- **Script.** A temporary copy of `islanding.jl` (`gui_test_ref`, with `open_report=false` so no browser tab opened) wrote its HTML, and its record has `html_report: true`.
- **HTML units.** POWR 211 in the new report starts at 616.25 MW, where the channel file holds 6.1625 pu.
- **Test instance on 8090:**
  - The savnw run of 16:07, loaded from History, found its channels through its report's name.
  - On ACTIVSg500 the tab drew 60 curves 1.3 s after the click, with notes on the 16 buses that lost power and on the 60 of 484 drawn.
  - Voltage showed the 5 buses outside the band. The buses typed "142, 410, 438, 99999" gave three curves with a legend and "No bus voltage at bus 99999.".
  - Generator P outside the zone showed in MW, with no statistics.
  - With the browser's own pointer (its positions corrected for the tool's 2.3 % scale, and read back from the page), the curve was named 5 px from its line ("bus 211 HYDRO_G") and nothing 20 px away.
  - A real wheel without Ctrl scrolled the page and left the zoom alone. A real drag moved a 20–60 % window to 30–70 %, and Whole time undid a zoom to 20–60 %.
  - History's "Only with a report" left out the two runs without HTML, and their REPORT column reads "–". The Summary says "not written: HTML file unticked", with Open report off.
  - In a live GUI run with HTML off: while the simulation ran, the line over the tabs said "UFLS shed, simulated frequency and curves come when it ends", and the tab said its curves would come, with the turning ring. The final results drew the tab without a click.
  - The form's boxes: at the start "HTML file" is unticked and "open when done" off. Ticking "HTML file" turns "open when done" on. PSS®E greys both. Back on ANDES with "HTML file" unticked, "open when done" is off again.
  - A preset or older settings without the key come in unticked (pure check).
- **Console.** No traceback in the three test instances' logs.

*Seen and not explained:*
- Once, a chart's time axis was zoomed to 8.5–18 s, although the test had not zoomed it.
- Later, the Quantity list of the test tab changed twice (Bus voltage, then Load Q) with its list open, with no action of the test.

As in earlier rounds, the test tab is in the user's own Chrome, and a hand on it is the likely cause. The later checks were made in a second tab of the test and from code.

*Not exercised:*
- a PSS®E run (its sentence was checked as a pure function);
- a simulation that stops early (WTVSI then differs from `voltage_stats.json`, whose script divides by the planned 25 s);
- a channel file that cannot be read;
- the batch dialog's "open its report" in the app (read, not clicked);
- Ctrl + wheel zooming (the browser tool's wheel has no Ctrl). The zoom was set from code, and a drag and Whole time were checked from there.

Test folders added: two runs in the older test folder `savnw_flow_shed_gui_test_dyn`, `savnw_flow_shed_gui_test_dyn_gui`, `ACTIVSg500_flow_shed_gui_test_dyn`, and one run in `ACTIVSg500_flow_shed_gui_test_ref`.

**Dynamics tab round (2026-11-23), at the user's request, after phase 13:** "zoom be like plotly, drag on a vertical line show that vertical section, same for horiz, if drag is like rect, show the section in the rect ... double click on the chart to reset the axis ... connect table row to the chart next to it ... add a all buses checkbox for frequency as well ... I don't see thresholds (UFLS and frqtpat) in frequency charts. we want them."

*What changed (`dynamics.py`, `components/dynamics_view.py`, `theme.css`; nothing in Julia or in what a run writes):*
- **Zoom as Plotly.** A drag in the chart greys what it will zoom (`.dyn-zoom-box`): a drag across, the time between two vertical lines over the whole height; a drag up or down, the values between two horizontal lines over the whole width; a box, the box. On release it zooms what it covered. A drag across, under `MIN_DRAG_PX` (8 px) up or down, zooms the time only. A drag up or down, under 8 px across, zooms the values only. A box zooms both. A double-click shows the whole chart again. A click zooms nothing.
  - The chart's two dataZoom components (0: time, 1: values, `PROGRAM_ZOOM`) take no mouse input themselves. The browser script `CHART_JS` moves them with `dispatchAction`.
  - Ctrl + wheel zoom, the drag that moved the time, and the Whole time button are gone; double-click replaces the button.
  - The numbers on the axes are rounded (`build_axis_labels`), since a zoom puts the edges at any value.
  - ECharts listens to pointer events, and a pointerdown whose default is prevented (so no text is selected) fires no mouse events after it. So the drag follows `pointermove` and `pointerup` on the document. A first version listened to mouse events and never heard the end of a drag.
  - ECharts stops the moves of a drag that starts in the grid before they reach the document, so the document hears them in the capture phase. Before that the box moved only while the pointer was off the chart, and the user saw none (fixed 2026-11-23).
- **A row of the statistics brings its curve forward.** Under the mouse, a row of the frequency, voltage or WTVSI table (its first cell starts with the bus number) shows that bus's curve alone, the others hidden, and names it (the nearest curve under the cursor only pales the others; the user asked for hidden on 2026-11-23). The row gets the hover background. A bus whose curve is not drawn does nothing. The handlers are properties of the statistics box (`onmouseover`, `onmouseleave`), so each new chart replaces the last one's. A drawing without a chart clears them and the name (`CLEAR_JS`).
- **"all buses" for frequency too.** For frequency and voltage, the box draws every bus of the chosen side, without the cap of 60 and, for voltage, with the buses inside 0.9–1.1 pu (`all_buses`, in place of `all_voltages`). The P and Q quantities still draw the 60 that move most. Many curves share a budget of `MAX_TOTAL_POINTS` (120,000 points, about 2 MB), with at least `MIN_POINTS` (200) each.
- **Relay thresholds.** The fixed lines copied from the report (57, 59, 60.5, 61.8 Hz and the three UFLS stages) gave way to the thresholds of the relays in the run's `.dyr` (`<case>_<objective>.dyr` in the results folder, `read_relay_thresholds`). These are the LDSHBL stages (f1, f2 and f3) in amber, and the FRQTPAT trips (FL and FU) in red. A FRQTPAT threshold outside 48–72 Hz never acts (the cases write FL 20 and FU 90) and is left out.
  - Each line is named at its right end: "UFLS 59.3", "gen trip 61.8", "UFLS, gen trip 59.5".
  - The y axis is widened to show every line (`build_value_axis_range`, JavaScript `min` and `max`), since lines outside the curves' range do not widen it themselves. That was why they were not seen.
  - The sentence under the chart names only the kinds of relay the case has.
  - savnw has 57.8, 59.1, 59.3, 59.5, 60.5 and 61.8 Hz; ACTIVSg500 has the three UFLS stages and no FRQTPAT.
  - The frequency statistics still count the report's thresholds (59, 57, 60.5 and 61.8 Hz).

*How it was verified* (test instance on 8090, in a tab of the test's own; positions read from the page):
- **Pure functions.** The thresholds of both cases are as above. savnw's axis runs 57.75–61.85 Hz. "all buses" on ACTIVSg500 frequency makes 484 curves of 218 points, 2.15 MB, in 0.54 s, against 60 curves and 0.91 MB without it.
- **In the app, on the savnw run of 19:39:**
  - The relay lines with their labels showed, and the axis ran 57.75–61.85 Hz.
  - A real drag across from 5 to 15 s gave 5.01–14.99 s with the values unchanged.
  - A drag down from 60.3 to 59.5 Hz then gave 59.498–60.3 Hz, with the time kept.
  - A double-click gave back 0–25 s and 57.75–61.85 Hz.
  - A box zoomed both axes.
  - A click changed nothing and selected no text.
  - The row "205 SUB230" named "bus 205 SUB230" and paled the other curves.
- **In the app, on the ACTIVSg500 run of 19:32:** ticking "all buses" drew 484 curves 1.9 s after the click. A zoom's edges read 60.099, 59.451, 5.12 and 12.99. Naming the nearest of 484 curves takes about 15 ms per move of the pointer.
- **Console.** No traceback in the test instances' logs.

*Not exercised:* a drag that leaves the chart before it ends (the document's `pointerup` ends it, clamped to the grid; read, not run); a case without relays (its sentence was checked as a pure function).

**Phase 14 (2026-11-23):** "go for the next phase".

*What changed:*
- **`dynamics.py`.**
  - `build_chart` is split in two. `build_curve_series` makes one curve, and `build_chart_options` makes the axes, the zoom components and the lines. So the Compare page passes its own curves, and the Dynamics tab draws as before.
  - `load_run_curve` reads one run's curve. That is a bus's frequency or voltage, or at each sample the lowest or the highest of the live buses on one side of the run's target. The extreme is taken over every sample before the curve is thinned, so the lowest point of a "lowest" curve is the side's simulated nadir.
- **`comparison.py`** decides, without drawing:
  - which runs are drawn (`find_curve_runs`, at most eight, in the group colours) and why the others are not (`find_curve_refusal`);
  - whether the runs share a target (`find_shared_target`), by its buses and not its name, because one run spells the zone "SPARTANB" and another "Spartanb";
  - the choices of Where (`find_curve_places`);
  - whether a run's curve follows a side's lowest or highest bus (`find_side_extreme`). The side's islands with frequency limits decide this, and a nadir in any of them makes it the lowest. Without frequency security, the sign of the net boundary flow decides. Voltage always follows the lowest bus;
  - the sentence above the chart (`describe_curves`).
- **`pages/compare.py`.** A "Dynamic response" section sits under the trade-off charts.
  - Its controls are Quantity (Frequency or Voltage), Where ("zone X", "outside zone X" or "a bus") and a bus number. Runs that share no target get only the bus field.
  - The section reads nothing until the Trade-off tab has been shown. Then it reads the runs one after another through `run.io_bound`, under a Cover that names the run being read. It reads again when the runs or the choices change, and a newer read drops an older one.
  - The chart has a legend of the runs. It also has the trip line, the relay lines of the first drawn run's `.dyr` for frequency (or the 0.9–1.1 pu band for voltage), and the Dynamics tab's zoom and curve naming (`CHART_JS`).
  - The runs that are not drawn are listed under the chart, each with its reason.
- **`CHART_JS`** (`components/dynamics_view.py`), which the Dynamics tab shares:
  - A chart drawn while another page was shown now gets its zoom and naming. NiceGUI keeps such a chart, with its label, out of the document until its page is shown. The script used to find the chart but not the label, and stopped. It now waits until the chart is in the document, for as long as the chart is among NiceGUI's elements (`mounted_app.elements`). The Dynamics tab uses the same script, so a run that ends while the Run page is hidden should be covered too; that case was reasoned, not reproduced.
  - A curve hidden through the legend is no longer named under the cursor (`legendselectchanged`).
  - `build_script` takes no statistics box.
- **`theme.css`** has `.curves-section`, `.curves-chart`, `.compare-bus` and `.curves-missing`.

*Where it differs from the phase text:*
- **Lines.** The chart draws the relay thresholds and the voltage band, as the Dynamics tab does, following the user's request of the last round that frequency charts show the thresholds.
- **Lowest or highest, per run.** A side can import in one run and export in another, so each run follows its own direction. The sentence above the chart names the runs whose side exports. When every run exports, it says that each curve is the highest bus frequency.
- **The case** is that of the first run that can be drawn, so a PSS®E run first on the page does not hide the others. The eight-run limit counts only runs that can be drawn.
- **More reasons.** Besides those the phase text named, a run can be "kept before the GUI read the channels, with no report to name its channel file", or its channel file "could not be read".
- **Names.** A curve is named as its run's column, but History names a run by the minute it started, and several runs often share one. The legend tells curves apart by name, so a repeated name gets the run's tag, and a number if it still repeats (`find_curve_names`).
- **Where is kept.** When the runs on show share no target, Where shows only the bus field. The page keeps the choice made before, so runs that share a zone, added later, open on that zone again.
- **Files.** `components/dynamics_view.py` changed as well, for `CHART_JS`.

*How it was verified:*
- **Pure functions, on kept runs.**
  - savnw, zone SECOND: three runs from 19:30 to 19:39 have their lowest point inside the zone at 59.615 Hz and their highest outside it at 60.223 Hz. The run of 16:07 has 59.445 and 60.283 Hz. These are the runs' simulated nadirs and peaks in the Frequency rows.
  - ACTIVSg500, zone SPARTANB, two older runs: 59.537 and 60.327 Hz, with the 6 and 10 buses that lost power left out. Each run reads in about 0.45 s.
- **Four new ACTIVSg500 runs.** These were made with `send_jobs.py` from paired settings written by hand, not from the Batch dialog. Zone SPARTANB has penalties of 0.5, 1.5, 2.5 and 4 × λ, all other loads 2, 1.5, 1 and 0.5 × λ, with frequency security and ANDES, without HTML.
  - Inside the zone, the curves' lowest points are 59.586, 59.576 and 59.569 Hz, equal to the simulated nadirs.
  - In the run with 0.5 and 2 the zone exports, and its curve tops at 60.512 Hz, its simulated peak.
  - Outside the zone, the peaks are 60.163, 60.201, 60.162 and 60.122 Hz.
- **In the app** (test instance on 8090, in a tab of its own), seven runs were added from History:
  - Five savnw runs were drawn. "2026-11-23 16:31: no dynamic simulation" and "2026-11-23 19:32: another case (ACTIVSg500)" were listed. The curves' lowest points read from the chart equal the nadirs above, and outside the zone each curve followed the highest bus.
  - A drag across gave 5.70–11.37 s, and a double-click showed the whole chart again.
  - On voltage outside the zone, the run of 16:06 falls to 0 pu at 11.59 s. That is in its file: its outside island collapsed (bus 154 reaches -0.004 pu), and its simulation stopped there.
  - "a bus" with 3005 gave "Each run's voltage at bus 3005 WEST." With 99999, every run was listed with "no channel at bus 99999".
  - The four new ACTIVSg500 runs showed on one chart, with the UFLS lines and the sentence naming the run of 20:24 as exporting.
  - A box zoom gave 7.57–15.14 s and 59.450–59.914 Hz.
  - With a run hidden through the legend, its curve was not named under the cursor. Shown again, it was.
- **A redraw while the page was hidden.** A run was added from History while Compare was hidden. Before the fix, the chart came back with the new run but without zoom. After it, the zoom box was there and a box zoom worked.
- **After the advisor's review** (a new test instance):
  - With only a run without a simulation on the page, the section said "No run here has curves to draw." and listed that run. Two SPARTANB runs added after it opened on "zone SPARTANB".
  - Adding a SPARTANB run kept on 2026-11-21, whose results have no target yet, left only the Bus field. Bus 438 then drew in all three runs ("Each run's frequency at bus 438 CHESNEE 2 10."), with the zoom.
  - The two savnw runs that started at 16:06 showed as "2026-11-23 16:06 · gui_test_b2_pen1.6" and "2026-11-23 16:06 · gui_test_b2_pen0.8", in two colours.
- **The Dynamics tab after the split** (the savnw run of 19:39): 23 curves, the trip line and six relay lines, the zoom, the row "205 SUB230" naming "bus 205 SUB230", and a drag up or down zooming the values to 58.76–60.96 Hz.
- **Reasons, as pure functions:** PSS®E, no dynamic simulation, a channel file that is gone, and an older run with nothing to name its file. With ten runs, eight were drawn and two were listed as "the chart shows 8 runs at most".
- **Console.** There was no traceback in the test instances' logs.

*Not exercised:*
- a GUI batch whose runs join the page as they finish (the redraw on a change of the list was exercised through Add to compare);
- runs of the app session itself: every run on the page came from History;
- a live PSS®E run (checked as a pure function);
- a channel file that cannot be read;
- a side made of several islands.

Test folders added: `ACTIVSg500_flow_shed_gui_test_cmp_pen0.5-2`, `_pen1.5-1.5`, `_pen2.5-1` and `_pen4-0.5`.

**Soft colour (2026-11-23), at the user's request:** "a bit of coloring can help the app. like for buttons or other places, not too much though and also I like soft colors."

*What changed:*
- **Tokens (`theme.css`).** The accent has soft tints (`--accent-soft`, `--accent-soft-hover`, `--accent-soft-line`, `--accent-ink`), and two soft tones serve buttons only (`--violet-*`, `--teal-*`). The soft tints of the state colours (`--ok-*`, `--warn-*`, `--bad-*`) replace the values that were written out three or four times (the Julia pill, the problems line, the queue note, the paused Queue button). The recipe is that of the results panel's yellow Clear: a pale fill, dark text of the same hue and a 1 px line of the same hue.
- **Buttons.** `theme.button` has the kind `soft` and the argument `tone` (`"violet"`, `"teal"`). A soft button reads its colours from `--tone-*`, which `.btn-soft` sets to the accent's and a `tone-*` class to its own. The paused Queue sets them to amber.
  - Soft: the Run toolbar's Advanced (blue), Batch (violet) and Queue (teal), Open report and Open folder in the results panel and the Dynamics tab, the Files tab's Open, Details (voltage), Full log, Copy in the log dialog, Add to compare in History and Set penalty on the Network page.
  - `danger` is soft red while it can be clicked (Stop during a run, Delete and Quit in their dialogs). Before, only its text was red.
  - `ghost` turns soft blue on hover instead of grey.
  - `default` stays plain for Cancel and the queue's Pause. A tinted Cancel beside the dialog's primary read as a second action.
  - A soft or danger button that is off is a plain button, faded, so colour means "can be clicked".
- **Other places.** The Julia pill is soft green when Julia is ready. The chosen tab (page tabs, results tabs, dialog tabs) and the chosen segment of a toggle have the accent's text. The line of network modifications and the note over the results tabs are soft blue.

*How it was verified* (test instance on 8090, in a tab of its own): the values were tried by injecting a stylesheet into the page, then written and read after a restart.
- **Run page.** Toolbar at rest and during a run (Stop soft red, Run turned "Add to queue"). The paused Queue's computed colours were the amber ones (`rgb(255, 248, 232)`, text `rgb(135, 90, 0)`). The results panel: the off Open report was plain, Open folder soft blue. The Files tab: soft Open on files that exist and plain on the others. Full log in the strip. A runs-table action turned blue on hover.
- **Batch dialog.** Cancel stayed plain beside "Add 1 run to the queue".
- **History.** Load into Run solid, Add to compare soft blue, the Julia pill soft green, the busy pill amber.
- **Network.** Set penalty plain while nothing is selected and soft blue with zone SECOND selected.

Test folder added: `savnw_flow_shed_gui_test_colors`.
