"""
History page: the runs in results/psse, from the GUI and from the scripts, with filters, a table
sorted by any column, and the details of the run selected. Its report and its folder open from
there, and its settings go back into the Run form.

The rows come from `results_index.py`, which reads the per-run settings files (and the reports
of older runs) and draws nothing. The folder is read when the page is built, on Refresh, and
when a run of this session starts or ends. Nothing is deleted here: the user deletes folders by
hand.
"""

import copy
from datetime import datetime

from nicegui import ui

import advanced
import results_index
import theme
from components.results_view import open_folder, open_report
from components.sortable_table import SortableTable
from settings import OBJECTIVES, format_bus_pairs

# ==================== Settings ====================
TITLE = "History"
NO_VALUE = results_index.NO_VALUE
COLUMNS = [
    {"key": "time", "label": "Time"},
    {"key": "case", "label": "Case"},
    {"key": "objective", "label": "Objective"},
    {"key": "tag", "label": "Tag", "wide": True},
    {"key": "boundary", "label": "Boundary", "wide": True},
    {"key": "lambda", "label": "λ", "numeric": True},
    {"key": "penalties", "label": "Penalties", "wide": True},
    {"key": "shed", "label": "Shed (MW)", "numeric": True},
    {"key": "simulator", "label": "Simulation"},
    {"key": "security", "label": "Security"},
    {"key": "status", "label": "Status"},
    {"key": "report", "label": "Report"},
]
STATUS_CHOICES = {"": "Any status", "finished": "finished", "started": "incomplete", "running": "running", "older": "no settings"}
TONES = {"started": "warn", "older": "muted"}
STATE_DOTS = {"finished": "finished", "started": "failed", "running": "running", "older": "stopped"}      # colour of the status dot


# ==================== What the table and the details say ====================
def build_table_row(row):
    """A row of the table for a row of results_index: texts to show, and values to sort by."""
    return {
        "id": row["id"],
        "tone": TONES.get(row["status"], ""),
        "time": row["time_text"],
        "case": row["case"] or NO_VALUE,
        "objective": row["objective"] or NO_VALUE,
        "tag": row["tag"] or NO_VALUE,
        "boundary": row["boundary"],
        "lambda": results_index.format_number(row["lambda"]),
        "penalties": row["penalties"],
        "shed": results_index.format_number(row["shed_mw"]),
        "simulator": row["simulator"],
        "security": row["security"].replace("frequency", "freq").replace("voltage", "volt"),
        "status": results_index.STATUS_LABELS[row["status"]],
        "report": "report" if row["report"] else NO_VALUE,
        "sort": {"time": row["time"], "lambda": row["lambda"], "shed": row["shed_mw"]},
    }


def describe_seconds(seconds):
    """"solve 19.1 s, simulation 52.0 s, total 80.3 s" from a record's `seconds`."""
    if not seconds:
        return NO_VALUE
    parts = []
    for key, name in (("solve", "solve"), ("dynamic_sim", "simulation"), ("total", "total")):
        if seconds.get(key) is not None:
            parts.append(f"{name} {seconds[key]:.1f} s")
    return ", ".join(parts) or NO_VALUE


def describe_result(summary):
    """The facts of a record's summary: [(name, text)]."""
    if not summary:
        return [("Result", "none: the run did not finish")]
    facts = [("Solver", summary.get("termination_status") or NO_VALUE),
             ("Objective value", NO_VALUE if summary.get("objective") is None else str(summary["objective"])),
             ("Load shed", f"{results_index.format_number(summary.get('preemptive_shed_mw'))} MW")]
    voltage = summary.get("voltage_security")
    if voltage:
        verified = "verified" if voltage.get("verified") else "not verified"
        worst = voltage.get("worst_indicator")
        worst_text = NO_VALUE if worst is None else f"{worst:.3f}"
        facts.append(("Voltage", f"{verified} in {voltage.get('rounds')} rounds, worst indicator {worst_text}"))
    return facts


def describe_settings_row(row):
    """The facts of a run with a settings file: [(name, text)], and notes as sentences."""
    record = row["record"]
    gui_settings = record.get("gui_settings")
    facts = [
        ("Started", format_iso(record.get("started"))),
        ("Finished", format_iso(record.get("finished")) if record.get("finished") else "never"),
        ("Took", describe_seconds(record.get("seconds"))),
        ("Folder", row["folder"]),
        ("Case", row["case_path"] or row["case"]),
        ("Objective", f"{record.get('objective')}, {record.get('opf_model')}, flow penalty {record.get('flow_model')}"),
    ]
    boundary = row["boundary"]
    target_lines = record.get("target_lines") or []
    if gui_settings and gui_settings["boundary"]["kind"] == "bus_pairs":
        boundary = format_bus_pairs(gui_settings["boundary"]["bus_pairs"])
    elif not gui_settings and not any(record.get(f"target_{kind}") for kind in ("zone", "area")):
        boundary = format_bus_pairs(results_index.find_bus_pairs(target_lines))
    facts.append(("Boundary", f"{boundary} ({len(target_lines)} branches)"))
    facts.append(("λ", results_index.format_number(record.get("lambda"))))
    facts.append(("Penalties", row["penalties"]))
    if gui_settings:
        modifications = advanced.describe(gui_settings.get("modifications") or {})
        facts.append(("Modifications", "; ".join(modifications) if modifications else "none"))
    else:
        facts.append(("Modifications", "not recorded"))
    facts.append(("Security", row["security"]))
    facts.append(("Simulation", row["simulator"]))
    facts.extend(describe_result(record.get("summary")))
    files = record.get("files") or {}
    names = [row["file"]] + [files[key] for key in ("excel", "report") if files.get(key)]
    facts.append(("Files", "\n".join(names)))

    notes = []
    if row["status"] == "started":
        notes.append("This run never finished: it failed, was stopped, or is running outside this GUI.")
    elif row["status"] == "running":
        notes.append("This run is running now in this GUI.")
    if gui_settings:
        notes.append("Started from the GUI: Load into Run gives the form these settings as they were.")
    else:
        notes.append("Started from a script (islanding.jl or batch_islanding.jl): Load into Run fills the form with what "
                     "the run recorded. Changes the script made to the network, such as load scaling, are not recorded.")
    if files.get("raw"):
        notes.append(f"The RAW file {files['raw']} is the folder's, and a later run of this folder writes over it.")
    return facts, notes


def describe_report_row(row):
    """The facts of an older run (a report without a settings file): [(name, text)], and notes."""
    facts = [
        ("Report written", row["time_text"]),
        ("Folder", row["folder"]),
        ("Case", row["case"] or NO_VALUE),
        ("Objective", row["objective"] or NO_VALUE),
        ("Tag", row["tag"] or NO_VALUE),
        ("Simulation", row["simulator"]),
        ("Files", row["file"]),
    ]
    notes = ["This run is from before runs kept a settings file, so its settings are not known and it cannot be loaded into the Run form."]
    info = row["run_info"]
    if info:
        facts.extend([
            ("Boundary", row["boundary"]),
            ("Penalties", row["penalties"]),
            ("Load shed", f"{results_index.format_number(row['shed_mw'])} MW"),
            ("Flow penalty", info.get("flow_model") or NO_VALUE),
            ("Security", row["security"]),
        ])
        notes.append("Boundary, penalties, shed and security come from the folder's run_info.json, which this run wrote "
                     "(it was the folder's last run).")
    return facts, notes


def format_iso(iso):
    """"2026-11-21 02:15:52" from an ISO time."""
    return iso.replace("T", " ") if iso else NO_VALUE


# ==================== The page ====================
class HistoryPage:
    """The History page of one browser tab: the runs, the filters, the selected run."""

    def __init__(self, ctx, client_state):
        self.ctx = ctx
        self.client_state = client_state    # of this browser tab: the Run form, the functions that load it and show a page
        self.rows = []                      # every run, from results_index
        self.shown = []                     # the runs that pass the filters
        self.selected = None                # id of the selected run
        self.running = set()                # (number, stages reached) of this session's runs that are running

    # -------------------- layout --------------------
    def build(self):
        with theme.panel().classes("history-panel"):
            with theme.toolbar():
                theme.eyebrow("Runs in results/psse")
                self.count = theme.toolbar_text()
                theme.button("Refresh", icon="refresh", kind="ghost", on_click=self.refresh).tooltip(
                    "Read the results folders again"
                )
            with ui.element("div").classes("history-filters"):
                self.text = ui.input(placeholder="folder or tag", on_change=self._filter).classes("field-text")
                self.case = ui.select({"": "All cases"}, value="", on_change=self._filter).classes("field-choice")
                self.objective = ui.select({"": "All objectives"}, value="", on_change=self._filter).classes("field-choice")
                self.group = ui.select({"": "Any zone or area"}, value="", with_input=True, on_change=self._filter).classes("field-group")
                self.simulator = ui.select({"": "Any simulation"}, value="", on_change=self._filter).classes("field-choice")
                self.status = ui.select(dict(STATUS_CHOICES), value="", on_change=self._filter).classes("field-choice")
                theme.label("From")
                self.date_from = ui.input(on_change=self._filter).props("type=date").classes("field-date")
                theme.label("to")
                self.date_to = ui.input(on_change=self._filter).props("type=date").classes("field-date")
                self.with_report = ui.checkbox("Only with a report", on_change=self._filter)
                theme.button("Clear", kind="ghost", on_click=self._clear_filters).tooltip("Show every run")
            with ui.element("div").classes("history-body"):
                self.table = SortableTable(COLUMNS, order={"key": "time", "descending": True},
                                           empty="No run passes these filters.", on_select=self._select)
                with ui.element("div").classes("history-side"):
                    theme.eyebrow("Run")
                    self.details = ui.element("div").classes("history-details")
                    with theme.line():
                        self.report_button = theme.button("Open report", kind="ghost", on_click=self._open_report)
                        self.folder_button = theme.button("Open folder", kind="ghost", on_click=self._open_folder)
                    self.load_button = theme.button("Load into Run", kind="primary", on_click=self._load_into_run)
        self.refresh()

    # -------------------- reading the folders --------------------
    def refresh(self):
        """Read results/psse again, keeping the filters and the selection."""
        self.rows, unreadable = results_index.scan_results(self.ctx.repo_root)
        running = self.ctx.runs.find_running()
        if running is not None:
            folder = results_index.calc_folder_name(running["settings"])
            since = datetime.fromtimestamp(running["started_at"]).isoformat(timespec="seconds")
            results_index.mark_running(self.rows, folder, since)
        self.unreadable = unreadable
        self._offer_choices()
        self._filter()

    def runs_changed(self):
        """
        A run of this session started, reached a stage or ended: read the folders again, so it
        shows as it is (its settings file is written when it starts to solve). Other changes, such
        as a new log line, do not read them.
        """
        running = {(record["number"], len(record["stages"])) for record in self.ctx.runs.records if record["status"] == "running"}
        if running != self.running:
            self.running = running
            self.refresh()

    def _offer_choices(self):
        """What the filters offer: the cases, objectives, zones and areas, and simulations the runs have."""

        def offer(select, first, values):
            options = dict(first)
            options.update({value: value for value in values})
            select.set_options(options, value=select.value if select.value in options else "")

        offer(self.case, {"": "All cases"}, results_index.find_choices(self.rows, "case"))
        objectives = [objective for objective in OBJECTIVES if any(row["objective"] == objective for row in self.rows)]
        offer(self.objective, {"": "All objectives"}, objectives)
        offer(self.group, {"": "Any zone or area"}, results_index.find_group_choices(self.rows))
        offer(self.simulator, {"": "Any simulation"}, results_index.find_choices(self.rows, "simulator"))

    # -------------------- filters --------------------
    def _filter(self, _event=None):
        self.shown = results_index.filter_rows(
            self.rows, text=self.text.value, case=self.case.value, objective=self.objective.value, group=self.group.value,
            simulator=self.simulator.value, date_from=self.date_from.value or "", date_to=self.date_to.value or "",
            status=self.status.value, with_report=self.with_report.value,
        )
        if self.selected not in {row["id"] for row in self.shown}:
            self.selected = None
        text = f"{len(self.rows)} runs" if len(self.shown) == len(self.rows) else f"{len(self.shown)} of {len(self.rows)} runs"
        if self.unreadable:
            text += f"; {len(self.unreadable)} settings files could not be read"
        self.count.text = text
        self.table.show([build_table_row(row) for row in self.shown], self.selected)
        self._show_details()

    def _clear_filters(self):
        for field in (self.text, self.date_from, self.date_to):
            field.set_value("")
        for select in (self.case, self.objective, self.group, self.simulator, self.status):
            select.set_value("")
        self.with_report.set_value(False)
        self._filter()

    # -------------------- the selected run --------------------
    def _find_selected(self):
        for row in self.shown:
            if row["id"] == self.selected:
                return row
        return None

    def _select(self, row_id):
        self.selected = row_id
        self._show_details()

    def _show_details(self):
        row = self._find_selected()
        self.details.clear()
        with self.details:
            if row is None:
                theme.hint("Click a run in the table to see its settings and results. The arrow keys move up and down.")
            else:
                facts, notes = describe_settings_row(row) if row["kind"] == "settings" else describe_report_row(row)
                with theme.facts():
                    theme.fact_label("Status")
                    theme.State(STATE_DOTS[row["status"]], results_index.STATUS_LABELS[row["status"]])
                    for name, text in facts:
                        theme.fact(name, text)
                for note in notes:
                    theme.hint(note)
        self.report_button.set_enabled(row is not None and bool(row["report"]))
        self.folder_button.set_enabled(row is not None)
        self.load_button.set_enabled(row is not None and row["kind"] == "settings")

    # -------------------- actions --------------------
    def _open_report(self):
        row = self._find_selected()
        if row is not None and row["report"]:
            open_report({"output_path": row["path"], "report": row["report"]})

    def _open_folder(self):
        row = self._find_selected()
        if row is not None:
            open_folder({"output_path": row["path"]})

    async def _load_into_run(self):
        """Put the selected run's settings into the Run form of this browser tab, and show the Run page."""
        row = self._find_selected()
        if row is None or row["kind"] != "settings":
            return
        form = self.client_state.get("run_form")
        if form is None or not form.cases_loaded:
            ui.notify("The Run form is not ready yet: Julia has not given the case list.", position="top")
            return
        case = row["case_path"]
        if case not in (self.ctx.state.get("cases") or []):
            ui.notify(f"The case {case or row['case']} is not in cases/psse, so this run cannot be loaded.", position="top", type="warning")
            return
        record = row["record"]
        notes = []
        if row["from_gui"]:
            run_settings = copy.deepcopy(record["gui_settings"])
        else:
            case_info, error = await form.find_case_info(case)
            if error:
                ui.notify(f"The case could not be read: {error}", position="top", type="warning")
                return
            load_buses = {load["bus"] for load in case_info.get("loads", []) if load["status"] != 0}
            run_settings, notes = results_index.build_settings_from_record(record, case, load_buses)
        self.client_state["show_page"]("Run")
        message = f"The settings of the run of {row['time_text']} ({row['folder']}) are in the form."
        await self.client_state["load_settings"](run_settings, " ".join([message] + notes))


def build(ctx):
    """The History page of one browser tab."""
    page = HistoryPage(ctx, ctx.client_state())
    page.build()
    remove = ctx.runs.on_change(page.runs_changed)
    ui.context.client.on_delete(remove)
