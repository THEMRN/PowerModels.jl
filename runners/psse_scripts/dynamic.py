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

# specify your PSSE installation path here, in raw string format, i.e., r"your_path_here"
# 36.1 example path:
PSSE_PATH = r"C:\Program Files\PTI\PSSE36\36.5"
PYTHON_VERSION = "14"


class Tee(object):
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()


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

print("-- file paths:")
print("Raw file path:\r", raw_file_pth)
print("Dyr file path:\r", dyr_file_pth)
print("Excel file path:\r", excel_file_pth)
print("Output directory:\r", output_dir)
now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

print("-- Initializing PSSE...")
psspy.psseinit()
log_file = f"{output_dir}/log_{now}.txt"
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
f = open(log_file, "w")
sys.stdout = Tee(sys.stdout, f)
sys.stderr = Tee(sys.stderr, f)
# psspy.progress_output(2, log_file, [0, 0])
# psspy.progress_output(1, "", [0, 0])
psspy.progress_output(6, "", [0, 0])

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
psspy.run(0, 10.0, 1000, 1, 1)

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
psspy.run(0, 30.0, 1000, 1, 1)

# read the channel data
print("-- Reading channel data...")
ch_data = dyntools.CHNF(output_file)
# extract channel data
short_title, chanid_dict, chandata_dict = ch_data.get_data()
# build the channel data DataFrame
df = pd.DataFrame({chanid_dict[key]: values for key, values in chandata_dict.items()})

# print(df.head())

print("-- Plotting dynamic simulation channels...")
keywords = ["POWR", "VARS", "FREQ", "VOLT", "PLOD"]
# keywords = ["FREQ", "POWR"]
# keywords = ["POWR"]
keyword_map = {
    "POWR": {"title": "Generator Electrical Power (MW)", "yaxis": "Power (MW)"},
    "VARS": {"title": "Generator Reactive Power (MVar)", "yaxis": "Reactive Power (MVar)"},
    "FREQ": {"title": "Bus Frequency (Hz)", "yaxis": "Frequency (Hz)"},
    "VOLT": {"title": "Bus Voltage (pu)", "yaxis": "Voltage (pu)"},
    "PLOD": {"title": "Load Active Power (MW)", "yaxis": "Load P (MW)"},
}

time_col = "Time(s)"
if time_col not in df.columns:
    print(f"-- Time column '{time_col}' not found; available columns: {list(df.columns)}")
    sys.exit(1)

# midlands zone buses
# midlands_buses = get_buses_in_zone(5)

plot_blocks = []
for keyword in keywords:
    fig = go.Figure()
    cols_to_plot = [col for col in df.columns if keyword in col and col != time_col]

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
                if not any(df[col].iloc[-100:].values):
                    continue
                # skip voltage channels that don't exceed normal voltage range (0.9-1.1) during the whole simulation
                if np.all((df[col].values >= 0.9) & (df[col].values <= 1.1)):
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

    plot_blocks.append(pio.to_html(fig, include_plotlyjs=(len(plot_blocks) == 0), full_html=False))

plots_path = output_dir / f"dynamic_channels_{now}.html"
html_doc = (
    "<html><head><meta charset='utf-8'><title>Dynamic Simulation Channels</title>"
    "<style>body{margin:0;padding:20px;font-family:Arial,sans-serif;background:#fafafa;}"
    ".plot{margin:0 0 24px 0;background:#fff;padding:8px;border-radius:8px;"
    "box-shadow:0 1px 4px rgba(0,0,0,0.08);}</style></head><body>"
)
html_doc += "".join([f"<div class='plot'>{block}</div>" for block in plot_blocks])
html_doc += "</body></html>"

with open(plots_path, "w", encoding="utf-8") as pf:
    pf.write(html_doc)

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

# ------------------------------------------------------------------
# parse load shedding (LDSTBL) events from the log file
try:
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

sys.stdout = _orig_stdout
sys.stderr = _orig_stderr
f.close()
sys.exit(0)
