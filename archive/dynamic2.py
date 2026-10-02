import datetime as dt
import json
import os
import re
import sys
import webbrowser
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio


PSSE_PATH = r"C:\Program Files\PTI\PSSE36\36.5"
PYTHON_VERSION = "14"
BASE_FREQ_HZ = 60.0
EVENT_TIME = 10.0
SIM_END_TIME = 30.0
VOLTAGE_LOW = 0.9
VOLTAGE_HIGH = 1.1
WTVSI_K = 1
WTVSI_TOP_N = 5
OPEN_BROWSER = False


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for file in self.files:
            file.write(obj)
            file.flush()

    def flush(self):
        for file in self.files:
            file.flush()


def parse_args():
    try:
        raw_file = sys.argv[1]
        dyr_file = sys.argv[2]
        excel_file = sys.argv[3]
    except IndexError:
        print("-- Files not provided via command line.")
        sys.exit(1)

    return raw_file, dyr_file, excel_file, Path(raw_file).parent


def configure_psse_imports():
    os.environ["PATH"] = f"{PSSE_PATH}\\PSSBIN;" + os.environ["PATH"]
    os.environ["PSSPY_PATH"] = f"{PSSE_PATH}\\PSSPY3{PYTHON_VERSION}"
    sys.path.append(f"{PSSE_PATH}\\PSSPY3{PYTHON_VERSION}")
    sys.path.append(f"{PSSE_PATH}\\PSSLIB")


def solve_power_flow(psspy):
    print("-- Solving power flow...")
    default_pf_params_intgar = [100, 20, 20, 100, 10, 20, 4, 20, 0]
    mismatch_tol = 0.001
    default_pf_params_realar = [
        1.6,
        1.6,
        1.0,
        0.0001,
        1.0,
        mismatch_tol,
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
        mismatch_tol,
        0.00001,
        100.0,
        0.01,
        0.3,
    ]
    psspy.solution_parameters_5(default_pf_params_intgar, default_pf_params_realar)
    ierr = psspy.fnsl()
    if ierr != 0:
        print(f"-- Power flow did not converge, error code: {ierr}")
        sys.exit(1)
    print("-- Power flow solved successfully.")


def write_power_flow_report(psspy, excel_file_pth):
    print("-- Building solved power flow report...")
    load_bus_numbers = set()
    try:
        ierr, bus_nums = psspy.abusint(-1, 2, ["NUMBER"])
        ierr, bus_v = psspy.abusreal(-1, 2, ["PU"])
        ierr, bus_ang = psspy.abusreal(-1, 2, ["ANGLED"])
        ierr, bus_msmtch = psspy.abusreal(-1, 2, ["MISMATCH"])
        bus_report_df = pd.DataFrame(
            [
                {
                    "number": b,
                    "volt (pu)": bus_v[0][i],
                    "angle (d)": bus_ang[0][i],
                    "mismatch (MW)": bus_msmtch[0][i],
                }
                for i, b in enumerate(bus_nums[0])
            ]
        )

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

        try:
            ierr, load_buses = psspy.aloadint(-1, 2, ["NUMBER"])
            ierr, load_ids = psspy.aloadchar(-1, 2, ["ID"])
            ierr, load_cplx = psspy.aloadcplx(-1, 2, ["TOTALACT", "TOTALNOM"])
            total_act_list, total_nom_list = load_cplx
            load_rows = []
            for i in range(len(load_buses[0])):
                act = total_act_list[i]
                nom = total_nom_list[i]
                if abs(act.real) > 1e-9 or abs(nom.real) > 1e-9:
                    load_bus_numbers.add(int(load_buses[0][i]))
                served = 0.0 if nom.real == 0 else (act.real / nom.real) * 100.0
                load_rows.append(
                    {
                        "bus": load_buses[0][i],
                        "id": load_ids[0][i].strip(),
                        "MW nom": nom.real,
                        "MW": act.real,
                        "Mvar nom": nom.imag,
                        "Mvar": act.imag,
                        "% served": served,
                    }
                )
            load_report_df = pd.DataFrame(load_rows)
        except Exception as exc:
            print(f"-- Load collection issue: {exc}")
            load_report_df = pd.DataFrame(columns=["bus", "id", "MW", "Mvar", "% served"])

        try:
            ierr, br_ints = psspy.abrnint(-1, 2, 1, 4, 1, ["FROMNUMBER", "TONUMBER"])
            ierr, br_ids = psspy.abrnchar(-1, 2, 1, 4, 1, ["ID"])
            ierr, br_flows = psspy.abrnreal(-1, 2, 1, 4, 1, ["P", "Q", "PLOSS", "QLOSS"])
            from_list, to_list = br_ints
            id_list = br_ids[0]
            p_to, q_to, p_loss, q_loss = br_flows
            p_from = [pl - pt for pl, pt in zip(p_loss, p_to)]
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
        except Exception as exc:
            print(f"-- Branch collection issue: {exc}")
            branch_report_df = pd.DataFrame(columns=["from", "to", "circuit", "MW from", "MW to"])

        report_path = excel_file_pth.replace("pm", "psse")
        print(f"-- Writing report to: {report_path}")
        with pd.ExcelWriter(report_path, engine="xlsxwriter") as writer:
            bus_report_df.to_excel(writer, sheet_name="bus", index=False)
            gen_report_df.to_excel(writer, sheet_name="gen", index=False)
            load_report_df.to_excel(writer, sheet_name="load", index=False)
            branch_report_df.to_excel(writer, sheet_name="branch", index=False)
        print("-- Report written.")
        return load_bus_numbers
    except Exception as exc:
        print(f"-- Failed to build report: {exc}")
        return load_bus_numbers


def run_dynamic_simulation(psspy, raw_output_dir, output_file, dyr_file_pth):
    print("-- Converting generators...")
    psspy.cong(0)

    print("-- Converting loads...")
    psspy.conl(0, 1, 1, [0, 0], [100.0, 0.0, 0.0, 100.0])
    psspy.conl(0, 1, 2, [0, 0], [100.0, 0.0, 0.0, 100.0])
    psspy.conl(0, 1, 3, [0, 0], [100.0, 0.0, 0.0, 100.0])

    print("-- Factoring and initializing switching study...")
    psspy.fact()
    psspy.tysl(0)

    print("-- Loading dynamic data...")
    psspy.dyre_new_2([1, 1, 1, 1], dyr_file_pth)

    print("-- Setting up output channels...")
    psspy.chsb(0, 1, [-1, -1, -1, 1, 2, 0])  # generator pelec
    psspy.chsb(0, 1, [-1, -1, -1, 1, 3, 0])  # generator qelec
    psspy.chsb(0, 1, [-1, -1, -1, 1, 12, 0])  # bus frequency
    psspy.chsb(0, 1, [-1, -1, -1, 1, 13, 0])  # bus voltage
    psspy.chsb(0, 1, [-1, -1, -1, 1, 25, 0])  # p load
    psspy.chsb(0, 1, [-1, -1, -1, 1, 26, 0])  # q load

    if Path(output_file).exists():
        os.remove(output_file)
    print(f"-- output file: {output_file}")
    psspy.strt_2([0, 0], output_file)
    psspy.run(0, -0.02, 1000, 1, 1)

    print("-- Running dynamic simulation... (pre-event)")
    psspy.run(0, EVENT_TIME, 1000, 1, 1)

    outage_file = raw_output_dir / "line_outage.json"
    if outage_file.exists():
        print(f"-- Reading line outage file: {outage_file}")
        with open(outage_file, "r", encoding="utf-8") as file:
            outages = json.load(file)
        if isinstance(outages, list):
            for outage in outages:
                try:
                    fbus = int(outage["from"])
                    tbus = int(outage["to"])
                    circuit_id = str(outage["id"]).strip()
                    psspy.dist_branch_trip(fbus, tbus, circuit_id)
                except Exception as exc:
                    print(f"-- Failed to trip outage entry {outage}: {exc}")
            print(f"-- Tripped {len(outages)} branches")
        else:
            print("-- Outage file format unexpected; skipping branch trips.")
    else:
        print(f"-- No line outage file found at {outage_file}; skipping branch trips.")

    print("-- Running dynamic simulation... (post-event)")
    psspy.run(0, SIM_END_TIME, 1000, 1, 1)


def extract_bus_number(channel_name):
    match = re.search(r"(\d+)", channel_name)
    return int(match.group(1)) if match else None


def finite_series(values, times):
    value_array = np.asarray(values, dtype=float)
    time_array = np.asarray(times, dtype=float)
    mask = np.isfinite(value_array) & np.isfinite(time_array)
    return value_array[mask], time_array[mask]


def is_valid_voltage_profile(values):
    value_array = np.asarray(values, dtype=float)
    tail_values = value_array[-100:]
    return bool(np.any(np.isfinite(tail_values) & (np.abs(tail_values) > 1e-9)))


def calculate_wtvsi(df, time_col, load_bus_numbers, t0=EVENT_TIME, t_end=SIM_END_TIME, k=WTVSI_K):
    duration = float(t_end - t0)
    load_bus_numbers = {int(bus) for bus in load_bus_numbers}
    bus_integrals = {}
    voltage_channel_count = 0

    if time_col not in df.columns or duration <= 0.0 or not load_bus_numbers:
        return {
            "wtvsi": 0.0,
            "event_time": float(t0),
            "end_time": float(t_end),
            "duration": max(duration, 0.0),
            "k": k,
            # "load_bus_count": len(load_bus_numbers),
            "bus_count": 0,
            "integrated_bus_count": 0,
            # "missing_voltage_profile_count": len(load_bus_numbers),
            "voltage_channel_count": 0,
            "top_contributors": [],
            "bus_integrals": {},
        }

    for col in [c for c in df.columns if "VOLT" in c and c != time_col]:
        bus = extract_bus_number(col)
        # if bus not in load_bus_numbers:
        #     continue

        if not is_valid_voltage_profile(df[col]):
            continue

        values, times = finite_series(df[col], df[time_col])
        interval = (times >= t0) & (times <= t_end)
        if not np.any(interval):
            continue

        voltage_channel_count += 1
        interval_values = values[interval]
        interval_times = times[interval]
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
    wtvsi = total_integral / (voltage_channel_count * duration)
    # wtvsi = total_integral / (len(load_bus_numbers) * duration)
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
        # "load_bus_count": len(load_bus_numbers),
        "bus_count": len(bus_integrals),
        "integrated_bus_count": len(bus_integrals),
        # "missing_voltage_profile_count": max(0, len(load_bus_numbers) - len(bus_integrals)),
        "voltage_channel_count": voltage_channel_count,
        "top_contributors": top_contributors,
        "bus_integrals": {str(bus): value for bus, value in sorted(bus_integrals.items())},
    }


def build_voltage_stats(df, time_col, load_bus_numbers):
    bus_stats = {}
    for col in [c for c in df.columns if "VOLT" in c and c != time_col]:
        bus = extract_bus_number(col)
        if bus is None:
            continue

        if not is_valid_voltage_profile(df[col]):
            continue

        values, times = finite_series(df[col], df[time_col])
        if len(values) == 0 or not np.any(values):
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
        }

        previous = bus_stats.get(str(bus))
        if previous is None or record["worst_violation"] > previous["worst_violation"]:
            bus_stats[str(bus)] = record

    summary = {
        "voltage_low": VOLTAGE_LOW,
        "voltage_high": VOLTAGE_HIGH,
        "bus_count": len(bus_stats),
        "outside_band_count": sum(1 for row in bus_stats.values() if row["worst_violation"] > 0.0),
    }
    if bus_stats:
        worst_bus, worst_row = max(bus_stats.items(), key=lambda item: item[1]["worst_violation"])
        summary["worst_bus"] = int(worst_bus)
        summary["worst_violation"] = worst_row["worst_violation"]
    else:
        summary["worst_bus"] = None
        summary["worst_violation"] = 0.0

    wtvsi_summary = calculate_wtvsi(df, time_col, load_bus_numbers)
    return {"summary": summary, "buses": bus_stats, "wtvsi": wtvsi_summary}


def write_voltage_stats(df, output_dir, load_bus_numbers):
    time_col = "Time(s)"
    if time_col not in df.columns:
        print(f"-- Time column '{time_col}' not found; voltage stats skipped.")
        return None

    stats = build_voltage_stats(df, time_col, load_bus_numbers)
    stats_path = output_dir / "voltage_stats.json"
    with open(stats_path, "w", encoding="utf-8") as file:
        json.dump(stats, file, indent=2)

    summary = stats["summary"]
    wtvsi_summary = stats["wtvsi"]
    print(
        "-- Voltage stats written: "
        f"{stats_path} | outside band={summary['outside_band_count']} "
        f"| worst bus={summary['worst_bus']} "
        f"| worst violation={summary['worst_violation']:.5f} "
        f"| WTVSI={wtvsi_summary['wtvsi']:.3e}"
    )
    return stats


def fmt(value, digits=4):
    return f"{value:.{digits}f}"


def metric_card(label, value, detail=""):
    detail_html = f"<span>{escape(detail)}</span>" if detail else ""
    return f"<div class='metric'><label>{escape(label)}</label><strong>{escape(value)}</strong>{detail_html}</div>"


def stats_table(rows, columns):
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


def build_wtvsi_table_html(wtvsi_summary):
    if not wtvsi_summary or not wtvsi_summary["top_contributors"]:
        return ""

    rows = [
        {"bus": row["bus"], "integral": fmt(row["integral"], 6)}
        for row in wtvsi_summary["top_contributors"]
        if row["integral"] > 0.0
    ]
    if not rows:
        return ""
    return stats_table(rows, [("bus", "Top WTVSI Bus"), ("integral", "Integral")])


def wtvsi_metric_html(wtvsi_summary):
    if not wtvsi_summary:
        return ""

    return metric_card(
        "WTVSI",
        f"{wtvsi_summary['wtvsi']:.3e}",
        (
            # f"load buses: {wtvsi_summary['load_bus_count']}, "
            f"buses: {wtvsi_summary['bus_count']}, "
            f"t: {wtvsi_summary['event_time']:.1f}-{wtvsi_summary['end_time']:.1f}s"
        ),
    )


def build_stats_html(keyword, plotted_series, wtvsi_summary=None):
    rows = []
    for series_info in plotted_series:
        values, times = finite_series(series_info["values"], series_info["time"])
        if len(values) == 0:
            continue
        min_idx = int(np.argmin(values))
        max_idx = int(np.argmax(values))
        min_val = float(values[min_idx])
        max_val = float(values[max_idx])
        min_time = float(times[min_idx])
        max_time = float(times[max_idx])

        if keyword == "FREQ":
            min_dev = abs(min_val - BASE_FREQ_HZ)
            max_dev = abs(max_val - BASE_FREQ_HZ)
            worst = max(min_dev, max_dev)
            worst_time = min_time if min_dev >= max_dev else max_time
            rows.append(
                {"channel": series_info["name"], "min": min_val, "max": max_val, "worst": worst, "time": worst_time}
            )
        elif keyword == "VOLT":
            under = max(0.0, VOLTAGE_LOW - min_val)
            over = max(0.0, max_val - VOLTAGE_HIGH)
            worst = max(under, over)
            worst_time = min_time if under >= over else max_time
            rows.append(
                {"channel": series_info["name"], "min": min_val, "max": max_val, "worst": worst, "time": worst_time}
            )

    if not rows:
        wtvsi_metric = wtvsi_metric_html(wtvsi_summary) if keyword == "VOLT" else ""
        metrics_html = f"<div class='metrics'>{wtvsi_metric}</div>" if wtvsi_metric else ""
        wtvsi_table_html = build_wtvsi_table_html(wtvsi_summary) if keyword == "VOLT" else ""
        return (
            f"<section class='stats-card'><h3>{keyword} Stats</h3>{metrics_html}"
            f"<div class='stats-empty'>No signals available.</div>{wtvsi_table_html}</section>"
        )

    top_rows = sorted(rows, key=lambda row: row["worst"], reverse=True)[:5]
    metric_rows = [
        metric_card("Channels", str(len(rows))),
        metric_card("Minimum", fmt(min(row["min"] for row in rows))),
        metric_card("Maximum", fmt(max(row["max"] for row in rows))),
        metric_card("Worst", fmt(max(row["worst"] for row in rows))),
    ]
    wtvsi_table_html = ""
    if keyword == "VOLT":
        metric_rows.append(wtvsi_metric_html(wtvsi_summary))
        wtvsi_table_html = build_wtvsi_table_html(wtvsi_summary)

    metrics_html = "".join(metric_rows)
    table_html = stats_table(
        [
            {
                "channel": row["channel"],
                "min": fmt(row["min"]),
                "max": fmt(row["max"]),
                "worst": fmt(row["worst"]),
                "time": fmt(row["time"], 3),
            }
            for row in top_rows
        ],
        [("channel", "Top Channels"), ("min", "Min"), ("max", "Max"), ("worst", "Worst"), ("time", "Time s")],
    )
    return (
        f"<section class='stats-card'><h3>{keyword} Stats</h3><div class='metrics'>{metrics_html}</div>"
        f"{table_html}{wtvsi_table_html}</section>"
    )


def write_plots(df, output_dir, now, load_bus_numbers, wtvsi_summary=None):
    print("-- Plotting dynamic simulation channels...")
    time_col = "Time(s)"
    if time_col not in df.columns:
        print(f"-- Time column '{time_col}' not found; plots skipped.")
        return None

    keyword_map = {
        "POWR": {"title": "Generator Electrical Power (MW)", "yaxis": "Power (MW)"},
        "VARS": {"title": "Generator Reactive Power (MVar)", "yaxis": "Reactive Power (MVar)"},
        "FREQ": {"title": "Bus Frequency (Hz)", "yaxis": "Frequency (Hz)"},
        "VOLT": {"title": "Bus Voltage (pu)", "yaxis": "Voltage (pu)"},
        "PLOD": {"title": "Load Active Power (MW)", "yaxis": "Load P (MW)"},
    }
    load_bus_numbers = {int(bus) for bus in load_bus_numbers}
    plot_blocks = []
    plot_count = 0

    for keyword, labels in keyword_map.items():
        fig = go.Figure()
        plotted_series = []
        cols_to_plot = [col for col in df.columns if keyword in col and col != time_col]

        for col in cols_to_plot:
            values = df[col]
            # if keyword == "VOLT" and extract_bus_number(col) not in load_bus_numbers:
            #     continue
            if keyword == "VOLT" and not is_valid_voltage_profile(values):
                continue
            if keyword == "VOLT" and np.all((values >= VOLTAGE_LOW) & (values <= VOLTAGE_HIGH)):
                continue
            if keyword == "FREQ" and all(np.abs(values.values) < 1e-6):
                continue

            series_to_plot = values
            hover_value_fmt = "%{y:.4f}"
            if keyword == "FREQ":
                series_to_plot = BASE_FREQ_HZ * (values + 1.0)
                hover_value_fmt = "%{y:.4f} Hz"

            if keyword in {"FREQ", "VOLT"}:
                plotted_series.append({"name": col, "values": series_to_plot, "time": df[time_col]})

            fig.add_trace(
                go.Scatter(
                    x=df[time_col],
                    y=series_to_plot,
                    mode="lines",
                    name=col,
                    hovertemplate="Time: %{x:.4f}s<br>Value: " + hover_value_fmt + f"<extra>{col}</extra>",
                )
            )

        if keyword == "FREQ":
            freq_lines = [
                {"y": 57, "color": "red", "style": "dash", "width": 1},
                {"y": 59, "color": "orange", "style": "dash", "width": 1},
                {"y": 60.5, "color": "orange", "style": "dash", "width": 1},
                {"y": 61.8, "color": "red", "style": "dash", "width": 1},
                {"y": 59.5, "color": "blue", "style": "dot", "width": 0.5},
                {"y": 59.3, "color": "blue", "style": "dot", "width": 0.5},
                {"y": 59.1, "color": "blue", "style": "dot", "width": 0.5},
            ]
            for line in freq_lines:
                fig.add_hline(
                    y=line["y"],
                    line_dash=line.get("style", "solid"),
                    line_width=line["width"],
                    line_color=line["color"],
                )
        if keyword == "VOLT":
            fig.add_hline(y=VOLTAGE_LOW, line_dash="dash", line_width=1, line_color="red")
            fig.add_hline(y=VOLTAGE_HIGH, line_dash="dash", line_width=1, line_color="red")

        fig.update_layout(
            title=labels["title"],
            xaxis_title="Time (s)",
            yaxis_title=labels["yaxis"],
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
            margin=dict(b=120),
            hovermode="closest",
            template="plotly_white",
            height=560,
        )
        plot_blocks.append(
            {"kind": "plot", "html": pio.to_html(fig, include_plotlyjs=(plot_count == 0), full_html=False)}
        )
        plot_count += 1
        if keyword in {"FREQ", "VOLT"}:
            plot_blocks.append({"kind": "stats", "html": build_stats_html(keyword, plotted_series, wtvsi_summary)})

    plots_path = output_dir / f"dynamic_channels_{now}.html"
    html_doc = (
        "<html><head><meta charset='utf-8'><title>Dynamic Simulation Channels</title>"
        "<style>body{margin:0;padding:20px;font-family:Arial,sans-serif;background:#fafafa;}"
        ".plot{margin:0 0 24px 0;background:#fff;padding:8px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);}"
        ".stats{margin:-12px 0 24px 0;background:#fff;padding:12px 14px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);}"
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
    html_doc += "".join([f"<div class='{block['kind']}'>{block['html']}</div>" for block in plot_blocks])
    html_doc += "</body></html>"

    with open(plots_path, "w", encoding="utf-8") as file:
        file.write(html_doc)

    if OPEN_BROWSER:
        webbrowser.open(plots_path.resolve().as_uri())
    print(f"-- Interactive Plotly page written: {plots_path}")
    return plots_path


def print_max_frequency_deviation(df):
    print("-- Analyzing Frequency channels...")
    time_col = "Time(s)"
    if time_col not in df.columns:
        print(f"-- Time column '{time_col}' not found; frequency analysis skipped.")
        return None

    max_dev_overall = -1.0
    bus_max_overall = None
    val_max_overall = 0.0
    time_max_overall = 0.0

    freq_cols = [col for col in df.columns if "FREQ" in col and col != time_col]
    for col in freq_cols:
        bus = extract_bus_number(col)
        if bus is None:
            continue

        values, times = finite_series(df[col], df[time_col])
        if len(values) == 0 or np.all(np.abs(values) < 1e-6):
            continue

        abs_idx = int(np.argmax(np.abs(values)))
        mag = float(abs(values[abs_idx]))
        extreme_val = float(values[abs_idx])
        extreme_hz = float(BASE_FREQ_HZ * (extreme_val + 1.0))
        extreme_time = float(times[abs_idx])

        if mag > max_dev_overall:
            max_dev_overall = mag
            bus_max_overall = bus
            val_max_overall = extreme_hz
            time_max_overall = extreme_time

    if bus_max_overall is not None:
        deviation_hz = max_dev_overall * BASE_FREQ_HZ
        print(
            "-- Bus with maximum frequency deviation: "
            f"Bus {bus_max_overall} "
            f"(Value: {val_max_overall:.4f} Hz, "
            f"Deviation: {deviation_hz:.4f} Hz, "
            f"Time: {time_max_overall:.4f}s)"
        )
    else:
        print("-- No nonzero frequency channels found.")


def parse_load_shedding_events(psspy, log_file):
    print("-- Parsing load shedding events...")
    try:
        detailed_shedding_log = False
        ierr, event_buses = psspy.abusint(-1, 2, ["NUMBER"])
        ierr, event_zones = psspy.abusint(-1, 2, ["ZONE"])
        zone_by_bus = {int(bus): int(zone) for bus, zone in zip(event_buses[0], event_zones[0])}

        ierr, zone_names_raw = psspy.azonechar(-1, 2, ["ZONENAME"])
        zone_names = [name.strip() for name in zone_names_raw[0]]

        events = []
        with open(log_file, "r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()

        for i, line in enumerate(lines):
            m1 = re.search(
                r"(\S+)\s+AT BUS\s+(\d+)\s+LOAD\s+(\S+).*?BREAKER TIMER TIMED OUT AT TIME\s*=\s*([0-9.]+)",
                line,
            )
            if not m1:
                continue

            bus = int(m1.group(2))
            load_id = m1.group(3)
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

            zone = zone_by_bus.get(bus, 0)
            zone_name = zone_names[zone - 1] if 1 <= zone <= len(zone_names) else ""
            events.append(
                {
                    "bus": bus,
                    "zone": zone,
                    "zone_name": zone_name,
                    "load": load_id,
                    "time": time_val,
                    "percent": float(m2.group(1)),
                    "p": float(m3.group(1)),
                    "q": float(m3.group(2)),
                    "v": float(m3.group(3)),
                    "f": float(m3.group(4)),
                }
            )

        ptot = sum(event["p"] for event in events)
        qtot = sum(event["q"] for event in events)
        zone_totals = {}
        for event in events:
            zone = event.get("zone", 0)
            if zone == 0:
                continue
            zone_totals.setdefault(zone, {"p": 0.0, "q": 0.0, "count": 0})
            zone_totals[zone]["p"] += event["p"]
            zone_totals[zone]["q"] += event["q"]
            zone_totals[zone]["count"] += 1

        print(f"-- Parsed {len(events)} load shed events (UFLS). Totals: P={ptot:.2f} MW, Q={qtot:.2f} Mvar.")
        if zone_totals:
            print("-- Load shed totals by zone:")
            for zone in sorted(zone_totals):
                totals = zone_totals[zone]
                zone_name = zone_names[zone - 1] if 1 <= zone <= len(zone_names) else f"Zone {zone}"
                print(f"   {zone_name}: {totals['count']} events P {totals['p']:.2f} MW Q {totals['q']:.2f} Mvar")
        else:
            print("-- No zone assignments found for parsed load shed events.")

        if len(events) > 0 and (detailed_shedding_log or not zone_totals):
            print("-- Detailed load shed events:")
            for event in events:
                zone_label = event["zone_name"] or "N/A"
                print(
                    f"   Bus {event['bus']} Zone {zone_label} Load {event['load']} "
                    f"Time {event['time']}s P {event['p']} MW Q {event['q']} Mvar"
                )

        return events
    except Exception as exc:
        print(f"-- Failed to parse load shed events: {exc}")
        return []


def main():
    print("-- Starting dynamic2 simulation script...")
    print(f"-- Python version: {sys.version.split()[0]} executable: {sys.executable}")
    raw_file_pth, dyr_file_pth, excel_file_pth, output_dir = parse_args()
    output_dir.mkdir(parents=True, exist_ok=True)

    configure_psse_imports()
    import psse3605  # noqa: F401
    import psspy  # type: ignore
    import dyntools  # type: ignore

    print("-- file paths:")
    print("Raw file path:\r", raw_file_pth)
    print("Dyr file path:\r", dyr_file_pth)
    print("Excel file path:\r", excel_file_pth)
    print("Output directory:\r", output_dir)

    now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_dir / f"log_dynamic2_{now}.txt"
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    log_handle = open(log_file, "w", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, log_handle)
    sys.stderr = Tee(sys.stderr, log_handle)

    try:
        print("-- Initializing PSSE...")
        psspy.psseinit()
        psspy.progress_output(6, "", [0, 0])

        print("-- Reading RAW file...")
        psspy.read(0, raw_file_pth)

        solve_power_flow(psspy)
        load_bus_numbers = write_power_flow_report(psspy, excel_file_pth)

        if dyr_file_pth == "":
            print("-- No dynamic data file provided, skipping dynamic simulation.")
            return

        output_file = str(output_dir / f"output_psse_dynamic2_{now}.out")
        run_dynamic_simulation(psspy, output_dir, output_file, dyr_file_pth)

        print("-- Reading channel data...")
        ch_data = dyntools.CHNF(output_file)
        short_title, chanid_dict, chandata_dict = ch_data.get_data()
        df = pd.DataFrame({chanid_dict[key]: values for key, values in chandata_dict.items()})

        voltage_stats = write_voltage_stats(df, output_dir, load_bus_numbers)
        wtvsi_summary = voltage_stats["wtvsi"] if voltage_stats else None
        write_plots(df, output_dir, now, load_bus_numbers, wtvsi_summary)
        print_max_frequency_deviation(df)
        parse_load_shedding_events(psspy, log_file)
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_handle.close()


if __name__ == "__main__":
    main()
