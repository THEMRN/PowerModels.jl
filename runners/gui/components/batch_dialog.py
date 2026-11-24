"""
The batch dialog: the settings of the Run form, where a field may take several values. Every
combination of the values is one run, and Add puts them all in the run queue, each with a tag
of its own. What may take a list, how the runs are made and what keeps them from running is
batch.py's business; this is its form.

The fields are those batch_islanding.jl sweeps (objective, OPF model, flow penalty, λ, target
zone or area, load shedding penalties) and the load scaling factors of the network
modifications. The target and the penalties are set here in full: the targets are ticked, and
the penalty rows start as the form's and can be added, changed and removed, each with a list of
values. A penalty row may be for the target itself, so that in each run it is on that run's
target, and "paired" takes the penalty lists together by position instead of in every
combination. Everything else is the form's, the same in every run.
"""

import copy
from pathlib import Path

from nicegui import ui

import advanced
import batch
import theme
from advanced import where
from components.row_list import RowList
from settings import FLOW_MODELS, GROUP_KINDS, OBJECTIVES, OPF_MODELS

# ==================== Settings ====================
CHOICE_NAMES = {"objective": "objective", "opf_model": "OPF model", "flow_model": "flow penalty"}
KIND_LABELS = {"zone": "Zone", "area": "Area", "bus": "Bus"}
EXCEPT_MARK = "!"               # a penalty row's kind in its list: "zone", "!zone" (all but the zone) or "bus", as in the Run form
TARGET_KIND = "target"          # and here "target", "!target": the row is for each run's target, or for all but it
VALUES_HINT = (
    "Every combination of the values below is one run in the queue; penalties that are paired go "
    "together. A list of numbers has commas between them, and first:step:last is a range: "
    "1, 2.5, 4 or 1:0.5:3."
)
LAMBDA_HINT = (
    "The penalties are multiples of λ, so in flow_shed a list of λ alone changes the solution "
    "little or not at all. What moves the trade-off there is a penalty."
)
TARGET_HINT = "A penalty row stays on the {kind} it names. A row for the target {kind} is on each run's own target."
PENALTY_HINT = (
    "Rows count from the top down: where rows reach the same load, the lower row counts. "
    "All other loads are those no row reaches; empty is the default."
)
PAIRED_HINT = (
    "Paired: the lists go together by position, the first values in one run, the second in the "
    "next. Every list has the same number of values, or one value for every run."
)
NOTHING_VARIES = "nothing varies"


def find_row_kind(row):
    """
    (kind, is_except) of a penalty row of the dialog, from its choice in the kind list: "zone",
    "!zone", "bus", or "target" and "!target" for a row on each run's target.
    """
    key = row["key"]
    return key.removeprefix(EXCEPT_MARK), key.startswith(EXCEPT_MARK)


class BatchDialog:
    """
    One dialog of a browser tab. `open(settings, study)` shows the form's settings with a list
    for each field that may vary; Add hands the runs' settings and whether they go to the Compare
    page to `on_add(settings_list, compare)`.
    """

    def __init__(self, on_add):
        self.on_add = on_add
        self.settings = None            # the form's settings, the same in every run but for the lists
        self.study = None               # the study they are for: its groups and loads, and what the modifications are checked against
        self.runs = []                  # the runs of the batch as it stands (batch.expand_batch)
        self.choices = {}               # field -> {value: its checkbox}
        self.lists = {}                 # field, or (field, position) -> (name, its input)
        self.penalty_rows = []          # the penalty rows being edited: {"key", "name", "values"}, values as typed
        self.dialog, box = theme.dialog()
        self.dialog.props("no-backdrop-dismiss")        # a click beside the dialog would lose what was typed
        with box:
            with theme.toolbar():
                ui.label("Batch run").classes("dialog-title")
                self.subtitle = theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close)
            self.body = ui.element("div").classes("batch-body")
            self.problems = ui.label("").classes("problems")
            with ui.element("div").classes("dialog-foot"):
                self.count = theme.hint()
                ui.element("div").classes("grow")
                theme.button("Cancel", on_click=self.dialog.close)
                self.add_button = theme.button("Add to the queue", kind="primary", on_click=self._add)

    def open(self, settings, study):
        """
        Show a batch that starts as the one run of `settings`, for the study in the Run form. The
        settings have no problems, except that a zone or area boundary may still be without its
        zone or area: the targets are ticked here.
        """
        self.settings = settings
        self.study = study
        self.subtitle.text = f"{Path(settings['case']).name}, from the settings in the form"
        self._build()
        self._update()
        self.dialog.open()

    # -------------------- layout --------------------
    def _build(self):
        settings = self.settings
        spec = batch.find_base_spec(settings)
        kind = settings["boundary"]["kind"]
        scalings = batch.find_scalings(settings)
        self.choices = {}
        self.lists = {}
        self.body.clear()
        with self.body:
            theme.hint(VALUES_HINT)
            with ui.element("div").classes("batch-sides"):
                # left: what may vary
                with ui.element("div").classes("batch-side"):
                    with theme.fields().classes("batch-fields"):
                        self._build_choices("Objective", "objective", OBJECTIVES, spec["objective"])
                        self._build_choices("OPF model", "opf_model", OPF_MODELS, spec["opf_model"])
                        self._build_choices("Flow penalty", "flow_model", FLOW_MODELS, spec["flow_model"])
                        self._build_list("Flow weight λ", "lambda", spec["lambda"], hint=LAMBDA_HINT)
                        if kind in GROUP_KINDS:
                            names = [group["name"] for group in self.study.groups]
                            self._build_choices(f"Target {kind}", "target", names, spec["target"], hint=TARGET_HINT.format(kind=kind))

                    self._build_penalties()

                    if scalings:
                        theme.eyebrow("Load scaling factors")
                        with theme.fields().classes("batch-fields"):
                            for position, entry in enumerate(scalings):
                                label = f"Loads {where.describe_of(entry)}"
                                self._build_list(label, ("load_scaling", position), spec["load_scaling"][position])

                # right: the runs that come of it
                with ui.element("div").classes("batch-side"):
                    with theme.fields().classes("batch-fields"):
                        theme.label("Tag starts with")
                        self.tag = ui.input(value=settings["output_tag"] or batch.DEFAULT_TAG, on_change=self._update)
                        self.tag.props("debounce=300")
                        theme.label("When a run ends")
                        with theme.stack():
                            self.open_report = ui.checkbox("open its report", value=False)
                            with self.open_report:
                                self.open_report_tooltip = ui.tooltip()     # why it is off, when it is
                            self.compare = ui.checkbox("add it to the Compare page", value=True)
                    self._show_report_choice()
                    theme.eyebrow("Runs")

                    @ui.refreshable
                    def run_list():
                        self._build_run_list()

                    self.run_list = run_list
                    run_list()

    def _build_choices(self, label, field, options, chosen, hint=""):
        """A field with a few options: one checkbox per option, those of the form's value ticked."""
        chosen = {str(value).lower() for value in chosen}
        theme.label(label)
        self.choices[field] = {}
        with theme.stack():
            with ui.element("div").classes("batch-choices"):
                for option in options:
                    self.choices[field][option] = ui.checkbox(
                        str(option), value=str(option).lower() in chosen, on_change=self._update
                    )
            if hint:
                theme.hint(hint)

    def _build_list(self, label, key, values, hint="", placeholder=""):
        """A field that takes a list of numbers, starting with the form's value."""
        theme.label(label)
        with theme.stack():
            field = ui.input(value=batch.format_values(values), placeholder=placeholder, on_change=self._update)
            field.props("debounce=300")
            if hint:
                theme.hint(hint)
        self.lists[key] = (label, field)

    # -------------------- load shedding penalties --------------------
    def _find_penalty_kinds(self):
        """
        What a penalty row may be: the study's kind of group, all but one of them, or a bus, as in
        the Run form; and with a zone or area boundary the target of each run, or all but it.
        """
        group_kind = self.study.group_kind
        target_kind = self.settings["boundary"]["kind"]
        kinds = {}
        if group_kind is not None:
            kinds[group_kind] = KIND_LABELS[group_kind]
            kinds[EXCEPT_MARK + group_kind] = f"All but {group_kind}"
        if target_kind in GROUP_KINDS:
            kinds[TARGET_KIND] = f"Target {target_kind}"
            kinds[EXCEPT_MARK + TARGET_KIND] = f"All but target {target_kind}"
        kinds["bus"] = KIND_LABELS["bus"]
        return kinds

    def _describe_row(self, number, row):
        """A penalty row of the dialog as its problems name it: "penalty row 2 (zone SECOND)", "penalty row 1 (target zone)"."""
        where_text = self._find_penalty_kinds()[row["key"]].lower()
        if find_row_kind(row)[0] == TARGET_KIND:
            return f"penalty row {number} ({where_text})"
        if row["name"] in (None, ""):
            return f"penalty row {number}"
        return f"penalty row {number} ({where_text} {row['name']})"

    def _find_penalty_rows(self):
        """The dialog's rows for the form's penalty rows: where each applies, and its value as the start of its list."""
        kinds = self._find_penalty_kinds()
        rows = []
        for row in self.settings["penalties"].get("rows", []):
            key = (EXCEPT_MARK if row.get("except") else "") + row["kind"]
            if key not in kinds:
                continue
            name = row["name"] if row["kind"] == "bus" else self.study.match_group(row["name"])
            rows.append({"key": key, "name": name, "values": batch.format_values([row["times_lambda"]])})
        return rows

    def _build_penalties(self):
        """
        The penalties of the batch: one value list for every load (uniform), or rows as in the Run
        form, each with a list of values, and a list for all other loads. They start as the form's.
        """
        penalties = self.settings["penalties"]
        is_uniform = penalties.get("uniform") is not None
        self.penalty_rows = self._find_penalty_rows()
        with ui.element("div").classes("batch-head"):
            theme.eyebrow("LOAD SHEDDING PENALTIES, × λ").classes("exact")      # as typed: capitals would turn λ into Λ
            with ui.element("div").classes("batch-choices"):
                self.paired = ui.checkbox("paired", value=False, on_change=self._penalty_mode_changed)
                self.uniform = ui.checkbox("uniform", value=is_uniform, on_change=self._penalty_mode_changed)
        with theme.fields().classes("batch-fields") as self.uniform_box:
            theme.label("Every load")
            self.uniform_values = ui.input(
                value=batch.format_values([penalties.get("uniform")]), on_change=self._update
            ).props("debounce=300")
        with theme.stack() as self.rows_box:
            self.row_list = RowList(
                self.penalty_rows,
                titles=("Where", "", "Values"),
                row_class="batch-penalty-row",
                new_row=lambda: {"key": next(iter(self._find_penalty_kinds())), "name": None, "values": ""},
                build_row=self._build_penalty_row,
                on_change=self._update,
            )
            with ui.element("div").classes("edit-row batch-penalty-row"):
                theme.label("All other loads").classes("wide")
                self.others = ui.input(
                    value=batch.format_values([penalties.get("others")]), placeholder="default", on_change=self._update
                ).props("debounce=300")
            theme.hint(PENALTY_HINT)
            self.paired_hint = theme.hint(PAIRED_HINT)
        self._show_penalties()

    def _build_penalty_row(self, row):
        """One penalty row: its kind, the zone, area or bus (the target needs none), and its list of values."""
        kind, _is_except = find_row_kind(row)
        kind_select = ui.select(
            self._find_penalty_kinds(),
            value=row["key"],
            on_change=lambda event: self._penalty_kind_changed(row, event.value),
        )
        if kind == TARGET_KIND:
            kind_select.classes("wide")         # nothing to choose beside it: the row is on each run's target
        else:
            names = self.study.find_load_bus_options() if kind == "bus" else self.study.find_group_options()
            if row["name"] not in names:
                row["name"] = None
            ui.select(names, value=row["name"], with_input=True, on_change=lambda event: self._penalty_changed(row, name=event.value))
        ui.input(value=row["values"], on_change=lambda event: self._penalty_changed(row, values=event.value)).props(
            "debounce=300"
        )

    def _penalty_changed(self, row, **values):
        row.update(values)
        self._update()

    def _penalty_kind_changed(self, row, key):
        """A row's kind chosen: its zone or area stays (also behind a target row, which shows none), to a bus or back it goes."""
        was_bus = find_row_kind(row)[0] == "bus"
        is_bus = key.removeprefix(EXCEPT_MARK) == "bus"
        if was_bus != is_bus:
            row["name"] = None
        row["key"] = key
        self.row_list.refresh()
        self._update()

    def _penalty_mode_changed(self, _event=None):
        self._show_penalties()
        self._update()

    def _show_penalties(self):
        """The one list of uniform shedding, or the rows: only one of the two counts, and only rows can be paired."""
        is_uniform = bool(self.uniform.value)
        self.uniform_box.set_visibility(is_uniform)
        self.rows_box.set_visibility(not is_uniform)
        self.paired.set_visibility(not is_uniform)
        self.paired_hint.set_visibility(bool(self.paired.value))

    # -------------------- the runs --------------------
    def _show_report_choice(self):
        """
        Only the ANDES script can leave its report closed, and a run without a simulation, or whose
        form left "HTML file" unticked, has none (the runs keep the form's `html_report`).
        """
        settings = self.settings
        if not settings["run_dynamic_sim"]:
            self.open_report.disable()
            self.open_report_tooltip.text = "No dynamic simulation, so no report"
        elif settings["simulator"] != "andes":
            self.open_report.set_value(True)
            self.open_report.disable()
            self.open_report_tooltip.text = "PSS®E always opens its report"
        elif not settings.get("html_report", False):
            self.open_report.disable()
            self.open_report_tooltip.text = "No HTML report: \"HTML file\" is unticked in the Run form"
        else:
            self.open_report_tooltip.set_visibility(False)

    def _build_run_list(self):
        if not self.runs:
            return
        rows = [
            {"number": number, "varied": run["varied"] or NOTHING_VARIES, "folder": run["folder"]}
            for number, run in enumerate(self.runs, start=1)
        ]
        with ui.element("div").classes("table-scroll batch-runs"):
            theme.data_table([("Run", "number", 0), ("What it has", "varied", None), ("Results folder", "folder", None)], rows)

    # -------------------- reading the form --------------------
    def _read_values(self, label, text, problems, needed=True, unique=True):
        """
        The numbers of a list field; a list that cannot be read, or is empty when one is needed, is
        a problem. With `unique` off a number written twice stays twice (a paired list).
        """
        try:
            values = batch.parse_values(text, unique)
        except ValueError as error:
            problems.append(f"{label}: {error}")
            return []
        if not values and needed:
            problems.append(f"{label} needs a value")
        return values

    def _read_penalties(self, problems, targets):
        """
        (penalties, spec) of the dialog's penalties: the settings' `penalties` with the first value
        of every list, and the lists themselves as batch.py reads them ("uniform", or
        "penalty_rows" and "others", with which rows follow the target and whether the lists are
        paired). A row that follows the target is written for the first of `targets`, the
        targets ticked; batch.py gives it each run's own.
        """
        if self.uniform.value:
            values = self._read_values("Every load", self.uniform_values.value, problems)
            return {"uniform": values[0] if values else None, "rows": [], "others": None}, {"uniform": values}

        is_paired = bool(self.paired.value)
        rows, row_values, follows = [], [], []
        counts = []                     # (list, how many values it has), for the paired lists
        for number, row in enumerate(self.penalty_rows, start=1):
            kind, is_except = find_row_kind(row)
            follows_target = kind == TARGET_KIND
            label = self._describe_row(number, row)
            missing = []                # what a row left half filled still needs
            if not follows_target and row["name"] in (None, ""):
                missing.append(f"{'an' if kind == 'area' else 'a'} {kind}")
            if not (row["values"] or "").strip():
                missing.append("a value")
            if missing:
                problems.append(f"{label} needs {' and '.join(missing)}")
                continue
            values = self._read_values(label, row["values"], problems, unique=not is_paired)
            if not values:
                continue
            is_bus = kind == "bus"
            if follows_target:
                kind, name = self.settings["boundary"]["kind"], targets[0] if targets else ""
            else:
                name = int(row["name"]) if is_bus else str(row["name"])
            rows.append({"kind": kind, "name": name, "except": is_except and not is_bus, "times_lambda": values[0]})
            row_values.append(values)
            follows.append(follows_target)
            counts.append((label, len(values)))
        others = self._read_values("All other loads", self.others.value, problems, needed=False, unique=not is_paired) or [None]
        counts.append(("all other loads", len(others)))

        # paired lists go together by position, so those with more than one value have the same number
        if is_paired and len({count for _label, count in counts if count > 1}) > 1:
            has = ", ".join(f"{label} has {count}" for label, count in counts if count > 1)
            problems.append(f"paired lists need the same number of values, or one value: {has}")
        spec = {"penalty_rows": row_values, "others": others, "penalty_paired": is_paired, "penalty_follows": follows}
        return {"uniform": None, "rows": rows, "others": others[0]}, spec

    def _read(self):
        """
        (settings, spec, problems) of the dialog: the settings every run starts from (the form's,
        with the dialog's penalties), the batch as batch.py reads it, and what could not be read.
        """
        spec, problems = {}, []
        for field, boxes in self.choices.items():
            spec[field] = [option for option, box in boxes.items() if box.value]
            if not spec[field]:
                name = f"target {self.settings['boundary']['kind']}" if field == "target" else CHOICE_NAMES[field]
                problems.append(f"choose at least one {name}")

        scalings = {}
        for key, (label, field) in self.lists.items():
            values = self._read_values(label, field.value, problems)
            if isinstance(key, tuple):
                scalings[key[1]] = values
            else:
                spec[key] = values
        spec["load_scaling"] = [scalings[position] for position in sorted(scalings)]

        settings = copy.deepcopy(self.settings)
        settings["penalties"], penalty_spec = self._read_penalties(problems, spec.get("target") or [])
        spec.update(penalty_spec)
        return settings, spec, problems

    def _check_modifications(self, run_settings):
        """The problems of a run's network modifications, named as the Run page names them."""
        return [f"Advanced, {problem}" for problem in advanced.find_problems(run_settings["modifications"], self.study)]

    def _update(self, _event=None):
        """Read the fields, make the runs, and show them with what keeps them from running."""
        settings, spec, problems = self._read()
        self.runs = []
        if not problems:
            try:
                self.runs = batch.expand_batch(settings, spec, (self.tag.value or "").strip())
            except ValueError as error:
                problems.append(str(error))
        if self.runs:
            if self.open_report.enabled:
                for run in self.runs:
                    run["settings"]["open_report"] = bool(self.open_report.value)
            problems.extend(batch.find_problems(self.runs, self._check_modifications))

        count = len(self.runs)
        self.problems.text = "\n".join(f"• {problem}" for problem in problems)
        self.count.text = f"{count} run" + ("" if count == 1 else "s") if count else ""
        self.add_button.text = f"Add {count} run" + ("" if count == 1 else "s") + " to the queue" if count else "Add to the queue"
        self.add_button.set_enabled(bool(self.runs) and not problems)
        self.run_list.refresh()

    # -------------------- actions --------------------
    def _add(self):
        self._update()                  # a value typed just before the click
        if not self.runs or self.problems.text:
            return
        self.on_add([run["settings"] for run in self.runs], bool(self.compare.value))
        self.dialog.close()
