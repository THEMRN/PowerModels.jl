"""
Advanced settings, tab "Load scaling": multiply the P and Q of the loads of a zone or an area, or
of the loads at a list of buses, by a factor (`scale_loads!` in utils.jl).

Entries of settings["modifications"]["load_scaling"], applied in the order of the list:
    {"kind": "zone" | "area", "name": "SPARTANB", "factor": 0.7}
    {"kind": "buses", "buses": [3005, 3007, 3008, 153], "factor": 1.6}
"""

from nicegui import ui

import theme
from advanced import where
from components.row_list import RowList
from settings import clean_number, format_value, is_number

# ==================== Settings ====================
TITLE = "Load scaling"
KEY = "load_scaling"
HINT = "Multiplies the P and Q of every load in the group, or at the buses listed. A factor of 0.7 leaves 70 % of the load."


# ==================== What the entries say ====================
def describe(entries):
    """One short text per entry: "loads of zone SPARTANB × 0.7"."""
    return [f"loads {where.describe_of(entry)} × {format_value(entry.get('factor'))}" for entry in entries]


def find_problems(entries, study):
    """What keeps the entries from running in this study (its case, its kind of group)."""
    problems = []
    seen_groups = set()
    for entry in entries:
        place = where.describe_where(entry)
        factor = entry.get("factor")
        if not is_number(factor) or factor < 0:
            problems.append(f"the factor of {place} must be zero or more")
        problems.extend(where.find_where_problems(entry, study, study.find_load_buses(), "load"))
        key = where.find_group_key(entry)
        if key is not None and key in seen_groups:
            problems.append(f"{place} has two rows")
        seen_groups.add(key)
    return problems


# ==================== Rows of the dialog ====================
def new_row(study):
    return dict(where.new_where(study), factor=None)


def find_rows(entries, study):
    """The dialog's rows for entries; a group that does not fit the study comes back to be chosen again."""
    return [dict(where.find_where(entry, study), factor=entry.get("factor")) for entry in entries]


def read_rows(rows, study):
    """(entries, problems) of the dialog's rows; a row left half filled is a problem."""
    entries, problems = [], []
    for number, row in enumerate(rows, start=1):
        factor = clean_number(row["factor"])
        try:
            place = where.read_where(row)
        except ValueError as error:
            problems.append(f"row {number}: {error}")
            continue
        missing = where.describe_missing(row, place, "a factor" if factor is None else "")
        if missing:
            problems.append(f"row {number} needs {missing}")
            continue
        entries.append(dict(place, factor=factor))
    return entries, problems


# ==================== The tab ====================
def build(study, rows, on_change):
    """The tab's content: one row per scaling (where, factor). It edits `rows` in place."""

    def build_row(row):
        where.build_where(study, row, lambda: row_list.refresh(), placeholder="3005, 3007, 3008")
        ui.number(value=row["factor"], min=0, on_change=lambda event: row.update(factor=event.value))

    theme.hint(HINT)
    row_list = RowList(
        rows, titles=("Loads of", "", "Factor"), row_class="scaling-row",
        new_row=lambda: new_row(study), build_row=build_row, on_change=on_change,
    )
