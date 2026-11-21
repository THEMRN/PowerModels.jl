"""
Run settings of the GUI, schema v1 (runners/gui/gui_plan.md, "Settings schema v1"): the defaults,
the conversion between the form's values and the settings in both directions, validation, and
JSON files. Pure functions, no GUI. The entries of the network modifications are described and
checked by the tabs of the advanced dialog (advanced/).
"""

import copy
import json
import re
from pathlib import Path

# ==================== Settings ====================
SCHEMA = 1
OBJECTIVES = ["opf", "flow", "flow_shed", "opf_shed"]
OPF_MODELS = ["AC", "DC"]
FLOW_MODELS = ["squared", "abs_sum", "combined"]
SIMULATORS = ["andes", "psse"]
BOUNDARY_KINDS = ["zone", "area", "bus_pairs"]
GROUP_KINDS = ["zone", "area"]                  # kinds a group of buses may be
FORBIDDEN_TAG_CHARACTERS = '\\/:*?"<>|'         # not allowed in a Windows folder name

DEFAULT_SETTINGS = {
    "schema": SCHEMA,
    "case": "cases/psse/ACTIVSg500",
    "objective": "flow_shed",
    "opf_model": "AC",
    "flow_model": "squared",
    "lambda": 500,                              # weight of the boundary flow penalty
    "boundary": {"kind": "zone", "name": "", "bus_pairs": []},
    "penalties": {"uniform": None, "groups": [], "buses": {}, "others": None},      # multiples of lambda
    "frequency_security": False,
    "voltage_security": False,
    "run_dynamic_sim": True,
    "simulator": "andes",
    "output_tag": "",
    "modifications": {},
}


def default_settings():
    """A fresh copy of the default settings."""
    return copy.deepcopy(DEFAULT_SETTINGS)


# ==================== Bus pairs ====================
def parse_bus_pairs(text):
    """
    Bus pairs of a text like "154-3008, 154-153" (pairs separated by commas, semicolons or new
    lines) as [[154, 3008], [154, 153]]. Raises ValueError with a readable message.
    """
    pairs = []
    for item in re.split(r"[,;\n]", text or ""):
        item = item.strip()
        if not item:
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", item)
        if match is None:
            raise ValueError(f'bus pairs: "{item}" is not two bus numbers joined by "-", like 154-3008')
        from_bus, to_bus = int(match.group(1)), int(match.group(2))
        if from_bus == to_bus:
            raise ValueError(f'bus pairs: "{item}" names the same bus twice')
        pairs.append([from_bus, to_bus])
    return pairs


def format_bus_pairs(pairs):
    """Bus pairs as the text parse_bus_pairs reads: "154-3008, 154-153"."""
    return ", ".join(f"{int(pair[0])}-{int(pair[1])}" for pair in pairs)


# ==================== Form values <-> settings ====================
def clean_number(value):
    """A form number for the settings: None stays None, a whole number becomes an int."""
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def clean_modifications(modifications):
    """A copy of the network modifications without the kinds that have no entry, so that {} means none."""
    return {key: copy.deepcopy(entries) for key, entries in (modifications or {}).items() if entries}


def format_value(value):
    """A number as a description shows it ("0.7", "400"); "?" for what is not a number."""
    return f"{value:g}" if is_number(value) else "?"


def build_settings(form):
    """
    The settings (schema v1) for the form's values, with the problems found while reading them
    (malformed bus pairs, penalty rows left half filled). `form` holds: case, objective,
    opf_model, flow_model, lambda, boundary_kind, boundary_name, bus_pairs_text, uniform (bool),
    uniform_value, penalty_rows ([{kind: "zone" | "area" | "bus", name, times_lambda}]), others,
    frequency_security, voltage_security, run_dynamic_sim, simulator, output_tag, and
    modifications (as in the settings: the advanced dialog keeps them in that shape).

    With uniform shedding the penalty rows and `others` are left out, because the run ignores them.
    """
    problems = []

    # boundary
    boundary_kind = form["boundary_kind"]
    boundary = {"kind": boundary_kind, "name": "", "bus_pairs": []}
    if boundary_kind == "bus_pairs":
        try:
            boundary["bus_pairs"] = parse_bus_pairs(form["bus_pairs_text"])
        except ValueError as error:
            problems.append(str(error))
    else:
        boundary["name"] = str(form["boundary_name"] or "").strip()

    # load shedding penalties
    penalties = {"uniform": None, "groups": [], "buses": {}, "others": None}
    if form["uniform"]:
        penalties["uniform"] = clean_number(form["uniform_value"])
        if penalties["uniform"] is None:
            problems.append("uniform shedding needs a penalty value")
    else:
        for number, row in enumerate(form["penalty_rows"], start=1):
            name = row.get("name")
            times_lambda = clean_number(row.get("times_lambda"))
            if name in (None, "") or times_lambda is None:
                problems.append(f"penalty row {number} needs a {row['kind']} and a value")
                continue
            if row["kind"] == "bus":
                penalties["buses"][str(name)] = times_lambda
            else:
                penalties["groups"].append({"kind": row["kind"], "name": str(name), "times_lambda": times_lambda})
        penalties["others"] = clean_number(form["others"])

    settings = {
        "schema": SCHEMA,
        "case": form["case"] or "",
        "objective": form["objective"],
        "opf_model": form["opf_model"],
        "flow_model": form["flow_model"],
        "lambda": clean_number(form["lambda"]),
        "boundary": boundary,
        "penalties": penalties,
        "frequency_security": bool(form["frequency_security"]),
        "voltage_security": bool(form["voltage_security"]),
        "run_dynamic_sim": bool(form["run_dynamic_sim"]),
        "simulator": form["simulator"],
        "output_tag": str(form["output_tag"] or "").strip(),
        "modifications": clean_modifications(form.get("modifications")),
    }
    return settings, problems


def form_values(settings):
    """The form's values for settings (schema v1): the inverse of build_settings."""
    boundary = settings["boundary"]
    penalties = settings["penalties"]
    penalty_rows = []
    for group in penalties.get("groups", []):
        penalty_rows.append({"kind": group["kind"], "name": group["name"], "times_lambda": group["times_lambda"]})
    for bus, times_lambda in penalties.get("buses", {}).items():
        penalty_rows.append({"kind": "bus", "name": int(bus), "times_lambda": times_lambda})

    return {
        "case": settings["case"],
        "objective": settings["objective"],
        "opf_model": settings["opf_model"],
        "flow_model": settings["flow_model"],
        "lambda": settings["lambda"],
        "boundary_kind": boundary["kind"],
        "boundary_name": boundary.get("name", ""),
        "bus_pairs_text": format_bus_pairs(boundary.get("bus_pairs", [])),
        "uniform": penalties.get("uniform") is not None,
        "uniform_value": penalties.get("uniform"),
        "penalty_rows": penalty_rows,
        "others": penalties.get("others"),
        "frequency_security": settings["frequency_security"],
        "voltage_security": settings["voltage_security"],
        "run_dynamic_sim": settings["run_dynamic_sim"],
        "simulator": settings["simulator"],
        "output_tag": settings.get("output_tag", ""),
        "modifications": clean_modifications(settings.get("modifications")),
    }


# ==================== Validation ====================
def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(settings):
    """
    Readable problems with settings (schema v1); empty when they can be sent to the worker.
    Of the network modifications only the shape is checked here: their entries belong to the tabs
    of the advanced dialog, which check them against the case (`find_problems` in advanced/).
    """
    problems = []
    if not settings.get("case"):
        problems.append("choose a case")
    if settings.get("objective") not in OBJECTIVES:
        problems.append(f"the objective must be one of {', '.join(OBJECTIVES)}")
    if settings.get("opf_model") not in OPF_MODELS:
        problems.append("the OPF model must be AC or DC")
    if settings.get("flow_model") not in FLOW_MODELS:
        problems.append(f"the flow model must be one of {', '.join(FLOW_MODELS)}")
    if settings.get("simulator") not in SIMULATORS:
        problems.append(f"the simulator must be one of {', '.join(SIMULATORS)}")
    if not is_number(settings.get("lambda")) or settings["lambda"] <= 0:
        problems.append("λ must be a positive number")
    if settings.get("voltage_security") and settings.get("opf_model") != "AC":
        problems.append("voltage security needs the AC model")

    # boundary
    boundary = settings.get("boundary", {})
    boundary_kind = boundary.get("kind")
    if boundary_kind not in BOUNDARY_KINDS:
        problems.append("the boundary must be a zone, an area or bus pairs")
    elif boundary_kind == "bus_pairs":
        if not boundary.get("bus_pairs"):
            problems.append("the boundary needs at least one bus pair, like 154-3008")
    elif not str(boundary.get("name", "")).strip():
        problems.append(f"choose the {boundary_kind} the boundary encloses")

    # load shedding penalties (multiples of lambda)
    penalties = settings.get("penalties", {})
    uniform = penalties.get("uniform")
    if uniform is not None and (not is_number(uniform) or uniform < 0):
        problems.append("the uniform penalty must be zero or more")
    others = penalties.get("others")
    if others is not None and (not is_number(others) or others < 0):
        problems.append("the penalty of all other loads must be zero or more")
    seen_groups = set()
    for group in penalties.get("groups", []):
        group_kind = group.get("kind")
        group_name = str(group.get("name", "")).strip()
        if group_kind not in GROUP_KINDS or not group_name:
            problems.append("a penalty group needs a zone or an area")
            continue
        if boundary_kind in GROUP_KINDS and group_kind != boundary_kind:
            problems.append(f"penalty on {group_kind} {group_name}: this study is by {boundary_kind}, so use {boundary_kind}s or buses")
        if not is_number(group.get("times_lambda")) or group["times_lambda"] < 0:
            problems.append(f"the penalty of {group_kind} {group_name} must be zero or more")
        key = (group_kind, group_name.lower())
        if key in seen_groups:
            problems.append(f"{group_kind} {group_name} has two penalty rows")
        seen_groups.add(key)
    if len({group.get("kind") for group in penalties.get("groups", [])}) > 1:
        problems.append("penalty groups must be all zones or all areas")
    for bus, times_lambda in penalties.get("buses", {}).items():
        if not str(bus).isdigit():
            problems.append(f'"{bus}" is not a bus number')
        if not is_number(times_lambda) or times_lambda < 0:
            problems.append(f"the penalty of bus {bus} must be zero or more")

    # network modifications: a list of entries per kind
    modifications = settings.get("modifications", {})
    if not isinstance(modifications, dict) or not all(isinstance(entries, list) for entries in modifications.values()):
        problems.append("the network modifications must be lists of entries, one list per kind")

    # output tag: suffix of the results folder
    output_tag = settings.get("output_tag", "")
    if not isinstance(output_tag, str):
        problems.append("the output tag must be text")
    elif any(character in FORBIDDEN_TAG_CHARACTERS for character in output_tag):
        problems.append(f"the output tag cannot contain any of {FORBIDDEN_TAG_CHARACTERS}")
    return problems


# ==================== JSON files ====================
def save_settings(path, settings):
    """Write settings to a JSON file."""
    Path(path).write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def load_settings(path):
    """Settings read from a JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
