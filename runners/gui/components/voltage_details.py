"""
The details of a run's voltage security check, as tables in a dialog (gui_plan.md, decision 10).
One block per round of the loop between the optimizer and the indicator, each with four tables:
the islands' state, their largest indicators, their generators at a reactive limit, and the
sheds that were sized. The numbers come from `voltage` -> `details` of the run's @@result
summary: MW and Mvar to 2 decimals, voltages (pu) and indicators to 3.

The `find_*` functions build what each table shows from one round, without drawing anything.
"""

from nicegui import ui

import theme

# ==================== Settings ====================
ISLAND_STATUS = {               # island status -> what the table says
    "checked": "checked",
    "no_generator": "no generator, not checked",
    "power_flow_failed": "power flow failed, not verified",
}


# ==================== What a round says ====================
def find_checked_islands(voltage_round):
    """The islands of a round whose state was computed."""
    return [island for island in voltage_round["islands"] if island["status"] == "checked"]


def find_island_table(voltage_round):
    """(columns, rows, footers) of every island: its size, what holds its voltage, its slack and its worst indicator."""
    columns = [
        ("Island at bus", "bus", None),
        ("Buses", "n_buses", 0),
        ("With generation", "n_with_generation", 0),
        ("Holding voltage", "n_holding_voltage", 0),
        ("Slack bus", "slack_bus", None),
        ("Slack P (MW)", "slack_pg_mw", 2),
        ("Slack Q (Mvar)", "slack_qg_mvar", 2),
        ("Worst indicator", "worst_indicator", 3),
        ("State", "state", None),
    ]
    rows = [dict(island, state=ISLAND_STATUS.get(island["status"], island["status"])) for island in voltage_round["islands"]]
    return columns, rows, []


def find_indicator_table(voltage_round):
    """(columns, rows, footers) of each checked island's largest indicators, with the bus voltage and load."""
    columns = [("Island at bus", "island", None), ("Indicator", "value", 3), ("Bus", "bus", None), ("V (pu)", "vm", 3), ("Load (MW)", "pd_mw", 2)]
    rows = []
    for island in find_checked_islands(voltage_round):
        for indicator in island["largest_indicators"]:
            rows.append(dict(indicator, island=island["bus"]))
    return columns, rows, []


def find_limit_table(voltage_round):
    """(columns, rows, footers) of each checked island's generators at a reactive limit, as lists of bus numbers."""
    columns = [("Island at bus", "island", None), ("At upper limit", "upper", None), ("At lower limit", "lower", None)]
    rows = []
    for island in find_checked_islands(voltage_round):
        rows.append({
            "island": island["bus"],
            "upper": ", ".join(str(bus) for bus in island["at_upper_limit"]) or "none",
            "lower": ", ".join(str(bus) for bus in island["at_lower_limit"]) or "none",
        })
    return columns, rows, []


def find_shed_table(voltage_round):
    """(columns, rows, footers) of the sheds sized in a round, with the indicator predicted after each island's sheds."""
    columns = [
        ("Island at bus", "island", None),
        ("Shed at bus", "bus", None),
        ("Shed (MW)", "shed_mw", 2),
        ("Of load (MW)", "of_mw", 2),
        ("Indicator after", "indicator_after", 3),
        ("At bus", "indicator_after_bus", None),
    ]
    rows = []
    for island in find_checked_islands(voltage_round):
        shed = island["shed"]
        if shed is None:
            continue
        for sized in shed["sheds"]:
            rows.append(dict(sized, island=island["bus"], indicator_after=shed["indicator_after"], indicator_after_bus=shed["indicator_after_bus"]))
    return columns, rows, []


def describe_round(voltage_round):
    """A round's title line, as the console prints it."""
    return f"optimization {voltage_round['termination_status']}, indicator threshold {voltage_round['indicator_threshold']}"


# ==================== The dialog ====================
class VoltageDetailsDialog:
    """One dialog of a browser tab, filled for a run when it opens: `open(record)`."""

    def __init__(self):
        self.dialog, box = theme.dialog()
        with box:
            with theme.toolbar():
                self.title = ui.label().classes("dialog-title")
                self.result = theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close).tooltip("Close")
            self.body = ui.element("div").classes("dialog-body")

    def open(self, record):
        """Show the rounds of the run's voltage security check."""
        voltage = record["summary"]["voltage"]
        rounds = voltage["rounds"]
        self.title.text = f"Voltage security of run {record['number']}"
        self.result.text = (
            ("verified" if voltage["verified"] else "not verified")
            + f" in {rounds} round" + ("" if rounds == 1 else "s")
            + f", worst indicator {theme.format_number(voltage['worst_indicator'], 3)}"
        )
        self.body.clear()
        with self.body:
            for voltage_round in voltage["details"]:
                self._build_round(voltage_round)
        self.dialog.open()

    def _build_round(self, voltage_round):
        with ui.element("div").classes("round"):
            with theme.line():
                ui.label(f"Round {voltage_round['round']}").classes("round-title")
                theme.hint(describe_round(voltage_round))
            self._build_block("Islands", find_island_table(voltage_round))
            with ui.element("div").classes("tables"):
                self._build_block("Largest indicators", find_indicator_table(voltage_round))
                self._build_block("Sheds sized", find_shed_table(voltage_round), empty="No shed was sized in this round.")
            self._build_block("Generators at a reactive limit", find_limit_table(voltage_round), wrap=True)

    @staticmethod
    def _build_block(title, table, empty="None.", wrap=False):
        """A titled table, or a line saying it is empty. `wrap` lets long cells (lists of buses) break into lines."""
        columns, rows, footers = table
        with ui.element("div").classes("table-block"):
            theme.eyebrow(title)
            if not rows:
                theme.hint(empty)
                return
            element = theme.data_table(columns, rows, footers)
            if wrap:
                element.classes("wrap-cells")
