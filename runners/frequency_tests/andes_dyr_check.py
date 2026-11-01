"""
Independent check of read_dyr_machine_data (frequency.jl): ANDES reads the same .dyr with its
own parser, and its inertia (M = 2H), governor droop R and machine base are compared with the
values Julia read for every online unit.

    python andes_dyr_check.py <raw> <dyr> <machines.json>

Writes dyr_check_<case>.json next to machines.json (written by 1_offline.jl).
"""

import sys
import json
import logging
from pathlib import Path

import andes

GOVERNOR_MODELS = ("TGOV1", "HYGOV", "GAST")  # ANDES governors with a permanent droop R
TOLERANCE = 1e-9

raw_file, dyr_file, machines_file = sys.argv[1:4]
machines_file = Path(machines_file)

andes.config_logger(stream_level=logging.ERROR)
ss = andes.load(raw_file, addfile=dyr_file, setup=False, no_output=True, default_config=True, autogen_stale=False)

# machine id of each static generator (PV or Slack)
gen_ids = {}
for static_model in (ss.PV, ss.Slack):
    for idx, machine_id in zip(static_model.idx.v, static_model.subidx.v):
        gen_ids[idx] = str(machine_id).strip()

# inertia and machine base per (bus, id), from the synchronous machine models
andes_units = {}
unit_of_machine = {}
for model_name in ("GENROU", "GENCLS"):  # ANDES reads GENSAL as GENROU
    model = getattr(ss, model_name)
    for idx, bus, gen, M, Sn in zip(model.idx.v, model.bus.v, model.gen.v, model.M.v, model.Sn.v):
        key = (int(bus), gen_ids[gen])
        andes_units[key] = {"H": M / 2, "mbase": Sn, "R": None, "governor": None}
        unit_of_machine[idx] = key

# governor droop per unit
for model_name in GOVERNOR_MODELS:
    model = getattr(ss, model_name)
    for machine, R in zip(model.syn.v, model.R.v):
        andes_units[unit_of_machine[machine]]["R"] = R
        andes_units[unit_of_machine[machine]]["governor"] = model_name


def same_value(a, b):
    """Both missing, or both present and equal within TOLERANCE."""
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < TOLERANCE


with open(machines_file) as f:
    julia_units = json.load(f)["units"]

rows = []
for unit in julia_units:
    andes_unit = andes_units.get((unit["bus"], unit["id"]), {})
    rows.append(
        {
            "bus": unit["bus"],
            "id": unit["id"],
            "H_julia": unit["H"],
            "H_andes": andes_unit.get("H"),
            "R_julia": unit["R"],
            "R_andes": andes_unit.get("R"),
            "mbase_julia": unit["mbase"],
            "mbase_andes": andes_unit.get("mbase"),
            "governor_andes": andes_unit.get("governor"),
            "H_match": same_value(unit["H"], andes_unit.get("H")),
            "R_match": same_value(unit["R"], andes_unit.get("R")),
            "mbase_match": same_value(unit["mbase"], andes_unit.get("mbase")),
        }
    )

mismatches = [row for row in rows if not (row["H_match"] and row["R_match"] and row["mbase_match"])]
case_name = machines_file.stem.replace("machines_", "")
output_file = machines_file.parent / f"dyr_check_{case_name}.json"
with open(output_file, "w") as f:
    json.dump({"case": case_name, "units": rows, "mismatches": len(mismatches)}, f)

print(f"{case_name}: ANDES and Julia agree on H, R and machine base for {len(rows) - len(mismatches)} of {len(rows)} online units")
for row in mismatches:
    print(f"   mismatch: {row}")
