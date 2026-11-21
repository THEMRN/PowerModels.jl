"""
The results panel of the Run page: the report numbers of one run of the session as tables,
from the run's @@result summary (gui_plan.md, "Result summary").

The summary is in MW and Mvar, already rounded as the console prints, so the panel shows its
numbers as they are. Tabs: Summary, Generation, Load shedding, Boundary flows, Frequency,
Voltage and Files; a tab whose part the run does not have (a security check that was off) is
left out. Load shedding is always there, in two sides: the shed of the optimization before the
event and the UFLS relays' shed in the dynamic simulation after it, each with a sentence in its
place when the run has none. "Results of" switches between the runs that have results.

The `find_*` functions build what each table shows from a summary, without drawing anything,
so a script can check them against the printed reports.
"""

import os
import webbrowser
from pathlib import Path

from nicegui import ui

import advanced
import theme
from components.voltage_details import VoltageDetailsDialog

# ==================== Settings ====================
TAB_LABELS = {                  # tab -> its title, in the order shown
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
FILE_LABELS = {                 # key in the summary's `files` -> what the file is
    "report": "Simulation report",
    "excel": "Excel report",
    "raw": "Solved case (RAW)",
    "settings": "Run record",
}
SOLVED_STATUSES = ("LOCALLY_SOLVED", "OPTIMAL")     # termination statuses shown as good
IMPORT_TOLERANCE = 0.006        # MW, an import this far over its limit is still on it (both are rounded to 0.01 MW)


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


# ==================== What a summary says ====================
def describe_run(record):
    """A run in the selector: its number, case, objective, boundary, output tag and start time."""
    run_settings = record["settings"]
    boundary = run_settings["boundary"]
    if boundary["kind"] == "bus_pairs":
        count = len(boundary["bus_pairs"])
        where = f"{count} bus pair" + ("" if count == 1 else "s")
    else:
        where = f"{boundary['kind']} {boundary['name']}"
    parts = [f"run {record['number']}", Path(run_settings["case"]).name, run_settings["objective"], where]
    if run_settings["output_tag"]:
        parts.append(run_settings["output_tag"])
    parts.append(record["started"])
    return "  ·  ".join(parts)


def find_tabs(summary):
    """The tabs a summary fills, in order: a part that is null (the feature was off) has no tab."""
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
    total = {"name": "Total", "load_mw": load_shed["total_load_mw"], "shed_mw": load_shed["total_shed_mw"], "shed_pct": ""}
    return columns, load_shed["groups"], [total]


def find_shed_bus_table(summary, only_shed=True):
    """(columns, rows, footers) of load and shed by bus; `only_shed` keeps the buses that shed load."""
    columns = [("Bus", "bus", None), ("Load (MW)", "pd_mw", 2), ("Shed (MW)", "shed_mw", 2), ("Shed (%)", "shed_pct", 2)]
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


def describe_missing_ufls(summary):
    """
    Why a run shows no UFLS tables, in a sentence, or None when it has the relays' sheds. A run
    whose summary has no `ufls` key came from a worker older than the UFLS record.
    """
    if "ufls" not in summary:
        return "This run has no UFLS record: Julia was started before the GUI reported the UFLS shed."
    ufls = summary["ufls"]
    if ufls is None:
        return "The dynamic simulation was off for this run, so no UFLS relay could act."
    status = ufls["status"]
    if status == "not_reported":
        return "This run used PSS®E, whose script does not pass the UFLS shed to the GUI. The simulation report has it."
    if status == "no_record":
        return "The simulation left no UFLS record (ufls_shed.json) in the results folder. The simulation report may have it."
    if status == "no_relays":
        return "The case's .dyr file has no UFLS relays (LDSHBL), so the simulation could not shed load."
    if ufls["stages"] == 0:
        return f"No UFLS relay acted in the simulation, which ran to t = {theme.format_number(ufls['end_time_s'], 2)} s."
    return None


def describe_ufls_stages(ufls):
    """How many relay stages acted, at how many buses, and how far the simulation ran."""
    stages = ufls["stages"]
    buses = sum(1 for row in ufls["buses"] if row["stages"] > 0)
    return (
        f"{stages} relay stage" + ("" if stages == 1 else "s") + f" acted at {buses} bus" + ("" if buses == 1 else "es")
        + f"; the simulation ran to t = {theme.format_number(ufls['end_time_s'], 2)} s."
    )


def describe_ufls_fact(summary):
    """The UFLS shed on one line, for the Summary tab."""
    ufls = summary.get("ufls")
    if ufls is None:
        return "not simulated" if "ufls" in summary else "no record"
    texts = {
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
    columns = [("Line", "id", None), ("From", "from", None), ("To", "to", None), ("P (MW)", "p_mw", 2), ("Q (Mvar)", "q_mvar", 2), ("P + Q", "total", 2)]
    rows = [dict(line, total="") for line in flows["lines"]]       # P + Q is printed for the two sums only
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


def find_frequency_table(summary):
    """(columns, rows, footers) of the islands with frequency limits: their inertia, the three limits and the scheduled import."""
    columns = [
        ("Island at bus", "island_bus", None),
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
    for island in summary["frequency"]:
        within, _limit_mw, limit_name = calc_frequency_verdict(island)
        row = dict(island, **island["limits_mw"])
        row["binding_name"] = limit_name
        row["verdict"] = "within the limit" if within else "over the limit"
        rows.append(row)
    return columns, rows, []


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
    return "..." if record["seconds"] is None else format_seconds(record["seconds"])


# ==================== The panel ====================
class ResultsView:
    """
    The results panel of one browser tab. `refresh()` after a change of the runs: it shows the
    results of a run that has just delivered them, and otherwise leaves what is on show alone,
    with its tab and filter. Hidden until a run of the session has results.
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.shown = None           # job id of the run on show
        self.newest = None          # job id of the newest run with results that was seen
        self.tab = "summary"        # the tab on show, kept from run to run
        self.only_shed = True       # the bus table lists only the buses that shed load
        self.only_ufls_shed = True  # the UFLS bus table lists only the buses where a relay acted
        self.setting = False        # the selector is being set from code
        self.options = {}           # the runs the selector lists
        self.run_time = None        # label of the whole-run time, which comes after the results
        self.details = VoltageDetailsDialog()
        with theme.panel() as self.box:
            with theme.toolbar():
                theme.eyebrow("Results of")
                self.selector = ui.select({}, on_change=self._selected).classes("results-run")
                self.modified = theme.toolbar_text()        # the network modifications of the run on show

            @ui.refreshable
            def body():
                self._build_body()

            self.body = body
            body()
        self.refresh()

    def find_records(self):
        """The runs of the session that have results, oldest first."""
        return [record for record in self.ctx.runs.records if record["summary"]]

    def find_shown(self):
        """The record of the run on show, or None."""
        return self.ctx.runs.find(self.shown) if self.shown is not None else None

    def refresh(self):
        """Follow the runs: list those with results, and show the results of a run that has just delivered them."""
        records = self.find_records()
        self.box.set_visibility(bool(records))
        if not records:
            return
        before = self.shown
        if records[-1]["id"] != self.newest:
            self.newest = records[-1]["id"]
            self.shown = self.newest
        options = {record["id"]: describe_run(record) for record in reversed(records)}
        if options != self.options or self.shown != before:     # not at every stage of a run: an open list would close
            self.options = options
            self.setting = True
            try:
                self.selector.set_options(options, value=self.shown)
            finally:
                self.setting = False
        if self.shown != before:
            self.body.refresh()
        elif self.run_time is not None:
            self.run_time.text = describe_run_time(self.find_shown())

    def _selected(self, event):
        if self.setting or event.value is None or event.value == self.shown:
            return
        self.shown = event.value
        self.body.refresh()

    # -------------------- tabs --------------------
    def _build_body(self):
        self.run_time = None
        record = self.find_shown()
        if record is None:
            return
        self.modified.text = describe_modifications(record)
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
                    theme.fact("Report", files["report"] or "not written").classes("" if files["report"] else "muted")
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
        for position, island in enumerate(frequency):
            within, limit_mw, limit_name = calc_frequency_verdict(island)
            theme.fact_label("Frequency" if position == 0 else "")
            text = (
                f"island at bus {island['island_bus']}: import {theme.format_number(island['scheduled_import_mw'], 2)} MW, "
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
        text = ("verified" if voltage["verified"] else "not verified") + f" in {rounds} round" + ("" if rounds == 1 else "s")
        text += f", worst indicator {theme.format_number(voltage['worst_indicator'], 3)}"
        theme.State("finished" if voltage["verified"] else "failed", text)

    def _build_generation(self, record):
        summary = record["summary"]
        with ui.element("div").classes("tab-body"):
            theme.data_table(*find_generation_table(summary))
            if not summary["generation"]["groups"]:
                theme.hint(f"The case has no {summary['generation']['group_kind']} records, so there is only the total.")

    def _build_load_shed(self, record):
        """Two sides: the optimization's shed before the event, then the UFLS relays' shed in the dynamic simulation."""
        summary = record["summary"]
        with ui.element("div").classes("tab-body"), ui.element("div").classes("shed-sides"):
            with ui.element("div").classes("shed-side"):
                ui.label("Before the event: optimization").classes("shed-side-title")
                self._build_pre_event_shed(summary)
            with ui.element("div").classes("shed-side"):
                ui.label("After the event: UFLS relays").classes("shed-side-title")
                self._build_ufls_shed(summary)

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
                        with ui.element("div").classes("table-scroll"):     # a case can have thousands of load buses
                            theme.data_table(columns, rows, footers)
                    else:
                        theme.hint("No bus sheds load.")

                def filter_changed(event):
                    self.only_shed = bool(event.value)
                    bus_table.refresh()

                only_shed.on_value_change(filter_changed)
                bus_table()

    def _build_ufls_shed(self, summary):
        ufls = summary.get("ufls")
        files = summary["files"]
        if ufls is not None and ufls["status"] == "simulated" and ufls["stopped_early"]:
            stopped_at = theme.format_number(ufls["end_time_s"], 2)
            theme.show_hint(theme.hint(), f"The simulation stopped early at t = {stopped_at} s, so this is only the shed up to then.", bad=True)

        missing = describe_missing_ufls(summary)
        if missing is not None:
            theme.hint(missing)
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
            theme.data_table(*find_flow_table(summary))
            theme.hint(describe_flow_sign(summary))

    def _build_frequency(self, record):
        summary = record["summary"]
        with ui.element("div").classes("tab-body"):
            if not summary["frequency"]:
                theme.hint("No island has synchronous inertia, so no frequency limits were added.")
                return
            theme.data_table(*find_frequency_table(summary))
            theme.hint(
                "The scheduled import is positive into the island, the opposite sign of the boundary flows. "
                "The limits hold in both directions, so its size is compared with the limit that binds."
            )

    def _build_voltage(self, record):
        voltage = record["summary"]["voltage"]
        with ui.element("div").classes("tab-body"):
            with theme.facts().style("width: auto"):
                theme.fact_label("Voltage")
                theme.State("finished" if voltage["verified"] else "failed", "verified" if voltage["verified"] else "not verified")
                theme.fact("Rounds", str(voltage["rounds"]))
                theme.fact("Worst indicator", theme.format_number(voltage["worst_indicator"], 3))
                if voltage["details"]:
                    theme.fact("Indicator threshold", str(voltage["details"][0]["indicator_threshold"]))
            with theme.line():
                details_button = theme.button("Details", on_click=lambda: self.details.open(record))
                details_button.set_enabled(bool(voltage["details"]))
                theme.hint("Each round: the islands' state, their largest indicators, the generators at a reactive limit and the sheds sized.")

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
