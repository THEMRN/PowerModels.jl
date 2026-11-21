"""
Presets: named run settings kept as files, like the commented scenario blocks in islanding.jl
(gui_plan.md, phase 12). The Run page chooses, saves and deletes them (components/preset_bar.py).

A preset is one JSON file in runners/gui/presets/: the settings (schema 2) at its top level, with two
more keys, `preset` (its name, as the Run page lists it) and `note` (a line about the scenario, or
""). The form reads only the settings' own keys, so a preset file passes `validate` as it is. The
file name comes from the name; the name is what the user sees and types.

Draws nothing. `PresetStore` holds the presets for the whole app and tells every open browser tab
when one is saved or deleted.
"""

import json
import re
from pathlib import Path

from julia_worker import call_listeners
from settings import SCHEMA, upgrade_settings

# ==================== Settings ====================
PRESETS_DIR = Path(__file__).with_name("presets")
PRESET_KEYS = ("preset", "note")                # the keys of a preset file that are not settings
NAME_LENGTH = 80                                # characters a name may have
FORBIDDEN_NAME_CHARACTERS = '\\/:*?"<>|'        # not allowed in a name (Windows file names, kept for the eye too)


# ==================== Files ====================
def find_file_stem(name):
    """The file name (without .json) for a preset name: "savnw – island on top" → "savnw_island_on_top"."""
    stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return stem or "preset"


def read_preset(path):
    """
    A preset file as a dict: `key` (its file stem, which tells presets apart), `name`, `note`,
    `settings` (in the current schema, a file of schema 1 upgraded; without the preset's own keys), `path`, and `error` ("" when it could
    be read; then `settings` is None).
    """
    path = Path(path)
    preset = {"key": path.stem, "name": path.stem, "note": "", "settings": None, "path": path, "error": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        preset["error"] = f"it is not a JSON file that can be read: {error}"
        return preset
    if not isinstance(data, dict) or data.get("schema") not in (1, SCHEMA):
        preset["error"] = f"it does not hold settings of schema 1 or {SCHEMA}"
        return preset
    preset["name"] = str(data.get("preset") or path.stem)
    preset["note"] = str(data.get("note") or "")
    preset["settings"] = upgrade_settings({key: value for key, value in data.items() if key not in PRESET_KEYS})
    return preset


def list_presets(folder=PRESETS_DIR):
    """Every preset file of the folder, by name (ignoring case); an empty list without the folder."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    presets = [read_preset(path) for path in folder.glob("*.json")]
    return sorted(presets, key=lambda preset: preset["name"].lower())


def check_name(name):
    """Why a name cannot be a preset's name, or "" when it can."""
    if not name:
        return "the preset needs a name"
    if len(name) > NAME_LENGTH:
        return f"the name is longer than {NAME_LENGTH} characters"
    if any(character in FORBIDDEN_NAME_CHARACTERS for character in name):
        return f"the name cannot contain any of {FORBIDDEN_NAME_CHARACTERS}"
    return ""


def find_by_name(presets, name):
    """The preset with this name, ignoring case and spaces at the ends (two such names would be confused), or None."""
    wanted = name.strip().lower()
    for preset in presets:
        if preset["name"].strip().lower() == wanted:
            return preset
    return None


def find_free_path(folder, name, presets):
    """A file for a new preset: its name's stem, with _2, _3, ... when another preset already has that file."""
    taken = {preset["key"].lower() for preset in presets}
    stem = find_file_stem(name)
    candidate = stem
    number = 2
    while candidate.lower() in taken or (Path(folder) / f"{candidate}.json").exists():
        candidate = f"{stem}_{number}"
        number += 1
    return Path(folder) / f"{candidate}.json"


def write_preset(path, name, note, settings):
    """Write a preset file: its name and note first, then the settings (the current schema)."""
    data = {"preset": name, "note": note}
    data.update({key: value for key, value in settings.items() if key not in PRESET_KEYS})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ==================== The presets of the app ====================
class PresetStore:
    """
    The presets of the app, read from the folder when the app starts and after each change made
    through it. `on_change(listener)` is called after a save or a delete, so every browser tab
    lists the same presets. A file added or edited by hand shows after `reread()` (the Run page's
    preset list reads the folder again when a browser tab opens it).
    """

    def __init__(self, folder=PRESETS_DIR):
        self.folder = Path(folder)
        self.presets = list_presets(self.folder)
        self._listeners = []

    def on_change(self, listener):
        """Call `listener()` after the presets changed. Returns its remover."""
        self._listeners.append(listener)

        def remove():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def reread(self):
        """Read the folder again; the listeners hear of it only when the presets differ."""
        presets = list_presets(self.folder)
        changed = [(preset["key"], preset["name"], preset["note"], preset["settings"], preset["error"]) for preset in presets] != \
                  [(preset["key"], preset["name"], preset["note"], preset["settings"], preset["error"]) for preset in self.presets]
        self.presets = presets
        if changed:
            call_listeners(self._listeners)

    def find(self, key):
        """The preset with this key (file stem), or None."""
        for preset in self.presets:
            if preset["key"] == key:
                return preset
        return None

    def save(self, name, note, settings):
        """
        Save settings as a preset under a name: into the file of the preset that has the name (a
        replace), or a new file. Returns the preset as read back. Raises ValueError for a name that
        cannot be used, OSError when the file cannot be written.
        """
        name = name.strip()
        problem = check_name(name)
        if problem:
            raise ValueError(problem)
        existing = find_by_name(self.presets, name)
        path = existing["path"] if existing is not None else find_free_path(self.folder, name, self.presets)
        write_preset(path, name, note.strip(), settings)
        self.presets = list_presets(self.folder)
        call_listeners(self._listeners)
        return self.find(path.stem)

    def delete(self, key):
        """Delete the file of a listed preset (never a path typed by someone). Raises OSError when it cannot be deleted."""
        preset = self.find(key)
        if preset is None:
            return
        preset["path"].unlink(missing_ok=True)
        self.presets = list_presets(self.folder)
        call_listeners(self._listeners)
