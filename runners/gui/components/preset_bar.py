"""
The presets in the Run page's settings toolbar (gui_plan.md, phase 12): a list to choose a preset,
whose settings then go into the form; a "changed" mark with Reload while the form differs from
the preset; Save as and Delete, each with its dialog. The files are presets.py's business.
"""

import copy

from nicegui import ui

import theme
from presets import check_name, find_by_name

# ==================== Settings ====================
CHECK_SECONDS = 1.0             # how often the form is compared with the preset it came from, while one is chosen


class PresetBar:
    """
    The presets of one browser tab. Build it inside the settings toolbar, after the fold button.
    `on_loaded()` is called after a preset went into the form (the page unfolds the sheet),
    `on_choice()` whenever the chosen preset may have changed (the page shows its note, `find_note()`),
    and `update_buttons()` is for the page to call whenever the form starts or stops waiting.
    """

    def __init__(self, ctx, form, on_loaded, on_choice):
        self.ctx = ctx
        self.store = ctx.presets
        self.form = form
        self.on_loaded = on_loaded
        self.on_choice = lambda: None       # the page's own, once the bar is built (the page builds its text after it)
        self.chosen = None              # key of the preset the form came from
        self.snapshot = None            # the form's settings right after the preset went in (None while it waits for Julia)
        self.setting = False            # the list is being set from code: its handler stays quiet

        theme.label("Preset").classes("preset-label")
        # no tooltip on the list: it would cover the first preset while the list is open
        self.select = ui.select({}, on_change=self._chosen).classes("field-preset")
        self.changed = theme.hint("changed").classes("preset-changed")
        self.reload_button = theme.button("Reload", kind="ghost", small=True, on_click=self._reload, busy=True)
        self.reload_button.tooltip("The form differs from this preset: put the preset's settings back")
        self.save_button = theme.button("Save as", kind="ghost", on_click=self._open_save)
        self.save_button.tooltip("Keep the settings in the form as a preset")
        self.delete_button = theme.button("Delete", kind="ghost", on_click=self._open_delete)
        self.delete_button.tooltip("Delete the chosen preset")
        with theme.offstage():
            self.timer = ui.timer(CHECK_SECONDS, self._check_changed, active=False)
            self._build_save_dialog()
            self._build_delete_dialog()

        self.store.reread()             # a file added or edited by hand shows in a newly opened browser tab
        self._show_presets()
        remove = self.store.on_change(self._show_presets)
        ui.context.client.on_delete(remove)
        self.on_choice = on_choice

    # -------------------- the list --------------------
    def _show_presets(self):
        """List the presets; a chosen preset that is gone is no longer chosen."""
        options = {}
        for preset in self.store.presets:
            options[preset["key"]] = preset["name"] + (" (cannot be read)" if preset["error"] else "")
        if self.chosen not in options:
            self.chosen = None
            self.snapshot = None
        self.setting = True
        try:
            self.select.set_options(options, value=self.chosen)
        finally:
            self.setting = False
        self.update_buttons()

    def _show_choice(self):
        """The list shows the preset the form came from (after a refused choice, it goes back to it)."""
        self.setting = True
        try:
            self.select.set_value(self.chosen)
        finally:
            self.setting = False

    def find_note(self):
        """The note of the chosen preset, or ""."""
        preset = self.store.find(self.chosen) if self.chosen is not None else None
        return preset["note"] if preset is not None else ""

    def update_buttons(self):
        """What the bar offers now: Save as while the form is not waiting, Delete with a preset chosen; the page hears of the choice."""
        preset = self.store.find(self.chosen) if self.chosen is not None else None
        self.delete_button.set_enabled(preset is not None)
        self.save_button.set_enabled(self.form.cases_loaded and not self.form.is_waiting())
        self.timer.active = preset is not None
        if preset is None:
            self._show_changed(False)
        self.on_choice()

    # -------------------- choosing --------------------
    def _find_refusal(self, preset):
        """Why a preset cannot go into the form now, or ""."""
        if preset is None:
            return "This preset is gone."
        if preset["error"]:
            return f"The preset {preset['name']} cannot be read: {preset['error']}"
        if not self.form.cases_loaded:
            return "The Run form is not ready yet: Julia has not given the case list."
        case = preset["settings"].get("case")
        if case not in (self.ctx.state.get("cases") or []):
            return f"The case {case} of the preset {preset['name']} is not in cases/psse."
        return ""

    async def _chosen(self, event):
        if self.setting or event.value is None:
            return
        await self._load(self.store.find(event.value))

    async def _reload(self):
        await self._load(self.store.find(self.chosen))

    async def _load(self, preset):
        """Put a preset's settings into the form; the bar remembers what the form held right after, to see changes."""
        refusal = self._find_refusal(preset)
        if refusal:
            ui.notify(refusal, position="top", type="warning")
            self._show_choice()
            return
        key = preset["key"]
        self.chosen = key
        self.snapshot = None
        self._show_changed(False)
        self.update_buttons()
        filled = await self.form.write(copy.deepcopy(preset["settings"]))
        if self.chosen != key:              # another preset was chosen meanwhile
            return
        if filled:
            self.snapshot = self.form.read()[0]
            self.on_loaded()
            note = f" {preset['note']}" if preset["note"] else ""
            ui.notify(f"The preset “{preset['name']}” is in the form.{note}", position="top")
        elif self.form.retry is not None:
            ui.notify("Julia stopped before it read the case: the preset goes into the form once Julia is back.", position="top")
        else:                               # the form went on to another case
            self.chosen = None
            self._show_choice()
        self.update_buttons()

    # -------------------- changed --------------------
    def _check_changed(self):
        """Compare the form with what it held right after the preset went in; the form's own waits are not changes."""
        if self.chosen is None or self.form.is_waiting():
            return
        settings = self.form.read()[0]
        if self.snapshot is None:           # the preset went in after a wait for Julia
            self.snapshot = settings
        self._show_changed(settings != self.snapshot)

    def _show_changed(self, changed):
        self.changed.set_visibility(changed)
        self.reload_button.set_visibility(changed)

    # -------------------- Save as --------------------
    def _build_save_dialog(self):
        self.save_dialog, box = theme.dialog()
        self.save_dialog.props("no-backdrop-dismiss")      # a click beside it would lose what was typed
        box.classes("narrow")
        with box:
            with theme.toolbar():
                ui.label("Save as a preset").classes("dialog-title")
                self.save_subtitle = theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.save_dialog.close).tooltip("Close without saving")
            with ui.element("div").classes("dialog-form"):
                with theme.fields():
                    theme.label("Name")
                    self.name_input = ui.input(placeholder="savnw – island on top", on_change=self._name_changed)
                    theme.label("Note")
                    self.note_input = ui.textarea(placeholder="what the scenario is, in a line (optional)")
                self.name_hint = theme.hint()
            self.save_problems = ui.label("").classes("problems")
            with ui.element("div").classes("dialog-foot"):
                ui.element("div").classes("grow")
                theme.button("Cancel", on_click=self.save_dialog.close)
                self.save_confirm = theme.button("Save", kind="primary", on_click=self._save)

    def _open_save(self):
        """The dialog starts from the chosen preset's name and note, so saving it again is Save as and Replace."""
        if not self.form.cases_loaded or self.form.is_waiting():
            ui.notify("The form is waiting for Julia: save once it has read the case.", position="top")
            return
        preset = self.store.find(self.chosen) if self.chosen is not None else None
        self.name_input.set_value(preset["name"] if preset is not None else "")
        self.note_input.set_value(preset["note"] if preset is not None else "")
        settings, problems = self.form.read()
        self.save_subtitle.text = f"{settings['case'].split('/')[-1]} · {len(self.store.presets)} presets in runners/gui/presets"
        self.save_problems.text = "\n".join(["These settings cannot run, so they are not saved as a preset:"] + [f"• {problem}" for problem in problems]) if problems else ""
        self._name_changed()
        self.save_dialog.open()

    def _name_changed(self, _event=None):
        """Save becomes Replace for the name of a preset that exists; a name that cannot be used says why."""
        name = (self.name_input.value or "").strip()
        existing = find_by_name(self.store.presets, name) if name else None
        problem = check_name(name) if name else ""
        if problem:
            theme.show_hint(self.name_hint, problem, bad=True)
        elif existing is not None:
            theme.show_hint(self.name_hint, f"A preset with this name exists ({existing['path'].name}): Replace overwrites it.")
        else:
            theme.show_hint(self.name_hint, "")
        self.save_confirm.text = "Replace" if existing is not None else "Save"
        self.save_confirm.set_enabled(bool(name) and not problem and not self.save_problems.text)

    def _save(self):
        if self.form.is_waiting():
            return
        settings, problems = self.form.read()
        if problems:
            self.save_problems.text = "\n".join(["These settings cannot run, so they are not saved as a preset:"] + [f"• {problem}" for problem in problems])
            self._name_changed()
            return
        try:
            preset = self.store.save(self.name_input.value or "", self.note_input.value or "", settings)
        except ValueError as error:
            theme.show_hint(self.name_hint, str(error), bad=True)
            return
        except OSError as error:
            self.save_problems.text = f"The preset file could not be written: {error}"
            return
        self.chosen = preset["key"]
        self.snapshot = settings
        self._show_choice()
        self._show_changed(False)
        self.update_buttons()
        self.save_dialog.close()
        ui.notify(f"Saved as the preset “{preset['name']}” ({preset['path'].name}).", position="top")

    # -------------------- Delete --------------------
    def _build_delete_dialog(self):
        self.delete_dialog, box = theme.dialog()
        box.classes("narrow")
        with box:
            with theme.toolbar():
                ui.label("Delete a preset").classes("dialog-title")
                theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.delete_dialog.close).tooltip("Close without deleting")
            with ui.element("div").classes("dialog-form"):
                self.delete_text = ui.label()
                theme.hint("Runs made with it keep their own settings, in their results folders.")
            with ui.element("div").classes("dialog-foot"):
                ui.element("div").classes("grow")
                theme.button("Cancel", on_click=self.delete_dialog.close)
                theme.button("Delete", kind="danger", on_click=self._delete)

    def _open_delete(self):
        preset = self.store.find(self.chosen) if self.chosen is not None else None
        if preset is None:
            return
        self.delete_key = preset["key"]
        self.delete_text.text = f"Delete the preset “{preset['name']}”? Its file runners/gui/presets/{preset['path'].name} goes."
        self.delete_dialog.open()

    def _delete(self):
        preset = self.store.find(self.delete_key)
        self.delete_dialog.close()
        if preset is None:
            return
        try:
            self.store.delete(preset["key"])
        except OSError as error:
            ui.notify(f"The preset file could not be deleted: {error}", position="top", type="negative")
            return
        ui.notify(f"The preset “{preset['name']}” was deleted.", position="top")
