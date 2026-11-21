"""
Advanced settings: where a row applies. Load scaling and the generator settings both name a zone
or an area of the study's kind, or a list of buses. This module has what the two tabs share:
that part of an entry, its words, its problems, and its two fields in a row of the dialog.

    {"kind": "zone" | "area", "name": "SPARTANB", ...}
    {"kind": "buses", "buses": [3005, 3007, 3008, 153], ...}
"""

import re

from nicegui import ui

from settings import GROUP_KINDS

# ==================== Settings ====================
KIND_LABELS = {"zone": "Zone", "area": "Area", "buses": "Buses"}
BUSES_NAMED = 5                 # a description names up to this many buses, and counts them beyond it


# ==================== Bus lists ====================
def parse_buses(text):
    """Bus numbers of a text like "3005, 3007 3008" (commas, semicolons, spaces or brackets between them). Raises ValueError."""
    buses = []
    for item in re.split(r"[\s,;\[\]]+", text or ""):
        if not item:
            continue
        if not item.isdigit():
            raise ValueError(f'"{item}" is not a bus number')
        if int(item) not in buses:
            buses.append(int(item))
    return buses


def format_buses(buses):
    return ", ".join(str(bus) for bus in buses)


# ==================== What an entry says ====================
def describe_where(entry):
    """Where an entry applies: "zone SPARTANB", "buses 3005, 3007", or "12 buses"."""
    if entry.get("kind") == "buses":
        buses = entry.get("buses") or []
        if len(buses) > BUSES_NAMED:
            return f"{len(buses)} buses"
        return ("bus " if len(buses) == 1 else "buses ") + format_buses(buses)
    return f"{entry.get('kind')} {entry.get('name')}"


def describe_of(entry):
    """The same with its preposition: "of zone SPARTANB", "at buses 3005, 3007"."""
    return ("at " if entry.get("kind") == "buses" else "of ") + describe_where(entry)


def find_where_problems(entry, study, buses_with, thing):
    """
    What keeps an entry's zone, area or buses from fitting this study. `buses_with` are the buses
    of the case that have a `thing` ("load", "generator"); a listed bus without one is a problem.
    """
    kind = entry.get("kind")
    where = describe_where(entry)
    if kind == "buses":
        buses = entry.get("buses") or []
        if not buses:
            return ["a row by buses needs at least one bus"]
        without = [bus for bus in buses if bus not in buses_with]
        if without:
            return [f"no {thing} at {'bus' if len(without) == 1 else 'buses'} {format_buses(without)}"]
        return []
    if kind not in GROUP_KINDS:
        return [f'"{kind}" is not a zone, an area or buses']
    if kind != study.group_kind:
        instead = ", so list buses" if study.group_kind is None else " or buses"
        return [f"{where}: {study.describe_group_kind()}{instead}"]
    if study.match_group(entry.get("name")) is None:
        return [f"{where} is not in the case"]
    return []


def find_group_key(entry):
    """What tells two rows on the same zone or area apart from two on different ones; None for a bus list."""
    if entry.get("kind") == "buses":
        return None
    return (entry.get("kind"), str(entry.get("name")).lower())


# ==================== Rows of the dialog ====================
def find_kinds(study):
    """Kinds a row may have: the study's kind of group when the case has one, and a bus list."""
    kinds = {} if study.group_kind is None else {study.group_kind: KIND_LABELS[study.group_kind]}
    kinds["buses"] = KIND_LABELS["buses"]
    return kinds


def new_where(study):
    """The "where" fields of a new row: the first kind on offer, nothing chosen."""
    return {"kind": next(iter(find_kinds(study))), "name": None, "buses_text": ""}


def find_where(entry, study):
    """
    The "where" fields of a row for an entry. A group of the kind this study does not use, or one
    the case does not have, comes back without a group, which has to be chosen again.
    """
    row = new_where(study)
    if entry.get("kind") == "buses":
        row["kind"] = "buses"
        row["buses_text"] = format_buses(entry.get("buses") or [])
    elif entry.get("kind") == study.group_kind:
        row["name"] = study.match_group(entry.get("name"))
    return row


def read_where(row):
    """
    The "where" part of an entry from a row's fields, or None while nothing is chosen or listed.
    Raises ValueError for a bus list that cannot be read.
    """
    if row["kind"] == "buses":
        buses = parse_buses(row["buses_text"])
        return {"kind": "buses", "buses": buses} if buses else None
    return {"kind": row["kind"], "name": row["name"]} if row["name"] else None


def describe_missing(row, place, value_missing):
    """
    What a row still needs, or "" when it is complete: its "where" ("bus numbers", "a zone", "an
    area") while `place` (from read_where) is None, and `value_missing` (such as "a factor"; ""
    when the values are there).
    """
    needs = []
    if place is None:
        needs.append("bus numbers" if row["kind"] == "buses" else f"{'an' if row['kind'] == 'area' else 'a'} {row['kind']}")
    if value_missing:
        needs.append(value_missing)
    return " and ".join(needs)


def build_where(study, row, refresh, placeholder):
    """The two "where" fields of a row: the kind, then the group or the bus list. `refresh` draws the rows again."""

    def change_kind(kind):
        row.update(kind=kind, name=None, buses_text="")
        refresh()

    ui.select(find_kinds(study), value=row["kind"], on_change=lambda event: change_kind(event.value))
    if row["kind"] == "buses":
        ui.input(value=row["buses_text"], placeholder=placeholder, on_change=lambda event: row.update(buses_text=event.value))
    else:
        ui.select(study.find_group_options(), value=row["name"], with_input=True, on_change=lambda event: row.update(name=event.value))
