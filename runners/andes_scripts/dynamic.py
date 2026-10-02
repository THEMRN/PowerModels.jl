"""
ANDES dynamic simulation of a solved islanding case, the open-source counterpart of
psse_scripts/dynamic.py with the same command line and outputs:

    python dynamic.py <raw> <dyr> <excel>

Loads the case exported by PowerModels, solves the power flow, trips the lines listed in
line_outage.json at EVENT_TIME, runs to SIM_END_TIME and writes into the case folder the power
flow report (andes_res_*.xlsx), the channels (output_andes_*.csv.gz), voltage_stats.json, the
Plotly HTML report and the ANDES log.

Not modelled by ANDES (skipped or approximated when reading the dyr): UFLS (LDSHBL) and generator
frequency relays (FRQTPAT) are skipped, GENSAL is approximated by GENROU and SCRX by SEXS with
default parameters.

Run `andes prepare` once after installing or upgrading ANDES; it generates the model code.
"""

import sys
import json
import logging
import datetime as dt
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd
import andes

from report import build_voltage_stats_json, write_voltage_stats_json, write_html_report, print_frequency_extremes

# ==================== Settings ====================
EVENT_TIME = 5.0  # s, the outage lines trip
SIM_END_TIME = 25.0  # s
TIME_STEP = 1 / 120  # s, half a cycle as in PSS®E (the ANDES default of 1/30 s is too coarse for relays)
TIME_COL = "Time(s)"


def read_raw_block(raw_file, block_name):
    """
    Records of one data block of a PSS®E RAW file ("LOAD", "BRANCH", "TRANSFORMER", ...), one list
    of string fields per file line, with quotes stripped. The block is found by the
    "BEGIN <name> DATA" / "END OF <name> DATA" comments that PowerModels and PSS®E write.
    """
    records = []
    inside_block = False
    with open(raw_file, "r") as f:
        for line in f:
            if f"END OF {block_name} DATA" in line:
                break
            if inside_block:
                fields = line.split("/")[0].split(",")
                records.append([field.strip().strip("'").strip() for field in fields])
            if f"BEGIN {block_name} DATA" in line:
                inside_block = True
    return records


def find_dead_island_buses(ss, tripped_lines):
    """
    Buses of the islands left without an in-service generator once `tripped_lines` open,
    found by a depth-first search over the lines still in service. Sorted bus numbers.
    """
    neighbours = {bus: [] for bus in ss.Bus.idx.v}
    for line_idx, bus1, bus2, status in zip(ss.Line.idx.v, ss.Line.bus1.v, ss.Line.bus2.v, ss.Line.u.v):
        if status == 0 or line_idx in tripped_lines:
            continue
        neighbours[bus1].append(bus2)
        neighbours[bus2].append(bus1)

    generator_buses = set()
    for gen_model in (ss.PV, ss.Slack):
        for bus, status in zip(gen_model.bus.v, gen_model.u.v):
            if status == 1:
                generator_buses.add(bus)

    dead_buses = []
    unvisited = set(ss.Bus.idx.v)
    while unvisited:
        # collect the island around one unvisited bus
        first_bus = unvisited.pop()
        island = [first_bus]
        to_visit = [first_bus]
        while to_visit:
            for neighbour in neighbours[to_visit.pop()]:
                if neighbour in unvisited:
                    unvisited.remove(neighbour)
                    island.append(neighbour)
                    to_visit.append(neighbour)
        if not generator_buses.intersection(island):
            dead_buses.extend(island)
    return sorted(dead_buses)


def calc_bus_mismatches(ss):
    """Complex power mismatch at each bus (MVA) for the present ANDES voltages, keyed by bus number."""
    p_mismatch = ss.dae.g[ss.Bus.a.a]
    q_mismatch = ss.dae.g[ss.Bus.v.a]
    mismatch = np.hypot(p_mismatch, q_mismatch) * ss.config.mva
    return dict(zip(ss.Bus.idx.v, mismatch))


print("-- Starting ANDES dynamic simulation script...")
print(f"-- Python version: {sys.version.split()[0]}  executable: {sys.executable}  ANDES: {andes.__version__}")

# case file paths
try:
    raw_file_pth = sys.argv[1]
    dyr_file_pth = sys.argv[2]
    excel_file_pth = sys.argv[3]
    output_dir = Path(raw_file_pth).parent
except IndexError:
    print("-- Files not provided via command line.")
    sys.exit(1)

print("-- file paths:")
print("Raw file path:\r", raw_file_pth)
print("Dyr file path:\r", dyr_file_pth)
print("Excel file path:\r", excel_file_pth)
print("Output directory:\r", output_dir)
now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
run_dynamics = dyr_file_pth != ""

# ANDES messages go to the log file, warnings also to the console
log_file = f"log_{now}.txt"
print(f"-- ANDES log: {output_dir / log_file}")
andes.config_logger(
    stream_level=logging.WARNING, log_path=str(output_dir), log_file=log_file, file_level=logging.INFO
)

# ==================== Load the case ====================
# setup=False: every device, including the trip events and frequency measurements,
# has to be added before ANDES sets the system up.
# autogen_stale=False: never regenerate model code here (it spawns processes), see `andes prepare`
print("-- Loading case...")
ss = andes.load(
    raw_file_pth,
    addfile=dyr_file_pth if run_dynamics else None,
    setup=False,
    no_output=True,
    default_config=True,
    autogen_stale=False,
)
base_mva = ss.config.mva

# ANDES reads neither the circuit ids nor the line-end shunts (GI, BI, GJ, BJ) of the RAW, and
# PowerModels writes the line charging into those shunts, so both are taken from the file here.
# ANDES creates one Line per branch record, then one per two-winding transformer, in file order.
branch_records = read_raw_block(raw_file_pth, "BRANCH")
transformer_records = read_raw_block(raw_file_pth, "TRANSFORMER")[::4]  # 4 lines per two-winding transformer
line_bus_pairs = [(int(r[0]), int(r[1])) for r in branch_records + transformer_records]
line_circuits = [r[2] for r in branch_records] + [r[3] for r in transformer_records]
if line_bus_pairs != list(zip(ss.Line.bus1.v, ss.Line.bus2.v)):
    print("-- ANDES lines don't match the RAW branch and transformer records (three-winding transformers?)")
    sys.exit(1)

for i, record in enumerate(branch_records):
    ss.Line.g1.v[i] = float(record[9])  # GI, pu on system base
    ss.Line.b1.v[i] = float(record[10])  # BI
    ss.Line.g2.v[i] = float(record[11])  # GJ
    ss.Line.b2.v[i] = float(record[12])  # BJ

load_ids = [r[1] for r in read_raw_block(raw_file_pth, "LOAD")]  # in the order of ANDES PQ loads

# generator reactive limits in the power flow, as PSS®E
ss.PV.config.pv2pq = 1

# load conversion for the dynamic simulation, as in the PSS®E script:
# P 100 % constant current, Q 100 % constant admittance
ss.PQ.config.p2p = 0.0
ss.PQ.config.p2i = 1.0
ss.PQ.config.p2z = 0.0
ss.PQ.config.q2q = 0.0
ss.PQ.config.q2i = 0.0
ss.PQ.config.q2z = 1.0

if run_dynamics:
    # bus frequency measurement at every bus (FREQ channels)
    for bus in ss.Bus.idx.v:
        ss.add("BusFreq", {"bus": bus})

    # reading the line outages from the file, each one becomes a trip event at EVENT_TIME
    tripped_lines = []
    outage_file = output_dir / "line_outage.json"
    if outage_file.exists():
        print(f"-- Reading line outage file: {outage_file}")
        with open(outage_file, "r") as f:
            outages = json.load(f)

        line_by_circuit = {}
        for line_idx, (bus1, bus2), circuit in zip(ss.Line.idx.v, line_bus_pairs, line_circuits):
            line_by_circuit[(frozenset((bus1, bus2)), circuit)] = line_idx

        for o in outages:
            circuit_key = (frozenset((int(o["from"]), int(o["to"]))), str(o["id"]).strip())
            if circuit_key not in line_by_circuit:
                print(f"-- No line found for outage entry {o}")
                continue
            ss.add("Toggle", {"model": "Line", "dev": line_by_circuit[circuit_key], "t": EVENT_TIME})
            tripped_lines.append(line_by_circuit[circuit_key])
        print(f"-- {len(tripped_lines)} of {len(outages)} branches will trip at t={EVENT_TIME}s")
    else:
        print(f"-- No line outage file found at {outage_file}, skipping branch trips.")

    # islands left without generation are de-energized with the trip, as PSS®E does
    # (ANDES can't solve an island with no generator; it holds isolated buses at their last voltage)
    dead_buses = find_dead_island_buses(ss, tripped_lines)
    for bus in dead_buses:
        ss.add("Toggle", {"model": "Bus", "dev": bus, "t": EVENT_TIME})
    if dead_buses:
        print(f"-- {len(dead_buses)} buses left without generation are de-energized at t={EVENT_TIME}s: {dead_buses}")

ss.setup()

# ==================== Power flow ====================
# check mismatch for all buses before solving power flow (at the RAW voltages)
print("-- Checking initial bus mismatches...")
ss.PFlow.init()
ss.PFlow.fg_update()
initial_mismatches = calc_bus_mismatches(ss)
large_mismatches = []
for b, m in initial_mismatches.items():
    if abs(m) > 1.0:
        large_mismatches.append(b)
        print(f"Warning: Bus {b} has high initial mismatch of {m:.2f} MW")
if len(large_mismatches) == 0:
    print("-- No large initial mismatches found.")

# solve the power flow (Newton-Raphson)
print("-- Solving power flow...")
if not ss.PFlow.run():
    print("-- Power flow did not converge, see the ANDES log.")
    sys.exit(1)
print(f"-- Power flow solved successfully in {ss.PFlow.niter} iterations.")
solved_mismatches = calc_bus_mismatches(ss)

# build excel report (bus, gen, load, branch); device powers are the ANDES equation values (.e)
print("-- Building solved power flow report...")
bus_report_df = pd.DataFrame(
    {
        "number": ss.Bus.idx.v,
        "volt (pu)": ss.Bus.v.v,
        "angle (d)": np.degrees(ss.Bus.a.v),
        "mismatch (MW)": [solved_mismatches[b] for b in ss.Bus.idx.v],
        "initial mismatch (MW)": [initial_mismatches[b] for b in ss.Bus.idx.v],
    }
)

# in-service machines only, as PSS®E lists them; their ids are kept for the channels because the
# dynamic simulation switches off the static generators that the machine models replace
gen_rows = []
in_service_gen_ids = {}  # machine id by ANDES static generator (PV or Slack) idx
for gen_model in (ss.PV, ss.Slack):
    for i in range(gen_model.n):
        if gen_model.u.v[i] == 0:
            continue
        in_service_gen_ids[gen_model.idx.v[i]] = gen_model.subidx.v[i]
        gen_rows.append(
            {
                "bus": gen_model.bus.v[i],
                "id": str(gen_model.subidx.v[i]),
                "PGEN": gen_model.p.v[i] * base_mva,
                "QGEN": gen_model.q.v[i] * base_mva,
            }
        )
gen_report_df = pd.DataFrame(gen_rows).sort_values("bus")

load_rows = []
load_bus_numbers = set()
for i in range(ss.PQ.n):
    p_nom = ss.PQ.p0.v[i] * base_mva
    p_act = ss.PQ.a.e[i] * base_mva
    if abs(p_act) > 1e-9 or abs(p_nom) > 1e-9:
        load_bus_numbers.add(int(ss.PQ.bus.v[i]))
    served = (p_act / p_nom) * 100.0 if p_nom != 0 else 0.0
    load_rows.append(
        {
            "bus": ss.PQ.bus.v[i],
            "id": load_ids[i],
            "MW nom": p_nom,
            "MW": p_act,
            "Mvar nom": ss.PQ.q0.v[i] * base_mva,
            "Mvar": ss.PQ.v.e[i] * base_mva,
            "% served": served,
        }
    )
load_report_df = pd.DataFrame(load_rows)

# flows into the line at each end, so from + to = loss
branch_report_df = pd.DataFrame(
    {
        "from": ss.Line.bus1.v,
        "to": ss.Line.bus2.v,
        "circuit": line_circuits,
        "MW from": ss.Line.a1.e * base_mva,
        "MW to": ss.Line.a2.e * base_mva,
        "MW loss": (ss.Line.a1.e + ss.Line.a2.e) * base_mva,
        "Mvar from": ss.Line.v1.e * base_mva,
        "Mvar to": ss.Line.v2.e * base_mva,
        "Mvar loss": (ss.Line.v1.e + ss.Line.v2.e) * base_mva,
    }
)

report_path = output_dir / Path(excel_file_pth).name.replace("pm_", "andes_", 1)
print(f"-- Writing report to: {report_path}")
try:
    with pd.ExcelWriter(report_path, engine="xlsxwriter") as writer:
        bus_report_df.to_excel(writer, sheet_name="bus", index=False)
        gen_report_df.to_excel(writer, sheet_name="gen", index=False)
        load_report_df.to_excel(writer, sheet_name="load", index=False)
        branch_report_df.to_excel(writer, sheet_name="branch", index=False)
    print("-- Report written.")
except Exception as e:
    print(f"-- Failed to write report: {e}")

# ------------------------------------------------------------------
if not run_dynamics:
    print("-- No dynamic data file provided, skipping dynamic simulation.")
    sys.exit(0)

# ==================== Dynamic simulation ====================
print("-- Initializing dynamic simulation...")
ss.TDS.config.tf = SIM_END_TIME
ss.TDS.config.tstep = TIME_STEP
ss.TDS.config.criteria = 0  # keep running after a loss of synchronism, as PSS®E does
ss.TDS.config.no_tqdm = 1
ss.TDS.init()
if not ss.TDS.test_ok:
    print("-- Warning: dynamic initialization is not at steady state, see the ANDES log.")
ss.dae.store()  # keep the initial point (t=0) in the channels

print(f"-- Running dynamic simulation to t={SIM_END_TIME}s (lines trip at t={EVENT_TIME}s)...")
ss.TDS.run()
if ss.TDS.busted:
    print("-- Warning: dynamic simulation stopped early, see the ANDES log.")

# build the channel DataFrame with PSS®E channel names and units:
# FREQ in pu deviation from 60 Hz, VOLT in pu, POWR/VARS/PLOD/QLOD in pu on the system base
print("-- Reading channel data...")
bus_names = {}  # e.g. "[NUC-A 21.600]"
for bus, name, base_kv in zip(ss.Bus.idx.v, ss.Bus.name.v, ss.Bus.Vn.v):
    bus_names[bus] = f"[{name} {base_kv:.3f}]"

bus_voltage = ss.TDS.get_timeseries(ss.Bus.v)  # pu, one column per bus
frequency_deviation = ss.TDS.get_timeseries(ss.BusFreq.f) - 1.0  # pu, one column per BusFreq device
frequency_deviation.columns = ss.BusFreq.bus.v  # one BusFreq per bus

# de-energized buses read zero after the trip, as in PSS®E (the sample at EVENT_TIME is pre-trip)
after_trip = bus_voltage.index > EVENT_TIME
bus_voltage.loc[after_trip, dead_buses] = 0.0
frequency_deviation.loc[after_trip, dead_buses] = 0.0

channels = {TIME_COL: bus_voltage.index.to_numpy()}

for gen_model in (ss.GENROU, ss.GENCLS):  # GENSAL is read as GENROU
    if gen_model.n == 0:
        continue
    electrical_power = ss.TDS.get_timeseries(gen_model.Pe)
    reactive_power = ss.TDS.get_timeseries(gen_model.Qe)
    for gen_idx, bus, static_gen in zip(gen_model.idx.v, gen_model.bus.v, gen_model.gen.v):
        if static_gen not in in_service_gen_ids:
            continue  # channels for in-service machines only, as in PSS®E
        gen_id = in_service_gen_ids[static_gen]
        channels[f"POWR {bus}{bus_names[bus]}{gen_id}"] = electrical_power[gen_idx].to_numpy()
        channels[f"VARS {bus}{bus_names[bus]}{gen_id}"] = reactive_power[gen_idx].to_numpy()

for bus in ss.Bus.idx.v:
    channels[f"FREQ {bus} {bus_names[bus]}"] = frequency_deviation[bus].to_numpy()
for bus in ss.Bus.idx.v:
    channels[f"VOLT {bus} {bus_names[bus]}"] = bus_voltage[bus].to_numpy()

# load power from the converted load model: P = Ipeq * V (constant current), Q = Xeq * V^2 (constant admittance)
for i in range(ss.PQ.n):
    if ss.PQ.u.v[i] == 0:
        continue
    bus = ss.PQ.bus.v[i]
    voltage = bus_voltage[bus].to_numpy()
    channels[f"PLOD {bus}{bus_names[bus]}{load_ids[i]}"] = ss.PQ.Ipeq.v[i] * voltage
    channels[f"QLOD {bus}{bus_names[bus]}{load_ids[i]}"] = ss.PQ.Xeq.v[i] * voltage**2

df = pd.DataFrame(channels)

output_file = output_dir / f"output_andes_{now}.csv.gz"
print(f"-- output file: {output_file}")
df.to_csv(output_file, index=False, float_format="%.6g")

# ==================== Stability metrics and report ====================
voltage_stats = build_voltage_stats_json(df, TIME_COL, load_bus_numbers, EVENT_TIME, SIM_END_TIME)
write_voltage_stats_json(output_dir, voltage_stats)

# UFLS relays (LDSHBL) are not modelled, so there are no load shed events to report
print("-- UFLS (LDSHBL) is not modelled in ANDES, no load shed events.")

print("-- Plotting dynamic simulation channels...")
plots_path = write_html_report(df, output_dir, now, voltage_stats["wtvsi"], ufls_total_p_mw=None, simulator="ANDES")
webbrowser.open(plots_path.resolve().as_uri())
print(f"-- Interactive Plotly page opened: {plots_path}")

print_frequency_extremes(df)
sys.exit(0)
