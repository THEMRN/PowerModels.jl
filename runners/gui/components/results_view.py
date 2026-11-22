"""
The results panel of the Run page: the report numbers of one run as tables, from the run's
@@result summary (gui_plan.md, "Result summary"). The run is one of the session's, or one
loaded from History, whose summary the worker kept in its results folder (`result_<ts>.json`).

The summary is in MW and Mvar, already rounded as the console prints, so the panel shows its
numbers as they are. Tabs: Summary, Generation, Load shedding, Boundary flows, Frequency,
Voltage and Files; a tab whose part the run does not have (a security check that was off) is
left out. Load shedding is always there, in two sides: the shed of the optimization before the
event and the UFLS relays' shed in the dynamic simulation after it, each with a sentence in its
place when the run has none. "Results of" switches between the runs: the session's, then those
loaded from History into this browser tab; Clear empties the panel.

A run of the session takes the panel when it starts, so the results of the run before go. It
shows what the solve found as soon as the worker sends it, before the dynamic simulation (a
summary marked `partial`), and the simulation's parts (the UFLS shed, the simulated frequency,
the report) once the final summary replaces it.

The `find_*` functions build what each table shows from a summary, without drawing anything,
so a script can check them against the printed reports.
"""

import os
import webbrowser
from pathlib import Path

from nicegui import ui

import advanced
import theme
from components.voltage_details import VoltageDetailsDialog, describe_size, name_islands

# ==================== Settings ====================
TAB_LABELS = {  # tab -> its title, in the order shown
    "summary": "Summary",
    "generation": "Generation",
    "load_shed": "Load shedding",
    "boundary_flows": "Boundary flows",
    "frequency": "Frequency",
    "voltage": "Voltage",
    "files": "Files",
}
GROUP_LABELS = {"zone": "Zone", "area": "Area"}
LIMIT_LABELS = {"rocof": "RoCoF", "qss": "QSS", "nadir": "nadir"}
FILE_LABELS = {  # key in the summary's `files` -> what the file is
    "report": "Simulation report",
    "excel": "Excel report",
    "raw": "Solved case (RAW)",
    "settings": "Run record",
    "result": "Kept results",
}
HISTORY_KEY = "history:"  # a run loaded from History is keyed by this and its History row id
SOLVED_STATUSES = ("LOCALLY_SOLVED", "OPTIMAL")  # termination statuses shown as good
IMPORT_TOLERANCE = 0.006  # MW, an import this far over its limit is still on it (both are rounded to 0.01 MW)


# ==================== Opening a run's files ====================
def open_path(path, in_browser=False):
    """
    Open a file or a folder of a run: in the browser, or with the program Windows has for it.
    When it is gone, or Windows has no program for it, a notification says so.
    """
    path = Path(path)
    if not path.exists():
        ui.notify(f"{path.name} is not there any more.", type="negative", position="top")
        return
    try:
        if in_browser:
            webbrowser.open(path.as_uri())
        else:
            os.startfile(path)
    except OSError as error:
        ui.notify(f"Windows could not open {path.name}: {error}", type="negative", position="top")


def open_report(files):
    """Open the run's simulation report in the browser."""
    open_path(Path(files["output_path"]) / files["report"], in_browser=True)


def open_folder(files):
    """Open the run's results folder in the file explorer."""
    open_path(files["output_path"])


def open_file(files, key):
    """Open one file of the run with the program Windows has for it; the report goes to the browser."""
    open_path(Path(files["output_path"]) / files[key], in_browser=key == "report")


# ==================== The runs the panel shows ====================
def build_loaded_record(row_id, run_settings, summary, started):
    """
    A run loaded from History, shaped like a session run for the panel: no `number`, the History
    row's id in its key, its settings, its kept summary and its start ("2026-11-21 02:15").
    """
    return {
        "id": HISTORY_KEY + row_id,
        "number": None,
        "settings": run_settings,
        "status": "finished",
        "started": started,
        "seconds": (summary.get("seconds") or {}).get("total"),
        "summary": summary,
    }


def find_session_record(records, folder, settings_file):
    """The run of this session whose results are those of `settings_file` in the results folder named `folder`, or None."""
    for record in records:
        files = (record["summary"] or {}).get("files") or {}
        if files.get("settings") == settings_file and Path(files.get("output_path") or "").name == folder:
            return record
    return None


def describe_run_name(record):
    """ "run 3" for a run of this session, "the run of 2026-11-21 02:15" for one loaded from History."""
    if record["number"] is None:
        return f"the run of {record['started']}"
    return f"run {record['number']}"


# ==================== What a summary says ====================
def describe_partial(record):
    """
    (text, is_bad) of the line over the tabs of a run whose results are those of its solve only,
    sent before its dynamic simulation; ("", False) for a run with its final results.
    """
    if not record.get("partial"):
        return "", False
    if record["status"] == "running":
        return (
            "The results of the solve. The dynamic simulation is running: its UFLS shed, simulated frequency and report come when it ends.",
            False,
        )
    ended = "was stopped" if record["status"] == "stopped" else "failed"
    return (
        f"The run {ended} during its dynamic simulation, so these are the results of the solve only: no UFLS shed, simulated frequency or report.",
        True,
    )


def describe_no_results(record):
    """(text, is_bad, waiting) for a run of the session that has no results (yet)."""
    name = describe_run_name(record).capitalize()
    if record["status"] == "running":
        if record["settings"].get("run_dynamic_sim"):
            return (
                f"{name} is running. Its results show here once it is solved, and those of the dynamic simulation when it ends.",
                False,
                True,
            )
        return f"{name} is running. Its results show here once it is solved.", False, True
    if record["status"] == "stopped":
        return f"{name} was stopped before it was solved, so it has no results.", False, False
    error = (record.get("error") or "").splitlines()[0] if record.get("error") else ""
    return f"{name} failed before it was solved, so it has no results" + (f": {error}" if error else "."), True, False


def describe_run(record):
    """A run in the selector: its number (or History), case, objective, boundary, output tag, start time, and its status unless it finished."""
    run_settings = record["settings"]
    boundary = run_settings["boundary"]
    if boundary["kind"] == "bus_pairs":
        count = len(boundary["bus_pairs"])
        where = f"{count} bus pair" + ("" if count == 1 else "s")
    else:
        where = f"{boundary['kind']} {boundary['name']}"
    first = "History" if record["number"] is None else f"run {record['number']}"
    parts = [first, Path(run_settings["case"]).name, run_settings["objective"], where]
    if run_settings["output_tag"]:
        parts.append(run_settings["output_tag"])
    parts.append(record["started"])
    if record["status"] != "finished":
        parts.append(record["status"])
    return "  ·  ".join(parts)


def find_tabs(summary):
    """
    The tabs a summary fills, in order: a frequency or voltage part that is null (the check was
    off) has no tab. Load shedding is always there, its sides saying when they have nothing.
    """
    optional = ("frequency", "voltage")
    return [tab for tab in TAB_LABELS if tab not in optional or summary.get(tab) is not None]


def find_generation_table(summary):
    """(columns, rows, footers) of generation by zone or area: MW, Mvar and the share of the limit in use."""
    generation = summary["generation"]
    columns = [
        (GROUP_LABELS[generation["group_kind"]], "name", None),
        ("Pg (MW)", "pg_mw", 2),
        ("Pmax (MW)", "pmax_mw", 2),
        ("P used (%)", "p_used_pct", 2),
        ("Qg (Mvar)", "qg_mvar", 2),
        ("Qmax (Mvar)", "qmax_mvar", 2),
        ("Q used (%)", "q_used_pct", 2),
    ]
    total = dict(generation["total"], name="Total")
    return columns, generation["groups"], [total]


def find_shed_group_table(summary):
    """(columns, rows, footers) of load and shed by zone or area."""
    load_shed = summary["load_shed"]
    columns = [
        (GROUP_LABELS[load_shed["group_kind"]], "name", None),
        ("Load (MW)", "load_mw", 2),
        ("Shed (MW)", "shed_mw", 2),
        ("Shed (%)", "shed_pct", 2),
    ]
    total = {
        "name": "Total",
        "load_mw": load_shed["total_load_mw"],
        "shed_mw": load_shed["total_shed_mw"],
        "shed_pct": "",
    }
    return columns, load_shed["groups"], [total]


def find_shed_bus_table(summary, only_shed=True):
    """(columns, rows, footers) of load and shed by bus; `only_shed` keeps the buses that shed load."""
    columns = [
        ("Bus", "bus", None),
        ("Load (MW)", "pd_mw", 2),
        ("Shed (MW)", "shed_mw", 2),
        ("Shed (%)", "shed_pct", 2),
    ]
    rows = summary["load_shed"]["buses"]
    if only_shed:
        rows = [row for row in rows if row["shed_mw"] > 0]
    return columns, rows, []


def find_ufls_group_table(summary):
    """(columns, rows, footers) of the UFLS shed by zone or area, against the load in service when the lines opened."""
    ufls = summary["ufls"]
    columns = [
        (GROUP_LABELS[ufls["group_kind"]], "name", None),
        ("Load (MW)", "load_mw", 2),
        ("Shed (MW)", "shed_mw", 2),
        ("Shed (%)", "shed_pct", 2),
        ("Stages", "stages", 0),
    ]
    total = {
        "name": "Total",
        "load_mw": ufls["total_load_mw"],
        "shed_mw": ufls["total_shed_mw"],
        "shed_pct": ufls["total_shed_pct"],
        "stages": ufls["stages"],
    }
    return columns, ufls["groups"], [total]


def find_ufls_bus_table(summary, only_shed=True):
    """(columns, rows, footers) of the UFLS shed by bus; `only_shed` keeps the buses where a relay acted."""
    columns = [
        ("Bus", "bus", None),
        ("Load (MW)", "pd_mw", 2),
        ("Shed (MW)", "shed_mw", 2),
        ("Shed (%)", "shed_pct", 2),
        ("Stages", "stages", 0),
    ]
    rows = summary["ufls"]["buses"]
    if only_shed:
        rows = [row for row in rows if row["stages"] > 0]
    return columns, rows, []


def describe_missing_ufls(summary, running=True):
    """
    Why a run shows no UFLS tables, in a sentence, or None when it has the relays' sheds. A run
    whose summary has no `ufls` key came from a worker older than the UFLS record. `running`
    says whether a run whose simulation is "pending" is still going.
    """
    if "ufls" not in summary:
        return "This run has no UFLS record: Julia was started before the GUI reported the UFLS shed."
    ufls = summary["ufls"]
    if ufls is None:
        return "The dynamic simulation was off for this run, so no UFLS relay could act."
    status = ufls["status"]
    if status == "pending":
        if running:
            return "The dynamic simulation is running: the UFLS relays' shed shows here when it ends."
        return "The run ended before its dynamic simulation did, so there is no UFLS shed."
    if status == "not_reported":
        return "This run used PSS®E, whose script does not pass the UFLS shed to the GUI. The simulation report has it."
    if status == "no_record":
        return "The simulation left no UFLS record (ufls_shed.json) in the results folder. The simulation report may have it."
    if status == "no_relays":
        return "The case's .dyr file has no UFLS relays (LDSHBL), so the simulation could not shed load."
    if ufls["stages"] == 0:
        return (
            f"No UFLS relay acted in the simulation, which ran to t = {theme.format_number(ufls['end_time_s'], 2)} s."
        )
    return None


def describe_ufls_stages(ufls):
    """How many relay stages acted, at how many buses, and how far the simulation ran."""
    stages = ufls["stages"]
    buses = sum(1 for row in ufls["buses"] if row["stages"] > 0)
    return (
        f"{stages} relay stage"
        + ("" if stages == 1 else "s")
        + f" acted at {buses} bus"
        + ("" if buses == 1 else "es")
        + f"; the simulation ran to t = {theme.format_number(ufls['end_time_s'], 2)} s."
    )


def describe_ufls_fact(summary):
    """The UFLS shed on one line, for the Summary tab."""
    ufls = summary.get("ufls")
    if ufls is None:
        return "not simulated" if "ufls" in summary else "no record"
    texts = {
        "pending": "after the dynamic simulation",
        "not_reported": "PSS®E: in the simulation report",
        "no_record": "no record",
        "no_relays": "no UFLS relays in the .dyr",
    }
    if ufls["status"] in texts:
        return texts[ufls["status"]]
    text = f"{theme.format_number(ufls['total_shed_mw'], 2)} MW"
    if ufls["stopped_early"]:
        text += f" (simulation stopped at t = {theme.format_number(ufls['end_time_s'], 2)} s)"
    return text


def find_flow_table(summary):
    """(columns, rows, footers) of the boundary lines' flows, with the net flow and the sum of absolute flows."""
    flows = summary["boundary_flows"]
    columns = [
        ("Line", "id", None),
        ("From", "from", None),
        ("To", "to", None),
        ("P (MW)", "p_mw", 2),
        ("Q (Mvar)", "q_mvar", 2),
        ("P + Q", "total", 2),
    ]
    rows = [dict(line, total="") for line in flows["lines"]]  # P + Q is printed for the two sums only
    footers = [dict(flows["net"], id="Net flow"), dict(flows["abs_sum"], id="Sum of absolute flows")]
    return columns, rows, footers


def describe_flow_sign(summary):
    """Where the boundary flows are measured and which way is positive."""
    if summary["boundary_flows"]["oriented"]:
        kind = summary["generation"]["group_kind"]
        return f"Each line is measured at its end inside the {kind} (From) and is positive leaving the {kind}."
    return "Each line is measured at its From end, as in the case file."


def calc_frequency_verdict(island):
    """(within, limit_mw, limit_name): whether the island's scheduled import, in either direction, is within its binding limit."""
    limit_mw = island["limits_mw"][island["binding"]]
    within = abs(island["scheduled_import_mw"]) <= limit_mw + IMPORT_TOLERANCE
    return within, limit_mw, LIMIT_LABELS.get(island["binding"], island["binding"])


def find_frequency_names(summary):
    """The names of the islands with frequency limits, in their order: by the run's target zone or area (name_islands)."""
    islands = [(island["island_bus"], island["n_buses"]) for island in summary["frequency"]]
    return name_islands(summary.get("target"), islands)


def find_frequency_table(summary):
    """(columns, rows, footers) of the islands with frequency limits: their name and size, inertia, the three limits and the scheduled import."""
    columns = [
        ("Island", "name", None),
        ("Buses", "n_buses", 0),
        ("Generators", "gens", 0),
        ("With governor", "governors", 0),
        ("H (s)", "H", 3),
        ("K (pu)", "K", 3),
        ("D (pu)", "D", 3),
        ("RoCoF limit (MW)", "rocof", 2),
        ("QSS limit (MW)", "qss", 2),
        ("Nadir limit (MW)", "nadir", 2),
        ("Binding", "binding_name", None),
        ("Scheduled import (MW)", "scheduled_import_mw", 2),
        ("Verdict", "verdict", None),
    ]
    rows = []
    for island, name in zip(summary["frequency"], find_frequency_names(summary)):
        within, _limit_mw, limit_name = calc_frequency_verdict(island)
        row = dict(island, **island["limits_mw"])
        row["name"] = name
        row["binding_name"] = limit_name
        row["verdict"] = "within the limit" if within else "over the limit"
        rows.append(row)
    return columns, rows, []


def find_nadir_table(summary):
    """
    (columns, rows, footers) of each island's frequency once the lines open: its nadir (an island
    that imports) or peak (one that exports), the limit the nadir limit holds it to, the SFR
    model's prediction and the dynamic simulation's value with where and when it came. Empty rows
    for a run kept before the worker predicted it.
    """
    columns = [
        ("Island", "name", None),
        ("Frequency", "extreme", None),
        ("Limit (Hz)", "limit_hz", 3),
        ("Predicted (Hz)", "predicted_hz", 3),
        ("Simulated (Hz)", "simulated_hz", 3),
        ("At bus", "simulated_bus", None),
        ("At t (s)", "simulated_time_s", 2),
    ]
    rows = []
    for island, name in zip(summary["frequency"], find_frequency_names(summary)):
        if "predicted_hz" not in island:
            return columns, [], []
        rows.append(dict(island, name=name, simulated_bus=island["simulated_bus"] or theme.NO_VALUE))
    return columns, rows, []


def describe_frequency_simulation(summary, running=True):
    """
    (text, is_bad) on where the simulated frequency stands: why there is none, or that the
    simulation stopped early; ("", False) when the simulated values are all there.
    """
    if "frequency_simulation" not in summary:
        return "This run was kept before the GUI took the nadir from the simulation.", False
    simulation = summary["frequency_simulation"]
    if simulation is None:
        return "The dynamic simulation was off, so there is no simulated frequency.", False
    status = simulation["status"]
    if status == "pending":
        if running:
            return "The dynamic simulation is running: the simulated frequency shows here when it ends.", False
        return "The run ended before its dynamic simulation did, so there is no simulated frequency.", False
    if status == "not_reported":
        return (
            "This run used PSS®E, whose script does not pass the frequency to the GUI. The simulation report has it.",
            False,
        )
    if status == "no_record":
        return "The simulation left no frequency record (frequency_stats.json) in the results folder.", False
    if simulation["stopped_early"]:
        return (
            f"The simulation stopped early at t = {theme.format_number(simulation['end_time_s'], 2)} s, so the simulated values are those up to then.",
            True,
        )
    return "", False


def describe_nadir_sources(summary):
    """What the predicted and the simulated frequencies are, with the time the lines open when it is known."""
    simulation = summary.get("frequency_simulation") or {}
    event = (
        f" The lines open at t = {theme.format_number(simulation['event_time_s'], 2)} s."
        if simulation.get("status") == "simulated"
        else ""
    )
    return (
        "Predicted: the island's one frequency in the SFR model of the frequency limits, when it loses its scheduled import; "
        "the nadir limit keeps it from passing the limit (the first UFLS stage, or as far above 60 Hz for a peak). "
        "Simulated: the lowest (for a peak, the highest) frequency of the island's buses in the dynamic simulation, "
        "which also has local swings, the UFLS relays and generator trips." + event
    )


def find_file_rows(summary):
    """The run's files as [(key, what it is, file name or None)], the folder not among them."""
    files = summary["files"]
    return [(key, label, files.get(key)) for key, label in FILE_LABELS.items()]


def describe_modifications(record):
    """What a run changed in the network before solving, on one line; empty when it changed nothing."""
    texts = advanced.describe(record["settings"].get("modifications") or {})
    return "network modified:  " + "  ·  ".join(texts) if texts else ""


def format_seconds(seconds):
    return theme.NO_VALUE if seconds is None else f"{seconds:.2f} s"


def describe_run_time(record):
    """The time Julia took for the whole run, as the runs table shows it; it is known when the run has ended."""
    if record["seconds"] is None:
        return "..." if record["status"] == "running" else theme.NO_VALUE
    return format_seconds(record["seconds"])


# ==================== The panel ====================
def find_version(record):
    """What the panel draws of a run; it draws it again when this changes: its results come (first those of the solve, then the final ones), or it ends."""
    if record is None:
        return None
    return record["id"], id(record["summary"]), record["status"]


class ResultsView:
    """
    The results panel of one browser tab. `refresh()` after a change of the runs: a run that has
    just started takes the panel, and the run on show is drawn again when its results come or it
    ends; otherwise what is on show stays, with its tab and filter. `show(record)` shows a run:
    one of the session's, or one loaded from History (`build_loaded_record`), which the tab keeps
    in its list. `clear()` empties the panel. Hidden until there is a run to show.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.loaded = []  # runs loaded from History into this tab, oldest first, once each
        self.shown = None  # key (`id`) of the run on show
        self.drawn = None  # what the body holds (find_version of the run drawn)
        self.newest = None  # job id of the newest session run that was seen
        self.cleared = False  # Clear was pressed: no run on show until one is chosen or loaded, or a new run starts
        self.tab = "summary"  # the tab on show, kept from run to run
        self.only_shed = True  # the bus table lists only the buses that shed load
        self.only_ufls_shed = True  # the UFLS bus table lists only the buses where a relay acted
        self.setting = False  # the selector is being set from code
        self.options = {}  # the runs the selector lists
        self.run_time = None  # label of the whole-run time, which comes after the results
        self.details = VoltageDetailsDialog()
        with theme.panel() as self.box:
            with theme.toolbar():
                theme.eyebrow("Results of")
                self.selector = ui.select({}, on_change=self._selected).classes("results-run")
                self.clear_button = theme.button("Clear", kind="ghost", small=True, on_click=self.clear).classes(
                    "btn-clear"
                )
                with self.clear_button:
                    self.clear_tooltip = ui.tooltip()  # what Clear does, or why it is off
                self.modified = theme.toolbar_text()  # the network modifications of the run on show

            @ui.refreshable
            def body():
                self._build_body()

            self.body = body
            body()
        self.refresh()

    def find_session_records(self):
        """The runs of the session, oldest first: with their results, or a sentence on why they have none (yet)."""
        return list(self.ctx.runs.records)

    def find_records(self):
        """The runs the selector lists, in its order: the session's newest first, then those loaded from History newest first."""
        return list(reversed(self.find_session_records())) + list(reversed(self.loaded))

    def find_shown(self):
        """The record of the run on show, or None."""
        for record in self.find_records():
            if record["id"] == self.shown:
                return record
        return None

    def refresh(self):
        """Follow the runs: a run that has just started takes the panel (the results on show go), and the run on show is drawn again when its results come."""
        session_records = self.find_session_records()
        if session_records and session_records[-1]["id"] != self.newest:
            self.newest = session_records[-1]["id"]
            self.shown = self.newest
            self.cleared = False
        self._update()

    def show(self, record):
        """Show the results of a run: a session run, or a run loaded from History, which joins the list."""
        if record["number"] is None:
            self.loaded = [old for old in self.loaded if old["id"] != record["id"]]
            self.loaded.append(record)
        self.shown = record["id"]
        self.cleared = False
        self._update()

    def clear(self):
        """Empty the panel: no run on show until one is chosen in the list or loaded, or a new run starts. Not during a run."""
        if self.ctx.runs.find_running() is not None:  # a click that came before the button was turned off
            return
        self.shown = None
        self.cleared = True
        self._update()

    def _update(self):
        """List the runs, show the panel when there is one, and draw the run on show when it changed since it was drawn."""
        records = self.find_records()
        self.box.set_visibility(bool(records))
        if not records:
            return
        if self.find_shown() is None and not self.cleared:
            self.shown = records[0]["id"]
        options = {record["id"]: describe_run(record) for record in records}
        if (
            options != self.options or self.selector.value != self.shown
        ):  # not at every stage of a run: an open list would close
            self.options = options
            self.setting = True
            try:
                self.selector.set_options(options, value=self.shown)
            finally:
                self.setting = False
        self.show_clear()
        record = self.find_shown()
        if find_version(record) != self.drawn:
            self.body.refresh()
        elif self.run_time is not None:
            self.run_time.text = describe_run_time(record)

    def show_clear(self):
        """Clear is off while a run is in progress (its results are on their way to the panel) and while the panel is empty."""
        running = self.ctx.runs.find_running()
        if running is not None:
            self.clear_button.set_enabled(False)
            self.clear_tooltip.text = f"Run {running['number']} is in progress: its results come here as it goes"
        elif self.shown is None:
            self.clear_button.set_enabled(False)
            self.clear_tooltip.text = "The panel is empty"
        else:
            self.clear_button.set_enabled(True)

    def _selected(self, event):
        if self.setting or event.value is None or event.value == self.shown:
            return
        self.shown = event.value
        self.cleared = False
        self._update()

    # -------------------- tabs --------------------
    def _build_body(self):
        self.run_time = None
        record = self.find_shown()
        self.drawn = find_version(record)
        self.modified.text = "" if record is None else describe_modifications(record)
        if record is None:
            with ui.element("div").classes("tab-body"):
                theme.hint("Cleared. Choose a run in the list to see its results again.")
            return
        if not record["summary"]:
            text, is_bad, waiting = describe_no_results(record)
            with ui.element("div").classes("tab-body"):
                theme.show_hint(theme.hint(), text, bad=is_bad, waiting=waiting)
            return
        note, is_bad = describe_partial(record)
        if note:
            with ui.element("div").classes("results-note"):
                theme.show_hint(theme.hint(), note, bad=is_bad, waiting=not is_bad)
        names = find_tabs(record["summary"])
        if self.tab not in names:
            self.tab = "summary"
        with ui.tabs(value=self.tab, on_change=self._tab_changed).classes("results-tabs w-full") as tabs:
            for name in names:
                ui.tab(name, label=TAB_LABELS[name])
        with ui.tab_panels(tabs, value=self.tab, animated=False).classes("w-full"):
            for name in names:
                with ui.tab_panel(name):
                    getattr(self, f"_build_{name}")(record)

    def _tab_changed(self, event):
        if event.value:
            self.tab = event.value

    def _build_summary(self, record):
        summary = record["summary"]
        with theme.sheet().classes("plain w-full"):
            with theme.Section("Solution"), theme.facts():
                status = summary["termination_status"]
                theme.fact_label("Status")
                theme.State("finished" if status in SOLVED_STATUSES else "failed", status)
                objective = summary["objective"]
                theme.fact("Objective", theme.NO_VALUE if objective is None else str(objective))
                seconds = summary["seconds"] or {}
                theme.fact("Solve", format_seconds(seconds.get("solve")))
                if seconds.get("dynamic_sim") is not None:
                    theme.fact("Dynamic simulation", format_seconds(seconds["dynamic_sim"]))
                elif record.get("partial"):
                    theme.fact(
                        "Dynamic simulation", "running..." if record["status"] == "running" else "did not end"
                    ).classes("muted")
                self.run_time = theme.fact("Whole run", describe_run_time(record))

            with theme.Section("Load and boundary"):
                with theme.facts():
                    load_shed = summary["load_shed"]
                    if load_shed is None:
                        theme.fact("Load shed", "none: the objective sheds no load").classes("muted")
                    else:
                        theme.fact("Total load", f"{theme.format_number(load_shed['total_load_mw'], 2)} MW")
                        theme.fact("Load shed", f"{theme.format_number(load_shed['total_shed_mw'], 2)} MW")
                    ufls = summary.get("ufls")
                    simulated = ufls is not None and ufls["status"] == "simulated"
                    theme.fact("UFLS shed", describe_ufls_fact(summary)).classes("" if simulated else "muted")
                    flows = summary["boundary_flows"]
                    theme.fact("Net flow P", f"{theme.format_number(flows['net']['p_mw'], 2)} MW")
                    theme.fact("Net flow Q", f"{theme.format_number(flows['net']['q_mvar'], 2)} Mvar")
                    theme.fact("Sum of |P|", f"{theme.format_number(flows['abs_sum']['p_mw'], 2)} MW")
                    theme.fact("Sum of |Q|", f"{theme.format_number(flows['abs_sum']['q_mvar'], 2)} Mvar")
                theme.hint(describe_flow_sign(summary))

            with theme.Section("Security"):
                with theme.facts():
                    self._build_frequency_facts(summary)
                    self._build_voltage_facts(summary)

            with theme.Section("Output"):
                files = summary["files"]
                with theme.facts():
                    theme.fact("Folder", Path(files["output_path"]).name).tooltip(files["output_path"])
                    no_report = (
                        "written when the simulation ends"
                        if record.get("partial") and record["status"] == "running"
                        else "not written"
                    )
                    theme.fact("Report", files["report"] or no_report).classes("" if files["report"] else "muted")
                with theme.line():
                    report_button = theme.button("Open report", on_click=lambda: open_report(files))
                    report_button.set_enabled(bool(files["report"]))
                    theme.button("Open folder", on_click=lambda: open_folder(files))

    def _build_frequency_facts(self, summary):
        """Per island: the scheduled import against the limit that binds."""
        frequency = summary["frequency"]
        if frequency is None:
            theme.fact("Frequency", "not checked").classes("muted")
            return
        if not frequency:
            theme.fact("Frequency", "no island has inertia, no limits").classes("muted")
            return
        for position, (island, name) in enumerate(zip(frequency, find_frequency_names(summary))):
            within, limit_mw, limit_name = calc_frequency_verdict(island)
            theme.fact_label("Frequency" if position == 0 else "")
            text = (
                f"{name} ({describe_size(island['n_buses'])}): import {theme.format_number(island['scheduled_import_mw'], 2)} MW, "
                f"limit {theme.format_number(limit_mw, 2)} MW ({limit_name})"
            )
            theme.State("finished" if within else "failed", text).tooltip(
                "Scheduled import, positive into the island (the opposite sign of the boundary flows); the limit holds in both directions"
            )

    def _build_voltage_facts(self, summary):
        voltage = summary["voltage"]
        if voltage is None:
            theme.fact("Voltage", "not checked").classes("muted")
            return
        rounds = voltage["rounds"]
        theme.fact_label("Voltage")
        text = (
            ("verified" if voltage["verified"] else "not verified")
            + f" in {rounds} round"
            + ("" if rounds == 1 else "s")
        )
        text += f", worst indicator {theme.format_number(voltage['worst_indicator'], 3)}"
        theme.State("finished" if voltage["verified"] else "failed", text)

    def _build_generation(self, record):
        summary = record["summary"]
        with ui.element("div").classes("tab-body"):
            theme.data_table(*find_generation_table(summary))
            if not summary["generation"]["groups"]:
                theme.hint(
                    f"The case has no {summary['generation']['group_kind']} records, so there is only the total."
                )

    def _build_load_shed(self, record):
        """Two sides: the optimization's shed before the event, then the UFLS relays' shed in the dynamic simulation."""
        summary = record["summary"]
        with ui.element("div").classes("tab-body"), ui.element("div").classes("shed-sides"):
            with ui.element("div").classes("shed-side"):
                ui.label("Before the event: optimization").classes("shed-side-title")
                self._build_pre_event_shed(summary)
            with ui.element("div").classes("shed-side"):
                ui.label("After the event: UFLS relays").classes("shed-side-title")
                self._build_ufls_shed(summary, running=record["status"] == "running")

    def _build_pre_event_shed(self, summary):
        if summary["load_shed"] is None:
            theme.hint("The objective sheds no load, so all of it is in service when the lines open.")
            return
        kind = summary["load_shed"]["group_kind"]
        theme.hint("The preemptive shed of the solution, in % of the case's load.")
        with ui.element("div").classes("tables"):
            with ui.element("div").classes("table-block"):
                theme.eyebrow(f"By {kind}")
                theme.data_table(*find_shed_group_table(summary))
            with ui.element("div").classes("table-block"):
                with theme.line():
                    theme.eyebrow("By bus")
                    only_shed = ui.checkbox("only buses with shed", value=self.only_shed)

                @ui.refreshable
                def bus_table():
                    columns, rows, footers = find_shed_bus_table(summary, self.only_shed)
                    if rows:
                        with ui.element("div").classes("table-scroll"):  # a case can have thousands of load buses
                            theme.data_table(columns, rows, footers)
                    else:
                        theme.hint("No bus sheds load.")

                def filter_changed(event):
                    self.only_shed = bool(event.value)
                    bus_table.refresh()

                only_shed.on_value_change(filter_changed)
                bus_table()

    def _build_ufls_shed(self, summary, running):
        ufls = summary.get("ufls")
        files = summary["files"]
        if ufls is not None and ufls["status"] == "simulated" and ufls["stopped_early"]:
            stopped_at = theme.format_number(ufls["end_time_s"], 2)
            theme.show_hint(
                theme.hint(),
                f"The simulation stopped early at t = {stopped_at} s, so this is only the shed up to then.",
                bad=True,
            )

        missing = describe_missing_ufls(summary, running)
        if missing is not None:
            pending = ufls is not None and ufls["status"] == "pending" and running
            theme.show_hint(theme.hint(), missing, waiting=pending)
            if ufls is not None and ufls["status"] in ("not_reported", "no_record") and files["report"]:
                with theme.line():
                    theme.button("Open report", on_click=lambda: open_report(files))
            return

        kind = ufls["group_kind"]
        theme.hint(describe_ufls_stages(ufls))
        with ui.element("div").classes("tables"):
            with ui.element("div").classes("table-block"):
                theme.eyebrow(f"By {kind}")
                theme.data_table(*find_ufls_group_table(summary))
            with ui.element("div").classes("table-block"):
                with theme.line():
                    theme.eyebrow("By bus")
                    only_shed = ui.checkbox("only buses with shed", value=self.only_ufls_shed)

                @ui.refreshable
                def bus_table():
                    columns, rows, footers = find_ufls_bus_table(summary, self.only_ufls_shed)
                    with ui.element("div").classes("table-scroll"):
                        theme.data_table(columns, rows, footers)

                def filter_changed(event):
                    self.only_ufls_shed = bool(event.value)
                    bus_table.refresh()

                only_shed.on_value_change(filter_changed)
                bus_table()
        theme.hint(
            "Load is what was in service when the lines opened, after the preemptive shed. Shed (MW) is at 1 pu "
            "voltage, as the relays and the simulation report give it, and Shed (%) is the share of the load the "
            "relays tripped. Stages counts the relay stages that acted."
        )

    def _build_boundary_flows(self, record):
        summary = record["summary"]
        with ui.element("div").classes("tab-body"):
            theme.data_table(*find_flow_table(summary), totals_on_top=True)
            theme.hint(describe_flow_sign(summary))

    def _build_frequency(self, record):
        """The islands' limits on their import, then their frequency once the lines open: predicted, and simulated."""
        summary = record["summary"]
        running = record["status"] == "running"
        with ui.element("div").classes("tab-body"):
            if not summary["frequency"]:
                theme.hint("No island has synchronous inertia, so no frequency limits were added.")
                return
            with ui.element("div").classes("table-block"):
                theme.eyebrow("Limits on the import")
                theme.data_table(*find_frequency_table(summary))
                theme.hint(
                    "The scheduled import is positive into the island, the opposite sign of the boundary flows. "
                    "The limits hold in both directions, so its size is compared with the limit that binds."
                )

            with ui.element("div").classes("table-block"):
                theme.eyebrow("Frequency when the lines open: nadir, or peak for an island that exports")
                columns, rows, footers = find_nadir_table(summary)
                if not rows:
                    theme.hint("This run was kept before the GUI predicted the nadir.")
                    return
                text, is_bad = describe_frequency_simulation(summary, running)
                pending = (summary.get("frequency_simulation") or {}).get("status") == "pending" and running
                theme.show_hint(theme.hint(), text, bad=is_bad, waiting=pending)
                theme.data_table(columns, rows, footers)
                theme.hint(describe_nadir_sources(summary))

    def _build_voltage(self, record):
        voltage = record["summary"]["voltage"]
        with ui.element("div").classes("tab-body"):
            with theme.facts().style("width: auto"):
                theme.fact_label("Voltage")
                theme.State(
                    "finished" if voltage["verified"] else "failed",
                    "verified" if voltage["verified"] else "not verified",
                )
                theme.fact("Rounds", str(voltage["rounds"]))
                theme.fact("Worst indicator", theme.format_number(voltage["worst_indicator"], 3))
                if voltage["details"]:
                    theme.fact("Indicator threshold", str(voltage["details"][0]["indicator_threshold"]))
            with theme.line():
                details_button = theme.button(
                    "Details", on_click=lambda: self.details.open(record, describe_run_name(record))
                )
                details_button.set_enabled(bool(voltage["details"]))
                theme.hint(
                    "Each round: the islands' state, their largest indicators, the generators at a reactive limit and the sheds sized."
                )

    def _build_files(self, record):
        files = record["summary"]["files"]
        with ui.element("div").classes("tab-body"):
            with ui.element("div").classes("file-list"):
                theme.fact_label("Folder")
                ui.label(files["output_path"]).classes("file-name")
                theme.button("Open", small=True, on_click=lambda: open_folder(files))
                for key, label, name in find_file_rows(record["summary"]):
                    theme.fact_label(label)
                    ui.label(name or "not written").classes("file-name" if name else "fact-value muted")
                    open_button = theme.button("Open", small=True, on_click=lambda key=key: open_file(files, key))
                    open_button.set_enabled(bool(name))
