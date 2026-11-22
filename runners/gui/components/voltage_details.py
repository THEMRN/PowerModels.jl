"""
The details of a run's voltage security check, as tables in a dialog (gui_plan.md, decision 10).
One block per round of the loop between the optimizer and the indicator. Its title line says how
many buses are left dead: those of islands without a generator to hold their voltage, which are
not checked and get no rows. An island whose power flow did not solve gets a red line instead
of rows. Then come four tables of the checked islands: their state, their largest indicators,
their generators at a reactive limit, and the sheds that were sized. A bus is named with its
island, "zone SECOND at bus 3005", so the tables have no bus column. The numbers come from
`voltage` -> `details` of the run's @@result summary: MW and Mvar to 2 decimals, voltages (pu)
and indicators to 3.

The `find_*` and `describe_*` functions build what the dialog shows from one round, without
drawing anything.
"""

from nicegui import ui

import theme

# ==================== Settings ====================
DEAD_BUSES_TOOLTIP = (
    "Buses of the islands left without a generator that can hold their voltage. "
    "They lose their supply when the boundary lines open, so they are not checked and have no rows."
)


# ==================== Island names ====================
def find_island_side(target, bus):
    """The side of the target's boundary an island lies on, by one of its buses: "zone SECOND", "outside zone SECOND", or "" without a target."""
    if not target:
        return ""
    group = f"{target['kind']} {target['name']}"
    return group if bus in target["buses"] else f"outside {group}"


def name_islands(target, islands):
    """
    Names of islands, in their order. `islands` are (bus, n_buses): a bus of each island and its
    size. Pass only the islands that are shown, so that each side counts only those.
    With a target zone or area (the summary's `target`) an island is named by its side: "zone
    SECOND" or "outside zone SECOND". Every island lies wholly on one side, since the target's
    boundary lines are open. When a side has more than one island, they are numbered by size,
    largest first: "zone SECOND island 1". Without a target (bus pairs, or a run kept before the
    summary had one) they are "island 1", "island 2", ..., or "island" when there is one.
    """
    sides = [find_island_side(target, bus) for bus, _ in islands]
    names = []
    for island, side in zip(islands, sides):
        same_side = [other for other, other_side in zip(islands, sides) if other_side == side]
        if len(same_side) == 1:
            names.append(side or "island")
            continue
        by_size = sorted(same_side, key=lambda other: (-other[1], other[0]))
        number = by_size.index(island) + 1
        names.append(f"{side} island {number}".strip())
    return names


def describe_size(n_buses):
    """An island's size: "7 buses", "1 bus"."""
    return f"{n_buses} bus" + ("" if n_buses == 1 else "es")


def find_island_names(voltage_round, target=None):
    """The name of each island of a round that has a generator to hold its voltage, by its bus."""
    islands = [(island["bus"], island["n_buses"]) for island in find_live_islands(voltage_round)]
    return dict(zip([bus for bus, _ in islands], name_islands(target, islands)))


# ==================== What a round says ====================
def find_dead_islands(voltage_round):
    """The islands of a round without a generator to hold their voltage: dead once the boundary opens, and not checked."""
    return [island for island in voltage_round["islands"] if island["status"] == "no_generator"]


def find_live_islands(voltage_round):
    """The islands of a round with a generator to hold their voltage: those checked and those whose power flow did not solve."""
    return [island for island in voltage_round["islands"] if island["status"] != "no_generator"]


def find_checked_islands(voltage_round):
    """The islands of a round whose state was computed."""
    return [island for island in voltage_round["islands"] if island["status"] == "checked"]


def describe_dead_buses(voltage_round, target=None):
    """
    The buses of a round's dead islands, by side of the target: "dead buses: 6 inside zone
    SECOND, 10 outside", or their total without a target, "dead buses: 16"; "" when there are none.
    """
    dead_islands = find_dead_islands(voltage_round)
    if not dead_islands:
        return ""
    total = sum(island["n_buses"] for island in dead_islands)
    if not target:
        return f"dead buses: {total}"

    group = f"{target['kind']} {target['name']}"
    inside = sum(island["n_buses"] for island in dead_islands if island["bus"] in target["buses"])
    outside = total - inside
    parts = []
    if inside:
        parts.append(f"{inside} inside {group}")
    if outside:
        parts.append(f"{outside} outside" if inside else f"{outside} outside {group}")
    return "dead buses: " + ", ".join(parts)


def describe_failed_islands(voltage_round, target=None):
    """The islands of a round whose power flow did not solve, which leaves the round not verified; "" when there are none."""
    names = find_island_names(voltage_round, target)
    failed = []
    for island in voltage_round["islands"]:
        if island["status"] != "power_flow_failed":
            continue
        failed.append(f"{names[island['bus']]} ({describe_size(island['n_buses'])})")
    if not failed:
        return ""
    return "the power flow did not solve in " + ", ".join(failed) + ", so this round is not verified"


def find_island_table(voltage_round, target=None):
    """
    (columns, rows, footers) of every checked island: its name (by the run's `target`,
    name_islands), its size, what holds its voltage, its slack and its worst indicator.
    """
    names = find_island_names(voltage_round, target)
    columns = [
        ("Island", "name", None),
        ("Buses", "n_buses", 0),
        ("With generation", "n_with_generation", 0),
        ("Holding voltage", "n_holding_voltage", 0),
        ("Slack bus", "slack_bus", None),
        ("Slack P (MW)", "slack_pg_mw", 2),
        ("Slack Q (Mvar)", "slack_qg_mvar", 2),
        ("Worst indicator", "worst_indicator", 3),
    ]
    rows = []
    for island in find_checked_islands(voltage_round):
        rows.append(dict(island, name=names[island["bus"]]))
    return columns, rows, []


def find_indicator_table(voltage_round, target=None):
    """
    (columns, rows, footers) of each checked island's largest indicators, with the bus voltage and
    load. The bus is named with its island ("zone SECOND at bus 3005"); `island` is the island's bus.
    """
    names = find_island_names(voltage_round, target)
    columns = [("Where", "where", None), ("Indicator", "value", 3), ("V (pu)", "vm", 3), ("Load (MW)", "pd_mw", 2)]
    rows = []
    for island in find_checked_islands(voltage_round):
        island_name = names[island["bus"]]
        for indicator in island["largest_indicators"]:
            rows.append(dict(indicator, island=island["bus"], where=f"{island_name} at bus {indicator['bus']}"))
    return columns, rows, []


def find_limit_table(voltage_round, target=None):
    """(columns, rows, footers) of each checked island's generators at a reactive limit, as lists of bus numbers; `island` is the island's bus."""
    names = find_island_names(voltage_round, target)
    columns = [("Island", "island_name", None), ("At upper limit", "upper", None), ("At lower limit", "lower", None)]
    rows = []
    for island in find_checked_islands(voltage_round):
        rows.append(
            {
                "island": island["bus"],
                "island_name": names[island["bus"]],
                "upper": ", ".join(str(bus) for bus in island["at_upper_limit"]) or "none",
                "lower": ", ".join(str(bus) for bus in island["at_lower_limit"]) or "none",
            }
        )
    return columns, rows, []


def find_shed_table(voltage_round, target=None):
    """
    (columns, rows, footers) of the sheds sized in a round. The bus is named with its island
    ("zone SECOND at bus 3005"). "Worst indicator after" is the island's worst indicator once all
    its sheds of the round are applied, and the bus where it is, so it stands on the island's
    last shed row only. `island` is the island's bus.
    """
    names = find_island_names(voltage_round, target)
    columns = [
        ("Where", "where", None),
        ("Shed (MW)", "shed_mw", 2),
        ("Of load (MW)", "of_mw", 2),
        ("Worst indicator after", "after", None),
    ]
    rows = []
    for island in find_checked_islands(voltage_round):
        shed = island["shed"]
        if shed is None or not shed["sheds"]:
            continue
        island_name = names[island["bus"]]
        island_rows = []
        for sized in shed["sheds"]:
            island_rows.append(dict(sized, island=island["bus"], where=f"{island_name} at bus {sized['bus']}"))

        last_row = island_rows[-1]
        last_row["indicator_after"] = shed["indicator_after"]
        last_row["indicator_after_bus"] = shed["indicator_after_bus"]
        last_row["after"] = f"{theme.format_number(shed['indicator_after'], 3)} at bus {shed['indicator_after_bus']}"
        rows.extend(island_rows)
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
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close)
            self.body = ui.element("div").classes("dialog-body")

    def open(self, record, name):
        """Show the rounds of the run's voltage security check; `name` is how the title names the run ("run 3")."""
        voltage = record["summary"]["voltage"]
        rounds = voltage["rounds"]
        self.title.text = f"Voltage security of {name}"
        self.result.text = (
            ("verified" if voltage["verified"] else "not verified")
            + f" in {rounds} round"
            + ("" if rounds == 1 else "s")
            + f", worst indicator {theme.format_number(voltage['worst_indicator'], 3)}"
        )
        target = record["summary"].get("target")  # names the islands; runs kept before it have none
        self.body.clear()
        with self.body:
            for voltage_round in voltage["details"]:
                self._build_round(voltage_round, target)
        self.dialog.open()

    def _build_round(self, voltage_round, target):
        with ui.element("div").classes("round"):
            with theme.line():
                ui.label(f"Round {voltage_round['round']}").classes("round-title")
                theme.hint(describe_round(voltage_round))
                dead_buses = describe_dead_buses(voltage_round, target)
                if dead_buses:
                    theme.hint(f"· {dead_buses}").tooltip(DEAD_BUSES_TOOLTIP)
            failed = describe_failed_islands(voltage_round, target)
            if failed:
                theme.hint(failed).classes("bad")
            self._build_block("Islands", find_island_table(voltage_round, target))
            with ui.element("div").classes("tables"):
                self._build_block("Largest indicators", find_indicator_table(voltage_round, target))
                self._build_block(
                    "Sheds sized", find_shed_table(voltage_round, target), empty="No shed was sized in this round."
                )
            self._build_block("Generators at a reactive limit", find_limit_table(voltage_round, target), wrap=True)

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
