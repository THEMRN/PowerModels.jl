"""
One-page summary of the frequency-security tests, for meetings: the story on one black-and-white
page, and its three figures as separate files.

    python runners/frequency_tests/build_summary.py

Reads results/frequency_tests/report_data.json (written by build_report.py, so run that first)
and writes to results/frequency_tests/summary/:
    fig1_opf_tests.{png,pdf}            import / cap of each OPF test, constraint off and on
    fig2_frequency_off_on.{png,pdf}     frequency range after the split, full pipeline with relays
    fig3_nadir_model.{png,pdf}          nadir model against the calibration sweeps
    frequency_security_summary.pdf      summary.html printed with Edge or Chrome headless (US Letter)
    frequency_security_summary_short.pdf  summary_short.html, the same story in half the length
"""

import json
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# ==================== Settings ====================
ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "frequency_tests"
OUTPUT_DIR = RESULTS / "summary"
PAGES = {  # page source -> PDF
    Path(__file__).with_name("summary.html"): OUTPUT_DIR / "frequency_security_summary.pdf",
    Path(__file__).with_name("summary_short.html"): OUTPUT_DIR / "frequency_security_summary_short.pdf",
}
BROWSERS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
]

# Fig. 3: the zone or north island of each calibration sweep, and its marker
SWEEP_ISLANDS = [
    ("activsg_midlands_light", "MIDLANDS (steam, gas, hydro)", dict(marker="o", mfc="0.3", mec="0.3")),
    ("activsg_spartanb_light", "SPARTANB (hydro only)", dict(marker="s", mfc="white", mec="black")),
    ("savnw_north", "savnw north (steam)", dict(marker="^", mfc="0.7", mec="black")),
]
ZERO_IMPORT = 0.5  # MW, a sweep run below this counts as zero import
ZERO_LIMIT = 0.01  # MW, an import limit below this counts as zero (island with no load and no governor)
FAILED_CHECK_NAMES = {  # Fig. 2 verdict, in this order
    "no_ufls": "UFLS",
    "no_trips": "trip",
    "nadir": "nadir",
    "zenith": "zenith",
    "rocof": "RoCoF",
    "qss": "settling",
}
SHORT_NAMES = {
    "savnw_top": "savnw top",
    "savnw_top_heavy": "savnw top, 400 MW",
    "savnw_north": "savnw north-south",
    "savnw_north_heavy": "savnw north ×1.6",
    "savnw_bottom": "savnw bottom",
    "savnw_left": "savnw left",
    "savnw_gen_only": "savnw gen 3018 alone",
    "savnw_dead_bus": "savnw bus 202 alone",
    "savnw_north_line_out": "savnw north-south, line out",
    "activsg_spartanb": "SPARTANB",
    "activsg_midlands": "MIDLANDS",
    "activsg_york": "YORK",
    "activsg_columbia": "COLUMBIA",
    "activsg_greenvil": "GREENVIL",
}

# figures: black and grey only, so they print the same as they show
FIGURE_WIDTH = 6.5  # in
BAND_GREY = "0.88"
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "legend.frameon": False,
    "pdf.fonttype": 42,  # embed TrueType, so the text stays editable
})


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_figure(fig, name):
    for suffix, options in ((".png", {"dpi": 300}), (".pdf", {})):
        fig.savefig(OUTPUT_DIR / f"{name}{suffix}", bbox_inches="tight", **options)
    plt.close(fig)
    print(f"Figure written to {OUTPUT_DIR / name}.png and .pdf")


def times_label(value):
    """Tick label of a ratio axis: −10×, 0, 1×."""
    if value == 0:
        return "0"
    return f"{'−' if value < 0 else ''}{abs(value):g}×"


# ==================== Figure data ====================
def calc_import_ratio(import_mw, limit_mw):
    """Import / limit; for a zero limit 0 when the import is zero too, else ±inf."""
    if import_mw is None:
        return None
    if limit_mw >= ZERO_LIMIT:
        return import_mw / limit_mw
    if abs(import_mw) < ZERO_LIMIT:
        return 0.0
    return float("inf") if import_mw > 0 else float("-inf")


def calc_model_row(test):
    """Fig. 1 row: import / limit, off and on, of the island furthest over its limit with the constraint off."""
    islands = [island for island in test["islands"] if island["import_off_mw"] is not None]
    key_island = max(islands, key=lambda island: abs(calc_import_ratio(island["import_off_mw"], island["limit_mw"])))
    label = f"{SHORT_NAMES[test['scenario']]} · {test['objective']}"
    if test["opf_model"] == "DC":
        label += " · DC"
    return {
        "label": label,
        "passed": test["passed"],
        "error": test["error"] is not None,
        "off": calc_import_ratio(key_island["import_off_mw"], key_island["limit_mw"]),
        "on": calc_import_ratio(key_island["import_on_mw"], key_island["limit_mw"]),
    }


def calc_sweep_point(point, nadir_cap):
    """Fig. 3 point: import / nadir cap, and the lowest frequency for an import, the highest for an export."""
    sim = point["sim"]
    if point["import"] > ZERO_IMPORT:
        extreme = sim["nadir_hz"]
    elif point["import"] < -ZERO_IMPORT:
        extreme = sim["zenith_hz"]
    else:  # no import: whichever moves further from 60 Hz
        extreme = max(sim["nadir_hz"], sim["zenith_hz"], key=lambda f: abs(f - 60.0))
    return point["import"] / nadir_cap, extreme


def calc_frequency_range(run):
    """Fig. 2 bar: lowest and highest frequency of the zone or smaller island, and the verdict over both islands."""
    island = run["islands"][0]
    failed = []
    for check, name in FAILED_CHECK_NAMES.items():
        if not all(each["checks"][check] for each in run["islands"]):
            failed.append(name)
    return {
        "min_hz": island["sim"]["nadir_hz"],
        "max_hz": island["sim"]["zenith_hz"],
        "secure": not failed and not run["busted"],
        "fails": failed,
    }


# ==================== Figures ====================
def plot_model_tests(rows):
    """Fig. 1: import / cap of each OPF test, off (hollow) and on (filled), linear within ±1 and logarithmic beyond."""
    finite_ratios = [abs(r[key]) for r in rows for key in ("off", "on") if r[key] is not None and abs(r[key]) < float("inf")]
    extent = max(10.0, max(finite_ratios) * 1.25)
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 0.165 * len(rows) + 0.9))
    ax.set_xscale("symlog", linthresh=1, linscale=1)
    ax.axvspan(-1, 1, color=BAND_GREY, lw=0)
    ticks = [t for t in (-1000, -100, -10, -1, 0, 1, 10, 100, 1000) if abs(t) <= extent]
    ax.set_xticks(ticks, [times_label(t) for t in ticks])
    ax.grid(axis="x", color="0.85", lw=0.5)
    ax.set_axisbelow(True)

    for k, row in enumerate(rows):
        # an import over a zero cap sits at the end of the axis
        off, on = row["off"], row["on"]
        if off is not None and abs(off) == float("inf"):
            off = extent if off > 0 else -extent
            ax.annotate("cap 0 MW", (off, k), xytext=(6 if off < 0 else -6, 4), textcoords="offset points",
                        ha="left" if off < 0 else "right", fontsize=6.5)
        if off is not None and on is not None:
            ax.plot([off, on], [k, k], color="0.6", lw=1, zorder=2)
        if off is not None:
            ax.plot(off, k, ls="", marker="o", ms=4.5, mfc="white", mec="black", mew=0.9, zorder=3, clip_on=False)
        if on is not None:
            ax.plot(on, k, ls="", marker="o", ms=4.5, mfc="black", mec="black", zorder=3)
        else:  # no solution with the constraint on: say why, on the side away from the off point
            text = "on: model build failed" if row["error"] else "on: infeasible"
            ax.text(-0.15 if off > 0 else 0.15, k, text, ha="right" if off > 0 else "left", va="center", fontsize=6.5,
                    fontweight="normal" if row["passed"] else "bold")

    ax.set_xlim(-extent, extent)
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_yticks(range(len(rows)), [r["label"] for r in rows])
    for label, row in zip(ax.get_yticklabels(), rows):
        label.set_fontweight("normal" if row["passed"] else "bold")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("scheduled import ÷ cap (negative: export)")
    ax.legend(handles=[
        Line2D([], [], ls="", marker="o", ms=4.5, mfc="white", mec="black", label="constraint off"),
        Line2D([], [], ls="", marker="o", ms=4.5, mfc="black", mec="black", label="constraint on"),
        Patch(color=BAND_GREY, label="allowed: |import| ≤ cap"),
    ], loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, borderaxespad=0.2)
    ax.set_title("Fig. 1  OPF tests: scheduled import ÷ the island's cap, constraint off and on", pad=20)
    save_figure(fig, "fig1_opf_tests")


def plot_frequency_ranges(runs):
    """Fig. 2: lowest to highest frequency after the split, off (thin) and on (thick), with the verdict when on."""
    low, high = 57.5, 62.0
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 0.33 * len(runs) + 0.95))
    ax.axvspan(59.5, 60.5, color=BAND_GREY, lw=0)
    styles = {
        "off": dict(color="black", lw=1.1, offset=-0.17),
        "on": dict(color="0.45", lw=4.5, offset=0.17),
    }
    for k, run in enumerate(runs):
        for state, style in styles.items():
            frequencies = run[state]
            y = k + style["offset"]
            ax.plot([max(low, frequencies["min_hz"]), min(high, frequencies["max_hz"])], [y, y],
                    color=style["color"], lw=style["lw"], solid_capstyle="butt")
            # beyond the axis: an arrowhead at its end and the value
            for value, edge, marker, align in ((frequencies["min_hz"], low, "<", "left"), (frequencies["max_hz"], high, ">", "right")):
                if (value < edge) if marker == "<" else (value > edge):
                    ax.plot(edge, y, marker=marker, ms=4, color=style["color"], clip_on=False)
                    ax.text(edge, y - 0.2, f"{value:.1f} Hz", ha=align, va="bottom", fontsize=6.5)
        verdict = "secure" if run["on"]["secure"] else "not secure: " + ", ".join(run["on"]["fails"][:2])
        ax.text(1.02, k, verdict, transform=ax.get_yaxis_transform(), va="center", fontsize=7.5,
                fontweight="bold" if run["on"]["secure"] else "normal")
    ax.text(1.02, -0.75, "constraint on", transform=ax.get_yaxis_transform(), va="center", fontsize=7.5, fontstyle="italic")

    ax.set_xlim(low, high)
    ax.set_ylim(len(runs) - 0.5, -0.5)
    ax.set_xticks([58, 59, 60, 61, 62])
    ax.grid(axis="x", color="0.85", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_yticks(range(len(runs)), [run["label"] for run in runs])
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("frequency after the split (Hz), zone or smaller island")
    ax.legend(handles=[
        Line2D([], [], color="black", lw=1.1, label="constraint off"),
        Line2D([], [], color="0.45", lw=4.5, label="constraint on"),
        Patch(color=BAND_GREY, label="59.5 to 60.5 Hz"),
    ], loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, borderaxespad=0.2)
    ax.set_title("Fig. 2  Frequency after the split in the full pipeline with relays, constraint off and on", pad=20)
    save_figure(fig, "fig2_frequency_off_on")


def plot_nadir_model(sweeps):
    """Fig. 3: simulated lowest / highest frequency against import / nadir cap, with the model's single line."""
    x_low, x_high = -2.1, 2.1
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 3.3))
    for threshold in (59.5, 60.5):
        ax.axhline(threshold, color="black", lw=0.7, ls=(0, (4, 3)))
        ax.text(x_high, threshold + 0.03, f"{threshold} Hz", ha="right", va="bottom", fontsize=6.5)
    for edge in (-1, 1):
        ax.axvline(edge, color="0.55", lw=0.7)
    ax.text(1.03, 61.3, "nadir cap", ha="left", va="top", fontsize=6.5)
    ax.text(-1.03, 57.9, "cap for exports", ha="right", va="bottom", fontsize=6.5)
    ax.text(-2.0, 58.9, "points further from 60 Hz than the line:\nthe cap is too generous", ha="left", va="top", fontsize=6.5, fontstyle="italic")
    # the model is linear: the nadir is 60 − 0.5 Hz × (import / nadir cap), and the same line gives the highest frequency for exports
    ax.plot([x_low, x_high], [60 - 0.5 * x_low, 60 - 0.5 * x_high], color="black", lw=1.2, label="model (every island)")
    for sweep in sweeps:
        x_values = [point[0] for point in sweep["points"]]
        y_values = [point[1] for point in sweep["points"]]
        ax.plot(x_values, y_values, ls="", ms=4.5, mew=0.8, label=sweep["label"], **sweep["style"])

    ax.set_xlim(x_low, x_high)
    ax.set_ylim(57.8, 61.4)
    ax.set_xticks([-2, -1, 0, 1, 2], [times_label(t) for t in (-2, -1, 0, 1, 2)])
    ax.grid(axis="y", color="0.85", lw=0.5)
    ax.set_axisbelow(True)
    ax.set_xlabel("scheduled import ÷ the island's nadir cap (negative: export)")
    ax.set_ylabel("lowest (import) or highest (export)\nfrequency in ANDES (Hz)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, borderaxespad=0.2)
    ax.set_title("Fig. 3  Nadir model against simulation, calibration sweeps without relays", pad=32)
    save_figure(fig, "fig3_nadir_model")


# ==================== Figures ====================
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
report = read_json(RESULTS / "report_data.json")

plot_model_tests([calc_model_row(test) for test in report["model"]])

ranges = []
for scenario in dict.fromkeys(run["scenario"] for run in report["passfail"]):  # run order
    run_off = next(r for r in report["passfail"] if r["scenario"] == scenario and not r["frequency_security"])
    run_on = next(r for r in report["passfail"] if r["scenario"] == scenario and r["frequency_security"])
    ranges.append({
        "label": f"{SHORT_NAMES[scenario]} · {run_on['objective']}",
        "off": calc_frequency_range(run_off),
        "on": calc_frequency_range(run_on),
    })
plot_frequency_ranges(ranges)

sweeps = []
for scenario, label, style in SWEEP_ISLANDS:
    sweep = next(s for s in report["sweeps"] if s["scenario"] == scenario)
    island = sweep["islands"][0]
    nadir_cap = island["limits_mw"]["nadir"]
    sweeps.append({"label": label, "style": style, "points": [calc_sweep_point(point, nadir_cap) for point in island["points"]]})
plot_nadir_model(sweeps)

# ==================== Pages ====================
browser = next((path for path in BROWSERS if path.exists()), None)
for page, output_pdf in PAGES.items():
    if browser is None:
        print(f"No Edge or Chrome found, PDF skipped (print {page} from a browser instead)")
        continue
    with tempfile.TemporaryDirectory() as profile:  # own profile, so a running browser is not disturbed
        subprocess.run([
            str(browser), "--headless", "--disable-gpu", f"--user-data-dir={profile}",
            "--no-pdf-header-footer", f"--print-to-pdf={output_pdf}", page.as_uri(),
        ], check=True, capture_output=True)
    pdf = output_pdf.read_bytes()
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    print(f"Summary written to {output_pdf} ({pages} page{'s' if pages != 1 else ''})")
