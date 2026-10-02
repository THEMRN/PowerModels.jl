import sys
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path
import json
import datetime as dt
import re
import webbrowser
from html import escape

print("-- Starting dynamic simulation script...")

# specify your PSSE installation path here, in raw string format, i.e., r"your_path_here"
# 36.1 example path:
PSSE_PATH = r"C:\Program Files\PTI\PSSE36\36.5"
PYTHON_VERSION = "14"


def get_buses_in_zone(zone_num: int) -> list[int]:
    """
    Get the buses in a given zone.
    """
    ierr, buses = psspy.abusint(-1, 2, ["NUMBER"])
    ierr, zones = psspy.abusint(-1, 2, ["ZONE"])
    buses = buses[0]
    zones = zones[0]
    return [b for b, z in zip(buses, zones) if z == zone_num]


print("-- Starting dynamic simulation script...")
print(f"-- Python version: {sys.version.split()[0]}  executable: {sys.executable}")


# set PSSE environment variables
os.environ["PATH"] = f"{PSSE_PATH}\\PSSBIN;" + os.environ["PATH"]
os.environ["PSSPY_PATH"] = f"{PSSE_PATH}\\PSSPY3{PYTHON_VERSION}"
# add PSSE modules to the system path
sys.path.append(f"{PSSE_PATH}\\PSSPY3{PYTHON_VERSION}")
sys.path.append(f"{PSSE_PATH}\\PSSLIB")

# case file paths
try:
    raw_file_pth = sys.argv[1]
    dyr_file_pth = sys.argv[2]
    excel_file_pth = sys.argv[3]
    output_dir = Path(raw_file_pth).parent
except IndexError:
    print("-- Files not provided via command line.")
    sys.exit(1)


# initialize PSSE
import psse3605
import psspy  # type: ignore
import dyntools  # type: ignore

base_freq = 60.0
EVENT_TIME = 5.0
SIM_END_TIME = 25.0
VOLTAGE_LOW = 0.9
VOLTAGE_HIGH = 1.1
WTVSI_K = 1
WTVSI_TOP_N = 5
POST_EVENT_AVG_WINDOW = 1.0

print("-- file paths:")
print("Raw file path:\r", raw_file_pth)
print("Dyr file path:\r", dyr_file_pth)
print("Excel file path:\r", excel_file_pth)
print("Output directory:\r", output_dir)
now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

print("-- Initializing PSSE...")
psspy.psseinit()
log_file = f"{output_dir}/log_{now}.txt"
print(f"-- PSSE progress log: {log_file}")
ierr = psspy.progress_output(2, log_file, [0, 0])
if ierr != 0:
    print(f"-- Warning: failed to redirect PSSE progress output (ierr={ierr})")

# read the raw file
psspy.read(0, raw_file_pth)

# read excel file
print("-- Reading Excel file...")
xls = pd.read_excel(excel_file_pth, sheet_name=None)
bus_df = xls["buses"]
gen_df = xls["generators"]

# set up the generator vsched (now done in raw export, leaving it here for reference)
# print("-- Setting up generator scheduled voltages...")
# for idx, row in gen_df.iterrows():
#     bus = int(row["bus number"])
#     v_sched = bus_df.loc[bus_df["bus number"] == bus, "vm"].values[0]
#     ierr = psspy.plant_data_4(bus, 0, [0, 0], [v_sched])
#     print(f"Setting generator at bus {bus} with scheduled voltage {v_sched}")

# check mismatch for all buses before solving power flow
print("-- Checking initial bus mismatches...")
ierr, bus_nums = psspy.abusint(-1, 2, ["NUMBER"])
ierr, bus_msmtch = psspy.abusreal(-1, 2, ["MISMATCH"])
initial_mismatches = {b: m for b, m in zip(bus_nums[0], bus_msmtch[0])}
large_mismatches = []
for b, m in initial_mismatches.items():
    if abs(m) > 1.0:
        large_mismatches.append(b)
        print(f"Warning: Bus {b} has high initial mismatch of {m:.2f} MW")
if len(large_mismatches) == 0:
    print("-- No large initial mismatches found.")

# solve the power flow
print("-- Solving power flow...")
default_pf_params_intgar = [100, 20, 20, 100, 10, 20, 4, 20, 0]
newton_pf_max_iters_idx = 1
N = 0.1  # default newton mismatch tol
default_pf_params_realar = [
    1.6,
    1.6,
    1.0,
    0.0001,
    1.0,
    N,
    1.0,
    0.00001,
    5.0,
    0.7,
    0.0001,
    0.005,
    1.0,
    0.05,
    0.99,
    0.99,
    N,
    0.00001,
    100.0,
    0.01,
    0.3,
]
newton_pf_mismatch_tol_idx = 5
default_pf_params_realar[newton_pf_mismatch_tol_idx] = 0.001
psspy.solution_parameters_5(default_pf_params_intgar, default_pf_params_realar)

# psspy.solv([0, 0, 0, 0, 0, 0])  # Gauss-Seidel solve, default settings (no flat start)
ierr = psspy.fnsl()  # Newton-Raphson, default options
if ierr != 0:
    print(f"-- Power flow did not converge, error code: {ierr}")
    sys.exit(1)
print("-- Power flow solved successfully.")
# ------------------------------------------------------------------

# build excel report (bus, gen, load, branch)
print("-- Building solved power flow report...")
load_bus_numbers = set()

try:
    # Buses
    ierr, bus_nums = psspy.abusint(-1, 2, ["NUMBER"])
    ierr, bus_v = psspy.abusreal(-1, 2, ["PU"])
    ierr, bus_ang = psspy.abusreal(-1, 2, ["ANGLED"])
    ierr, bus_msmtch = psspy.abusreal(-1, 2, ["MISMATCH"])
    bus_records = []
    for i, b in enumerate(bus_nums[0]):
        bus_records.append(
            {
                "number": b,
                "volt (pu)": bus_v[0][i],
                "angle (d)": bus_ang[0][i],
                "mismatch (MW)": bus_msmtch[0][i],
                "initial mismatch (MW)": initial_mismatches.get(b, None),
            }
        )
    bus_report_df = pd.DataFrame(bus_records)

    # Generators
    ierr, gen_buses = psspy.amachint(-1, 2, ["NUMBER"])
    ierr, gen_ids = psspy.amachchar(-1, 2, ["ID"])
    ierr, gen_pq = psspy.amachreal(-1, 2, ["PGEN", "QGEN"])
    gen_report_df = pd.DataFrame(
        [
            {
                "bus": gen_buses[0][i],
                "id": gen_ids[0][i].strip(),
                "PGEN": gen_pq[0][i],
                "QGEN": gen_pq[1][i],
            }
            for i in range(len(gen_buses[0]))
        ]
    )

    # Loads
    try:
        ierr, load_buses = psspy.aloadint(-1, 2, ["NUMBER"])
        ierr, load_ids = psspy.aloadchar(-1, 2, ["ID"])
        ierr, load_cplx = psspy.aloadcplx(-1, 2, ["TOTALACT", "TOTALNOM"])
        total_act_list, total_nom_list = load_cplx  # lists of complex numbers
        load_rows = []
        for i in range(len(load_buses[0])):
            act = total_act_list[i]
            nom = total_nom_list[i]
            p_act = act.real
            q_act = act.imag
            p_nom = nom.real
            if abs(p_act) > 1e-9 or abs(p_nom) > 1e-9:
                load_bus_numbers.add(int(load_buses[0][i]))
            if p_nom == 0:
                served = 0.0
            else:
                served = (p_act / p_nom) * 100.0
            load_rows.append(
                {
                    "bus": load_buses[0][i],
                    "id": load_ids[0][i].strip(),
                    "MW nom": p_nom,
                    "MW": p_act,
                    "Mvar nom": nom.imag,
                    "Mvar": q_act,
                    "% served": served,
                }
            )
        load_report_df = pd.DataFrame(load_rows)
    except Exception as e:
        print(f"-- Load collection issue: {e}")
        load_report_df = pd.DataFrame(columns=["bus", "id", "MW", "Mvar", "% served"])

    # Branches
    try:
        ierr, br_ints = psspy.abrnint(-1, 2, 1, 4, 1, ["FROMNUMBER", "TONUMBER"])
        ierr, br_ids = psspy.abrnchar(-1, 2, 1, 4, 1, ["ID"])
        ierr, br_flows = psspy.abrnreal(-1, 2, 1, 4, 1, ["P", "Q", "PLOSS", "QLOSS"])

        from_list, to_list = br_ints
        id_list = br_ids[0]
        p_to, q_to, p_loss, q_loss = br_flows

        p_from = [pl - pt for pl, pt in zip(p_loss, p_to)]  # p_from = p_loss - p_to
        q_from = [ql - qt for ql, qt in zip(q_loss, q_to)]

        branch_report_df = pd.DataFrame(
            {
                "from": from_list,
                "to": to_list,
                "circuit": [cid.strip() for cid in id_list],
                "MW from": p_from,
                "MW to": p_to,
                "MW loss": p_loss,
                "Mvar from": q_from,
                "Mvar to": q_to,
                "Mvar loss": q_loss,
            }
        )
    except Exception as e:
        print(f"-- Branch collection issue: {e}")
        branch_report_df = pd.DataFrame(
            columns=[
                "from",
                "to",
                "circuit",
                "MW from",
                "MW to",
                "MW loss",
                "Mvar from",
                "Mvar to",
                "Mvar loss",
            ]
        )

    # Derive report file name
    report_path = excel_file_pth.replace("pm", "psse")
    print(f"-- Writing report to: {report_path}")
    with pd.ExcelWriter(report_path, engine="xlsxwriter") as writer:
        bus_report_df.to_excel(writer, sheet_name="bus", index=False)
        gen_report_df.to_excel(writer, sheet_name="gen", index=False)
        load_report_df.to_excel(writer, sheet_name="load", index=False)
        branch_report_df.to_excel(writer, sheet_name="branch", index=False)
    print("-- Report written.")
except Exception as e:
    print(f"-- Failed to build report: {e}")

# ------------------------------------------------------------------
if dyr_file_pth == "":
    print("-- No dynamic data file provided, skipping dynamic simulation.")
    sys.exit(0)

# dynamic simulation -----------------------------------------------------
# converting generators
print("-- Converting generators...")
psspy.cong(0)

# convering loads
print("-- Converting loads...")
psspy.conl(0, 1, 1, [0, 0], [100.0, 0.0, 0.0, 100.0])
psspy.conl(0, 1, 2, [0, 0], [100.0, 0.0, 0.0, 100.0])
psspy.conl(0, 1, 3, [0, 0], [100.0, 0.0, 0.0, 100.0])

# factorize and initialize swithing study
print("-- Factoring and initializing switching study...")
psspy.fact()
psspy.tysl(0)

# load the dynamic data
print("-- Loading dynamic data...")
psspy.dyre_new_2([1, 1, 1, 1], dyr_file_pth)

# outpu channels for dynamic simulation
print("-- Setting up output channels...")
psspy.chsb(0, 1, [-1, -1, -1, 1, 2, 0])  # generator pelec (POWR)
psspy.chsb(0, 1, [-1, -1, -1, 1, 3, 0])  # generator qelec (VARS)
psspy.chsb(0, 1, [-1, -1, -1, 1, 12, 0])  # bus frequency  (FREQ)
psspy.chsb(0, 1, [-1, -1, -1, 1, 13, 0])  # bus voltage    (VOLT)
psspy.chsb(0, 1, [-1, -1, -1, 1, 25, 0])  # p load         (PLOD)
psspy.chsb(0, 1, [-1, -1, -1, 1, 26, 0])  # q load         (QLOD)

output_file = f"{output_dir}/output_psse_{now}.out"
if Path(output_file).exists():
    os.remove(output_file)
print(f"-- output file: {output_file}")
psspy.strt_2([0, 0], output_file)
print("-- Initializing dynamic simulation...")
psspy.run(0, -0.02, 1000, 1, 1)
print("-- Running dynamic simulation... (pre-event)")
psspy.run(0, EVENT_TIME, 1000, 1, 1)

# reading the line outages from the file
try:
    outage_file = output_dir / "line_outage.json"
    if outage_file.exists():
        print(f"-- Reading line outage file: {outage_file}")
        with open(outage_file, "r") as f:
            outages = json.load(f)
        if not isinstance(outages, list):
            print("-- Outage file format unexpected (not a list). Skipping trips.")
        else:
            for o in outages:
                try:
                    fbus = int(o["from"])
                    tbus = int(o["to"])
                    cid = str(o["id"]).strip()
                    # print(f"-- Tripping branch {fbus}-{tbus} id {cid}")
                    psspy.dist_branch_trip(fbus, tbus, cid)
                except Exception as e:
                    print(f"-- Failed to trip outage entry {o}, ({fbus}, {tbus}): {e}")
            print(f"-- Tripped {len(outages)} branches")

    else:
        print(f"-- No line outage file found at {outage_file}, skipping branch trips.")
except Exception as e:
    print(f"-- Error processing outage file: {e}")

# ----------------------------------------------
print("-- Running dynamic simulation... (post-event)")
psspy.run(0, SIM_END_TIME, 1000, 1, 1)

# read the channel data
print("-- Reading channel data...")
ch_data = dyntools.CHNF(output_file)
# extract channel data
short_title, chanid_dict, chandata_dict = ch_data.get_data()
# build the channel data DataFrame
df = pd.DataFrame({chanid_dict[key]: values for key, values in chandata_dict.items()})

# print(df.head())

print("-- Plotting dynamic simulation channels...")
keywords = ["FREQ", "VOLT", "POWR", "VARS", "PLOD"]
# keywords = ["FREQ", "POWR"]
# keywords = ["POWR"]
keyword_map = {
    "POWR": {"title": "Generator Electrical Power (MW)", "yaxis": "Power (MW)"},
    "VARS": {"title": "Generator Reactive Power (MVar)", "yaxis": "Reactive Power (MVar)"},
    "FREQ": {"title": "Bus Frequency (Hz)", "yaxis": "Frequency (Hz)"},
    "VOLT": {"title": "Bus Voltage (pu)", "yaxis": "Voltage (pu)"},
    "PLOD": {"title": "Load Active Power (MW)", "yaxis": "Load P (MW)"},
}
SHOW_SIGNAL_STATS = True
SIGNAL_STATS_KEYWORDS = {"FREQ", "VOLT"}
SIGNAL_STATS_TOP_N = 5

time_col = "Time(s)"
if time_col not in df.columns:
    print(f"-- Time column '{time_col}' not found; available columns: {list(df.columns)}")
    sys.exit(1)

# midlands zone buses
# midlands_buses = get_buses_in_zone(5)


def _fmt(value, digits=4):
    return f"{value:.{digits}f}"


def _series_arrays(series_info):
    values = np.asarray(series_info["values"], dtype=float)
    times = np.asarray(series_info["time"], dtype=float)
    finite = np.isfinite(values) & np.isfinite(times)
    return values[finite], times[finite]


def extract_bus_number(channel_name):
    match = re.search(r"(\d+)", channel_name)
    return int(match.group(1)) if match else None


def is_valid_voltage_profile(values):
    tail_values = np.asarray(values[-100:], dtype=float)
    return bool(np.any(np.isfinite(tail_values) & (np.abs(tail_values) > 1e-9)))


def calculate_wtvsi(df, time_col, load_buses, t0, t_end, k=WTVSI_K):
    duration = float(t_end - t0)
    load_buses = {int(bus) for bus in load_buses}
    bus_integrals = {}
    voltage_channel_count = 0

    if time_col not in df.columns or duration <= 0.0 or not load_buses:
        return {
            "wtvsi": 0.0,
            "event_time": float(t0),
            "end_time": float(t_end),
            "duration": max(duration, 0.0),
            "k": k,
            "load_bus_count": len(load_buses),
            "integrated_bus_count": 0,
            "missing_voltage_profile_count": len(load_buses),
            "voltage_channel_count": 0,
            "top_contributors": [],
            "bus_integrals": {},
        }

    all_times = np.asarray(df[time_col], dtype=float)
    for col in [c for c in df.columns if "VOLT" in c and c != time_col]:
        bus = extract_bus_number(col)
        # if bus not in load_buses:
        #     continue

        values = np.asarray(df[col], dtype=float)
        if not is_valid_voltage_profile(values):
            continue

        finite = np.isfinite(values) & np.isfinite(all_times)
        interval = finite & (all_times >= t0) & (all_times <= t_end)
        if not np.any(interval):
            continue

        voltage_channel_count += 1
        interval_values = values[interval]
        interval_times = all_times[interval]
        delta = np.maximum.reduce(
            [
                np.full_like(interval_values, VOLTAGE_LOW) - interval_values,
                np.zeros_like(interval_values),
                interval_values - np.full_like(interval_values, VOLTAGE_HIGH),
            ]
        )
        integral = float(np.trapezoid(delta**k, interval_times))
        bus_integrals[bus] = max(bus_integrals.get(bus, 0.0), integral)

    total_integral = sum(bus_integrals.values())
    wtvsi = total_integral / (voltage_channel_count * duration) if voltage_channel_count else 0.0
    # wtvsi = total_integral / (len(load_buses) * duration)
    top_contributors = [
        {"bus": bus, "integral": value}
        for bus, value in sorted(bus_integrals.items(), key=lambda item: item[1], reverse=True)[:WTVSI_TOP_N]
        if value > 0.0
    ]

    return {
        "wtvsi": float(wtvsi),
        "event_time": float(t0),
        "end_time": float(t_end),
        "duration": duration,
        "k": k,
        # "load_bus_count": len(load_buses),
        "bus_count": len(bus_integrals),
        "integrated_bus_count": len(bus_integrals),
        # "missing_voltage_profile_count": max(0, len(load_buses) - len(bus_integrals)),
        "voltage_channel_count": voltage_channel_count,
        "top_contributors": top_contributors,
        "bus_integrals": {str(bus): value for bus, value in sorted(bus_integrals.items())},
    }


def finite_voltage_series(values, times):
    values = np.asarray(values, dtype=float)
    times = np.asarray(times, dtype=float)
    finite = np.isfinite(values) & np.isfinite(times)
    return values[finite], times[finite]


def build_voltage_stats_json(df, time_col, load_buses, t0, t_end):
    all_times = np.asarray(df[time_col], dtype=float)
    bus_stats = {}

    for col in [c for c in df.columns if "VOLT" in c and c != time_col]:
        bus = extract_bus_number(col)
        if bus is None:
            continue

        values, times = finite_voltage_series(df[col], all_times)
        if len(values) == 0 or not is_valid_voltage_profile(values):
            continue

        min_idx = int(np.argmin(values))
        max_idx = int(np.argmax(values))
        min_val = float(values[min_idx])
        max_val = float(values[max_idx])
        min_time = float(times[min_idx])
        max_time = float(times[max_idx])
        under_violation = max(0.0, VOLTAGE_LOW - min_val)
        over_violation = max(0.0, max_val - VOLTAGE_HIGH)
        worst_violation = max(under_violation, over_violation)
        worst_time = min_time if under_violation >= over_violation else max_time

        pre_mask = times <= t0
        pre_event_voltage = float(values[pre_mask][-1]) if np.any(pre_mask) else float(values[0])
        event_mask = times >= t0
        event_values = values[event_mask] if np.any(event_mask) else values[-1:]
        event_times = times[event_mask] if np.any(event_mask) else times[-1:]
        event_deltas = event_values - pre_event_voltage
        worst_event_idx = int(np.argmax(np.abs(event_deltas)))
        worst_event_voltage = float(event_values[worst_event_idx])
        worst_event_time = float(event_times[worst_event_idx])
        worst_event_delta = float(event_deltas[worst_event_idx])
        tail_start = max(float(t0), float(t_end) - POST_EVENT_AVG_WINDOW)
        post_mask = times >= tail_start
        post_event_voltage = float(np.mean(values[post_mask])) if np.any(post_mask) else float(values[-1])
        final_voltage = float(values[-1])

        record = {
            "channel": col,
            "min": min_val,
            "max": max_val,
            "min_time": min_time,
            "max_time": max_time,
            "under_violation": under_violation,
            "over_violation": over_violation,
            "worst_violation": worst_violation,
            "worst_time": worst_time,
            "initial_voltage": float(values[0]),
            "pre_event_voltage": pre_event_voltage,
            "worst_event_voltage": worst_event_voltage,
            "worst_event_time": worst_event_time,
            "worst_event_delta": worst_event_delta,
            "post_event_voltage": post_event_voltage,
            "final_voltage": final_voltage,
            "post_event_delta": post_event_voltage - pre_event_voltage,
            "final_delta": final_voltage - pre_event_voltage,
        }

        previous = bus_stats.get(str(bus))
        if (
            previous is None
            or record["worst_violation"] > previous["worst_violation"]
            or abs(record["worst_event_delta"]) > abs(previous["worst_event_delta"])
        ):
            bus_stats[str(bus)] = record

    summary = {
        "voltage_low": VOLTAGE_LOW,
        "voltage_high": VOLTAGE_HIGH,
        "event_time": float(t0),
        "end_time": float(t_end),
        "post_event_avg_window": POST_EVENT_AVG_WINDOW,
        "bus_count": len(bus_stats),
        "outside_band_count": sum(1 for row in bus_stats.values() if row["worst_violation"] > 0.0),
    }
    if bus_stats:
        worst_bus, worst_row = max(bus_stats.items(), key=lambda item: item[1]["worst_violation"])
        largest_worst_delta_bus, largest_worst_delta_row = max(
            bus_stats.items(), key=lambda item: abs(item[1]["worst_event_delta"])
        )
        min_bus, min_row = min(bus_stats.items(), key=lambda item: item[1]["min"])
        max_bus, max_row = max(bus_stats.items(), key=lambda item: item[1]["max"])
        summary.update(
            {
                "worst_bus": int(worst_bus),
                "worst_violation": worst_row["worst_violation"],
                "largest_worst_event_delta_bus": int(largest_worst_delta_bus),
                "largest_worst_event_delta": largest_worst_delta_row["worst_event_delta"],
                "min_voltage_bus": int(min_bus),
                "min_voltage": min_row["min"],
                "max_voltage_bus": int(max_bus),
                "max_voltage": max_row["max"],
            }
        )
    else:
        summary.update(
            {
                "worst_bus": None,
                "worst_violation": 0.0,
                "largest_worst_event_delta_bus": None,
                "largest_worst_event_delta": 0.0,
                "min_voltage_bus": None,
                "min_voltage": None,
                "max_voltage_bus": None,
                "max_voltage": None,
            }
        )

    return {
        "summary": summary,
        "buses": {str(bus): row for bus, row in sorted(bus_stats.items(), key=lambda item: int(item[0]))},
        "wtvsi": calculate_wtvsi(df, time_col, load_buses, t0, t_end, WTVSI_K),
    }


def write_voltage_stats_json(output_dir, voltage_stats):
    stats_path = output_dir / "voltage_stats.json"
    with open(stats_path, "w", encoding="utf-8") as file:
        json.dump(voltage_stats, file, indent=2)

    summary = voltage_stats["summary"]
    wtvsi_summary = voltage_stats["wtvsi"]
    print(
        "-- Voltage stats written: "
        f"{stats_path} | outside band={summary['outside_band_count']} "
        f"| worst bus={summary['worst_bus']} "
        f"| worst violation={summary['worst_violation']:.5f} "
        f"| largest worst-event dV={summary['largest_worst_event_delta']:.5f} "
        f"| WTVSI={wtvsi_summary['wtvsi']:.6f}"
    )
    return stats_path


def _metric_card(label, value, detail=""):
    detail_html = f"<span>{escape(detail)}</span>" if detail else ""
    return f"<div class='metric'><label>{escape(label)}</label><strong>{escape(value)}</strong>{detail_html}</div>"


def _stats_table(rows, columns):
    if not rows:
        return "<div class='stats-empty'>No plotted signals available for stats.</div>"

    header_html = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    rows_html = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row[key]))}</td>" for key, _ in columns)
        rows_html.append(f"<tr>{cells}</tr>")
    return (
        f"<table class='stats-table'><thead><tr>{header_html}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"
    )


def build_frequency_stats_html(plotted_series):
    rows = []
    below_59 = 0
    below_57 = 0
    above_605 = 0
    above_618 = 0

    for series_info in plotted_series:
        values, times = _series_arrays(series_info)
        if len(values) == 0:
            continue

        min_idx = int(np.argmin(values))
        max_idx = int(np.argmax(values))
        min_val = float(values[min_idx])
        max_val = float(values[max_idx])
        min_time = float(times[min_idx])
        max_time = float(times[max_idx])
        min_dev = abs(min_val - base_freq)
        max_dev = abs(max_val - base_freq)
        if min_dev >= max_dev:
            worst_dev = min_dev
            worst_time = min_time
        else:
            worst_dev = max_dev
            worst_time = max_time

        below_59 += int(np.any(values < 59.0))
        below_57 += int(np.any(values < 57.0))
        above_605 += int(np.any(values > 60.5))
        above_618 += int(np.any(values > 61.8))
        rows.append(
            {
                "channel": series_info["name"],
                "min": min_val,
                "max": max_val,
                "min_time": min_time,
                "max_time": max_time,
                "worst_dev": worst_dev,
                "worst_time": worst_time,
            }
        )

    if not rows:
        return "<section class='stats-card'><h3>Frequency Stats</h3><div class='stats-empty'>No plotted frequency signals available.</div></section>"

    nadir = min(rows, key=lambda row: row["min"])
    zenith = max(rows, key=lambda row: row["max"])
    worst = max(rows, key=lambda row: row["worst_dev"])
    top_rows = sorted(rows, key=lambda row: row["worst_dev"], reverse=True)[:SIGNAL_STATS_TOP_N]
    table_rows = [
        {
            "channel": row["channel"],
            "min": _fmt(row["min"]),
            "max": _fmt(row["max"]),
            "dev": _fmt(row["worst_dev"]),
            "time": _fmt(row["worst_time"], 3),
        }
        for row in top_rows
    ]

    metrics_html = "".join(
        [
            _metric_card("Channels", str(len(rows))),
            _metric_card("Nadir", f"{_fmt(nadir['min'])} Hz", f"{nadir['channel']} at {nadir['min_time']:.3f}s"),
            _metric_card("Zenith", f"{_fmt(zenith['max'])} Hz", f"{zenith['channel']} at {zenith['max_time']:.3f}s"),
            _metric_card(
                "Worst Dev", f"{_fmt(worst['worst_dev'])} Hz", f"{worst['channel']} at {worst['worst_time']:.3f}s"
            ),
            _metric_card("Thresholds", f"<59: {below_59}, <57: {below_57}", f">60.5: {above_605}, >61.8: {above_618}"),
        ]
    )
    table_html = _stats_table(
        table_rows,
        [
            ("channel", "Top Frequency Channels"),
            ("min", "Min Hz"),
            ("max", "Max Hz"),
            ("dev", "Worst Dev"),
            ("time", "Time s"),
        ],
    )
    return f"<section class='stats-card'><h3>Frequency Stats</h3><div class='metrics'>{metrics_html}</div>{table_html}</section>"


def build_wtvsi_table_html(wtvsi_summary):
    if not wtvsi_summary or not wtvsi_summary["top_contributors"]:
        return ""

    rows = [
        {"bus": row["bus"], "integral": _fmt(row["integral"], 6)}
        for row in wtvsi_summary["top_contributors"]
        if row["integral"] > 0.0
    ]
    if not rows:
        return ""
    return _stats_table(rows, [("bus", "Top WTVSI Bus"), ("integral", "Integral")])


def build_voltage_stats_html(plotted_series, wtvsi_summary=None):
    rows = []
    below_09 = 0
    above_11 = 0
    outside_band = 0

    for series_info in plotted_series:
        values, times = _series_arrays(series_info)
        if len(values) == 0:
            continue

        min_idx = int(np.argmin(values))
        max_idx = int(np.argmax(values))
        min_val = float(values[min_idx])
        max_val = float(values[max_idx])
        min_time = float(times[min_idx])
        max_time = float(times[max_idx])
        under_violation = max(0.0, VOLTAGE_LOW - min_val)
        over_violation = max(0.0, max_val - VOLTAGE_HIGH)
        worst_violation = max(under_violation, over_violation)
        worst_time = min_time if under_violation >= over_violation else max_time

        below = bool(np.any(values < VOLTAGE_LOW))
        above = bool(np.any(values > VOLTAGE_HIGH))
        below_09 += int(below)
        above_11 += int(above)
        outside_band += int(below or above)
        rows.append(
            {
                "channel": series_info["name"],
                "min": min_val,
                "max": max_val,
                "min_time": min_time,
                "max_time": max_time,
                "worst_violation": worst_violation,
                "worst_time": worst_time,
            }
        )

    wtvsi_metric = ""
    wtvsi_table_html = ""
    if wtvsi_summary:
        wtvsi_metric = _metric_card(
            "WTVSI",
            _fmt(wtvsi_summary["wtvsi"], 6),
            (
                # f"load buses: {wtvsi_summary['load_bus_count']}, "
                f"buses: {wtvsi_summary['bus_count']}, "
                f"t: {wtvsi_summary['event_time']:.1f}-{wtvsi_summary['end_time']:.1f}s"
            ),
        )
        wtvsi_table_html = build_wtvsi_table_html(wtvsi_summary)

    if not rows:
        metrics_html = f"<div class='metrics'>{wtvsi_metric}</div>" if wtvsi_metric else ""
        return (
            "<section class='stats-card'><h3>Voltage Stats</h3>"
            f"{metrics_html}<div class='stats-empty'>No plotted voltage signals available.</div>{wtvsi_table_html}</section>"
        )

    min_voltage = min(rows, key=lambda row: row["min"])
    max_voltage = max(rows, key=lambda row: row["max"])
    worst = max(rows, key=lambda row: row["worst_violation"])
    top_rows = sorted(rows, key=lambda row: row["worst_violation"], reverse=True)[:SIGNAL_STATS_TOP_N]
    table_rows = [
        {
            "channel": row["channel"],
            "min": _fmt(row["min"]),
            "max": _fmt(row["max"]),
            "violation": _fmt(row["worst_violation"]),
            "time": _fmt(row["worst_time"], 3),
        }
        for row in top_rows
    ]

    metrics_html = "".join(
        [
            _metric_card("Channels", str(len(rows))),
            _metric_card(
                "Minimum",
                f"{_fmt(min_voltage['min'])} pu",
                f"{min_voltage['channel']} at {min_voltage['min_time']:.3f}s",
            ),
            _metric_card(
                "Maximum",
                f"{_fmt(max_voltage['max'])} pu",
                f"{max_voltage['channel']} at {max_voltage['max_time']:.3f}s",
            ),
            _metric_card("Outside Band", str(outside_band), f"{VOLTAGE_LOW}-{VOLTAGE_HIGH} pu"),
            _metric_card(
                "Violations",
                f"<{VOLTAGE_LOW}: {below_09}, >{VOLTAGE_HIGH}: {above_11}",
                f"worst {worst['worst_violation']:.4f} pu",
            ),
            wtvsi_metric,
        ]
    )
    table_html = _stats_table(
        table_rows,
        [
            ("channel", "Top Voltage Channels"),
            ("min", "Min pu"),
            ("max", "Max pu"),
            ("violation", "Worst Violation"),
            ("time", "Time s"),
        ],
    )
    return (
        f"<section class='stats-card'><h3>Voltage Stats</h3><div class='metrics'>{metrics_html}</div>"
        f"{table_html}{wtvsi_table_html}</section>"
    )


def load_run_info(output_dir):
    """Load run_info.json written by the julia runner. Returns {} if unavailable."""
    info_path = output_dir / "run_info.json"
    if not info_path.exists():
        return {}
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def build_page_title(info, default="Dynamic Simulation Channels"):
    parts = [str(info[key]) for key in ("target_zone", "objective", "flow_model") if info.get(key)]
    return ", ".join(parts) if parts else default


def build_run_info_html(info, ufls_shed_mw=None):
    """Build a compact header bar from run info.

    Returns an empty string if no relevant field is present.
    """

    def fmt_rel(value):
        if isinstance(value, list):
            return ", ".join(f"{v:g}\u00d7\u03bb" for v in value)
        return f"{value:g}\u00d7\u03bb"

    items = []
    if info.get("target_zone"):
        items.append(("Zone", str(info["target_zone"])))
    if info.get("objective"):
        items.append(("Objective", str(info["objective"])))
    if info.get("flow_model"):
        items.append(("Flow model", str(info["flow_model"])))
    if "uniform_shedding" in info:
        if info["uniform_shedding"]:
            label = "yes"
            if "uniform_penalty_rel" in info:
                label += f" ({fmt_rel(info['uniform_penalty_rel'])})"
            items.append(("Uniform shedding", label))
        else:
            items.append(("Uniform shedding", "no"))
            if "shed_penalty_rel" in info:
                text = fmt_rel(info["shed_penalty_rel"])
                if info.get("shed_penalty_scope"):
                    text += f" ({info['shed_penalty_scope']})"
                items.append(("Shed penalty", text))
    if "shed" in str(info.get("objective", "")):
        if "preemptive_shed_mw" in info:
            items.append(("Preemptive shed", f"{info['preemptive_shed_mw']:.2f} MW"))
        if ufls_shed_mw is not None:
            items.append(("UFLS shed", f"{ufls_shed_mw:.2f} MW"))

    if not items:
        return ""

    spans = "".join(
        f"<span class='run-info-item'><label>{escape(label)}</label>{escape(value)}</span>" for label, value in items
    )
    return f"<div class='run-info'>{spans}</div>"


def build_signal_stats_html(keyword, plotted_series, wtvsi_summary=None):
    if keyword == "FREQ":
        return build_frequency_stats_html(plotted_series)
    if keyword == "VOLT":
        return build_voltage_stats_html(plotted_series, wtvsi_summary)
    return ""


voltage_stats = build_voltage_stats_json(df, time_col, load_bus_numbers, EVENT_TIME, SIM_END_TIME)
wtvsi_summary = voltage_stats["wtvsi"]
write_voltage_stats_json(output_dir, voltage_stats)

# ------------------------------------------------------------------
# parse load shedding (LDSTBL) events from the log file
ufls_total_p_mw = None
try:
    # raise Exception("ignore for now")
    detailed_shedding_log = False
    ierr, event_buses = psspy.abusint(-1, 2, ["NUMBER"])
    ierr, event_zones = psspy.abusint(-1, 2, ["ZONE"])
    zone_by_bus = {int(bus): int(zone) for bus, zone in zip(event_buses[0], event_zones[0])}
    ierr, zone_names = psspy.azonechar(-1, 2, ["ZONENAME"])
    zone_names = [name.strip() for name in zone_names[0]]

    events = []
    with open(log_file, "r") as lf:
        lines = lf.readlines()

    for i, line in enumerate(lines):
        m1 = re.search(
            r"(\S+)\s+AT BUS\s+(\d+)\s+LOAD\s+(\S+).*?BREAKER TIMER TIMED OUT AT TIME\s*=\s*([0-9.]+)",
            line,
        )
        if not m1:
            continue

        bus = int(m1.group(2))
        load_id = m1.group(3)  # keep string (could be 1, A, B…)
        time_val = float(m1.group(4))

        if i + 2 >= len(lines):
            continue
        m2 = re.search(r"\s*([0-9.]+)\s+PERCENT OF INITIAL LOAD SHED", lines[i + 1])
        m3 = re.search(
            r"\s*([0-9.]+)\s+MW AND\s+([0-9.]+)\s+MVAR SHED\. VOLT\s*=\s*([0-9.]+)\s+FREQUENCY\s*=\s*([0-9.]+)",
            lines[i + 2],
        )
        if not (m2 and m3):
            continue

        percent = float(m2.group(1))
        p = float(m3.group(1))
        q = float(m3.group(2))
        v = float(m3.group(3))
        fval = float(m3.group(4))

        events.append(
            {
                "bus": bus,
                "zone": zone_by_bus.get(bus, 0),
                "zone_name": zone_names[zone_by_bus.get(bus, 0) - 1],
                "load": load_id,
                "time": time_val,
                "percent": percent,
                "p": p,
                "q": q,
                "v": v,
                "f": fval,
            }
        )

    ptot = sum(e["p"] for e in events)
    qtot = sum(e["q"] for e in events)
    ufls_total_p_mw = ptot
    zone_totals = {}
    for e in events:
        zone = e.get("zone", 0)
        if zone == 0:
            continue
        zone_totals.setdefault(zone, {"p": 0.0, "q": 0.0, "count": 0})
        zone_totals[zone]["p"] += e["p"]
        zone_totals[zone]["q"] += e["q"]
        zone_totals[zone]["count"] += 1

    print(f"-- Parsed {len(events)} load shed events (UFLS). Totals: P={ptot:.2f} MW, Q={qtot:.2f} Mvar.")
    if zone_totals:
        print("-- Load shed totals by zone:")
        for zone in sorted(zone_totals):
            totals = zone_totals[zone]
            zone_name = zone_names[zone - 1]
            print(f"   {zone_name}: {totals['count']} events P {totals['p']:.2f} MW Q {totals['q']:.2f} Mvar")
    else:
        print("-- No zone assignments found for parsed load shed events.")

    if len(events) > 0 and (detailed_shedding_log or not zone_totals):
        print("-- Detailed load shed events:")
        for e in events:
            zone_label = e["zone_name"] or "N/A"
            print(
                f"   Bus {e['bus']} Zone {zone_label} Load {e['load']} "
                f"Time {e['time']}s P {e['p']} MW Q {e['q']} Mvar"
            )

except Exception as e:
    print(f"-- Failed to parse load shed events: {e}")

plot_blocks = []
plot_count = 0
for keyword in keywords:
    fig = go.Figure()
    cols_to_plot = [col for col in df.columns if keyword in col and col != time_col]
    plotted_series = []

    if not cols_to_plot:
        fig.add_annotation(text=f"No channels found for {keyword}", showarrow=False)
    else:
        for col in cols_to_plot:

            # # only plot buses in the specifiec zone
            # greenvil_buses = get_buses_in_zone(2)
            # bus_num = int(re.search(r"(\d+)", col).group(1))
            # if bus_num not in greenvil_buses:
            #     continue

            if keyword == "VOLT":  # and not any(df[col].iloc[-100:].values):
                # skip voltage channels that are all zeros at the end
                if not is_valid_voltage_profile(df[col].values):
                    continue
                # skip voltage channels that don't exceed normal voltage range (0.9-1.1) during the whole simulation
                if np.all((df[col].values >= VOLTAGE_LOW) & (df[col].values <= VOLTAGE_HIGH)):
                    continue

            # skip frequency channels that are all zeros at all times
            if keyword == "FREQ" and all(np.abs(df[col].values) < 1e-6):
                # print(f"-- Skipping frequency channel {col} because it is all zeros")
                continue

            series_to_plot = df[col]
            hover_value_fmt = "%{y:.4f}"
            if keyword == "FREQ":
                series_to_plot = base_freq * (df[col] + 1.0)
                hover_value_fmt = "%{y:.4f} Hz"

            if SHOW_SIGNAL_STATS and keyword in SIGNAL_STATS_KEYWORDS:
                plotted_series.append({"name": col, "values": series_to_plot, "time": df[time_col]})

            fig.add_trace(
                go.Scatter(
                    x=df[time_col],
                    y=series_to_plot,
                    mode="lines",
                    name=col,
                    hovertemplate="Time: %{x:.4f}s<br>Value: " + hover_value_fmt + "<extra>" + col + "</extra>",
                )
            )

    if keyword == "FREQ":
        freq_lines = [
            {"y": 57, "color": "red", "style": "dash", "time": 0, "width": 1},
            {"y": 59, "color": "orange", "style": "dash", "time": 3, "width": 1},
            {"y": 60.5, "color": "orange", "style": "dash", "time": 8, "width": 1},
            {"y": 61.8, "color": "red", "style": "dash", "time": 0, "width": 1},
            {"y": 59.5, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
            {"y": 59.3, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
            {"y": 59.1, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
        ]
        for line in freq_lines:
            fig.add_hline(
                y=line["y"],
                line_dash=line.get("style", "solid"),
                line_width=line["width"],
                line_color=line["color"],
            )

    fig.update_layout(
        title=keyword_map[keyword]["title"],
        xaxis_title="Time (s)",
        yaxis_title=keyword_map[keyword]["yaxis"],
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        margin=dict(b=120),
        hovermode="closest",
        template="plotly_white",
        height=560,
    )

    plot_blocks.append({"kind": "plot", "html": pio.to_html(fig, include_plotlyjs=(plot_count == 0), full_html=False)})
    plot_count += 1
    if SHOW_SIGNAL_STATS and keyword in SIGNAL_STATS_KEYWORDS:
        plot_blocks.append({"kind": "stats", "html": build_signal_stats_html(keyword, plotted_series, wtvsi_summary)})

plots_path = output_dir / f"dynamic_channels_{now}.html"
run_info = load_run_info(output_dir)
html_doc = (
    f"<html><head><meta charset='utf-8'><title>{escape(build_page_title(run_info))}</title>"
    "<style>body{margin:0;padding:20px;font-family:Arial,sans-serif;background:#fafafa;}"
    ".run-info{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline;margin:0 0 14px 0;"
    "background:#fff;padding:6px 12px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);font-size:12px;}"
    ".run-info-item label{color:#666;font-size:10px;text-transform:uppercase;letter-spacing:.03em;margin-right:5px;}"
    ".plot{margin:0 0 24px 0;background:#fff;padding:8px;border-radius:8px;"
    "box-shadow:0 1px 4px rgba(0,0,0,0.08);}"
    ".stats{margin:-12px 0 24px 0;background:#fff;padding:12px 14px;border-radius:8px;"
    "box-shadow:0 1px 4px rgba(0,0,0,0.08);}"
    ".stats-card h3{margin:0 0 8px 0;font-size:16px;}"
    ".metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:10px;}"
    ".metric{border:1px solid #e6e6e6;border-radius:6px;padding:6px 8px;background:#fcfcfc;}"
    ".metric label{display:block;color:#666;font-size:11px;text-transform:uppercase;letter-spacing:.03em;}"
    ".metric strong{display:block;font-size:15px;margin-top:2px;}"
    ".metric span{display:block;color:#666;font-size:11px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
    ".stats-table{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed;}"
    ".stats-table th,.stats-table td{border-top:1px solid #eee;padding:4px 6px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
    ".stats-table th{color:#555;background:#fafafa;font-weight:600;}"
    ".stats-empty{color:#666;font-size:13px;}</style></head><body>"
)
html_doc += build_run_info_html(run_info, ufls_total_p_mw)
html_doc += "".join([f"<div class='{block['kind']}'>{block['html']}</div>" for block in plot_blocks])
html_doc += "</body></html>"

with open(plots_path, "w", encoding="utf-8") as pf:
    pf.write(html_doc)

if True:  # ignore for now
    webbrowser.open(plots_path.resolve().as_uri())
    print(f"-- Interactive Plotly page opened: {plots_path}")

# ------------------------------------------------------------------
# analyze Frequency Channels
print("-- Analyzing Frequency channels...")
freq_devs = {}
max_dev_overall = -1.0
bus_max_overall = None
val_max_overall = 0.0

freq_cols = [c for c in df.columns if "FREQ" in c and c != time_col]

for col in freq_cols:
    # extract bus number from column name (e.g., "FREQ 101 ...")
    match = re.search(r"(\d+)", col)
    if match:
        bus = int(match.group(1))

        series = df[col]
        if series.empty:
            continue

        max_val = series.max()
        min_val = series.min()

        if abs(min_val) > abs(max_val):
            extreme_val = min_val
            mag = abs(min_val)
        else:
            extreme_val = max_val
            mag = abs(max_val)

        extreme_val = float(base_freq * (extreme_val + 1))  # convert pu deviation to Hz
        freq_devs[bus] = round(extreme_val, 4)

        if mag > max_dev_overall:
            max_dev_overall = mag
            bus_max_overall = bus
            val_max_overall = extreme_val

# print(f"-- Frequency extremes per bus: {freq_devs}")
if bus_max_overall is not None:
    print(f"-- Bus with maximum frequency deviation: Bus {bus_max_overall} (Value: {val_max_overall:.4f})")

psspy.progress_output(1, "", [0, 0])
sys.exit(0)
