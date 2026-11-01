"""
Collects the results of the three frequency-security tests into the HTML report.

    python runners/frequency_tests/build_report.py

Reads results/frequency_tests/{offline,model,dynamic}/ and writes
results/frequency_tests/frequency_security_tests.html from report_template.html, with all the
data embedded as JSON (the page draws its tables and figures from it) and the chart library
(d3) embedded, so the page opens offline. The same data is written to report_data.json.
"""

import json
import datetime as dt
from pathlib import Path

import numpy as np

# ==================== Settings ====================
ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "frequency_tests"
TEMPLATE = Path(__file__).with_name("report_template.html")
CHART_LIBRARY = Path(__file__).with_name("d3.v7.8.5.min.js")
OUTPUT = RESULTS / "frequency_security_tests.html"

NOMINAL_FREQUENCY = 60.0  # Hz
MAX_ROCOF = 0.5  # Hz/s
MAX_QSS_DEVIATION = 0.3  # Hz
MIN_NADIR_FREQUENCY = 59.5  # Hz
MAX_ZENITH_FREQUENCY = 60.5  # Hz, the nadir limit is symmetric
LINEAR_RANGE = 1.0  # Hz, settling deviation up to which a run counts for the governor-gain fit
BASE_MVA = 100.0  # both cases


def read_json(path):
    with open(path) as f:
        return json.load(f)


def without_nan(x):
    """The same data with NaN and infinities replaced by None, so the page gets valid JSON."""
    if isinstance(x, float):
        return x if np.isfinite(x) else None
    if isinstance(x, dict):
        return {k: without_nan(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [without_nan(v) for v in x]
    return x


def find_crossing(points, value_of, threshold, side):
    """
    Import (MW) at which a simulated metric first crosses its threshold, by linear interpolation
    between sweep points, walking away from zero import on one side (+1 importing, -1 exporting).
    None when the sweep never crosses it on that side.
    """
    side_points = sorted([p for p in points if p["import"] * side >= 0], key=lambda p: abs(p["import"]))
    previous = None
    for point in side_points:
        value = value_of(point)
        if value >= threshold:
            if previous is None:
                return point["import"]
            x0, y0 = previous["import"], value_of(previous)
            x1, y1 = point["import"], value
            return x0 + (threshold - y0) * (x1 - x0) / (y1 - y0) if y1 != y0 else x1
        previous = point
    return None


def summarize_sweep_island(points, sfr_slopes):
    """Simulated and SFR-predicted import limits (MW) of one island, per requirement and side."""
    measures = {
        # value that grows with the violation, and its threshold
        "rocof": (lambda p: abs(p["sim"]["rocof_500ms"]), MAX_ROCOF, "rocof_500ms"),
        "nadir": (lambda p: NOMINAL_FREQUENCY - p["sim"]["nadir_hz"], NOMINAL_FREQUENCY - MIN_NADIR_FREQUENCY, None),
        "zenith": (lambda p: p["sim"]["zenith_hz"] - NOMINAL_FREQUENCY, MAX_ZENITH_FREQUENCY - NOMINAL_FREQUENCY, None),
        "qss": (lambda p: abs(p["sim"]["settle_hz"] - NOMINAL_FREQUENCY), MAX_QSS_DEVIATION, "settle_hz"),
    }
    limits = {}
    for name, (value_of, threshold, _) in measures.items():
        sides = (1,) if name == "nadir" else (-1,) if name == "zenith" else (1, -1)
        for side in sides:
            crossing = find_crossing(points, value_of, threshold, side)
            limits[f"{name}_{'import' if side > 0 else 'export'}"] = crossing
    # SFR-predicted crossings of the same measured quantities (linear in the import)
    predicted = {
        "rocof_500ms": MAX_ROCOF / sfr_slopes["rocof_500ms"] if sfr_slopes["rocof_500ms"] else None,
        "nadir": (NOMINAL_FREQUENCY - MIN_NADIR_FREQUENCY) / sfr_slopes["nadir"] if sfr_slopes["nadir"] else None,
        "settle_20s": MAX_QSS_DEVIATION / sfr_slopes["settle"] if sfr_slopes["settle"] else None,
    }
    return limits, predicted


# ==================== Offline and model tests ====================
offline_dir = RESULTS / "offline"
report = {
    "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "thresholds": {
        "nominal": NOMINAL_FREQUENCY,
        "rocof": MAX_ROCOF,
        "qss": MAX_QSS_DEVIATION,
        "nadir": MIN_NADIR_FREQUENCY,
        "zenith": MAX_ZENITH_FREQUENCY,
    },
    "offline": {
        "machines": {c: read_json(offline_dir / f"machines_{c}.json") for c in ("savnw", "ACTIVSg500")},
        "dyr_check": {c: read_json(offline_dir / f"dyr_check_{c}.json") for c in ("savnw", "ACTIVSg500")},
        "islands": read_json(offline_dir / "islands.json"),
        "nadir": read_json(offline_dir / "nadir.json"),
        "sensitivity": read_json(offline_dir / "sensitivity.json"),
    },
    "model": read_json(RESULTS / "model" / "model_tests.json"),
}

# ==================== Dynamic: calibration sweeps ====================
sweeps = []
for sweep_file in sorted((RESULTS / "dynamic").glob("sweep_*/sweep.json")):
    sweep = read_json(sweep_file)
    runs = []
    for point in sweep["points"]:
        metrics_file = sweep_file.parent / point["folder"] / "metrics.json"
        metrics = read_json(metrics_file) if metrics_file.exists() else None
        if metrics is None:
            reason = f"no OPF solution ({point['status']})"
        elif not metrics["init_steady"]:
            reason = "ANDES initialization not at steady state (a unit below its governor minimum)"
            metrics = None
        elif metrics["busted"]:
            reason = f"simulation stopped {metrics['sim_end_s']:.1f} s after the split"
            metrics = None
        else:
            reason = None
        runs.append({"forced_import_mw": point["forced_import_mw"], "metrics": metrics, "excluded": reason})

    islands = []
    simulated = [r for r in runs if r["metrics"] is not None]
    n_islands = len(simulated[0]["metrics"]["islands"]) if simulated else 0
    for k in range(n_islands):
        points = []
        for r in simulated:
            island = r["metrics"]["islands"][k]
            points.append(
                {
                    "forced": r["forced_import_mw"],
                    "import": island["andes_import_mw"],
                    "import_pm": island["scheduled_import_mw"],
                    "reactive_import": island["andes_reactive_import_mvar"],
                    "power_step": island["power_step_mw"],
                    "load_step": island["load_step_mw"],
                    "voltage_step": island["voltage_step_pu"],
                    "sim": island["sim"],
                    "sfr": island["sfr"],
                    "sfr_no_damping": island["sfr_no_damping"],
                    "ufls_mw": island["ufls_mw"],
                    "trace": island["trace"],
                }
            )
        first = simulated[0]["metrics"]["islands"][k]
        # SFR model per MW of import (linear): from the point with the largest import
        reference = max(points, key=lambda p: abs(p["import"]))
        sfr_slopes = {
            "rocof_500ms": abs(reference["sfr"]["rocof_500ms"] / reference["import"]),
            "nadir": abs((NOMINAL_FREQUENCY - reference["sfr"]["nadir_hz"]) / reference["import"]) if reference["import"] > 0 else
            abs((reference["sfr"]["zenith_hz"] - NOMINAL_FREQUENCY) / reference["import"]),
            "settle": abs((reference["sfr"]["settle_hz"] - NOMINAL_FREQUENCY) / reference["import"]),
        }
        simulated_limits, predicted_measured = summarize_sweep_island(points, sfr_slopes)

        # effective share of the scheduled import the machines see at the split (least squares through zero)
        x = np.array([p["import"] for p in points])
        y = np.array([p["power_step"] for p in points])
        step_ratio = float(np.dot(x, y) / np.dot(x, x)) if np.dot(x, x) > 0 else None

        # governor gain the simulation delivers: straight-line fit of the settling deviation against
        # the import, K_eff = f0 / (base * slope) on the system base, over the runs that settle
        # within LINEAR_RANGE (beyond it the governors saturate); the intercept is the offset the
        # split causes on its own (zero import)
        settle_deviation = np.array([p["sim"]["settle_hz"] - NOMINAL_FREQUENCY for p in points])
        linear = np.abs(settle_deviation) <= LINEAR_RANGE
        if linear.sum() > 1:
            slope, offset = np.polyfit(x[linear], settle_deviation[linear], 1)
        else:
            slope, offset = np.nan, np.nan
        effective_gain = float(NOMINAL_FREQUENCY / (BASE_MVA * abs(slope))) if np.isfinite(slope) and slope != 0 else None
        collapsed = [p["import"] for p, ok in zip(points, linear) if not ok]

        islands.append(
            {
                "n_buses": first["n_buses"],
                "inertia": first["inertia"],
                "governor_gain": first["governor_gain"],
                "damping": first["damping"],
                "limits_mw": first["limits_mw"],
                "binding": first["binding"],
                "points": points,
                "simulated_limits": simulated_limits,
                "predicted_measured": predicted_measured,
                "step_ratio": step_ratio,
                "settle_offset_hz": float(offset),
                "effective_gain": effective_gain,
                "collapsed_imports": collapsed,
            }
        )
    sweeps.append({"scenario": sweep["scenario"], "description": sweep["description"], "runs": len(runs),
                   "excluded": [{"forced_import_mw": r["forced_import_mw"], "reason": r["excluded"]} for r in runs if r["excluded"]],
                   "islands": islands})
report["sweeps"] = sweeps

# ==================== Dynamic: pass/fail runs ====================
passfail = []
passfail_file = RESULTS / "dynamic" / "passfail" / "passfail.json"
if passfail_file.exists():
    for entry in read_json(passfail_file):
        run_dir = passfail_file.parent / entry["folder"]
        metrics = read_json(run_dir / "metrics.json")
        run_info = read_json(run_dir / "run_info.json")
        islands = []
        for island in metrics["islands"]:
            sim = island["sim"]
            # a run that stopped early has no settling value; it fails on what stopped it
            checks = {
                "nadir": sim["nadir_hz"] >= MIN_NADIR_FREQUENCY,
                "zenith": sim["zenith_hz"] <= MAX_ZENITH_FREQUENCY,
                "rocof": abs(sim["rocof_500ms"]) <= MAX_ROCOF,
                "qss": metrics["busted"] or abs(sim["settle_hz"] - NOMINAL_FREQUENCY) <= MAX_QSS_DEVIATION,
                "no_ufls": island["ufls_mw"] == 0,
                "no_trips": len(island["gen_trips"]) == 0,
            }
            islands.append(
                {
                    "n_buses": island["n_buses"],
                    "limits_mw": island["limits_mw"],
                    "binding": island["binding"],
                    "import": island["andes_import_mw"],
                    "import_pm": island["scheduled_import_mw"],
                    "power_step": island["power_step_mw"],
                    "sim": sim,
                    "sfr": island["sfr"],
                    "ufls_mw": island["ufls_mw"],
                    "first_ufls_s": island["first_ufls_s"],
                    "gen_trips": island["gen_trips"],
                    "checks": checks,
                    "secure": all(checks.values()),
                    "trace": island["trace"],
                }
            )
        passfail.append(
            {
                "scenario": entry["scenario"],
                "description": entry["description"],
                "objective": entry["objective"],
                "frequency_security": entry["frequency_security"],
                "status": entry["status"],
                "preemptive_shed_mw": run_info.get("preemptive_shed_mw", 0.0),
                "busted": metrics["busted"],
                "init_steady": metrics["init_steady"],
                "sim_end_s": metrics["sim_end_s"],
                "islands": islands,
            }
        )
report["passfail"] = passfail

# ==================== Page ====================
with open(RESULTS / "report_data.json", "w") as f:  # the same data, for reading outside the page
    json.dump(without_nan(report), f, indent=1, allow_nan=False)
page = TEMPLATE.read_text(encoding="utf-8")
data = json.dumps(without_nan(report), separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
page = page.replace("/*REPORT_DATA*/null", data)
page = page.replace("/*D3_LIBRARY*/", CHART_LIBRARY.read_text(encoding="utf-8"))
OUTPUT.write_text(page, encoding="utf-8")
print(f"Report written to {OUTPUT} ({OUTPUT.stat().st_size / 1e6:.2f} MB)")
