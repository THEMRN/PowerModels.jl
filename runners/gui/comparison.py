"""
The runs put side by side on the Compare page, and what the page says of them. Nothing here
draws, so the functions can be checked without a browser.

A run that is compared is a record as the results panel shows one: a run of this session, or a
run of History with the results it kept (`result_<timestamp>.json`). Only a run with its final
results can be compared, and it is known by its results folder and settings file, so the same
run added from the Run page and from History is there once. The list belongs to the app, like
the runs, and is not kept when the app stops.

What is compared comes from each run's settings and @@result summary (gui_plan.md, "Result
summary"), in MW, Mvar, Hz and pu as the summary has them. The two margins are those of the
proposal's trade-off ("How much preparation is enough"):
- the frequency margin of an island, in Hz, is how far its nadir stays above its limit (the
  first UFLS stage), or its peak below it; the simulated frequency gives the margin the
  simulation delivered, the SFR model's the margin that was predicted;
- the voltage margin is the indicator threshold minus the worst indicator of the predicted
  island state (voltage.jl); it does not come from the simulation.
"""

from pathlib import Path

import advanced
import results_index
from components.results_view import (
    SOLVED_STATUSES,
    calc_frequency_verdict,
    describe_run_name,
    describe_ufls_fact,
    find_frequency_names,
)
from julia_worker import call_listeners
from settings import format_bus_pairs, upgrade_settings

# ==================== Settings ====================
NO_VALUE = "–"
MARGIN_SOURCES = {"simulated": "simulated_hz", "predicted": "predicted_hz"}     # source -> the island's key in the summary
SHED_TOLERANCE = 0.005          # MW, a group whose shed is below this in every run is left out of the tables by group


# ==================== The list ====================
def calc_run_key(record):
    """What a run is known by: its results folder and settings file ("savnw_flow_shed/settings_<ts>.json"), as History's row id; None without final results."""
    files = (record.get("summary") or {}).get("files") or {}
    if not files.get("settings") or not files.get("output_path"):
        return None
    return f"{Path(files['output_path']).name}/{files['settings']}"


def find_refusal(record):
    """Why a run cannot be compared, as a sentence, or "" when it can: it needs its final results."""
    name = describe_run_name(record).capitalize()
    if record["status"] == "running":
        return f"{name} is still running: it can be compared once it has finished."
    if not record.get("summary") or record.get("partial") or record["status"] != "finished":
        return f"{name} did not finish, so it has no final results to compare."
    if calc_run_key(record) is None:
        return f"{name} kept no record of its results, so it cannot be compared."
    return ""


class CompareList:
    """
    The runs on the Compare page, in the order they were added. A batch's runs (`compare` on
    their record) are added by themselves as they finish.
    """

    def __init__(self, runs):
        self.runs = runs
        self.records = []
        self._seen = set()              # job ids of the session's runs already added by themselves
        self._listeners = []
        runs.on_change(self._runs_changed)

    def on_change(self, listener):
        """Call `listener()` whenever a run is added or removed. Returns its remover."""
        self._listeners.append(listener)

        def remove():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def find(self, key):
        for record in self.records:
            if calc_run_key(record) == key:
                return record
        return None

    def add(self, record):
        """Add a run. Returns "" when it was added, or a sentence saying why not (no final results, or there already)."""
        refusal = find_refusal(record)
        if refusal:
            return refusal
        if self.find(calc_run_key(record)) is not None:
            return f"{describe_run_name(record).capitalize()} is already on the Compare page."
        self.records.append(record)
        call_listeners(self._listeners)
        return ""

    def remove(self, key):
        self.records = [record for record in self.records if calc_run_key(record) != key]
        call_listeners(self._listeners)

    def clear(self):
        self.records = []
        call_listeners(self._listeners)

    def _runs_changed(self):
        """A batch's run that has finished joins the list, once."""
        for record in self.runs.records:
            if not record.get("compare") or record["id"] in self._seen or record["status"] == "running":
                continue
            self._seen.add(record["id"])
            self.add(record)            # a run that failed or was stopped is refused there


# ==================== Names ====================
def describe_title(record):
    """A run's name at the top of its column: "Run 3", or the start of a run from History ("2026-11-21 02:15")."""
    if record["number"] is None:
        return record["started"]
    return f"Run {record['number']}"


def describe_subtitle(record):
    """Under the name: the run's output tag, or its case and objective when it has none."""
    run_settings = record["settings"]
    return run_settings.get("output_tag") or f"{Path(run_settings['case']).name} {run_settings['objective']}"


# ==================== Settings side by side ====================
def find_setting_facts(record):
    """The settings of a run as [(name, text)], in the order of the Run form."""
    run_settings = upgrade_settings(record["settings"])
    boundary = run_settings["boundary"]
    if boundary["kind"] == "bus_pairs":
        boundary_text = format_bus_pairs(boundary.get("bus_pairs", []))
    else:
        boundary_text = f"{boundary['kind']} {boundary['name']}"
    modifications = advanced.describe(run_settings.get("modifications") or {})
    return [
        ("Case", Path(run_settings["case"]).name),
        ("Objective", run_settings["objective"]),
        ("OPF model", run_settings["opf_model"]),
        ("Flow penalty", run_settings["flow_model"]),
        ("λ", results_index.format_number(run_settings["lambda"])),
        ("Boundary", boundary_text),
        ("Penalties", results_index.describe_penalties({"gui_settings": run_settings})),
        ("Network modifications", "; ".join(modifications) if modifications else "none"),
        ("Frequency security", "on" if run_settings["frequency_security"] else "off"),
        ("Voltage security", "on" if run_settings["voltage_security"] else "off"),
        ("Simulation", results_index.describe_simulator(run_settings["simulator"], run_settings["run_dynamic_sim"])),
        ("Output tag", run_settings.get("output_tag") or NO_VALUE),
    ]


def find_setting_rows(records):
    """
    (rows, same): the settings in which the runs differ, as rows {"name", "values"} with one
    text per run, and those they share as one line ("Case savnw  ·  OPF model AC"). A single run
    has all its settings as rows.
    """
    facts = [find_setting_facts(record) for record in records]
    rows, same = [], []
    for place, (name, _text) in enumerate(facts[0] if facts else []):
        values = [run_facts[place][1] for run_facts in facts]
        if len(records) > 1 and len(set(values)) == 1:
            same.append(f"{name} {values[0]}")
        else:
            rows.append({"name": name, "values": values})
    return rows, "  ·  ".join(same)


# ==================== Margins ====================
def calc_preemptive_shed(summary):
    """The preemptive shed of a run in MW: 0 for an objective that sheds no load."""
    load_shed = summary.get("load_shed")
    return 0.0 if load_shed is None else load_shed["total_shed_mw"]


def find_islands(summary):
    """The islands with frequency limits of a run as [(name, island)]; empty without frequency security."""
    islands = summary.get("frequency") or []
    return list(zip(find_frequency_names(summary), islands)) if islands else []


def calc_frequency_margins(summary, source="simulated"):
    """
    The frequency margin of each island with frequency limits: a list of {"island", "extreme",
    "value_hz", "limit_hz", "margin_hz"}. The margin is positive while the nadir stays above its
    limit, or the peak below it; `source` picks the frequency of the dynamic simulation
    ("simulated") or of the SFR model ("predicted"). `value_hz` and `margin_hz` are None when
    the run has no such frequency. Empty without frequency security.
    """
    margins = []
    for name, island in find_islands(summary):
        value = island.get(MARGIN_SOURCES[source])
        limit = island.get("limit_hz")
        margin = None
        if value is not None and limit is not None:
            margin = round(value - limit if island.get("extreme") == "nadir" else limit - value, 3)
        margins.append({"island": name, "extreme": island.get("extreme"), "value_hz": value, "limit_hz": limit, "margin_hz": margin})
    return margins


def find_voltage_threshold(summary):
    """The indicator threshold of a run with voltage security, or None."""
    details = (summary.get("voltage") or {}).get("details") or []
    return details[0].get("indicator_threshold") if details else None


def calc_voltage_margin(summary):
    """The voltage margin of a run: the indicator threshold minus the worst indicator; None without voltage security."""
    voltage = summary.get("voltage")
    threshold = find_voltage_threshold(summary)
    if not voltage or threshold is None or voltage.get("worst_indicator") is None:
        return None
    return round(threshold - voltage["worst_indicator"], 3)


def is_stopped_early(summary):
    """True when the dynamic simulation broke off before its end, so its extremes are those up to then."""
    simulation = summary.get("frequency_simulation") or {}
    return bool(simulation.get("stopped_early"))


# ==================== Results side by side ====================
def format_value(value, digits):
    """A number with a fixed count of decimals, or NO_VALUE for none."""
    return NO_VALUE if value is None else f"{value:.{digits}f}"


def build_row(name, values, tones=None):
    """A row of the comparison: its name, one text per run, and one tone per run ("" , "bad", "muted")."""
    return {"name": name, "values": values, "tones": tones or [""] * len(values)}


def find_number_row(name, numbers, digits, bad=None):
    """A row of numbers; `bad(number)` marks the ones to show as a problem."""
    tones = ["bad" if number is not None and bad is not None and bad(number) else "" for number in numbers]
    return build_row(name, [format_value(number, digits) for number in numbers], tones)


def find_solution_rows(summaries):
    statuses = [summary.get("termination_status") or NO_VALUE for summary in summaries]
    seconds = [summary.get("seconds") or {} for summary in summaries]
    return [
        build_row("Solver", statuses, ["" if status in SOLVED_STATUSES else "bad" for status in statuses]),
        build_row("Objective value", [NO_VALUE if summary.get("objective") is None else str(summary["objective"]) for summary in summaries]),
        find_number_row("Solve (s)", [times.get("solve") for times in seconds], 2),
        find_number_row("Dynamic simulation (s)", [times.get("dynamic_sim") for times in seconds], 2),
    ]


def find_shed_rows(summaries):
    """Total load, the preemptive shed, the UFLS relays' shed, and the two together."""
    loads, sheds, shares, ufls_texts, ufls_tones, stages, totals = [], [], [], [], [], [], []
    for summary in summaries:
        load_shed = summary.get("load_shed")
        load = load_shed["total_load_mw"] if load_shed else None
        shed = calc_preemptive_shed(summary)
        ufls = summary.get("ufls")
        simulated = ufls is not None and ufls.get("status") == "simulated"
        loads.append(load)
        sheds.append(shed)
        shares.append(round(100 * shed / load, 2) if load else None)
        ufls_texts.append(format_value(ufls["total_shed_mw"], 2) if simulated else describe_ufls_fact(summary))
        ufls_tones.append("" if simulated else "muted")
        stages.append(ufls["stages"] if simulated else None)
        totals.append(round(shed + ufls["total_shed_mw"], 2) if simulated else None)
    return [
        find_number_row("Total load (MW)", loads, 2),
        find_number_row("Preemptive shed (MW)", sheds, 2),
        find_number_row("Preemptive shed (%)", shares, 2),
        build_row("UFLS shed (MW)", ufls_texts, ufls_tones),
        find_number_row("UFLS stages that acted", stages, 0),
        find_number_row("Shed in all (MW)", totals, 2),
    ]


def find_flow_rows(summaries):
    flows = [summary["boundary_flows"] for summary in summaries]
    return [
        find_number_row("Net flow P (MW)", [flow["net"]["p_mw"] for flow in flows], 2),
        find_number_row("Net flow Q (Mvar)", [flow["net"]["q_mvar"] for flow in flows], 2),
        find_number_row("Sum of |P| (MW)", [flow["abs_sum"]["p_mw"] for flow in flows], 2),
        find_number_row("Sum of |Q| (Mvar)", [flow["abs_sum"]["q_mvar"] for flow in flows], 2),
    ]


def find_island_names(summaries):
    """The islands with frequency limits of all the runs, each name once, in the order first seen."""
    names = []
    for summary in summaries:
        for name, _island in find_islands(summary):
            if name not in names:
                names.append(name)
    return names


def find_frequency_rows(summaries):
    """Per island: its scheduled import and the limit that binds, then its nadir or peak predicted and simulated, and the margin the simulation left."""
    rows = []
    for name in find_island_names(summaries):
        imports, limits, limit_tones, predicted, simulated, margins = [], [], [], [], [], []
        for summary in summaries:
            island = dict(find_islands(summary)).get(name)
            margin = next((entry for entry in calc_frequency_margins(summary) if entry["island"] == name), None)
            if island is None:
                imports.append(None)
                limits.append(NO_VALUE)
                limit_tones.append("")
                predicted.append(None)
                simulated.append(None)
                margins.append(None)
                continue
            within, limit_mw, limit_name = calc_frequency_verdict(island)
            imports.append(island["scheduled_import_mw"])
            limits.append(f"{format_value(limit_mw, 2)} ({limit_name})")
            limit_tones.append("" if within else "bad")
            predicted.append(island.get("predicted_hz"))
            simulated.append(island.get("simulated_hz"))
            margins.append(margin["margin_hz"])
        rows.extend([
            find_number_row(f"{name}: scheduled import (MW)", imports, 2),
            build_row(f"{name}: limit on it (MW)", limits, limit_tones),
            find_number_row(f"{name}: predicted nadir or peak (Hz)", predicted, 3),
            find_number_row(f"{name}: simulated (Hz)", simulated, 3),
            find_number_row(f"{name}: frequency margin (Hz)", margins, 3, bad=lambda margin: margin < 0),
        ])
    return rows


def find_voltage_rows(summaries):
    """Verified or not, the rounds, the worst indicator against its threshold, and the margin between them."""
    if not any(summary.get("voltage") for summary in summaries):
        return []
    verdicts, tones, rounds, worst, thresholds = [], [], [], [], []
    for summary in summaries:
        voltage = summary.get("voltage")
        if not voltage:
            verdicts.append("not checked")
            tones.append("muted")
            rounds.append(None)
            worst.append(None)
            thresholds.append(None)
            continue
        verdicts.append("verified" if voltage["verified"] else "not verified")
        tones.append("" if voltage["verified"] else "bad")
        rounds.append(voltage["rounds"])
        worst.append(voltage["worst_indicator"])
        thresholds.append(find_voltage_threshold(summary))
    margins = [calc_voltage_margin(summary) for summary in summaries]
    return [
        build_row("Voltage", verdicts, tones),
        find_number_row("Rounds", rounds, 0),
        find_number_row("Worst indicator", worst, 3),
        find_number_row("Indicator threshold", thresholds, 3),
        find_number_row("Voltage margin, predicted", margins, 3, bad=lambda margin: margin < 0),
    ]


def find_group_shed_rows(summaries, part):
    """
    (group kind, rows) of the shed by zone or area, one row per group that sheds in some run:
    `part` is "load_shed" (the preemptive shed) or "ufls" (the relays'). (None, []) when the
    runs do not share one kind of group, or no group sheds.
    """
    kinds, sheds = set(), []
    for summary in summaries:
        data = summary.get(part)
        has_groups = data is not None and data.get("groups") is not None
        if has_groups:
            kinds.add(data["group_kind"])
        sheds.append({group["name"]: group["shed_mw"] for group in data["groups"]} if has_groups else None)
    if len(kinds) != 1:
        return None, []
    names = []
    for by_name in sheds:
        for name, shed in (by_name or {}).items():
            if name not in names and shed is not None and abs(shed) >= SHED_TOLERANCE:
                names.append(name)
    rows = [find_number_row(name, [None if by_name is None else by_name.get(name) for by_name in sheds], 2) for name in names]
    return next(iter(kinds)), rows


def find_sections(records):
    """
    The comparison as sections, each (title, rows): the solution, load shedding, boundary flows,
    frequency per island and voltage, then the shed by zone or area before and after the event
    when the runs are of one case. A section none of the runs has anything for is left out.
    """
    summaries = [record["summary"] for record in records]
    same_case = len({Path(record["settings"]["case"]).name for record in records}) == 1
    sections = [
        ("Solution", find_solution_rows(summaries)),
        ("Load shedding", find_shed_rows(summaries)),
        ("Boundary flows", find_flow_rows(summaries)),
        ("Frequency", find_frequency_rows(summaries)),
        ("Voltage", find_voltage_rows(summaries)),
    ]
    if same_case:                       # the zones of two cases are not the same zones
        kind, rows = find_group_shed_rows(summaries, "load_shed")
        sections.append((f"Preemptive shed by {kind} (MW)", rows))
        kind, rows = find_group_shed_rows(summaries, "ufls")
        sections.append((f"UFLS shed by {kind} (MW)", rows))
    return [(title, rows) for title, rows in sections if rows]


# ==================== The trade-off ====================
def find_tradeoff(records, source="simulated"):
    """
    What the trade-off charts show: the preemptive shed of each run against its margins.
    - "frequency": one series per island, {"island", "points"}, a point being {"run", "tag",
      "shed_mw", "margin", "value_hz", "limit_hz", "extreme", "stopped_early"};
    - "voltage": the points of the runs with voltage security, {"run", "tag", "shed_mw",
      "margin", "worst_indicator", "threshold", "verified"}; a run that is not verified with a
      margin above zero has an island that could not be checked (its power flow did not solve);
    - "no_frequency" and "no_voltage": the names of the runs that have no such margin.
    `source` picks the frequency of the dynamic simulation ("simulated") or of the SFR model
    ("predicted"); the voltage margin is always that of the predicted island state.
    """
    series, voltage_points, no_frequency, no_voltage = {}, [], [], []
    for record in records:
        summary = record["summary"]
        point = {"run": describe_title(record), "tag": describe_subtitle(record), "shed_mw": calc_preemptive_shed(summary)}
        margins = [entry for entry in calc_frequency_margins(summary, source) if entry["margin_hz"] is not None]
        if not margins:
            no_frequency.append(point["run"])
        for entry in margins:
            series.setdefault(entry["island"], []).append(dict(
                point,
                margin=entry["margin_hz"],
                value_hz=entry["value_hz"],
                limit_hz=entry["limit_hz"],
                extreme=entry["extreme"],
                stopped_early=source == "simulated" and is_stopped_early(summary),
            ))
        margin = calc_voltage_margin(summary)
        if margin is None:
            no_voltage.append(point["run"])
        else:
            voltage_points.append(dict(
                point,
                margin=margin,
                worst_indicator=summary["voltage"]["worst_indicator"],
                threshold=find_voltage_threshold(summary),
                verified=bool(summary["voltage"]["verified"]),
            ))
    return {
        "frequency": [{"island": island, "points": points} for island, points in series.items()],
        "voltage": voltage_points,
        "no_frequency": no_frequency,
        "no_voltage": no_voltage,
    }
