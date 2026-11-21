"""
What the Network page shows, as plain data: the network of a case (the worker's `network` reply),
the values of the case or of a run, the colours, the selection and its boundary. Nothing here
draws, so the functions can be checked without a browser; `pages/network.py` puts the results on
the page and `components/network_canvas` draws the `graph` and the `look` built here.

Units are those of the worker: MW, Mvar, and pu for voltages.
"""

from settings import GROUP_KINDS

# ==================== Settings ====================
# colours of the groups (zones or areas), in this order; the palette of the dataviz rules, checked
# for colour-blind readers on a white surface. A ninth group and later ones share OTHER_GROUP_COLOR.
GROUP_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER_GROUP_COLOR = "#898781"
PLAIN_BUS_COLOR = "#6f7b8f"         # a bus when no colour says anything (a case without groups)
NO_VALUE_COLOR = "#c6cbd3"          # a bus or a line with no value, or with zero
LINE_COLOR = "#b3bac5"              # a line within a group
TIE_COLOR = "#7d8696"               # a line between two groups
OUT_OF_SERVICE_COLOR = "#dde0e6"    # a line with no circuit in service
# one hue from light to dark, for an amount (load, generation, flow)
AMOUNT_RAMP = ["#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
# two hues around a grey middle, for a voltage below and above 1 pu
LOW_RAMP = ["#d9d9d5", "#9ec5f4", "#3987e5", "#184f95"]
HIGH_RAMP = ["#d9d9d5", "#f3a8a0", "#e34948", "#a3171d"]
VOLTAGE_SPAN = 0.05                 # pu from 1 at which the voltage colours are darkest, at least
BUS_SIZE = 3.1                      # px, radius of a bus
GEN_SIZE = 3.6                      # px, half the side of a bus with a generator (drawn as a square)
BUS_SIZE_MOST = 9.0                 # px, radius of the bus with the largest amount
LINE_WIDTH = 1.0                    # px
TIE_WIDTH = 1.3
LINE_WIDTH_MOST = 5.0               # px, width of the line with the largest flow
CIRCLE_FILL = 0.07                  # how strongly a circle is filled with its group's colour (0 to 1)
CIRCLE_AMOUNT_COLOR = "#eb6834"     # a circle filled by an amount: a second hue, so that it is not read with the buses and lines
CIRCLE_FILL_LEAST = 0.04            # how strongly it is filled for no amount,
CIRCLE_FILL_MOST = 0.42             # and for the group with the largest amount

# what the buses, the lines and the circles can be coloured by: key -> (label, unit, value field)
BUS_VALUES = {
    "vm": ("Voltage", "pu", "vm"),
    "pd": ("Load P", "MW", "pd_mw"),
    "qd": ("Load Q", "Mvar", "qd_mvar"),
    "pg": ("Generation P", "MW", "pg_mw"),
    "qg": ("Generation Q", "Mvar", "qg_mvar"),
    "pmax": ("Capacity P", "MW", "pmax_mw"),
    "qmax": ("Capacity Q", "Mvar", "qmax_mvar"),
    "shed": ("Load shed", "MW", "shed_mw"),
}
LINE_VALUES = {
    "p": ("Flow P", "MW", "p_mw"),
    "q": ("Flow Q", "Mvar", "q_mvar"),
}
GROUP_VALUES = {key: value for key, value in BUS_VALUES.items() if key != "vm"}      # totals of a group
LINE_FIELDS = ("p_mw", "q_mvar", "p_to_mw", "q_to_mvar")       # what enters a line at its `from` bus, and at its `to` bus
RUN_ONLY = {"shed"}                 # values only a run has


# ==================== The network of a case ====================
class Network:
    """
    A case as the worker's `network` reply gives it, with the lookups the page needs. `buses` and
    `lines` keep the reply's order; a bus or a line is named by its place in them (its index).
    """

    def __init__(self, reply):
        self.case = reply["case"]
        self.buses = reply["buses"]
        self.lines = reply["lines"]
        self.layouts = reply["layouts"]
        self.group_names = reply["group_names"]
        self.kinds = [kind for kind in GROUP_KINDS if kind in self.layouts]      # kinds the case has more than one group of
        self.index_of_bus = {bus["bus"]: index for index, bus in enumerate(self.buses)}
        self.index_of_pair = {(line["from"], line["to"]): index for index, line in enumerate(self.lines)}

    def find_layout(self, kind):
        """The layout for a kind of group; the one layout of a case without groups."""
        return self.layouts[kind if kind in self.layouts else "none"]

    def find_group_name(self, kind, index):
        """Name of a zone or an area: its record's name, or its number when it has no record (as in case_info)."""
        return self.group_names.get(kind, {}).get(str(index)) or str(index)

    def find_groups(self, kind):
        """The groups of a kind that have buses, sorted by number: [(index, name, number of buses)]."""
        counts = {}
        for bus in self.buses:
            counts[bus[kind]] = counts.get(bus[kind], 0) + 1
        return [(index, self.find_group_name(kind, index), counts[index]) for index in sorted(counts)]

    def find_group_index(self, kind, name):
        """Number of the group with this name (case does not matter), or None."""
        for index, group_name, _ in self.find_groups(kind):
            if group_name.lower() == str(name).strip().lower():
                return index
        return None

    def find_group_buses(self, kind, index):
        """Bus numbers of a group."""
        return {bus["bus"] for bus in self.buses if bus[kind] == index}


def find_group_colors(network, kind):
    """
    Colour of each group of a kind: {index: colour}. The colours go to the groups in the order of
    their numbers; with more groups than colours, the largest groups get them and the others share
    OTHER_GROUP_COLOR. A group keeps its colour whatever is selected or shown.
    """
    groups = network.find_groups(kind)
    with_color = sorted(sorted(groups, key=lambda group: (-group[2], group[0]))[:len(GROUP_COLORS)])
    colors = {index: OTHER_GROUP_COLOR for index, _, _ in groups}
    for place, (index, _, _) in enumerate(with_color):
        colors[index] = GROUP_COLORS[place]
    return colors


# ==================== Values: of the case, or of a run ====================
def find_run_network(record):
    """The `network` part of a run's result, or None for a run that has none (not finished, or failed)."""
    return ((record or {}).get("summary") or {}).get("network")


def find_bus_values(network, record=None):
    """
    The values of every bus, in the order of `network.buses`: the case's own, or those of a run
    (`record`, of the session's runs) with its shed per bus (`shed_mw`, None for a run without
    load shedding and for the case).
    """
    if record is None:
        return [dict(bus, shed_mw=None) for bus in network.buses]
    summary = record["summary"]
    run_buses = {bus["bus"]: bus for bus in summary["network"]["buses"]}
    load_shed = summary.get("load_shed")
    shed_by_bus = None if load_shed is None else {bus["bus"]: bus["shed_mw"] for bus in load_shed["buses"]}
    values = []
    for bus in network.buses:
        run_bus = run_buses.get(bus["bus"], {})
        merged = dict(bus)
        for field in ("vm", "pd_mw", "qd_mvar", "pg_mw", "qg_mvar", "pmax_mw", "qmax_mvar", "gens"):
            merged[field] = run_bus.get(field)
        merged["shed_mw"] = None if shed_by_bus is None else shed_by_bus.get(bus["bus"], 0.0)
        values.append(merged)
    return values


def find_line_values(network, record=None):
    """The flow on every line, in the order of `network.lines`: the case's own, or a run's."""
    if record is None:
        return [dict(line) for line in network.lines]
    run_lines = {(line["from"], line["to"]): line for line in record["summary"]["network"]["lines"]}
    values = []
    for line in network.lines:
        run_line = run_lines.get((line["from"], line["to"]), {})
        values.append(dict(line, **{field: run_line.get(field) for field in LINE_FIELDS}))
    return values


def calc_group_totals(network, kind, bus_values):
    """
    Totals of each group: {index: {field: sum over its buses}} for the fields of GROUP_VALUES. A
    total is None when one of the group's buses has no value for it (the reactive power of a DC run).
    """
    totals = {}
    for bus in bus_values:
        group = totals.setdefault(bus[kind], {field: 0.0 for _, _, field in GROUP_VALUES.values()})
        for field in group:
            group[field] = None if group[field] is None or bus.get(field) is None else group[field] + bus[field]
    return totals


# ==================== Colours ====================
def mix_colors(first, second, share):
    """The colour `share` of the way from `first` to `second` (hex colours, share 0 to 1)."""
    parts = []
    for place in (1, 3, 5):
        a, b = int(first[place:place + 2], 16), int(second[place:place + 2], 16)
        parts.append(round(a + (b - a) * share))
    return "#" + "".join(f"{part:02x}" for part in parts)


def pick_from_ramp(ramp, share):
    """The colour at `share` (0 to 1) of a ramp of colours."""
    share = min(max(share, 0.0), 1.0) * (len(ramp) - 1)
    place = min(int(share), len(ramp) - 2)
    return mix_colors(ramp[place], ramp[place + 1], share - place)


def to_rgba(color, alpha):
    """A hex colour with an opacity, as CSS."""
    return f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, {alpha:.2f})"


def find_most(values):
    """The largest magnitude among the values that are there (0 when there is none)."""
    return max((abs(value) for value in values if value is not None), default=0.0)


def calc_amount_share(value, most):
    """How far an amount is towards the largest: 0 to 1 by its magnitude; None for no value or zero."""
    if value is None or most <= 0 or abs(value) < 1e-9:
        return None
    return abs(value) / most


def calc_voltage_color(vm, span):
    """Colour of a voltage: grey at 1 pu, blue below, red above, darkest `span` away."""
    if vm is None:
        return NO_VALUE_COLOR
    share = min(abs(vm - 1.0) / span, 1.0)
    return pick_from_ramp(LOW_RAMP if vm < 1.0 else HIGH_RAMP, share)


def calc_voltage_span(bus_values):
    """How far from 1 pu the voltage colours reach: the farthest voltage, VOLTAGE_SPAN at least."""
    return max(VOLTAGE_SPAN, max((abs(bus["vm"] - 1.0) for bus in bus_values if bus.get("vm") is not None), default=0.0))


# ==================== Text ====================
def format_number(value, unit=""):
    """A value for people: "1 250.5 MW", "1.017 pu"; "–" for none."""
    if value is None:
        return "–"
    text = f"{value:.3f}" if unit == "pu" else f"{value:,.1f}".replace(",", " ")
    return f"{text} {unit}".strip()


def lower_first(text):
    """A label inside a sentence: "Load P" becomes "load P"."""
    return text[:1].lower() + text[1:]


def describe_bus(network, bus, kind):
    """Tooltip of a bus: its number and name, its groups, its voltage, load, generation and shed."""
    title = f"Bus {bus['bus']}"
    if bus.get("name"):
        title += f" · {bus['name']}"
    if bus.get("kv"):
        title += f" · {bus['kv']:g} kV"
    groups = " · ".join(f"{group_kind} {network.find_group_name(group_kind, bus[group_kind])}" for group_kind in GROUP_KINDS)
    lines = [title, groups, f"Voltage {format_number(bus.get('vm'), 'pu')}"]
    if bus.get("pd_mw") or bus.get("qd_mvar"):
        lines.append(f"Load {format_number(bus['pd_mw'], 'MW')}, {format_number(bus['qd_mvar'], 'Mvar')}")
    if bus.get("gens"):
        units = "1 unit" if bus["gens"] == 1 else f"{bus['gens']} units"
        lines.append(f"Generation {format_number(bus['pg_mw'], 'MW')}, {format_number(bus['qg_mvar'], 'Mvar')} ({units})")
        lines.append(f"Capacity {format_number(bus['pmax_mw'], 'MW')}, {format_number(bus['qmax_mvar'], 'Mvar')}")
    if bus.get("shed_mw"):
        lines.append(f"Shed {format_number(bus['shed_mw'], 'MW')}")
    return "\n".join(lines)


def describe_line(line):
    """Tooltip of a line: its ends, its branches, and its flow with the bus the power goes to."""
    what = "Transformer" if line["transformer"] else "Line"
    ids = ", ".join(str(branch) for branch in line["ids"])
    circuits = f"branch {ids}" if len(line["ids"]) == 1 else f"{len(line['ids'])} circuits, branches {ids}"
    lines = [f"{what} {line['from']} – {line['to']} ({circuits})"]
    if line["in_service"] == 0:
        lines.append("out of service")
        return "\n".join(lines)
    if line["in_service"] < len(line["ids"]):
        lines.append(f"{line['in_service']} of {len(line['ids'])} circuits in service")
    if line.get("p_mw") is not None:
        lines.append(f"P {format_number(abs(line['p_mw']), 'MW')} towards {line['to'] if line['p_mw'] >= 0 else line['from']}")
    for end, p_field, q_field in (("from", "p_mw", "q_mvar"), ("to", "p_to_mw", "q_to_mvar")):
        if line.get(p_field) is not None:
            lines.append(f"into it at {line[end]}: {format_number(line[p_field], 'MW')}, {format_number(line.get(q_field), 'Mvar')}")
    return "\n".join(lines)


def describe_group(network, kind, index, totals, in_circle, of_group):
    """Tooltip of a circle: its group, how many of the group's buses it holds, and the group's totals."""
    name = network.find_group_name(kind, index)
    lines = [f"{kind.capitalize()} {name}: {of_group} buses" + ("" if in_circle == of_group else f", {in_circle} of them in this circle")]
    group = totals.get(index, {})
    lines.append(f"Load {format_number(group.get('pd_mw'), 'MW')}, {format_number(group.get('qd_mvar'), 'Mvar')}")
    lines.append(f"Generation {format_number(group.get('pg_mw'), 'MW')}, {format_number(group.get('qg_mvar'), 'Mvar')}")
    lines.append(f"Capacity {format_number(group.get('pmax_mw'), 'MW')}, {format_number(group.get('qmax_mvar'), 'Mvar')}")
    if group.get("shed_mw") is not None:
        lines.append(f"Shed {format_number(group['shed_mw'], 'MW')}")
    return "\n".join(lines)


# ==================== Selection ====================
def find_boundary(network, buses):
    """
    Indices of the lines with exactly one end among `buses` (bus numbers): the boundary of that
    set, in service or not, as find_branches_by_zone and find_branches_by_area take it.
    """
    return [index for index, line in enumerate(network.lines) if (line["from"] in buses) != (line["to"] in buses)]


def find_branch_ids(network, line_indices):
    """Branch ids of the lines, sorted (every circuit of each bus pair)."""
    return sorted(branch for index in line_indices for branch in network.lines[index]["ids"])


def find_islands(network, opened):
    """
    The islands left when the lines with the indices `opened` are open: sets of bus numbers,
    largest first. Lines with no circuit in service join nothing.
    """
    opened = set(opened)
    neighbors = {bus["bus"]: [] for bus in network.buses}
    for index, line in enumerate(network.lines):
        if index in opened or line["in_service"] == 0:
            continue
        neighbors[line["from"]].append(line["to"])
        neighbors[line["to"]].append(line["from"])
    seen, islands = set(), []
    for start in neighbors:
        if start in seen:
            continue
        island, stack = {start}, [start]
        seen.add(start)
        while stack:
            for other in neighbors[stack.pop()]:
                if other not in seen:
                    seen.add(other)
                    island.add(other)
                    stack.append(other)
        islands.append(island)
    return sorted(islands, key=lambda island: (-len(island), min(island)))


def calc_outflow(network, line_values, line_indices, buses):
    """
    P (MW) and Q (Mvar) that leave the set `buses` over the lines given, each measured at the
    line's end inside the set, as the boundary flows of a run with a target zone or area are.
    One of them is None when a line has no value for it (the reactive power of a DC run). Lines
    out of service carry nothing.
    """
    p_sum, q_sum = 0.0, 0.0
    for index in line_indices:
        line = line_values[index]
        if line["in_service"] == 0:
            continue
        p_field, q_field = ("p_mw", "q_mvar") if line["from"] in buses else ("p_to_mw", "q_to_mvar")
        p_sum = None if p_sum is None or line.get(p_field) is None else p_sum + line[p_field]
        q_sum = None if q_sum is None or line.get(q_field) is None else q_sum + line[q_field]
    return p_sum, q_sum


def describe_islands(islands):
    """How the network falls apart: "2 islands: 85 and 415 buses"."""
    if len(islands) == 1:
        return "the network stays in one piece"
    sizes = [str(len(island)) for island in islands[:6]]
    text = ", ".join(sizes[:-1]) + " and " + sizes[-1] if len(sizes) > 1 else sizes[0]
    more = f" and {len(islands) - 6} more" if len(islands) > 6 else ""
    return f"{len(islands)} islands: {text} buses{more}"


def calc_selection_facts(network, bus_values, line_values, buses, boundary):
    """
    What the side panel says about a selection, as (name, text): the buses selected (their load,
    generation and capacity) and the lines of its boundary (what they carry, what opening them
    leaves). `buses` may be empty for a selection of lines only.
    """
    facts = []
    if buses:
        chosen = [bus for bus in bus_values if bus["bus"] in buses]

        def total(field):
            """The sum over the chosen buses; None when one of them has no value (the reactive power of a DC run)."""
            values = [bus.get(field) for bus in chosen]
            return None if any(value is None for value in values) else sum(values)

        facts.append(("Buses", f"{len(chosen)}, {sum(1 for bus in chosen if bus.get('gens'))} with generation"))
        facts.append(("Load", f"{format_number(total('pd_mw'), 'MW')}, {format_number(total('qd_mvar'), 'Mvar')}"))
        facts.append(("Generation", f"{format_number(total('pg_mw'), 'MW')}, {format_number(total('qg_mvar'), 'Mvar')}"))
        facts.append(("Capacity", f"{format_number(total('pmax_mw'), 'MW')}, {format_number(total('qmax_mvar'), 'Mvar')}"))
        if total("shed_mw") is not None:
            facts.append(("Shed", format_number(total("shed_mw"), "MW")))
    if boundary:
        branches = find_branch_ids(network, boundary)
        facts.append(("Boundary", f"{len(boundary)} bus pairs, {len(branches)} branches"))
        if buses:
            p_out, q_out = calc_outflow(network, line_values, boundary, buses)
            facts.append(("Leaving it", f"{format_number(p_out, 'MW')}, {format_number(q_out, 'Mvar')}"))
        facts.append(("Opened", describe_islands(find_islands(network, boundary))))
    return facts


# ==================== What the canvas draws ====================
def build_graph(network, kind):
    """
    The `graph` of the canvas for a kind of group ("zone", "area", or anything else for a case
    without groups): the buses at their places, the lines, and the circles of the groups.
    """
    layout = network.find_layout(kind)
    with_groups = kind in network.layouts
    return {
        "key": f"{network.case}|{kind if with_groups else 'none'}",
        "nodes": [[x, y, 1 if bus["gens"] else 0] for x, y, bus in zip(layout["x"], layout["y"], network.buses)],
        "links": [[network.index_of_bus[line["from"]], network.index_of_bus[line["to"]]] for line in network.lines],
        "circles": [[circle["x"], circle["y"], circle["radius"]] for circle in layout["circles"]] if with_groups else [],
    }


def build_look(network, kind, bus_values, line_values, *, color_buses="group", color_lines="none", color_circles="group",
               selected_buses=(), selected_lines=(), selected_group=None):
    """
    The `look` of the canvas, and the legend that explains it.

    - `kind`: the kind of group shown ("zone" or "area"; anything else for a case without groups);
    - `color_buses`: "group" or a key of BUS_VALUES; `color_lines`: "none" or a key of
      LINE_VALUES; `color_circles`: "group" or a key of GROUP_VALUES;
    - `selected_buses` (bus numbers), `selected_lines` (line indices) and `selected_group` (the
      index of a group) are what the selection marks.

    Returns (look, legend); the legend is a list of entries: {"title"}, {"color", "text"} for a
    colour chip, {"ramp": [colours], "low", "high"} for a scale, {"note"} for a line of text.
    """
    with_groups = kind in network.layouts
    layout = network.find_layout(kind)
    group_colors = find_group_colors(network, kind) if with_groups else {}
    totals = calc_group_totals(network, kind, bus_values) if with_groups else {}
    selected_buses, selected_lines = set(selected_buses), set(selected_lines)
    legend = []

    # ---- buses ----
    node = {"color": [], "size": [], "mark": [], "label": [], "tip": []}
    if color_buses == "group":
        if with_groups:
            legend.append({"title": f"Buses by {kind}"})
            for index, name, count in network.find_groups(kind):
                legend.append({"color": group_colors[index], "text": f"{name}  ({count})", "group": index})
    elif color_buses == "vm":
        span = calc_voltage_span(bus_values)
        legend.append({"title": "Buses by voltage (pu)"})
        legend.append({"ramp": LOW_RAMP[::-1] + HIGH_RAMP[1:], "low": f"{1 - span:.3f}", "middle": "1.000", "high": f"{1 + span:.3f}"})
    else:
        label, unit, field = BUS_VALUES[color_buses]
        most = find_most(bus[field] for bus in bus_values)
        legend.append({"title": f"Buses by {lower_first(label)} ({unit})"})
        legend.append({"ramp": AMOUNT_RAMP, "low": "0", "high": format_number(most)})
        legend.append({"color": NO_VALUE_COLOR, "text": "none"})
        if any(bus[field] is not None and bus[field] < 0 for bus in bus_values):
            legend.append({"note": "by size; a negative value is coloured like a positive one"})
    for bus in bus_values:
        size = GEN_SIZE if bus["gens"] else BUS_SIZE
        if color_buses == "group":
            color = group_colors.get(bus[kind], PLAIN_BUS_COLOR) if with_groups else PLAIN_BUS_COLOR
        elif color_buses == "vm":
            color = calc_voltage_color(bus.get("vm"), span)
        else:
            share = calc_amount_share(bus.get(field), most)
            color = NO_VALUE_COLOR if share is None else pick_from_ramp(AMOUNT_RAMP, share)
            size = BUS_SIZE * 0.8 if share is None else BUS_SIZE + (BUS_SIZE_MOST - BUS_SIZE) * share ** 0.5
        node["color"].append(color)
        node["size"].append(round(size, 1))
        node["mark"].append(1 if bus["bus"] in selected_buses else 0)
        node["label"].append(str(bus["bus"]))
        node["tip"].append(describe_bus(network, bus, kind))

    # ---- lines ----
    link = {"color": [], "width": [], "arrow": [], "mark": [], "tip": []}
    circle_of_bus = layout["circle_of_bus"]
    field = None
    if color_lines != "none":
        label, unit, field = LINE_VALUES[color_lines]
        most = find_most(line[field] for line in line_values if line["in_service"])
        legend.append({"title": f"Lines by {lower_first(label)} ({unit})"})
        legend.append({"ramp": AMOUNT_RAMP, "low": "0", "high": format_number(most)})
        legend.append({"note": "the arrow shows where the power goes; wider is more"})
    for index, line in enumerate(line_values):
        between = circle_of_bus[network.index_of_bus[line["from"]]] != circle_of_bus[network.index_of_bus[line["to"]]]
        color, width, arrow = (TIE_COLOR, TIE_WIDTH, 0) if between and with_groups else (LINE_COLOR, LINE_WIDTH, 0)
        if line["in_service"] == 0:
            color = OUT_OF_SERVICE_COLOR
        elif field is not None:
            share = calc_amount_share(line.get(field), most)
            if share is None:
                color, width = NO_VALUE_COLOR, LINE_WIDTH
            else:
                color = pick_from_ramp(AMOUNT_RAMP, share)
                width = LINE_WIDTH + (LINE_WIDTH_MOST - LINE_WIDTH) * share
                arrow = 1 if line[field] > 0 else -1
        link["color"].append(color)
        link["width"].append(round(width, 1))
        link["arrow"].append(arrow)
        link["mark"].append(1 if index in selected_lines else 0)
        link["tip"].append(describe_line(line))

    # ---- circles ----
    circle = {"fill": [], "line": [], "mark": [], "label": [], "note": [], "ink": [], "tip": []}
    if with_groups:
        of_group = {index: count for index, _, count in network.find_groups(kind)}
        in_circle = [0] * len(layout["circles"])
        for place, bus in enumerate(network.buses):
            if bus[kind] == layout["circles"][circle_of_bus[place] - 1]["group"]:
                in_circle[circle_of_bus[place] - 1] += 1
        group_field = None
        if color_circles != "group":
            label, unit, group_field = GROUP_VALUES[color_circles]
            most = find_most(group.get(group_field) for group in totals.values())
            legend.append({"title": f"Circles by {lower_first(label)} of the {kind} ({unit})"})
            legend.append({"ramp": [mix_colors("#ffffff", CIRCLE_AMOUNT_COLOR, CIRCLE_FILL_LEAST), mix_colors("#ffffff", CIRCLE_AMOUNT_COLOR, CIRCLE_FILL_MOST)],
                           "low": "0", "high": format_number(most)})
        for place, item in enumerate(layout["circles"]):
            index = item["group"]
            color = group_colors[index]
            note = ""
            if group_field is None:
                fill = to_rgba(color, CIRCLE_FILL)
            else:
                value = totals.get(index, {}).get(group_field)
                share = calc_amount_share(value, most) or 0.0
                fill = to_rgba(CIRCLE_AMOUNT_COLOR, CIRCLE_FILL_LEAST + (CIRCLE_FILL_MOST - CIRCLE_FILL_LEAST) * share)
                note = format_number(value, unit)
            circle["fill"].append(fill)
            circle["line"].append(color)
            circle["mark"].append(1 if index == selected_group else 0)
            circle["label"].append(network.find_group_name(kind, index))
            circle["note"].append(note)
            circle["ink"].append(mix_colors(color, "#1b212c", 0.35))
            circle["tip"].append(describe_group(network, kind, index, totals, in_circle[place], of_group[index]))

    key = "|".join(str(part) for part in (color_buses, color_lines, color_circles, sorted(selected_buses), sorted(selected_lines), selected_group))
    return {"key": key, "node": node, "link": link, "circle": circle}, legend
