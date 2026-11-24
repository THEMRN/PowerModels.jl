"""
The dynamic simulation of one run as the Dynamics tab of the results panel shows it
(gui_plan.md, phase 13), without drawing: where the run's channel file is, what is read from it,
the curves to draw (thinned, as ECharts options) and the statistics beside them.

The channel file is `output_andes_<stamp>.csv.gz`, written by andes_scripts/dynamic.py with
PSS®E channel names and units: "Time(s)", then FREQ (deviation from 60 Hz, pu) and VOLT (pu)
per bus, POWR and VARS per generator, and PLOD and QLOD per load (pu on the system base). The
tab shows Hz, pu, MW and Mvar.

The statistics come from the channel file itself, never from the folder's voltage_stats.json or
frequency_stats.json, which hold only the latest run of a folder that later runs reuse. The
voltage statistics and WTVSI come from the function that writes voltage_stats.json
(`build_voltage_stats_json` of andes_scripts/report.py); the frequency statistics are taken from
the trip on, as frequency_stats.json is.
"""

import importlib.util
import re
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

import theme
from network_view import GROUP_COLORS, OTHER_GROUP_COLOR

# ==================== Settings ====================
REPORT_MODULE = Path(__file__).resolve().parents[1] / "andes_scripts" / "report.py"
TIME_COLUMN = "Time(s)"
NOMINAL_FREQUENCY = 60.0        # Hz, the FREQ channels are deviations from it in pu
DEFAULT_BASE_MVA = 100.0        # MVA, when the run's RAW is gone
DEFAULT_EVENT_TIME = 5.0        # s, the trip time of results kept before `frequency_simulation` (EVENT_TIME of the ANDES script)
MAX_POINTS = 1000               # points of one curve sent to the browser; each stretch of time keeps its lowest and highest value
MIN_POINTS = 200                # points of one curve when many are drawn ("all buses")
MAX_TOTAL_POINTS = 120_000      # points of all curves together, about 2 MB: with many curves each gets fewer points
MAX_CURVES = 60                 # curves drawn at once, unless "all buses" is ticked
TOP_ROWS = 5                    # buses in a table of statistics, as the report lists
FREQUENCY_BELOW = (59.0, 57.0)  # Hz, the report's thresholds
FREQUENCY_ABOVE = (60.5, 61.8)  # Hz
VOLTAGE_BAND = (0.9, 1.1)       # pu, as VOLTAGE_LOW and VOLTAGE_HIGH of report.py
QUANTITIES = {  # quantity -> its channel kind, its name, its unit, the decimals of a point sent to the browser, what a curve is of
    "frequency": {"kind": "FREQ", "label": "Bus frequency", "unit": "Hz", "digits": 4, "of": "buses"},
    "voltage": {"kind": "VOLT", "label": "Bus voltage", "unit": "pu", "digits": 5, "of": "buses"},
    "gen_p": {"kind": "POWR", "label": "Generator P", "unit": "MW", "digits": 3, "of": "generators"},
    "gen_q": {"kind": "VARS", "label": "Generator Q", "unit": "Mvar", "digits": 3, "of": "generators"},
    "load_p": {"kind": "PLOD", "label": "Load P", "unit": "MW", "digits": 3, "of": "loads"},
    "load_q": {"kind": "QLOD", "label": "Load Q", "unit": "Mvar", "digits": 3, "of": "loads"},
}
BUS_KINDS = ("FREQ", "VOLT")    # channels of a bus; the others are of a generator or a load at a bus
RELAY_FIELDS = {                # relay model of the .dyr -> positions of its frequency thresholds (Hz) among the record's fields
    "LDSHBL": {"ufls": (3, 6, 9)},                      # bus, 'LDSHBL', load ID, f1, t1, frac1, f2, t2, frac2, f3, t3, frac3, tb
    "FRQTPAT": {"gen_low": (5,), "gen_high": (6,)},     # MINS, 'FRQTPAT', monitored bus, generator bus, generator ID, FL, FU, TP, TB
}
RELAY_LABELS = {"ufls": "UFLS", "gen_low": "gen trip", "gen_high": "gen trip"}
RELAY_COLORS = {"ufls": theme.WARN, "gen_low": theme.BAD, "gen_high": theme.BAD}   # a generator trip in red over a UFLS stage
RELAY_RANGE = (0.8, 1.2)        # × 60 Hz, a FRQTPAT threshold outside it is "never" (the cases write FL 20 and FU 90 Hz)
AXIS_MARGIN = 0.05              # Hz, room between the outermost relay line and the edge of the chart
CHANNEL_NAME = re.compile(r"(\w+) ?(\d+) ?\[(.*) ([\d.]+)\](.*)")     # "FREQ 3005 [NAME 138.000]", "POWR 9[NAME 13.800]1"
REPORT_NAME = re.compile(r"dynamic_channels_(\d{8}_\d{6})\.html")     # shares its stamp with the channel file
CHART_FONT = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
PROGRAM_ZOOM = {                # a dataZoom that only the tab's own drag and double-click move (dynamics_view.py)
    "type": "inside",
    "filterMode": "none",
    "zoomOnMouseWheel": False,
    "moveOnMouseMove": False,
    "moveOnMouseWheel": False,
}


def load_report_module():
    """andes_scripts/report.py, loaded from its path (it is a script's module, not a package)."""
    spec = importlib.util.spec_from_file_location("andes_report", REPORT_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load_report_module()


# ==================== The run's files ====================
def find_channel_file(files):
    """
    (path, "") of a run's channel file, or (None, why there is none). The summary's
    `files.channels` names it since 2026-11-23; for results kept before, the name of the HTML
    report gives it, since the two share the simulation script's stamp.
    """
    name = files.get("channels")
    if not name:
        match = REPORT_NAME.fullmatch(files.get("report") or "")
        if match is None:
            return None, (
                "This run names no channel file: it was kept before the GUI showed the simulation, "
                "and it has no report whose name would give it."
            )
        name = f"output_andes_{match.group(1)}.csv.gz"
    path = Path(files.get("output_path") or "") / name
    if not path.exists():
        return None, f"The simulation's channel file ({name}) is not in the results folder any more."
    return path, ""


def read_base_mva(files):
    """The system base (MVA) of a run: SBASE, the second field of its RAW's first record, or DEFAULT_BASE_MVA."""
    raw = files.get("raw")
    if not raw:
        return DEFAULT_BASE_MVA
    try:
        with open(Path(files["output_path"]) / raw, encoding="utf-8", errors="replace") as file:
            first_record = file.readline()
        return float(first_record.split("/")[0].split(",")[1])
    except (OSError, IndexError, ValueError):
        return DEFAULT_BASE_MVA


def read_dyr_records(path):
    """The records of a .dyr file as lists of fields (quotes stripped). A record ends at "/", which may start a comment."""
    records = []
    fields = []
    with open(path, encoding="utf-8", errors="replace") as file:
        for line in file:
            text, ends, _comment = line.partition("/")
            fields.extend(field.strip("'\"") for field in re.split(r"[,\s]+", text.strip()) if field)
            if ends:
                if fields:
                    records.append(fields)
                fields = []
    return records


def read_relay_thresholds(files):
    """
    The frequency thresholds (Hz) of the relays in the run's .dyr, as {value: set of kinds}: the
    stages of the UFLS relays (LDSHBL, "ufls") and the trips of the generator relays (FRQTPAT,
    "gen_low" and "gen_high"). A FRQTPAT threshold outside RELAY_RANGE never acts and is left
    out. Empty when the .dyr is not in the results folder.
    """
    raw = files.get("raw")
    if not raw:
        return {}
    path = Path(files["output_path"]) / (Path(raw).stem + ".dyr")
    if not path.exists():
        return {}
    low, high = (share * NOMINAL_FREQUENCY for share in RELAY_RANGE)
    thresholds = {}
    for fields in read_dyr_records(path):
        model = fields[1].upper() if len(fields) > 1 else ""
        for kind, positions in RELAY_FIELDS.get(model, {}).items():
            for position in positions:
                try:
                    hz = float(fields[position])
                except (IndexError, ValueError):
                    continue
                if low <= hz <= high:
                    thresholds.setdefault(hz, set()).add(kind)
    return thresholds


def find_event_time(summary):
    """When the lines tripped (s): from the summary's `frequency_simulation`, or DEFAULT_EVENT_TIME for results kept before it."""
    simulation = summary.get("frequency_simulation") or {}
    if simulation.get("status") == "simulated":
        return float(simulation["event_time_s"])
    return DEFAULT_EVENT_TIME


def describe_missing(summary, run_settings, running):
    """
    Why the tab cannot show a run's curves, in a sentence, with whether it waits; (None, False)
    when it can look for its channel file. `running` says whether the run is still going.
    """
    if run_settings.get("simulator") == "psse":
        return (
            "This run used PSS®E, whose channels (a binary .out file) the GUI does not read. Its simulation report has the curves.",
            False,
        )
    simulation = summary.get("frequency_simulation") or {}
    if simulation.get("status") == "pending":
        if running:
            return "The dynamic simulation is running: its curves show here when it ends.", True
        return "The run ended before its dynamic simulation did, so there are no curves.", False
    return None, False


# ==================== Channels ====================
def parse_channel(name):
    """
    A channel of the file by its name: its kind, bus, the bus's name and the device's id (a
    generator's or a load's, "" for a bus's channel); None for the time column.
    """
    match = CHANNEL_NAME.fullmatch(name)
    if match is None:
        return None
    kind, bus, bus_name, _base_kv, device = match.groups()
    return {"column": name, "kind": kind, "bus": int(bus), "bus_name": bus_name.strip(), "device": device.strip()}


def describe_channel(channel):
    """A curve's name: "bus 3005 NAME", "generator 1 at bus 9 NAME", "load 1 at bus 2 NAME"."""
    bus = f"bus {channel['bus']} {channel['bus_name']}".strip()
    if channel["kind"] in BUS_KINDS:
        return bus
    device = "generator" if channel["kind"] in ("POWR", "VARS") else "load"
    return f"{device} {channel['device']} at {bus}"


def read_channels(path, kinds):
    """
    The channels of `kinds` ("FREQ", "VOLT", ...) in a channel file, in the file's units, as
    (frame with the time column first, every channel of the file parsed from its name). Only the
    columns of those kinds are parsed: the whole ACTIVSg500 file (1522 channels) reads in 0.44 s.
    """
    header = list(pd.read_csv(path, nrows=0).columns)
    channels = [channel for channel in map(parse_channel, header) if channel is not None]
    columns = [TIME_COLUMN] + [channel["column"] for channel in channels if channel["kind"] in kinds]
    frame = pd.read_csv(path, usecols=columns)[columns]
    return frame, channels


def convert_values(values, kind, base_mva):
    """Channel values in the tab's units: Hz for FREQ, pu for VOLT, MW and Mvar for the others (pu on the system base)."""
    if kind == "FREQ":
        return NOMINAL_FREQUENCY * (1.0 + values)
    if kind == "VOLT":
        return values
    return base_mva * values


def find_dead_buses(frame, channels):
    """
    The buses the islanding left without power. The script sets their voltage and frequency
    deviation to 0 after the trip; they are found as voltage_stats.json leaves them out, by the
    report's `is_valid_voltage_profile` (a voltage that reads 0 at the end).
    """
    dead_buses = set()
    for channel in channels:
        if channel["kind"] != "VOLT":
            continue
        if not report.is_valid_voltage_profile(frame[channel["column"]].to_numpy(dtype=float)):
            dead_buses.add(channel["bus"])
    return dead_buses


def load_dynamics(path, quantity, files, summary):
    """
    What the tab needs to show one quantity of a run, read from its channel file: the times (s),
    the quantity's channels and their values in the tab's units (a column each), the frame of
    the file's units (for the voltage statistics), the dead buses, the trip and end times (s),
    the buses with a load (for WTVSI) and, for frequency, the relays' thresholds of its .dyr.
    It reads the files, so call it off the event loop.
    """
    kind = QUANTITIES[quantity]["kind"]
    frame, channels = read_channels(path, {kind, "VOLT"})
    times = frame[TIME_COLUMN].to_numpy(dtype=float)
    shown = [channel for channel in channels if channel["kind"] == kind]
    values = frame[[channel["column"] for channel in shown]].to_numpy(dtype=float)
    return {
        "quantity": quantity,
        "times": times,
        "channels": shown,
        "values": convert_values(values, kind, read_base_mva(files)),
        "frame": frame,
        "dead_buses": find_dead_buses(frame, channels),
        "event_time": find_event_time(summary),
        "end_time": float(times[-1]),
        "load_buses": sorted({channel["bus"] for channel in channels if channel["kind"] == "PLOD"}),
        "relay_thresholds": read_relay_thresholds(files) if quantity == "frequency" else {},
    }


# ==================== Which curves ====================
def find_sides(target):
    """The choices of Where, {key: name}: all buses and, with a target zone or area, its inside and its outside."""
    sides = {"all": "All buses"}
    if target:
        group = f"{target['kind']} {target['name']}"
        sides["inside"] = group
        sides["outside"] = f"outside {group}"
    return sides


def is_on_side(bus, target_buses, where):
    """Whether a bus is on the chosen side: `target_buses` is the target's set of buses, None without a target."""
    if where == "all" or target_buses is None:
        return True
    return (bus in target_buses) == (where == "inside")


def calc_movement(times, values, event_time):
    """How far each curve (a column of `values`) goes from its value just before the trip, after it, in the tab's units."""
    before = max(int(np.searchsorted(times, event_time, side="right")) - 1, 0)   # the last sample at or before the trip
    after = values[before + 1:]
    if after.size == 0:
        return np.zeros(values.shape[1])
    return np.nanmax(np.abs(after - values[before]), axis=0)


def calc_band_violation(values):
    """How far each voltage curve (a column, pu) leaves VOLTAGE_BAND at any time; 0 for a curve that stays in it."""
    low, high = VOLTAGE_BAND
    under = np.nanmax(low - values, axis=0)
    over = np.nanmax(values - high, axis=0)
    return np.maximum(np.maximum(under, over), 0.0)


def find_side_positions(data, target, where, keep_dead=False):
    """
    Positions (among `data["channels"]`) of the channels on the chosen side, without the dead
    buses for frequency and voltage unless `keep_dead`.
    """
    target_buses = set(target["buses"]) if target else None
    skip_dead = data["quantity"] in ("frequency", "voltage") and not keep_dead
    positions = []
    for position, channel in enumerate(data["channels"]):
        if not is_on_side(channel["bus"], target_buses, where):
            continue
        if skip_dead and channel["bus"] in data["dead_buses"]:
            continue
        positions.append(position)
    return positions


def find_curves(data, target, where, picked_buses, all_buses):
    """
    The curves to draw, as (positions among `data["channels"]`, notes on what is left out).
    With `picked_buses`: every channel at those buses. Otherwise the channels on the chosen
    side, without the dead buses (frequency and voltage), those that move most first. With
    `all_buses` (frequency and voltage) that is every one of them; without it, voltage keeps
    only those that leave 0.9–1.1 pu, and at most MAX_CURVES are drawn.
    """
    quantity = QUANTITIES[data["quantity"]]
    notes = []
    if picked_buses:
        positions = [position for position, channel in enumerate(data["channels"]) if channel["bus"] in picked_buses]
        found = {data["channels"][position]["bus"] for position in positions}
        missing = [str(bus) for bus in picked_buses if bus not in found]
        if missing:
            notes.append(f"No {quantity['label'].lower()} at bus {', '.join(missing)}.")
        order = {bus: rank for rank, bus in enumerate(picked_buses)}
        positions.sort(key=lambda position: order[data["channels"][position]["bus"]])
        return positions, notes

    positions = find_side_positions(data, target, where)
    if data["quantity"] in ("frequency", "voltage"):
        dead_count = len(find_side_positions(data, target, where, keep_dead=True)) - len(positions)
        if dead_count:
            notes.append(f"{dead_count} bus{'' if dead_count == 1 else 'es'} lost power when the lines opened; their curves are left out.")
    all_buses = all_buses and data["quantity"] in ("frequency", "voltage")
    if data["quantity"] == "voltage" and not all_buses and positions:
        violation = calc_band_violation(data["values"][:, positions])
        inside_band = len(positions) - int(np.count_nonzero(violation > 0))
        positions = [position for position, amount in zip(positions, violation) if amount > 0]
        if inside_band:
            notes.append(f"{inside_band} bus voltage{'' if inside_band == 1 else 's'} stay within 0.9–1.1 pu and are not drawn, as in the report.")
    if not positions:
        return positions, notes

    movement = calc_movement(data["times"], data["values"][:, positions], data["event_time"])
    order = np.argsort(-movement, kind="stable")
    if all_buses:
        return [positions[index] for index in order], notes
    if len(positions) > MAX_CURVES:
        notes.append(
            f"The {MAX_CURVES} {quantity['of']} that move most of {len(positions)} are drawn; type bus numbers to see others."
        )
    positions = [positions[index] for index in order[:MAX_CURVES]]
    return positions, notes


def thin_curve(values, max_points=MAX_POINTS):
    """
    The sample positions of a curve to send, at most about `max_points`: the time is cut into
    `max_points / 2` stretches and each keeps its lowest and its highest sample, so a nadir, a
    peak and any swing wider than a stretch stay. The first and the last sample stay too.
    """
    count = len(values)
    if count <= max_points:
        return np.arange(count)
    size = -(-count // (max_points // 2))       # samples per stretch, rounded up
    padding = (-count) % size
    lows = np.concatenate([values, np.full(padding, np.inf)]).reshape(-1, size)
    highs = np.concatenate([values, np.full(padding, -np.inf)]).reshape(-1, size)
    starts = np.arange(0, count, size)
    lowest = starts + np.argmin(np.nan_to_num(lows, nan=np.inf), axis=1)
    highest = starts + np.argmax(np.nan_to_num(highs, nan=-np.inf), axis=1)
    return np.unique(np.concatenate([lowest, highest, [0, count - 1]]))


# ==================== Statistics ====================
def calc_frequency_stats(data, positions):
    """
    The frequency statistics of the channels at `positions` (Hz), from the trip on as in
    frequency_stats.json: the nadir and the peak, how many buses pass each of the report's
    thresholds, and the TOP_ROWS buses that go furthest from 60 Hz. None without samples.
    """
    after = data["times"] > data["event_time"]
    if not positions or not after.any():
        return None
    times = data["times"][after]
    values = data["values"][after][:, positions]
    rows = []
    for column, position in enumerate(positions):
        curve = values[:, column]
        lowest, highest = int(np.nanargmin(curve)), int(np.nanargmax(curve))
        below_by = NOMINAL_FREQUENCY - curve[lowest]
        above_by = curve[highest] - NOMINAL_FREQUENCY
        worst = lowest if below_by >= above_by else highest
        channel = data["channels"][position]
        rows.append({
            "bus": channel["bus"],
            "name": channel["bus_name"],
            "min_hz": float(curve[lowest]),
            "min_time": float(times[lowest]),
            "max_hz": float(curve[highest]),
            "max_time": float(times[highest]),
            "deviation_hz": float(max(below_by, above_by)),
            "time_s": float(times[worst]),
        })
    return {
        "buses": len(rows),
        "nadir": min(rows, key=lambda row: row["min_hz"]),
        "peak": max(rows, key=lambda row: row["max_hz"]),
        "below": {limit: sum(1 for row in rows if row["min_hz"] < limit) for limit in FREQUENCY_BELOW},
        "above": {limit: sum(1 for row in rows if row["max_hz"] > limit) for limit in FREQUENCY_ABOVE},
        "top": sorted(rows, key=lambda row: row["deviation_hz"], reverse=True)[:TOP_ROWS],
    }


def calc_voltage_stats(data, positions):
    """
    The voltage statistics of the channels at `positions`, with `build_voltage_stats_json` of
    report.py as voltage_stats.json has them: the minimum and the maximum, the buses outside
    0.9–1.1 pu, the TOP_ROWS largest violations, and WTVSI from the trip to the last sample with
    its top buses. (The script passes its planned end, 25 s, as the end; the two agree for a
    simulation that did not stop early.) None without channels.
    """
    if not positions:
        return None
    columns = [data["channels"][position]["column"] for position in positions]
    frame = data["frame"][[TIME_COLUMN] + columns]
    stats = report.build_voltage_stats_json(frame, TIME_COLUMN, data["load_buses"], data["event_time"], data["end_time"])
    names = {channel["bus"]: channel["bus_name"] for channel in data["channels"]}
    violations = []
    for bus, row in stats["buses"].items():
        if row["worst_violation"] <= 0:
            continue
        violations.append({
            "bus": int(bus),
            "name": names.get(int(bus), ""),
            "min_pu": row["min"],
            "max_pu": row["max"],
            "violation_pu": row["worst_violation"],
            "time_s": row["worst_time"],
        })
    violations.sort(key=lambda row: row["violation_pu"], reverse=True)
    summary = stats["summary"]
    buses = stats["buses"]
    wtvsi = stats["wtvsi"]
    return {
        "buses": summary["bus_count"],
        "outside_band": summary["outside_band_count"],
        "min": None if summary["min_voltage_bus"] is None else {
            "pu": summary["min_voltage"],
            "bus": summary["min_voltage_bus"],
            "name": names.get(summary["min_voltage_bus"], ""),
            "time_s": buses[str(summary["min_voltage_bus"])]["min_time"],
        },
        "max": None if summary["max_voltage_bus"] is None else {
            "pu": summary["max_voltage"],
            "bus": summary["max_voltage_bus"],
            "name": names.get(summary["max_voltage_bus"], ""),
            "time_s": buses[str(summary["max_voltage_bus"])]["max_time"],
        },
        "top": violations[:TOP_ROWS],
        "wtvsi": wtvsi["wtvsi"],
        "wtvsi_buses": wtvsi.get("bus_count", 0),
        "wtvsi_from": wtvsi["event_time"],
        "wtvsi_to": wtvsi["end_time"],
        "wtvsi_top": [
            {"bus": int(row["bus"]), "name": names.get(int(row["bus"]), ""), "integral": row["integral"]}
            for row in wtvsi["top_contributors"]
        ],
    }


def describe_extreme(value, unit, digits, extreme):
    """A nadir, peak, minimum or maximum on one line: "59.159 Hz at bus 211 NAME, t = 7.76 s"."""
    where = f"bus {extreme['bus']} {extreme['name']}".strip()
    return f"{theme.format_number(value, digits)} {unit} at {where}, t = {theme.format_number(extreme['time_s'], 2)} s"


def find_frequency_facts(stats):
    """[(name, text)] of the frequency statistics."""
    nadir, peak = stats["nadir"], stats["peak"]
    below = ", ".join(f"{count} below {limit:g} Hz" for limit, count in stats["below"].items())
    above = ", ".join(f"{count} above {limit:g} Hz" for limit, count in stats["above"].items())
    return [
        ("Buses", str(stats["buses"])),
        ("Nadir", describe_extreme(nadir["min_hz"], "Hz", 3, dict(nadir, time_s=nadir["min_time"]))),
        ("Peak", describe_extreme(peak["max_hz"], "Hz", 3, dict(peak, time_s=peak["max_time"]))),
        ("Thresholds", f"{below}; {above}"),
    ]


def name_rows(rows):
    """Rows with the bus and its name in one cell ("211 HYDRO_G"), so a table fits beside the chart."""
    return [dict(row, where=f"{row['bus']} {row['name']}".strip()) for row in rows]


def find_frequency_table(stats):
    """(columns, rows, footers) of the buses whose frequency goes furthest from 60 Hz after the trip."""
    columns = [
        ("Bus", "where", None),
        ("Min (Hz)", "min_hz", 3),
        ("Max (Hz)", "max_hz", 3),
        ("Deviation (Hz)", "deviation_hz", 3),
        ("At t (s)", "time_s", 2),
    ]
    return columns, name_rows(stats["top"]), []


def find_voltage_facts(stats):
    """[(name, text)] of the voltage statistics."""
    facts = [("Buses", str(stats["buses"]))]
    if stats["min"] is not None:
        facts.append(("Minimum", describe_extreme(stats["min"]["pu"], "pu", 3, stats["min"])))
        facts.append(("Maximum", describe_extreme(stats["max"]["pu"], "pu", 3, stats["max"])))
    facts.append(("Outside 0.9–1.1 pu", f"{stats['outside_band']} of {stats['buses']} buses"))
    facts.append((
        "WTVSI",
        f"{theme.format_number(stats['wtvsi'], 6)} ({stats['wtvsi_buses']} buses, "
        f"t = {theme.format_number(stats['wtvsi_from'], 1)} to {theme.format_number(stats['wtvsi_to'], 1)} s)",
    ))
    return facts


def find_voltage_table(stats):
    """(columns, rows, footers) of the buses whose voltage leaves 0.9–1.1 pu furthest."""
    columns = [
        ("Bus", "where", None),
        ("Min (pu)", "min_pu", 3),
        ("Max (pu)", "max_pu", 3),
        ("Violation (pu)", "violation_pu", 4),
        ("At t (s)", "time_s", 2),
    ]
    return columns, name_rows(stats["top"]), []


def find_wtvsi_table(stats):
    """(columns, rows, footers) of the buses that add most to WTVSI."""
    columns = [("Bus", "where", None), ("Integral", "integral", 6)]
    return columns, name_rows(stats["wtvsi_top"]), []


# ==================== The chart ====================
def find_curve_colors(data, positions, target, picked_buses):
    """
    The colour of each curve, and the key that names them as [(colour, name)]: picked buses one
    colour each (the first eight group colours, then grey); otherwise the target's inside in the
    first group colour and its outside in the second, or every curve in the first without a target.
    """
    if picked_buses:
        bus_colors = {}
        for rank, bus in enumerate(picked_buses):
            bus_colors[bus] = GROUP_COLORS[rank] if rank < len(GROUP_COLORS) else OTHER_GROUP_COLOR
        return [bus_colors[data["channels"][position]["bus"]] for position in positions], []
    if not target:
        return [GROUP_COLORS[0]] * len(positions), []
    target_buses = set(target["buses"])
    sides = find_sides(target)
    colors = [GROUP_COLORS[0] if data["channels"][position]["bus"] in target_buses else GROUP_COLORS[1] for position in positions]
    key = [(GROUP_COLORS[0], sides["inside"]), (GROUP_COLORS[1], sides["outside"])]
    return colors, [entry for entry in key if entry[0] in colors]


def describe_relay_line(hz, kinds):
    """The label of a relay threshold: "UFLS 59.5", "gen trip 61.8", "UFLS, gen trip 59.5"."""
    names = []
    for kind in ("ufls", "gen_low", "gen_high"):
        if kind in kinds and RELAY_LABELS[kind] not in names:
            names.append(RELAY_LABELS[kind])
    return f"{', '.join(names)} {hz:g}"


def describe_lines(data):
    """What the dashed lines of a chart are, in a sentence; "" for a chart with the trip's line only."""
    if data["quantity"] == "voltage":
        return "Dashed: the band of 0.9 to 1.1 pu."
    if data["quantity"] != "frequency":
        return ""
    kinds = set().union(*data["relay_thresholds"].values()) if data["relay_thresholds"] else set()
    if not kinds:
        return "The case's .dyr has no UFLS or generator trip relay, so there is no threshold to draw."
    parts = []
    if "ufls" in kinds:
        parts.append("the UFLS stages (LDSHBL) in amber")
    if kinds & {"gen_low", "gen_high"}:
        parts.append("the generator trips (FRQTPAT) in red")
    return f"Dashed: the relays' thresholds in the case's .dyr, {' and '.join(parts)}."


def build_relay_lines(thresholds):
    """The chart's lines at the relays' thresholds (Hz): dashed, red for a generator trip, amber for a UFLS stage only, each named at its right end."""
    lines = []
    for hz, kinds in sorted(thresholds.items()):
        color = RELAY_COLORS["gen_low"] if kinds & {"gen_low", "gen_high"} else RELAY_COLORS["ufls"]
        lines.append({
            "yAxis": hz,
            "lineStyle": {"color": color, "type": "dashed", "width": 1},
            "label": {"formatter": describe_relay_line(hz, kinds), "position": "insideEndTop", "color": color, "fontSize": 10},
        })
    return lines


def build_guide_series(data):
    """
    A series without data that holds the lines of the chart: the trip, and the relays'
    thresholds of the case's .dyr (frequency) or the voltage band. It is apart from the curves,
    so a highlighted curve does not fade them.
    """
    lines = [{
        "xAxis": data["event_time"],
        "lineStyle": {"color": theme.INK_3, "type": "dashed", "width": 1},
        "label": {"formatter": "trip", "position": "end", "color": theme.INK_2, "fontSize": 11},
    }]
    if data["quantity"] == "frequency":
        lines.extend(build_relay_lines(data["relay_thresholds"]))
    if data["quantity"] == "voltage":
        for pu in VOLTAGE_BAND:
            lines.append({"yAxis": pu, "lineStyle": {"color": theme.WARN, "type": "dashed", "width": 1}, "label": {"show": False}})
    return {
        "type": "line",
        "name": "",
        "data": [],
        "silent": True,
        "tooltip": {"show": False},
        "markLine": {"silent": True, "symbol": "none", "data": lines, "animation": False},
    }


def build_axis_labels(digits):
    """The numbers along an axis, at most `digits` decimals: a zoom puts its edges at any value (60.30013404825738)."""
    return {"color": theme.INK_3, "fontSize": 11, ":formatter": f"value => String(+value.toFixed({digits}))"}


def build_axis_pointer(digits):
    """The cross-hair of one axis: a thin line at the cursor, with its value in a label on the axis."""
    return {
        "show": True,
        "snap": False,
        "type": "line",
        "lineStyle": {"color": theme.INK_3, "type": "solid", "width": 1},
        "label": {"show": True, "precision": digits, "backgroundColor": theme.INK_2, "color": theme.SURFACE, "fontSize": 11, "padding": [3, 6]},
    }


def calc_points_per_curve(curve_count):
    """How many points each curve gets: MAX_POINTS, fewer when many curves share MAX_TOTAL_POINTS, never under MIN_POINTS."""
    return int(min(MAX_POINTS, max(MIN_POINTS, MAX_TOTAL_POINTS // max(curve_count, 1))))


def build_value_axis_range(data):
    """
    The y axis's min and max as JavaScript functions of the data's own range, widened to show
    every relay line of a frequency chart (the lines do not widen it themselves); {} otherwise.
    """
    thresholds = data["relay_thresholds"]
    if data["quantity"] != "frequency" or not thresholds:
        return {}
    low = round(min(thresholds) - AXIS_MARGIN, 3)
    high = round(max(thresholds) + AXIS_MARGIN, 3)
    return {":min": f"value => Math.min(value.min, {low})", ":max": f"value => Math.max(value.max, {high})"}


def build_chart(data, positions, colors, show_legend):
    """
    The ECharts options of the curves at `positions`: time on x, the quantity on y (not from
    zero, widened to the relay lines of a frequency chart), one thin line per curve, thinned for
    the browser (`thin_curve`, fewer points each when many are drawn), and a cross-hair whose
    labels give the time and the value at the cursor. The two dataZoom components take no mouse
    input themselves: the tab zooms through them as Plotly does (a drag across, up or down, or a
    box; a double-click goes back), and names the curve nearest the cursor (dynamics_view.py).
    """
    quantity = QUANTITIES[data["quantity"]]
    digits = quantity["digits"]
    times = data["times"]
    points_per_curve = calc_points_per_curve(len(positions))
    series = []
    for position, color in zip(positions, colors):
        values = data["values"][:, position]
        keep = thin_curve(values, points_per_curve)
        points = [[round(float(times[i]), 4), round(float(values[i]), digits)] for i in keep if np.isfinite(values[i])]
        series.append({
            "type": "line",
            "name": describe_channel(data["channels"][position]),
            "data": points,
            "showSymbol": False,
            "symbolSize": 6,
            "color": color,
            "lineStyle": {"width": 1.2},
            "emphasis": {"focus": "series", "lineStyle": {"width": 2.4}},     # the curve the tab names (dynamics_view.py)
            "blur": {"lineStyle": {"opacity": 0.12}},
        })
    series.append(build_guide_series(data))
    axis = {
        "axisLine": {"show": True, "lineStyle": {"color": theme.LINE_STRONG}},
        "axisTick": {"show": False},
        "splitLine": {"lineStyle": {"color": theme.LINE}},
        "nameLocation": "middle",
        "nameTextStyle": {"color": theme.INK_2, "fontSize": 12},
    }
    unit = quantity["unit"]
    value_digits = min(digits, 3)
    return {
        "animation": False,
        "textStyle": {"fontFamily": CHART_FONT},
        "grid": {"left": 64, "right": 24, "top": 48 if show_legend else 22, "bottom": 44},     # room for the legend and the trip's label
        "legend": {
            "show": show_legend,
            "data": [entry["name"] for entry in series[:-1]],
            "type": "scroll",
            "top": 0,
            "left": 0,
            "icon": "roundRect",
            "itemWidth": 14,
            "itemHeight": 3,
            "textStyle": {"color": theme.INK_2, "fontSize": 12},
        },
        "dataZoom": [dict(PROGRAM_ZOOM, xAxisIndex=0), dict(PROGRAM_ZOOM, yAxisIndex=0)],     # 0: time, 1: values
        "xAxis": dict(
            axis,
            type="value",
            name="Time (s)",
            nameGap=28,
            min=0,
            max=round(data["end_time"], 4),
            axisLabel=build_axis_labels(2),
            axisPointer=build_axis_pointer(2),
        ),
        "yAxis": dict(
            axis,
            type="value",
            name=f"{quantity['label']} ({unit})",
            nameGap=48,
            scale=True,
            axisLabel=build_axis_labels(value_digits),
            axisPointer=build_axis_pointer(value_digits),
            **build_value_axis_range(data),
        ),
        "series": series,
    }


# ==================== What the tab shows ====================
def build_view(data, target, where, picked_buses, all_buses):
    """
    Everything the tab draws for one choice, without drawing: the chart's options (None when no
    curve is left), the notes on what is left out, the key of the colours, and the statistics
    of the chosen side (frequency and voltage only; None for the others). Call it off the event
    loop: the statistics of ACTIVSg500 take a moment.
    """
    positions, notes = find_curves(data, target, where, picked_buses, all_buses)
    colors, key = find_curve_colors(data, positions, target, picked_buses)
    chart = build_chart(data, positions, colors, show_legend=bool(picked_buses)) if positions else None
    side_positions = find_side_positions(data, target, where)
    stats = None
    if data["quantity"] == "frequency":
        stats = calc_frequency_stats(data, side_positions)
    if data["quantity"] == "voltage":
        stats = calc_voltage_stats(data, side_positions)
    return {"chart": chart, "notes": notes, "key": key, "stats": stats, "side": find_sides(target).get(where, "All buses")}


def build_key_html(key):
    """The key of the curves' colours as HTML: a dot and a name each, the names escaped."""
    items = [f'<span class="dyn-key-item"><span class="dyn-key-dot" style="background:{color}"></span>{escape(name)}</span>' for color, name in key]
    return "".join(items)
