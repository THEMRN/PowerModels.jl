"""
Advanced settings, tab "Loads": give single loads their own P (MW) and Q (Mvar). A value left
empty keeps the case's value. Applied after the load scaling, so these values are final.

Entries of settings["modifications"]["loads"]:
    {"id": 6, "bus": 3005, "pd_mw": 400, "qd_mvar": null}
`id` is the load's number in the case as PowerModels reads it (the order of the RAW records).
`bus` is recorded with it, and Julia refuses the entry when that load is at another bus, so
settings made for another version of the case do not change a different load.
"""

from nicegui import ui

import theme
from components.row_list import RowList
from settings import clean_number, format_value, is_number

# ==================== Settings ====================
TITLE = "Loads"
KEY = "loads"
HINT = "Sets the P and Q of single loads, after the load scaling. A field left empty keeps the case's value, shown in grey."


# ==================== What the entries say ====================
def describe_values(entry):
    """The values an entry sets: "P 400 MW, Q 50 Mvar"."""
    values = []
    if entry.get("pd_mw") is not None:
        values.append(f"P {format_value(entry['pd_mw'])} MW")
    if entry.get("qd_mvar") is not None:
        values.append(f"Q {format_value(entry['qd_mvar'])} Mvar")
    return ", ".join(values)


def describe(entries):
    """One short text per entry: "load 6 at bus 3005: P 400 MW"."""
    return [f"load {entry.get('id')} at bus {entry.get('bus')}: {describe_values(entry)}" for entry in entries]


def find_problems(entries, study):
    """What keeps the entries from running in this study (its case)."""
    problems = []
    seen_loads = set()
    for entry in entries:
        load_id = entry.get("id")
        load = study.find_load(load_id)
        if load is None:
            problems.append(f"load {load_id} is not in the case")
            continue
        if entry.get("bus") is not None and entry["bus"] != load["bus"]:
            problems.append(f"load {load_id} is at bus {load['bus']} in this case, not at bus {entry['bus']}")
        if entry.get("pd_mw") is None and entry.get("qd_mvar") is None:
            problems.append(f"load {load_id} needs a P or a Q")
        for key, name in (("pd_mw", "P"), ("qd_mvar", "Q")):
            if entry.get(key) is not None and not is_number(entry[key]):
                problems.append(f"the {name} of load {load_id} must be a number")
        if load_id in seen_loads:
            problems.append(f"load {load_id} has two rows")
        seen_loads.add(load_id)
    return problems


# ==================== Rows of the dialog ====================
def find_load_options(study):
    """The loads of the case: {id: "6  ·  bus 3005  ·  100 MW, 50 Mvar"}."""
    options = {}
    for load in study.loads:
        text = f"{load['id']}  ·  bus {load['bus']}  ·  {load['pd_mw']:g} MW, {load['qd_mvar']:g} Mvar"
        if load["status"] == 0:
            text += "  (out of service)"
        options[load["id"]] = text
    return options


def new_row(_study=None):
    return {"id": None, "pd_mw": None, "qd_mvar": None}


def find_rows(entries, study):
    """The dialog's rows for entries. A load the case does not have becomes a row without a load."""
    rows = []
    for entry in entries:
        load = study.find_load(entry.get("id"))
        rows.append({"id": None if load is None else load["id"], "pd_mw": entry.get("pd_mw"), "qd_mvar": entry.get("qd_mvar")})
    return rows


def read_rows(rows, study):
    """(entries, problems) of the dialog's rows; a row without a load or without a value is a problem."""
    entries, problems = [], []
    for number, row in enumerate(rows, start=1):
        load = study.find_load(row["id"])
        pd_mw = clean_number(row["pd_mw"])
        qd_mvar = clean_number(row["qd_mvar"])
        if load is None or (pd_mw is None and qd_mvar is None):
            problems.append(f"row {number} needs a load and a P or a Q")
            continue
        entries.append({"id": load["id"], "bus": load["bus"], "pd_mw": pd_mw, "qd_mvar": qd_mvar})
    return entries, problems


# ==================== The tab ====================
def build(study, rows, on_change):
    """The tab's content: one row per load (the load, its P, its Q). It edits `rows` in place."""
    options = find_load_options(study)

    def change_load(row, load_id):
        row["id"] = load_id
        row_list.refresh()          # the grey values are the chosen load's

    def build_row(row):
        load = study.find_load(row["id"])
        case_p = "" if load is None else format_value(load["pd_mw"])
        case_q = "" if load is None else format_value(load["qd_mvar"])
        ui.select(options, value=row["id"], with_input=True, on_change=lambda event: change_load(row, event.value))
        ui.number(value=row["pd_mw"], placeholder=case_p, on_change=lambda event: row.update(pd_mw=event.value))
        ui.number(value=row["qd_mvar"], placeholder=case_q, on_change=lambda event: row.update(qd_mvar=event.value))

    theme.hint(HINT)
    row_list = RowList(
        rows, titles=("Load", "P (MW)", "Q (Mvar)"), row_class="load-row",
        new_row=new_row, build_row=build_row, on_change=on_change,
    )
