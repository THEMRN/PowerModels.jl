"""
Advanced settings: changes to the network that are used rarely, in a dialog with one tab per
kind (gui_plan.md, decision 6). They are settings["modifications"]: a list of entries per tab,
which the worker applies before the boundary and the penalties (MODIFICATIONS in worker.jl).

A tab is a module of this folder, listed in ADVANCED_TABS. It exposes:
    TITLE                           the tab's name
    KEY                             its key in settings["modifications"] and in MODIFICATIONS
    describe(entries)               one short text per entry, for the Run page
    find_problems(entries, study)   what keeps the entries from running in this study
    find_rows(entries, study)       the dialog's rows for entries
    read_rows(rows, study)          (entries, problems) of the dialog's rows
    build(study, rows, on_change)   the tab's content, which edits `rows` in place
The functions above `build` draw nothing, so they also serve where there is no dialog.
where.py is not a tab: it has what load scaling and the generators share, a row's zone, area or buses.
"""

from pathlib import Path

from nicegui import ui

import theme
from advanced import generators, load_scaling, loads

# ==================== Settings ====================
ADVANCED_TABS = [load_scaling, loads, generators]       # in the order the worker applies them


# ==================== The study the modifications are for ====================
class Study:
    """
    What the tabs know of the study in the Run form: its case, the case's `case_info`, and the
    kind of group the study uses ("zone", "area", or None for a case without groups). A study is
    by zone or by area, never both (decision 11), so a tab offers groups of that kind only.
    """

    def __init__(self, case, case_info, group_kind):
        self.case = case
        self.case_info = case_info or {}
        self.group_kind = group_kind

    @property
    def groups(self):
        """The case's groups of the study's kind: index, name, buses, load_mw."""
        return [] if self.group_kind is None else self.case_info.get(f"{self.group_kind}s", [])

    @property
    def loads(self):
        """The case's loads: id, bus, pd_mw, qd_mvar, status."""
        return self.case_info.get("loads", [])

    def find_group_options(self):
        return {group["name"]: f"{group['name']}  ({group['buses']} buses, {group['load_mw']:g} MW)" for group in self.groups}

    def match_group(self, name):
        """The group's name as the case writes it, for a name in any case; None when the case has no such group."""
        wanted = str(name).strip().lower()
        for group in self.groups:
            if group["name"].strip().lower() == wanted:
                return group["name"]
        return None

    def describe_group_kind(self):
        """Why a group of another kind does not fit, and what to choose: "this study is by area, so choose an area"."""
        if self.group_kind is None:
            return "this case has no zones or areas"
        return f"this study is by {self.group_kind}, so choose {'an' if self.group_kind == 'area' else 'a'} {self.group_kind}"

    def find_load(self, load_id):
        for load in self.loads:
            if load["id"] == load_id:
                return load
        return None

    def find_load_buses(self):
        return {load["bus"] for load in self.loads}

    def find_gen_buses(self):
        return {gen["bus"] for gen in self.case_info.get("gens", [])}


# ==================== What the modifications say ====================
def find_entries(modifications, tab):
    return modifications.get(tab.KEY) or []


def count_entries(modifications):
    """How many modifications are active: every entry of every tab."""
    return sum(len(find_entries(modifications, tab)) for tab in ADVANCED_TABS)


def describe(modifications):
    """One short text per active modification, in the order they are applied."""
    texts = []
    for tab in ADVANCED_TABS:
        texts.extend(tab.describe(find_entries(modifications, tab)))
    return texts


def find_problems(modifications, study):
    """What keeps the modifications from running in this study, each named by its tab; empty when they can be sent."""
    problems = []
    known_keys = [tab.KEY for tab in ADVANCED_TABS]
    for key in modifications:
        if key not in known_keys:
            problems.append(f'"{key}" is not a kind of modification')
    for tab in ADVANCED_TABS:
        for problem in tab.find_problems(find_entries(modifications, tab), study):
            problems.append(f"{tab.TITLE.lower()}: {problem}")
    return problems


def format_problems(problems):
    return "\n".join(f"• {problem}" for problem in problems)


# ==================== The dialog ====================
class AdvancedDialog:
    """
    One dialog of a browser tab. `open(modifications, study)` shows a copy of the modifications
    as rows to edit; Apply checks the rows and hands the new modifications to `on_apply`, and
    Cancel, the close button and Escape leave them as they were.
    """

    def __init__(self, on_apply):
        self.on_apply = on_apply
        self.study = None
        self.rows = {}              # tab key -> the rows being edited
        self.tabs = {}              # tab key -> its tab element, which shows the count of rows
        self.tab = ADVANCED_TABS[0].KEY
        self.dialog, box = theme.dialog()
        self.dialog.props("no-backdrop-dismiss")        # a click beside the dialog would lose what was typed
        box.classes("medium")
        with box:
            with theme.toolbar():
                ui.label("Advanced settings").classes("dialog-title")
                self.subtitle = theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close).tooltip("Close without applying")
            self.body = ui.element("div").classes("advanced-body")
            self.problems = ui.label("").classes("problems")
            with ui.element("div").classes("dialog-foot"):
                theme.button("Clear all", kind="ghost", on_click=self._clear).tooltip("Remove every row of every tab")
                ui.element("div").classes("grow")
                theme.button("Cancel", on_click=self.dialog.close)
                theme.button("Apply", kind="primary", on_click=self._apply)

    def open(self, modifications, study):
        """Show the modifications of the Run form for editing, with what does not fit the study as it is now."""
        self.study = study
        self.rows = {tab.KEY: tab.find_rows(find_entries(modifications, tab), study) for tab in ADVANCED_TABS}
        self.subtitle.text = f"Changes to the network of {Path(study.case).name}, made at the start of a run"
        self.problems.text = format_problems(find_problems(modifications, study))
        with_rows = [key for key, rows in self.rows.items() if rows]
        if with_rows and self.tab not in with_rows:
            self.tab = with_rows[0]
        self._build()
        self.dialog.open()

    def _build(self):
        self.body.clear()
        self.tabs = {}
        with self.body:
            with ui.tabs(value=self.tab, on_change=self._tab_changed).classes("dialog-tabs w-full") as tabs:
                for tab in ADVANCED_TABS:
                    self.tabs[tab.KEY] = ui.tab(tab.KEY, label=tab.TITLE)
            with ui.tab_panels(tabs, value=self.tab, animated=False).classes("w-full"):
                for tab in ADVANCED_TABS:
                    with ui.tab_panel(tab.KEY), ui.element("div").classes("tab-body"):
                        tab.build(self.study, self.rows[tab.KEY], self._show_counts)
        self._show_counts()

    def _tab_changed(self, event):
        if event.value in self.rows:
            self.tab = event.value

    def _show_counts(self):
        """Each tab's name with its number of rows, so the tabs that change something stand out."""
        for tab in ADVANCED_TABS:
            count = len(self.rows[tab.KEY])
            self.tabs[tab.KEY].props["label"] = f"{tab.TITLE} ({count})" if count else tab.TITLE
            self.tabs[tab.KEY].update()

    def _clear(self):
        for rows in self.rows.values():
            rows.clear()
        self.problems.text = ""
        self._build()

    def _apply(self):
        modifications = {}
        problems = []
        for tab in ADVANCED_TABS:
            entries, tab_problems = tab.read_rows(self.rows[tab.KEY], self.study)
            if not tab_problems:            # rows that could not be read would only add follow-on problems
                tab_problems = tab.find_problems(entries, self.study)
            problems.extend(f"{tab.TITLE.lower()}: {problem}" for problem in tab_problems)
            if entries:
                modifications[tab.KEY] = entries
        self.problems.text = format_problems(problems)
        if problems:
            return
        self.on_apply(modifications)
        self.dialog.close()
