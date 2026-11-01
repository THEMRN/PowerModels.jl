"""
Frequency response of each island in one ANDES run of the frequency-security tests.

    python analyze_andes.py <run folder>

Reads islands.json (written by the Julia tests), the channels (output_andes_*.csv.gz), the ANDES
power flow report (andes_res_*.xlsx) and the console output (console.txt), and writes
metrics.json with, per island:
  - the scheduled import in the ANDES power flow and the power step the machines take at the split
  - simulated and SFR-predicted RoCoF, nadir / zenith and settling frequency of the island's
    centre of inertia (COI: bus frequencies at the machines, weighted by H x MVA base)
  - UFLS shedding and generator trips by the relays, from the console output
  - COI frequency and SFR prediction every PLOT_STEP for the report
"""

import re
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

# ==================== Settings ====================
EVENT_TIME = 5.0  # s, the boundary opens (andes_scripts/dynamic.py)
NOMINAL_FREQUENCY = 60.0  # Hz
ROCOF_WINDOWS = (0.1, 0.5)  # s, RoCoF measured as the frequency change over these windows after the split
SETTLE_WINDOW = 1.0  # s, settling frequency = average over the last second
POWER_STEP_DELAY = 0.02  # s, machine power right after the split, for the power step
PLOT_STEP = 0.05  # s
PLOT_START = -1.0  # s, relative to the split
TIME_COL = "Time(s)"

UFLS_EVENT = re.compile(r"t=([\d.]+)s\s+bus (\d+) load (\S+) stage (\d+)\s+([\d.]+) %\s+([\d.]+) MW")
TRIP_EVENT = re.compile(r"t=([\d.]+)s\s+relay (\S+)\s+(.+?) at bus (\d+)\s+f=([\d.]+) Hz\s+([-\d.]+) MW")


def newest(folder, pattern):
    """Most recent file matching `pattern` in `folder`, or None."""
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


def calc_andes_import(island, branch_report):
    """Scheduled import of an island in the ANDES power flow (MW, Mvar), at the island end of its boundary lines."""
    active_import = 0.0
    reactive_import = 0.0
    for line in island["boundary"]:
        same_pair = ((branch_report["from"] == line["from"]) & (branch_report["to"] == line["to"])) | (
            (branch_report["from"] == line["to"]) & (branch_report["to"] == line["from"])
        )
        rows = branch_report[same_pair & (branch_report["circuit"].astype(str).str.strip() == line["circuit"])]
        if rows.empty:
            continue  # out of service before the split
        row = rows.iloc[0]
        island_end = "from" if row["from"] == line["island_bus"] else "to"
        active_import -= row[f"MW {island_end}"]
        reactive_import -= row[f"Mvar {island_end}"]
    return active_import, reactive_import


def calc_step(channels, columns, before, step_index, scale):
    """Change of the sum of `columns` across the split: right after (row `step_index`) minus the last sample before."""
    if not columns:
        return 0.0
    return (channels.loc[step_index, columns].sum() - channels.loc[before, columns].iloc[-1].sum()) * scale


def calc_frequency_metrics(times, frequency, settle_start):
    """RoCoF over each window (Hz/s), nadir, zenith (Hz, with times) and settling frequency of a trajectory starting at the split."""
    f_start = frequency[0]
    metrics = {}
    for window in ROCOF_WINDOWS:
        metrics[f"rocof_{int(window * 1000)}ms"] = (np.interp(window, times, frequency) - f_start) / window
    metrics["nadir_hz"] = float(np.min(frequency))
    metrics["nadir_time_s"] = float(times[np.argmin(frequency)])
    metrics["zenith_hz"] = float(np.max(frequency))
    metrics["zenith_time_s"] = float(times[np.argmax(frequency)])
    metrics["settle_hz"] = float(np.mean(frequency[times >= settle_start]))
    return metrics


run_dir = Path(sys.argv[1])
with open(run_dir / "islands.json") as f:
    run = json.load(f)

channels = pd.read_csv(newest(run_dir, "output_andes_*.csv.gz"))
branch_report = pd.read_excel(newest(run_dir, "andes_res_*.xlsx"), sheet_name="branch")
console_file = run_dir / "console.txt"
console = console_file.read_text(errors="ignore") if console_file.exists() else ""

times = channels[TIME_COL].to_numpy()
before = times < EVENT_TIME  # samples before the split (the one at EVENT_TIME is pre-trip too, but may repeat)
after = times > EVENT_TIME
t_after = times[after] - EVENT_TIME
sim_duration = t_after[-1]

# channel names by bus / machine
frequency_column = {}
voltage_column = {}
power_column = {}
load_columns = {}  # PLOD channels by bus
for column in channels.columns:
    if column.startswith("FREQ "):
        frequency_column[int(column.split()[1])] = column
    elif column.startswith("VOLT "):
        voltage_column[int(column.split()[1])] = column
    elif column.startswith("POWR "):
        bus = int(re.match(r"POWR (\d+)\[", column).group(1))
        machine_id = column.rsplit("]", 1)[1].strip()
        power_column[(bus, machine_id)] = column
    elif column.startswith("PLOD "):
        bus = int(re.match(r"PLOD (\d+)\[", column).group(1))
        load_columns.setdefault(bus, []).append(column)
step_index = int(np.searchsorted(times, EVENT_TIME + POWER_STEP_DELAY))

ufls_events = [m.groups() for m in UFLS_EVENT.finditer(console)]
trip_events = [m.groups() for m in TRIP_EVENT.finditer(console)]

island_metrics = []
for island in run["islands"]:
    buses = set(island["buses"])
    base_mva = island["base_mva"]

    # centre-of-inertia frequency: bus frequency at each machine, weighted by H x MVA base
    weights = {}
    for machine in island["machines"]:
        weights[machine["bus"]] = weights.get(machine["bus"], 0.0) + machine["H"] * machine["mbase"]
    total_weight = sum(weights.values())
    coi_deviation = sum(w * channels[frequency_column[bus]].to_numpy() for bus, w in weights.items()) / total_weight
    coi_frequency = NOMINAL_FREQUENCY * (1 + coi_deviation)  # Hz

    # simulated metrics of the COI frequency, from the last pre-split sample
    f_sim = np.concatenate(([coi_frequency[before][-1]], coi_frequency[after]))
    t_sim = np.concatenate(([0.0], t_after))
    sim = calc_frequency_metrics(t_sim, f_sim, sim_duration - SETTLE_WINDOW)
    island_buses_with_channels = [bus for bus in buses if bus in frequency_column]
    bus_frequencies = NOMINAL_FREQUENCY * (1 + channels.loc[after, [frequency_column[b] for b in island_buses_with_channels]].to_numpy())
    sim["min_bus_hz"] = float(bus_frequencies.min())
    sim["max_bus_hz"] = float(bus_frequencies.max())

    # what changes at the split (MW, pu): the machines' electrical power, the island's load (voltage
    # dependent: constant current P) and the mean voltage at the island's load buses
    machine_columns = [power_column[(m["bus"], m["id"])] for m in island["machines"] if (m["bus"], m["id"]) in power_column]
    island_load_columns = [column for bus in buses for column in load_columns.get(bus, [])]
    load_bus_voltages = [voltage_column[bus] for bus in buses if bus in load_columns and bus in voltage_column]
    power_step = calc_step(channels, machine_columns, before, step_index, base_mva)
    load_step = calc_step(channels, island_load_columns, before, step_index, base_mva)
    voltage_step = calc_step(channels, load_bus_voltages, before, step_index, 1 / max(len(load_bus_voltages), 1))
    island_load_end = channels[island_load_columns].iloc[-1].sum() * base_mva if island_load_columns else 0.0
    island_load_before = channels.loc[before, island_load_columns].iloc[-1].sum() * base_mva if island_load_columns else 0.0

    # SFR prediction for the import ANDES actually scheduled (linear model: unit response x deficit)
    andes_import, andes_reactive_import = calc_andes_import(island, branch_report)
    deficit = andes_import / base_mva  # pu
    sfr_times = np.array(island["sfr_unit"]["t"])
    sfr_frequency = NOMINAL_FREQUENCY + deficit * np.array(island["sfr_unit"]["df_hz"])
    sfr_undamped = NOMINAL_FREQUENCY + deficit * np.array(island["sfr_unit"]["df_hz_undamped"])
    settle_start = min(sim_duration, sfr_times[-1]) - SETTLE_WINDOW
    sfr = calc_frequency_metrics(sfr_times, sfr_frequency, settle_start)
    sfr["rocof_initial"] = -deficit * NOMINAL_FREQUENCY / (2 * island["inertia"])
    sfr["settle_final_hz"] = (
        NOMINAL_FREQUENCY - deficit * NOMINAL_FREQUENCY / (island["damping"] + island["governor_gain"])
        if island["damping"] + island["governor_gain"] > 0
        else None
    )
    sfr_no_damping = calc_frequency_metrics(sfr_times, sfr_undamped, settle_start)
    # the initial RoCoF the machines' power step implies (swing equation, no measurement filter);
    # a positive step (machines deliver more than before) is a deficit and drives the frequency down
    sim["rocof_from_power_step"] = -power_step * NOMINAL_FREQUENCY / (2 * island["inertia"] * base_mva)

    # relay actions in this island
    ufls = [e for e in ufls_events if int(e[1]) in buses]
    trips = [e for e in trip_events if int(e[3]) in buses]

    # trajectories for the report, relative to the split
    plot_times = np.arange(PLOT_START, min(sim_duration, sfr_times[-1]) + 1e-9, PLOT_STEP)
    plot_sim = np.interp(plot_times, times - EVENT_TIME, coi_frequency)
    plot_sfr = np.where(plot_times < 0, NOMINAL_FREQUENCY, np.interp(plot_times, sfr_times, sfr_frequency))

    island_metrics.append(
        {
            "n_buses": len(buses),
            "inertia": island["inertia"],
            "governor_gain": island["governor_gain"],
            "damping": island["damping"],
            "limits_mw": island["limits_mw"],
            "binding": island["binding"],
            "scheduled_import_mw": island["scheduled_import_mw"],
            "andes_import_mw": andes_import,
            "andes_reactive_import_mvar": andes_reactive_import,
            "power_step_mw": power_step,
            "load_step_mw": load_step,
            "load_before_mw": island_load_before,
            "load_end_mw": island_load_end,
            "voltage_step_pu": voltage_step,
            "sim": sim,
            "sfr": sfr,
            "sfr_no_damping": sfr_no_damping,
            "ufls_mw": sum(float(e[5]) for e in ufls),
            "ufls_events": len(ufls),
            "first_ufls_s": min((float(e[0]) - EVENT_TIME for e in ufls), default=None),
            "gen_trips": [{"t": float(e[0]) - EVENT_TIME, "bus": int(e[3]), "mw": float(e[5])} for e in trips],
            "trace": {
                "t": np.round(plot_times, 3).tolist(),
                "sim": np.round(plot_sim, 5).tolist(),
                "sfr": np.round(plot_sfr, 5).tolist(),
            },
        }
    )

metrics = {
    "run_info": run["run_info"],
    "busted": "stopped early" in console,
    "init_steady": "not at steady state" not in console,  # False when ANDES clamped a variable at initialization
    "sim_end_s": float(sim_duration),  # s after the split; short of 20 s when the simulation stopped early
    "ufls_total_mw": sum(float(e[5]) for e in ufls_events),
    "gen_trips_total": len(trip_events),
    "islands": island_metrics,
}
with open(run_dir / "metrics.json", "w") as f:
    json.dump(metrics, f)

for k, m in enumerate(island_metrics, start=1):
    print(
        f"island {k}: import {m['andes_import_mw']:.1f} MW (PM {m['scheduled_import_mw']:.1f}), step {m['power_step_mw']:.1f} MW "
        f"(load {m['load_step_mw']:.1f} MW, V {m['voltage_step_pu']:+.3f} pu) | "
        f"nadir {m['sim']['nadir_hz']:.3f} (SFR {m['sfr']['nadir_hz']:.3f}) zenith {m['sim']['zenith_hz']:.3f} (SFR {m['sfr']['zenith_hz']:.3f}) | "
        f"RoCoF500 {m['sim']['rocof_500ms']:.3f} (SFR {m['sfr']['rocof_500ms']:.3f}) | settle {m['sim']['settle_hz']:.3f} (SFR {m['sfr']['settle_hz']:.3f}) | "
        f"UFLS {m['ufls_mw']:.1f} MW, trips {len(m['gen_trips'])}"
    )
