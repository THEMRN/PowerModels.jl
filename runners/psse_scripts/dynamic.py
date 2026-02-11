import sys
import os
import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import plotly.io as pio
from pathlib import Path
import json
import datetime as dt
import re

# specify your PSSE installation path here, in raw string format, i.e., r"your_path_here"
# 36.1 example path:
PSSE_PATH = r"C:\Program Files\PTI\PSSE36\36.1"


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


print("-- Starting dynamic simulation script...")
print(f"-- Python version: {sys.version.split()[0]}  executable: {sys.executable}")


# set PSSE environment variables
os.environ["PATH"] = f"{PSSE_PATH}\\PSSBIN;" + os.environ["PATH"]
os.environ["PSSPY_PATH"] = f"{PSSE_PATH}\\PSSPY311"
# add PSSE modules to the system path
sys.path.append(f"{PSSE_PATH}\\PSSPY311")
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
import psse3601
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
f = open(log_file, "w")
sys.stdout = Tee(sys.stdout, f)
sys.stderr = Tee(sys.stderr, f)
# psspy.progress_output(2, log_file, [0, 0])
# psspy.progress_output(1, "", [0, 0])

# read the raw file
psspy.read(0, raw_file_pth)

# read excel file
print("-- Reading Excel file...")
xls = pd.read_excel(excel_file_pth, sheet_name=None)
bus_df = xls["buses"]
gen_df = xls["generators"]

# set up the generator vsched
print("-- Setting up generator scheduled voltages...")
for idx, row in gen_df.iterrows():
    bus = int(row["bus number"])
    v_sched = bus_df.loc[bus_df["bus number"] == bus, "vm"].values[0]
    ierr = psspy.plant_data_4(bus, 0, [0, 0], [v_sched])
    print(f"Setting generator at bus {bus} with scheduled voltage {v_sched}")

# scaling loads
# print("-- Scaling loads...")
# scale_percent = 5.0
# psspy.scal_4(0, 1, 1, [0, 0, 0, 0, 0, 0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
# psspy.scal_4(0, 1, 2, [0, 0, 0, 2, 0, 1], [scale_percent, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

# solve the power flow
print("-- Solving power flow...")
psspy.solv([0, 0, 0, 0, 0, 0])
psspy.solv([0, 0, 0, 0, 0, 0])
psspy.solv([0, 0, 0, 0, 0, 0])
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
psspy.cong(0)

# convering loads
psspy.conl(0, 1, 1, [0, 0], [100.0, 0.0, 0.0, 100.0])
psspy.conl(0, 1, 2, [0, 0], [100.0, 0.0, 0.0, 100.0])
psspy.conl(0, 1, 3, [0, 0], [100.0, 0.0, 0.0, 100.0])

# factorize and initialize swithing study
psspy.fact()
psspy.tysl(0)

# load the dynamic data
psspy.dyre_new_2([1, 1, 1, 1], dyr_file_pth)

# outpu channels for dynamic simulation
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
psspy.run(0, -0.02, 100, 1, 1)
psspy.run(0, 15.0, 100, 1, 1)

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
                    print(f"-- Tripping branch {fbus}-{tbus} id {cid}")
                    psspy.dist_branch_trip(fbus, tbus, cid)
                except Exception as e:
                    print(f"-- Failed to trip outage entry {o}, ({fbus}, {tbus}): {e}")
    else:
        print(f"-- No line outage file found at {outage_file}, skipping branch trips.")
except Exception as e:
    print(f"-- Error processing outage file: {e}")

# ----------------------------------------------
psspy.run(0, 100.0, 100, 1, 1)

# read the channel data
ch_data = dyntools.CHNF(output_file)
# extract channel data
short_title, chanid_dict, chandata_dict = ch_data.get_data()
# build the channel data DataFrame
df = pd.DataFrame()
for key, values in chandata_dict.items():
    col_name = chanid_dict[key]
    df[col_name] = values

# print(df.head())

keywords = ["POWR", "FREQ", "VOLT", "PLOD"]
keywords = ["FREQ", "POWR"]
keyword_map = {
    "POWR": {"title": "Generator Electrical Power (MW)", "yaxis": "Power (MW)"},
    "FREQ": {"title": "Bus Frequency Deviation (pu)", "yaxis": "Freq. Deviation (pu)"},
    "VOLT": {"title": "Bus Voltage (pu)", "yaxis": "Voltage (pu)"},
    "PLOD": {"title": "Load Active Power (MW)", "yaxis": "Load P (MW)"},
}

time_col = "Time(s)"
if time_col not in df.columns:
    print(f"-- Time column '{time_col}' not found; available columns: {list(df.columns)}")
    sys.exit(1)


fig = make_subplots(
    rows=len(keywords),
    cols=1,
    shared_xaxes=True,
    subplot_titles=[keyword_map[k]["title"] for k in keywords],
    vertical_spacing=0.08,
)

for i, keyword in enumerate(keywords, start=1):
    cols_to_plot = [col for col in df.columns if keyword in col and col != time_col]
    if not cols_to_plot:
        fig.add_annotation(row=i, col=1, text=f"No channels found for {keyword}", showarrow=False)
        continue

    # use legend groups so items are grouped and can be toggled together
    for col in cols_to_plot:
        fig.add_trace(
            go.Scatter(
                x=df[time_col],
                y=df[col],
                mode="lines",
                name=col,
                hovertemplate="Time: %{x:.4f}s<br>Value: %{y:.4f}<extra>" + col + "</extra>",
            ),
            row=i,
            col=1,
        )
        first_in_group = False

    # horizontal reference lines for frequency subplot
    if keyword == "FREQ":
        freq_lines = [
            {"y": 57, "color": "red", "style": "dash", "time": 0, "width": 1},
            {"y": 59, "color": "orange", "style": "dash", "time": 3, "width": 1},
            {"y": 60.5, "color": "orange", "style": "dash", "time": 8, "width": 1},
            {"y": 61.8, "color": "red", "style": "dash", "time": 0, "width": 1},
            # UFLS steps
            {"y": 59.5, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
            {"y": 59.3, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
            {"y": 59.1, "color": "blue", "style": "dot", "time": 0.3, "width": 0.5},
        ]
        for line in freq_lines:
            fig.add_hline(
                y=line["y"] / 60 - 1,
                line_dash=line.get("style", "solid"),
                line_width=line["width"],
                line_color=line["color"],
                # annotation_text=f"{line['y']} ({line['time']})",
                # annotation_position="right",
                row=i,
                col=1,
            )

    fig.update_yaxes(title_text=keyword_map[keyword]["yaxis"], row=i, col=1)

fig.update_xaxes(title_text="Time (s)", row=len(keywords), col=1)
fig.update_layout(
    title="Dynamic Simulation Channels",
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.15,
        xanchor="center",
        x=0.5,
    ),
    margin=dict(b=120),  # extra bottom space for legend
    hovermode="x unified",
    template="plotly_white",
)

increase_height = False  # set True to increase figure height
if increase_height:
    per_row_height = 450  # px per row
    extra_pad = 200  # legend/margins
    fig.update_layout(height=2 * per_row_height + extra_pad)

pio.renderers.default = "browser"

fig.show()
print("-- Interactive Plotly window (browser) opened.")

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

print(f"-- Frequency extremes per bus: {freq_devs}")
if bus_max_overall is not None:
    print(f"-- Bus with maximum frequency deviation: Bus {bus_max_overall} (Value: {val_max_overall:.4f})")

# ------------------------------------------------------------------
# parse load shedding (LDSTBL) events from the log file
try:
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
            {"bus": bus, "load": load_id, "time": time_val, "percent": percent, "p": p, "q": q, "v": v, "f": fval}
        )

    ptot = sum(e["p"] for e in events)
    qtot = sum(e["q"] for e in events)

    print(f"-- Parsed {len(events)} load shed events (UFLS). Totals: P={ptot:.2f} MW, Q={qtot:.2f} Mvar.")
    for e in events:
        print(f"   Bus {e['bus']} Load {e['load']} Time {e['time']}s P {e['p']} MW Q {e['q']} Mvar")

except Exception as e:
    print(f"-- Failed to parse load shed events: {e}")

sys.exit(0)
sys.exit(0)
