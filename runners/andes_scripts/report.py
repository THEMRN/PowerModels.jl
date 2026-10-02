"""
Post-processing of the dynamic simulation channels: voltage stats (voltage_stats.json, WTVSI),
frequency stats and the Plotly HTML report.

Copied from psse_scripts/dynamic.py, which does the same after its simulation; it only needs a
channel DataFrame with PSS®E channel names ("FREQ <bus> ...", "VOLT", "POWR", "VARS", "PLOD")
and a "Time(s)" column. Keep the two in sync.
"""

import json
import re
from html import escape

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

base_freq = 60.0
VOLTAGE_LOW = 0.9
VOLTAGE_HIGH = 1.1
WTVSI_K = 1
WTVSI_TOP_N = 5
POST_EVENT_AVG_WINDOW = 1.0

keywords = ["FREQ", "VOLT", "POWR", "VARS", "PLOD"]
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
            return ", ".join(f"{v:g}×λ" for v in value)
        return f"{value:g}×λ"

    items = []
    if info.get("simulator"):
        items.append(("Simulator", str(info["simulator"])))
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


def write_html_report(df, output_dir, now, wtvsi_summary, ufls_total_p_mw=None, simulator=None):
    """
    Plot the FREQ, VOLT, POWR, VARS and PLOD channels of `df` with their stats into
    `dynamic_channels_<now>.html` in `output_dir`. Returns the file path.
    """
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

                if keyword == "VOLT":  # and not any(df[col].iloc[-100:].values):
                    # skip voltage channels that are all zeros at the end
                    if not is_valid_voltage_profile(df[col].values):
                        continue
                    # skip voltage channels that don't exceed normal voltage range (0.9-1.1) during the whole simulation
                    if np.all((df[col].values >= VOLTAGE_LOW) & (df[col].values <= VOLTAGE_HIGH)):
                        continue

                # skip frequency channels that are all zeros at all times
                if keyword == "FREQ" and all(np.abs(df[col].values) < 1e-6):
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

        plot_blocks.append(
            {"kind": "plot", "html": pio.to_html(fig, include_plotlyjs=(plot_count == 0), full_html=False)}
        )
        plot_count += 1
        if SHOW_SIGNAL_STATS and keyword in SIGNAL_STATS_KEYWORDS:
            plot_blocks.append(
                {"kind": "stats", "html": build_signal_stats_html(keyword, plotted_series, wtvsi_summary)}
            )

    plots_path = output_dir / f"dynamic_channels_{now}.html"
    run_info = load_run_info(output_dir)
    if simulator:
        run_info["simulator"] = simulator
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
    return plots_path


def print_frequency_extremes(df):
    """Print the bus with the largest frequency deviation over the whole run."""
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

    if bus_max_overall is not None:
        print(f"-- Bus with maximum frequency deviation: Bus {bus_max_overall} (Value: {val_max_overall:.4f})")
