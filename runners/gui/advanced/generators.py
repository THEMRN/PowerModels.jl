"""
Advanced settings, tab "Generators": set the Pmin and the Pmax (MW) of every generator of a zone
or an area, or at a list of buses. A value is given to each generator, not shared among them. A
limit left empty stays as the case has it, and a new row starts with both empty. Pmin 0 is the
scenario note in islanding.jl, which lets the generators go down to zero output.

Entries of settings["modifications"]["generators"]:
    {"kind": "zone" | "area", "name": "SPARTANB", "pmin_mw": 0, "pmax_mw": null}
    {"kind": "buses", "buses": [101, 102], "pmin_mw": null, "pmax_mw": 500}
"""

from nicegui import ui

import theme
from advanced import where
from components.row_list import RowList
from settings import clean_number, format_value, is_number

# ==================== Settings ====================
TITLE = "Generators"
KEY = "generators"
HINT = (
    "Sets the Pmin and Pmax of each generator in the group, or at the buses listed: every one of them gets the value. "
    "An empty field keeps the case's value."
)
LIMITS = {"pmin_mw": "Pmin", "pmax_mw": "Pmax"}      # key in an entry -> its name


# ==================== What the entries say ====================
def describe_limits(entry):
    """The limits an entry sets: "Pmin 0 MW, Pmax 500 MW"."""
    return ", ".join(f"{name} {format_value(entry[key])} MW" for key, name in LIMITS.items() if entry.get(key) is not None)


def describe(entries):
    """One short text per entry: "generators of zone SPARTANB: Pmin 0 MW"."""
    return [f"generators {where.describe_of(entry)}: {describe_limits(entry) or 'nothing set'}" for entry in entries]


def find_problems(entries, study):
    """What keeps the entries from running in this study (its case, its kind of group)."""
    problems = []
    seen_groups = set()
    for entry in entries:
        place = where.describe_where(entry)
        pmin_mw, pmax_mw = entry.get("pmin_mw"), entry.get("pmax_mw")
        if pmin_mw is None and pmax_mw is None:
            problems.append(f"the generators {where.describe_of(entry)} need a Pmin or a Pmax")
        for key, name in LIMITS.items():
            if entry.get(key) is not None and not is_number(entry[key]):
                problems.append(f"the {name} of {place} must be a number")
        if is_number(pmin_mw) and is_number(pmax_mw) and pmin_mw > pmax_mw:
            problems.append(f"the Pmin of {place} is above its Pmax")
        problems.extend(where.find_where_problems(entry, study, study.find_gen_buses(), "generator"))
        key = where.find_group_key(entry)
        if key is not None and key in seen_groups:
            problems.append(f"{place} has two rows")
        seen_groups.add(key)
    return problems


# ==================== Rows of the dialog ====================
def new_row(study):
    return dict(where.new_where(study), pmin_mw=None, pmax_mw=None)


def find_rows(entries, study):
    """
    The dialog's rows for entries, with the limits as the entries have them (a limit an entry
    leaves alone comes back empty).
    """
    return [dict(where.find_where(entry, study), pmin_mw=entry.get("pmin_mw"), pmax_mw=entry.get("pmax_mw")) for entry in entries]


def read_rows(rows, study):
    """(entries, problems) of the dialog's rows; a row without its group or buses, or without a limit, is a problem."""
    entries, problems = [], []
    for number, row in enumerate(rows, start=1):
        pmin_mw = clean_number(row["pmin_mw"])
        pmax_mw = clean_number(row["pmax_mw"])
        try:
            place = where.read_where(row)
        except ValueError as error:
            problems.append(f"row {number}: {error}")
            continue
        missing = where.describe_missing(row, place, "a Pmin or a Pmax" if pmin_mw is None and pmax_mw is None else "")
        if missing:
            problems.append(f"row {number} needs {missing}")
            continue
        entries.append(dict(place, pmin_mw=pmin_mw, pmax_mw=pmax_mw))
    return entries, problems


# ==================== The tab ====================
def build(study, rows, on_change):
    """The tab's content: one row per group or bus list (where, Pmin, Pmax). It edits `rows` in place."""

    def build_row(row):
        where.build_where(study, row, lambda: row_list.refresh(), placeholder="101, 102")
        ui.number(value=row["pmin_mw"], placeholder="unchanged", on_change=lambda event: row.update(pmin_mw=event.value))
        ui.number(value=row["pmax_mw"], placeholder="unchanged", on_change=lambda event: row.update(pmax_mw=event.value))

    theme.hint(HINT)
    row_list = RowList(
        rows, titles=("Generators of", "", "Pmin (MW)", "Pmax (MW)"), row_class="generator-row",
        new_row=lambda: new_row(study), build_row=build_row, on_change=on_change,
    )
