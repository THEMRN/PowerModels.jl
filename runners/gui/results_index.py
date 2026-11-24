"""
The runs in results/psse, for the History page. Nothing here draws, so the functions can be
checked without a browser.

A run is one row:
- a **settings file** (`settings_<timestamp>.json`, written by run_islanding since phase 3, by
  the GUI and by islanding.jl alike) is a row with everything the run recorded. A file still
  "started" is a run that never finished: it failed, was stopped, or is running now. A GUI run
  that finished also keeps its results (`result_<timestamp>.json`, the worker's @@result
  summary), which Load into Run shows;
- a **report** (`dynamic_channels_<timestamp>.html`) that no settings file of its folder names
  is an older run, from before the settings files. Its case, objective and tag come from the
  folder's name, its simulator from the files written beside it. A folder's `run_info.json`
  belongs to the folder's last run, so it is shown with the newest older row only when that run
  wrote it.

The results folder of a run is `<case>_<objective>[_<tag>]` (calc_output_path in worker.jl).
"""

import json
import re
from datetime import datetime
from pathlib import Path, PureWindowsPath

from settings import GROUP_KINDS, OBJECTIVES, default_settings, describe_penalty_row, upgrade_settings

# ==================== Settings ====================
RESULTS_DIR = Path("results") / "psse"           # relative to the repo root
CASES_DIR = Path("cases") / "psse"
SETTINGS_FILE = re.compile(r"settings_(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})\.json")
REPORT_FILE = re.compile(r"dynamic_channels_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.html")
RUN_INFO_LAG = 1800                 # s: a run_info.json written this long or less before a report belongs to its run
SIMULATOR_LABELS = {"andes": "ANDES", "psse": "PSS®E"}
STATUS_LABELS = {"finished": "finished", "started": "incomplete", "running": "running", "older": "no settings"}
NO_VALUE = "–"


# ==================== Small parts ====================
def format_number(value):
    """A number as the record has it, shortest form: 2.5, 500, 0.01; "–" for none."""
    if value is None:
        return NO_VALUE
    return f"{value:g}" if isinstance(value, float) else str(value)


def stamp_to_iso(match):
    """The ISO time "2026-11-21T02:15:52" of a file name stamp matched by SETTINGS_FILE or REPORT_FILE."""
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}"


def format_time(iso):
    """"2026-11-21 02:15" from an ISO time."""
    return iso[:16].replace("T", " ") if iso else NO_VALUE


def find_case_names(repo_root):
    """Names of the case folders under cases/psse, longest first (to read a results folder's name)."""
    folder = Path(repo_root) / CASES_DIR
    names = [path.name for path in folder.iterdir() if path.is_dir()] if folder.is_dir() else []
    return sorted(names, key=len, reverse=True)


def split_folder_name(folder_name, case_names):
    """
    (case, objective, tag) of a results folder named `<case>_<objective>[_<tag>]`. The case is
    the longest known case name the folder starts with; without one, the objective found first
    from the left splits the name. Parts that cannot be read are "".
    """
    objectives = sorted(OBJECTIVES, key=len, reverse=True)       # "flow_shed" before "flow"

    def split_rest(rest):
        for objective in objectives:
            if rest == objective or rest.startswith(objective + "_"):
                return objective, rest[len(objective) + 1:]
        return "", rest

    for case in case_names:
        if folder_name.startswith(case + "_"):
            objective, tag = split_rest(folder_name[len(case) + 1:])
            if objective:
                return case, objective, tag
    parts = folder_name.split("_")
    for place in range(1, len(parts)):
        objective, tag = split_rest("_".join(parts[place:]))
        if objective:
            return "_".join(parts[:place]), objective, tag
    return "", "", ""


def calc_result_file_name(settings_file):
    """The name of the results a GUI run kept beside its settings file: settings_<ts>.json -> result_<ts>.json."""
    return "result_" + settings_file.removeprefix("settings_")


def calc_folder_name(run_settings):
    """The results folder a run of these settings (schema v1) writes to: `<case>_<objective>[_<tag>]`."""
    name = f"{Path(run_settings['case']).name}_{run_settings['objective']}"
    tag = (run_settings.get("output_tag") or "").strip()
    return f"{name}_{tag}" if tag else name


def find_record_case(record, repo_root):
    """The case of a settings record as the case list names it ("cases/psse/savnw"), or "" when unknown."""
    gui_settings = record.get("gui_settings")
    if gui_settings:
        return gui_settings.get("case", "")
    raw = (record.get("case_files") or {}).get("raw")
    if not raw:
        return ""
    folder = PureWindowsPath(raw).parent
    if folder.is_absolute():
        try:
            folder = folder.relative_to(PureWindowsPath(Path(repo_root)))
        except ValueError:
            return ""
    return folder.as_posix()


# ==================== What a record says ====================
def describe_boundary(record):
    """The boundary of a record: "zone Spartanb", "area LIGHTCO", "4 bus pairs"; and the group's name ("" for bus pairs)."""
    gui_settings = record.get("gui_settings")
    if gui_settings:
        boundary = gui_settings["boundary"]
        if boundary["kind"] in GROUP_KINDS:
            return f"{boundary['kind']} {boundary['name']}", boundary["name"]
        return describe_pair_count(len(boundary.get("bus_pairs", []))), ""
    for kind in GROUP_KINDS:
        name = record.get(f"target_{kind}")
        if name:
            return f"{kind} {name}", str(name)
    return describe_pair_count(len(find_bus_pairs(record.get("target_lines") or []))), ""


def describe_pair_count(count):
    """"1 bus pair", "4 bus pairs"."""
    return f"{count} bus pair" + ("" if count == 1 else "s")


def find_bus_pairs(target_lines):
    """The bus pairs of a record's target lines, each once, in the order of the lines (parallel circuits are one pair)."""
    pairs, seen = [], set()
    for line in target_lines:
        key = frozenset((int(line["from"]), int(line["to"])))
        if key in seen:
            continue
        seen.add(key)
        pairs.append([int(line["from"]), int(line["to"])])
    return pairs


def describe_penalties(record):
    """
    The load shedding penalties of a record, short, in multiples of λ: "uniform 0.01 λ",
    "zone Spartanb 2.5 λ, all but zone Spartanb 1.6 λ", "85 buses at 2.5 λ". "none set" when loads
    keep the default penalty. The rows of zones and areas come in their order, then the buses.
    """
    gui_settings = record.get("gui_settings")
    if gui_settings:
        penalties = upgrade_settings(gui_settings)["penalties"]
        if penalties.get("uniform") is not None:
            return f"uniform {format_number(penalties['uniform'])} λ"
        rows = penalties.get("rows", [])
        parts = [f"{describe_penalty_row(row)} {format_number(row['times_lambda'])} λ" for row in rows if row["kind"] != "bus"]
        bus_rows = [row for row in rows if row["kind"] == "bus"]
        if len(bus_rows) == 1:
            parts.append(f"bus {bus_rows[0]['name']} {format_number(bus_rows[0]['times_lambda'])} λ")
        elif bus_rows:
            parts.append(describe_spread(len(bus_rows), [row["times_lambda"] for row in bus_rows]))
        if penalties.get("others") is not None:
            parts.append(f"others {format_number(penalties['others'])} λ")
        return ", ".join(parts) or "none set"

    lam = record.get("lambda") or 1
    if record.get("uniform_shedding"):
        return f"uniform {format_number(round(record.get('uniform_penalty', 0) / lam, 10))} λ"
    values = [round(value / lam, 10) for value in (record.get("load_shedding_penalties") or {}).values()]
    return describe_spread(len(values), values) if values else "none set"


def describe_spread(count, values):
    """"85 buses at 2.5 λ", or "12 buses, 0.5 to 20 λ" when the values differ."""
    low, high = min(values), max(values)
    if low == high:
        return f"{count} buses at {format_number(low)} λ"
    return f"{count} buses, {format_number(low)} to {format_number(high)} λ"


def find_penalty_groups(record):
    """Names of the zones or areas a record's penalty rows name, "all but" ones too (GUI records only)."""
    gui_settings = record.get("gui_settings")
    if not gui_settings:
        return []
    return [str(row["name"]) for row in upgrade_settings(gui_settings)["penalties"].get("rows", []) if row["kind"] != "bus"]


def describe_security(frequency, voltage):
    """"frequency, voltage", "frequency", "voltage" or "–"."""
    parts = [name for name, on in (("frequency", frequency), ("voltage", voltage)) if on]
    return ", ".join(parts) or NO_VALUE


def describe_simulator(simulator, ran):
    """The simulator's name, or "not run"."""
    if not ran:
        return "not run"
    return SIMULATOR_LABELS.get(simulator, simulator or NO_VALUE)


# ==================== Rows ====================
def build_settings_row(folder, path, record, repo_root):
    """The row of a settings file."""
    match = SETTINGS_FILE.fullmatch(path.name)
    started = record.get("started") or (stamp_to_iso(match) if match else "")
    boundary, group_name = describe_boundary(record)
    summary = record.get("summary") or {}
    files = record.get("files") or {}
    report = files.get("report")
    if report and not (folder / report).exists():
        report = None
    result = calc_result_file_name(path.name)
    if not (folder / result).exists():
        result = None
    return {
        "id": f"{folder.name}/{path.name}",
        "kind": "settings",
        "folder": folder.name,
        "path": str(folder),
        "file": path.name,
        "time": started,
        "time_text": format_time(started),
        "case": record.get("case_name", ""),
        "case_path": find_record_case(record, repo_root),
        "objective": record.get("objective", ""),
        "tag": record.get("output_tag") or "",
        "boundary": boundary,
        "groups": [name for name in [group_name] + find_penalty_groups(record) if name],
        "lambda": record.get("lambda"),
        "penalties": describe_penalties(record),
        "shed_mw": summary.get("preemptive_shed_mw"),
        "solver": summary.get("termination_status") or "",      # "" for a run that did not finish
        "simulator": describe_simulator(record.get("simulator"), record.get("run_dynamic_sim")),
        "security": describe_security(record.get("frequency_security"), record.get("voltage_security")),
        "status": "finished" if record.get("status") == "finished" else "started",
        "report": report,
        "result": result,
        "from_gui": bool(record.get("gui_settings")),
        "record": record,
        "run_info": None,
    }


def find_simulator_of_report(folder, stamp):
    """"andes" or "psse": the simulator whose output files carry the report's stamp; "" when none does."""
    for path in folder.glob(f"*{stamp}*"):
        name = path.name.lower()
        if "andes" in name:
            return "andes"
        if "psse" in name:
            return "psse"
    return ""


def build_report_row(folder, path, case_names):
    """The row of a report that no settings file names: a run from before the settings files."""
    match = REPORT_FILE.fullmatch(path.name)
    time = stamp_to_iso(match)
    case, objective, tag = split_folder_name(folder.name, case_names)
    stamp = path.name[len("dynamic_channels_"):-len(".html")]
    return {
        "id": f"{folder.name}/{path.name}",
        "kind": "report",
        "folder": folder.name,
        "path": str(folder),
        "file": path.name,
        "time": time,
        "time_text": format_time(time),
        "case": case,
        "case_path": "",
        "objective": objective,
        "tag": tag,
        "boundary": NO_VALUE,
        "groups": [],
        "lambda": None,
        "penalties": NO_VALUE,
        "shed_mw": None,
        "solver": "",
        "simulator": describe_simulator(find_simulator_of_report(folder, stamp), True),
        "security": NO_VALUE,
        "status": "older",
        "report": path.name,
        "result": None,
        "from_gui": False,
        "record": None,
        "run_info": None,
    }


def add_run_info(row, info):
    """Fill an older row with what run_info.json says (the folder's last run, which is this one)."""
    row["run_info"] = info
    for kind in GROUP_KINDS:
        name = info.get(f"target_{kind}")
        if name:
            row["boundary"] = f"{kind} {name}"
            row["groups"] = [str(name)]
    if info.get("uniform_shedding"):
        row["penalties"] = f"uniform {format_number(info.get('uniform_penalty_rel'))} λ"
    elif info.get("shed_penalty_rel") is not None:
        rel = info["shed_penalty_rel"]
        text = ", ".join(format_number(value) for value in rel) if isinstance(rel, list) else format_number(rel)
        scope = f" {info['shed_penalty_scope']}" if info.get("shed_penalty_scope") else ""
        row["penalties"] = f"{text} λ{scope}"
    row["shed_mw"] = info.get("preemptive_shed_mw")
    row["security"] = describe_security(info.get("frequency_security"), info.get("voltage_security"))


def read_run_info(folder, report_path):
    """
    The folder's run_info.json when the run of this report wrote it: it is written before the
    simulation, so no more than RUN_INFO_LAG before the report, and every later run rewrites it.
    None otherwise.
    """
    info_path = folder / "run_info.json"
    if not info_path.exists():
        return None
    lag = report_path.stat().st_mtime - info_path.stat().st_mtime
    if not 0 <= lag <= RUN_INFO_LAG:
        return None
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def scan_folder(folder, case_names, repo_root):
    """The rows of one results folder, and the settings files it could not read ([(file, reason)])."""
    rows, unreadable, named = [], [], set()
    for path in sorted(folder.glob("settings_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            unreadable.append((f"{folder.name}/{path.name}", str(error)))
            continue
        row = build_settings_row(folder, path, record, repo_root)
        rows.append(row)
        if row["report"]:
            named.add(row["report"])

    older = []
    for path in sorted(folder.glob("dynamic_channels_*.html")):
        if path.name not in named and REPORT_FILE.fullmatch(path.name):
            older.append((path, build_report_row(folder, path, case_names)))
    if older:
        newest_path, newest = older[-1]
        newest_settings = max((row["time"] for row in rows), default="")
        if newest_settings < newest["time"]:
            info = read_run_info(folder, newest_path)
            if info is not None:
                add_run_info(newest, info)
    rows.extend(row for _, row in older)
    return rows, unreadable


def scan_results(repo_root):
    """
    Every run in results/psse, newest first, and the settings files that could not be read
    ([(folder/file, reason)]).
    """
    root = Path(repo_root) / RESULTS_DIR
    case_names = find_case_names(repo_root)
    rows, unreadable = [], []
    if not root.is_dir():
        return rows, unreadable
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        folder_rows, folder_unreadable = scan_folder(folder, case_names, repo_root)
        rows.extend(folder_rows)
        unreadable.extend(folder_unreadable)
    rows.sort(key=lambda row: row["time"], reverse=True)
    return rows, unreadable


def mark_running(rows, folder_name, since):
    """
    Mark as running the newest started row of `folder_name` that started at `since` (ISO) or
    later: the run this session is running now. Its settings file says "started" like a run that
    never finished.
    """
    for row in rows:                    # newest first
        if row["folder"] == folder_name and row["status"] == "started" and row["time"] >= since:
            row["status"] = "running"
            return


# ==================== Filters ====================
def filter_rows(rows, *, text="", case=None, objective=None, group=None, simulator=None, date_from="", date_to="",
                status=None, with_report=False):
    """
    The rows that pass every filter given. `text` is found in the folder's name or the tag
    (case does not matter); `group` is a zone or area name the boundary or a penalty names (case
    does not matter); `date_from` and `date_to` are "YYYY-MM-DD", both days included.
    """
    text = (text or "").strip().lower()
    group = (group or "").lower()
    shown = []
    for row in rows:
        if text and text not in row["folder"].lower() and text not in row["tag"].lower():
            continue
        if case and row["case"] != case:
            continue
        if objective and row["objective"] != objective:
            continue
        if group and group not in [name.lower() for name in row["groups"]]:
            continue
        if simulator and row["simulator"] != simulator:
            continue
        if date_from and row["time"][:10] < date_from:
            continue
        if date_to and row["time"][:10] > date_to:
            continue
        if status and row["status"] != status:
            continue
        if with_report and not row["report"]:
            continue
        shown.append(row)
    return shown


def find_choices(rows, field):
    """The values a field takes in the rows, sorted, without blanks."""
    return sorted({row[field] for row in rows if row[field] and row[field] != NO_VALUE})


def find_group_choices(rows):
    """The zone and area names the rows name, once each whatever their case, in the spelling seen most."""
    spellings = {}
    for row in rows:
        for name in row["groups"]:
            spellings.setdefault(name.lower(), []).append(name)
    return sorted((max(set(names), key=names.count) for names in spellings.values()), key=str.lower)


# ==================== Load into Run ====================
def build_settings_from_record(record, case, load_buses):
    """
    Settings (schema v1) for the Run form from a record islanding.jl (or batch_islanding.jl)
    wrote, which has no `gui_settings`: the fields run_islanding recorded. Returns (settings,
    notes), the notes saying in sentences what could not be carried over.

    - The boundary is the target zone or area, or the bus pairs of the target lines.
    - Penalties are recorded per bus in absolute units: they become bus rows in multiples of λ,
      for the buses in `load_buses` only. A penalty on a bus without a load changes nothing, and
      the form offers only buses with a load.
    - Changes a script made to the network (scale_loads!, generator limits) are not recorded.
    """
    run_settings = default_settings()
    lam = record["lambda"]
    notes = []
    run_settings.update({
        "case": case,
        "objective": record["objective"],
        "opf_model": record["opf_model"],
        "flow_model": record["flow_model"],
        "lambda": lam,
        "frequency_security": bool(record.get("frequency_security")),
        "voltage_security": bool(record.get("voltage_security")),
        "run_dynamic_sim": bool(record.get("run_dynamic_sim")),
        "simulator": record.get("simulator") or run_settings["simulator"],
        "open_report": record.get("open_report", True),         # recorded since 2026-11-21
        "html_report": record.get("html_report", False),        # recorded since 2026-11-23; unticked before, as the GUI's default
        "output_tag": record.get("output_tag") or "",
        "modifications": {},
    })

    boundary = {"kind": "bus_pairs", "name": "", "bus_pairs": find_bus_pairs(record.get("target_lines") or [])}
    for kind in GROUP_KINDS:
        if record.get(f"target_{kind}"):
            boundary = {"kind": kind, "name": str(record[f"target_{kind}"]), "bus_pairs": []}
    run_settings["boundary"] = boundary

    penalties = {"uniform": None, "rows": [], "others": None}
    if record.get("uniform_shedding"):
        penalties["uniform"] = round(record.get("uniform_penalty", 0) / lam, 10)
    else:
        left_out = 0
        for bus, value in (record.get("load_shedding_penalties") or {}).items():
            if int(bus) in load_buses:
                penalties["rows"].append({"kind": "bus", "name": int(bus), "except": False, "times_lambda": round(value / lam, 10)})
            else:
                left_out += 1
        if left_out:
            notes.append(f"The penalties of {left_out} buses without a load were left out; they changed nothing in the run.")
    run_settings["penalties"] = penalties
    notes.append("This run came from a script, so changes it made to the network (load scaling, generator limits) are not known and not in the form.")
    return run_settings, notes


def read_result(row):
    """
    The results a GUI run kept beside its settings file (result_<timestamp>.json, the worker's
    @@result summary in MW), with `files.output_path` set to where the folder is now; and "".
    When there are none: None and a sentence saying why. Read only on Load into Run, never when
    the folders are scanned.
    """
    path = Path(row["path"]) / calc_result_file_name(row["file"])
    if not path.exists():
        if not row["from_gui"]:
            return None, "A run from a script keeps no results for the GUI: its Excel and simulation reports have them."
        if row["status"] == "running":
            return None, "It is still running, so it has no results yet."
        if row["status"] != "finished":
            return None, "It did not finish, so it has no results."
        return None, "Its results were not kept: it ran before the GUI kept them."
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"Its results could not be read: {error}"
    summary["files"]["output_path"] = row["path"]
    return summary, ""
