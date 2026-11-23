"""
Run page: a toolbar (fold, presets, Advanced, Batch, Queue, Stop and Run), the network modifications
that are active, the settings sheet with its four sections, the results of a run as tables, the
runs of this session and, fixed to the bottom of the window, the status strip of the run in progress.

Julia does one run at a time. While a run is in progress, Run puts the form's settings in the
run queue (`ctx.queue`, run_queue.py), which starts them when that run ends; Batch puts several
runs there at once, and Queue shows the runs that wait.

The form holds settings schema v1 (settings.py). Zones, areas and load buses come from Julia's
`case_info`, cached for the session in `ctx.state`, because the worker answers one job at a time
and a question asked during a run would wait for the run to end.
"""

from pathlib import Path

from nicegui import background_tasks, ui

import advanced
import theme
from components.batch_dialog import BatchDialog
from components.log_dialog import LogDialog
from components.preset_bar import PresetBar
from components.queue_dialog import QueueDialog
from components.results_view import ResultsView, open_folder, open_report
from components.status_strip import StatusStrip
from comparison import find_refusal
from julia_worker import JobError, WorkerError
from settings import (
    FLOW_MODELS,
    GROUP_KINDS,
    OBJECTIVES,
    OPF_MODELS,
    SIMULATORS,
    build_settings,
    default_settings,
    describe_missing_target,
    form_values,
    validate,
)

# ==================== Settings ====================
TITLE = "Run"
ERROR_PREVIEW = 140  # characters of an error message shown in a row (the tooltip has all of it)
KIND_LABELS = {"zone": "Zone", "area": "Area", "bus_pairs": "Bus pairs", "bus": "Bus"}
EXCEPT_MARK = "!"  # a penalty row's kind in the form's list: "zone", "!zone" (all but the zone) or "bus"
SIMULATOR_LABELS = {"andes": "ANDES", "psse": "PSS®E"}
OBJECTIVE_READS = {  # objective -> the parts of the form it reads (src/core/objective.jl); the others are dimmed
    "opf": set(),
    "flow": {"flow_model"},
    "flow_shed": {"flow_model", "lambda", "penalties"},
    "opf_shed": {"lambda", "penalties"},  # λ as the unit of the penalties
}
FLOW_PENALTIES = {  # flow model -> the flow penalty over the boundary lines: (AC, DC, which has no q)
    "squared": ("Σp² + Σq²", "Σp²"),
    "abs_sum": ("|Σp| + |Σq|", "|Σp|"),
    "combined": ("|Σp| + Σq²", "|Σp|"),
}
SHED_PENALTY = "Σ c·Pd·(1 − z)"


def match_option(options, value):
    """The option equal to `value`, ignoring case for names (a zone typed as "spartanb"), or None."""
    if value in options:
        return value
    wanted = str(value).strip().lower()
    for option in options:
        if str(option).strip().lower() == wanted:
            return option
    return None


def find_row_key(row):
    """A penalty row's choice in the kind list: "zone", "!zone" for all but the zone, or "bus"."""
    return (EXCEPT_MARK if row.get("except") else "") + row["kind"]


def is_same_target(row, other):
    """True when two penalty rows are for the same place (same kind, name and "all but"), names in any case."""
    return find_row_key(row) == find_row_key(other) and str(row["name"]).lower() == str(other["name"]).lower()


def describe_boundary(run_settings):
    """A run's boundary in a few words: "zone SPARTANB", or "4 bus pairs"."""
    boundary = run_settings["boundary"]
    if boundary["kind"] == "bus_pairs":
        count = len(boundary["bus_pairs"])
        return f"{count} bus pair" + ("" if count == 1 else "s") if count else "no bus pairs"
    return f"{boundary['kind']} {boundary['name']}" if boundary["name"] else f"no {boundary['kind']}"


def find_run_block(ctx, form):
    """
    Why Run (and Batch) cannot take the form's settings now, as the tooltip says it, or "" when
    it can. A run in progress does not block it: the new run waits in the queue. A run sent while
    Julia is busy with a question waits for it.
    """
    if ctx.worker.state in ("stopped", "crashed"):
        return "Julia is not running: Restart Julia first"
    if not form.cases_loaded:
        return "Waiting for Julia's case list"
    if form.is_waiting():
        return "Waiting for Julia to read the case"
    return ""


def is_run_queued(ctx):
    """True when a click on Run puts the run in the queue instead of starting it: a run is in progress, or runs wait and will start by themselves."""
    return ctx.runs.find_running() is not None or ctx.queue.is_active()


def describe_waiting(count):
    """ "1 run waits", "3 runs wait"."""
    return f"{count} run" + (" waits" if count == 1 else "s wait")


def describe_queue_button(queue):
    """The Queue button's text: how many runs wait, and that the queue is paused."""
    count = len(queue.entries)
    if not count:
        return "Queue"
    return f"Queue ({count}, paused)" if queue.paused else f"Queue ({count})"


def find_runs_signature(ctx):
    """What the runs table shows of each run; it is built again only when this changes, not at every stage of a run."""
    signature = []
    for record in ctx.runs.records:
        files = (record["summary"] or {}).get("files") or {}
        signature.append(
            (
                record["number"],
                record["status"],
                record["error"],
                record["seconds"],
                files.get("report"),
                files.get("output_path"),
            )
        )
    return signature


def describe_settings(run_settings):
    """The settings on one line, for the toolbar while the sheet is folded: case, objective, model, boundary, λ."""
    parts = [Path(run_settings["case"]).name or "no case", run_settings["objective"], run_settings["opf_model"]]
    parts.append(describe_boundary(run_settings))
    if run_settings["lambda"] is not None:
        parts.append(f"λ {run_settings['lambda']:g}")
    if run_settings["output_tag"]:
        parts.append(f"tag {run_settings['output_tag']}")
    return "  ·  ".join(parts)


# ==================== The settings form ====================
class RunForm:
    """
    The settings sheet and its four sections. `read()` gives the settings in the form with the problems that keep
    them from running, `write()` fills the form from settings, and `load_cases()` fills the case
    list and the first settings.

    While it waits for Julia (the case list, a case's zones, areas and loads) the hint under the
    case says for what, the settings below it are greyed out and `is_waiting()` is true; a read
    that Julia did not answer (Stop, Restart Julia) is made again when Julia is ready (`retry`).
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.cases_loaded = False
        self.loading_cases = False
        self.case_list_error = ""  # why there is no case list
        self.loaded_case = None  # case whose zones, areas and loads the form offers
        self.case_info = {}  # its case_info ({} while unknown or unreadable)
        self.case_error = ""  # why the case could not be read
        self.reading = None  # case whose case_info is being asked from Julia
        self.retry = None  # a read Julia did not answer, to make again once it is ready (an async function)
        self.on_wait = None  # called when the form starts or stops waiting (the Run button follows it)
        self.penalty_signature = None  # what the penalty rows were last built from
        self.penalty_rows = (
            []
        )  # [{"kind": "zone" | "area" | "bus", "name", "except", "times_lambda"}], in the order they apply
        self.modifications = {}  # network modifications, as in the settings; the advanced dialog edits them
        self.on_modifications = None  # called when the modifications, or the study they are for, may have changed
        self.writing = False  # write() is filling the form: change handlers stay quiet
        self.updating = False  # update_view() is running

    # -------------------- layout --------------------
    def build(self):
        with theme.sheet():
            with theme.Section("Case and model"), theme.fields():
                theme.label("Case")
                with theme.stack():
                    with theme.line():
                        self.case = ui.select({}, on_change=self._case_changed).classes("grow")
                        theme.button(icon="refresh", kind="ghost", on_click=self.reload_cases, busy=True)
                    self.case_message = theme.hint()
                theme.label("Objective")
                with theme.stack():
                    self.objective = ui.select(OBJECTIVES, value="flow_shed", on_change=self._changed)
                theme.label("OPF model")
                self.opf_model = ui.toggle(OPF_MODELS, value="AC", on_change=self._changed)
                self.flow_model_label = theme.label("Flow penalty")
                self.flow_model = ui.select(FLOW_MODELS, value="squared", on_change=self._changed)
                self.lam_label = theme.label("Flow weight λ")
                self.lam = ui.number(value=500, min=0)

            with theme.Section("Boundary") as boundary_section:
                with theme.fields():
                    theme.label("Select by")
                    self.boundary_kind = ui.toggle(
                        {"bus_pairs": KIND_LABELS["bus_pairs"]}, value="bus_pairs", on_change=self._changed
                    )
                    self.boundary_label = theme.label(KIND_LABELS["bus_pairs"])
                    with theme.stack():
                        self.boundary_name = ui.select({}, with_input=True)
                        self.bus_pairs = ui.textarea(placeholder="154-3008, 154-153")
                self.boundary_hint = theme.hint()

            with theme.Section("Load shedding penalties") as penalties:
                self.penalties_section = penalties
                with penalties.head:
                    self.uniform = ui.checkbox("uniform", on_change=self._changed).tooltip("One penalty for every load")
                with theme.fields() as self.uniform_box:
                    theme.label("Every load")
                    self.uniform_value = ui.number(min=0, suffix="× λ")
                with theme.stack() as self.penalty_box:
                    with ui.element("div").classes("penalty-row"):
                        theme.eyebrow("Where").classes("wide")
                        theme.eyebrow("× λ").classes("exact")

                    @ui.refreshable
                    def penalty_list():
                        self._build_penalty_rows()

                    self.penalty_list = penalty_list
                    penalty_list()
                    with theme.line():
                        theme.button("Add row", icon="plus", kind="ghost", small=True, on_click=self._add_penalty_row)
                    with ui.element("div").classes("penalty-row"):
                        theme.label("All other loads").classes("wide")
                        self.others = ui.number(min=0, placeholder="default").tooltip(
                            "Empty: the default, 1e4 as it is, not a multiple of λ"
                        )
                    theme.hint(
                        "Rows count from the top down: where rows reach the same load, the lower row counts. "
                        "All other loads are those no row reaches."
                    )

            with theme.Section("Security and simulation") as security_section:
                with theme.stack():
                    self.frequency_security = ui.checkbox("Frequency security")
                    self.voltage_security = ui.checkbox("Voltage security")
                    self.run_dynamic_sim = ui.checkbox("Dynamic simulation", value=True, on_change=self._changed)
                with theme.fields():
                    theme.label("Simulator")
                    self.simulator = ui.toggle(
                        {name: SIMULATOR_LABELS[name] for name in SIMULATORS}, value="andes", on_change=self._changed
                    )
                    theme.label("Report")
                    self.open_report = ui.checkbox("open when done", value=True)
                    with self.open_report:
                        self.open_report_tooltip = ui.tooltip()
                    theme.label("Output tag")
                    self.output_tag = ui.input(placeholder="none").tooltip("Added to the name of the results folder")
                self.dyr_message = theme.hint()
        # what greys out while the form waits for Julia: all but the case itself, which may still be changed
        self.waiting_parts = [
            self.objective,
            self.opf_model,
            self.flow_model,
            self.lam,
            boundary_section,
            penalties,
            security_section,
        ]
        self.update_view()  # before any case is read: only what needs no case is shown
        self._show_wait()

    def _build_penalty_rows(self):
        """
        One line per penalty row: kind, zone, area or bus, the penalty in multiples of λ, the arrows
        that move it up and down (the order is the order the rows apply in), and a remove button.
        """
        kinds = self._find_penalty_kinds()
        self.penalty_signature = self._find_penalty_signature()
        last = len(self.penalty_rows) - 1
        for position, row in enumerate(self.penalty_rows):
            names = self._find_bus_options() if row["kind"] == "bus" else self._find_group_options(row["kind"])
            row["name"] = match_option(names, row["name"]) if row["name"] is not None else None
            with ui.element("div").classes("penalty-row"):
                ui.select(
                    kinds,
                    value=find_row_key(row),
                    on_change=lambda event, row=row: self._penalty_kind_changed(row, event.value),
                )
                ui.select(
                    names,
                    value=row["name"],
                    with_input=True,
                    on_change=lambda event, row=row: row.update(name=event.value),
                )
                ui.number(
                    value=row["times_lambda"],
                    min=0,
                    on_change=lambda event, row=row: row.update(times_lambda=event.value),
                )
                with ui.element("div").classes("move-buttons"):
                    up = theme.button(
                        icon="chevron_up",
                        kind="ghost",
                        small=True,
                        on_click=lambda row=row: self._move_penalty_row(row, -1),
                    )
                    up.set_enabled(position > 0)
                    down = theme.button(
                        icon="chevron_down",
                        kind="ghost",
                        small=True,
                        on_click=lambda row=row: self._move_penalty_row(row, 1),
                    )
                    down.set_enabled(position < last)
                theme.button(
                    icon="close", kind="ghost", small=True, on_click=lambda row=row: self._remove_penalty_row(row)
                ).tooltip("Remove this row")

    # -------------------- what the case offers --------------------
    def _find_groups(self, kind):
        """The case's zones or areas (index, name, buses, load_mw); empty when it has fewer than two."""
        return self.case_info.get(f"{kind}s", [])

    def _find_group_options(self, kind):
        return {
            group["name"]: f"{group['name']}  ({group['buses']} buses, {group['load_mw']:g} MW)"
            for group in self._find_groups(kind)
        }

    def _find_bus_options(self):
        """Load buses of the case with their in-service load: {bus: "bus  (MW)"}."""
        load_by_bus = {}
        for load in self.case_info.get("loads", []):
            if load["status"] == 0:
                continue
            load_by_bus[load["bus"]] = load_by_bus.get(load["bus"], 0.0) + load["pd_mw"]
        return {bus: f"{bus}  ({load_by_bus[bus]:g} MW)" for bus in sorted(load_by_bus)}

    def _find_penalty_group_kind(self):
        """
        Kind of group a penalty row may name: the boundary's kind, and with bus pairs the kind the
        case uses (zones before areas), as find_group_kind in utils.jl. A study is by zone or by
        area, never both.
        """
        if self.boundary_kind.value in GROUP_KINDS:
            return self.boundary_kind.value
        for kind in GROUP_KINDS:
            if self._find_groups(kind):
                return kind
        return None

    def _find_penalty_kinds(self):
        """What a penalty row may be: the study's kind of group, all but one of them, or a bus (keys as find_row_key)."""
        group_kind = self._find_penalty_group_kind()
        kinds = {}
        if group_kind is not None:
            kinds[group_kind] = KIND_LABELS[group_kind]
            kinds[EXCEPT_MARK + group_kind] = f"All but {group_kind}"
        kinds["bus"] = KIND_LABELS["bus"]
        return kinds

    def find_study(self):
        """The study the network modifications are for: the case in the form and its kind of group."""
        return advanced.Study(self.loaded_case, self.case_info, self._find_penalty_group_kind())

    def set_modifications(self, modifications):
        self.modifications = modifications
        self._show_modifications()

    def _show_modifications(self):
        if self.on_modifications is not None:
            self.on_modifications()

    # -------------------- change handlers --------------------
    def _changed(self, _event=None):
        if not self.writing:
            self.update_view()

    def _case_changed(self, event):
        if self.writing or event.value is None or event.value == self.loaded_case:
            return
        background_tasks.create(self._switch_case(event.value), name="switch case")

    def _penalty_kind_changed(self, row, key):
        """A row's kind chosen: between a zone and all but a zone the name stays, to a bus or back it goes."""
        kind = key.removeprefix(EXCEPT_MARK)
        if kind != row["kind"]:
            row["name"] = None
        row["kind"] = kind
        row["except"] = key.startswith(EXCEPT_MARK)
        self.penalty_list.refresh()

    def _add_penalty_row(self):
        """A new row at the bottom, where it counts over the rows above it."""
        self.penalty_rows.append(
            {"kind": next(iter(self._find_penalty_kinds())), "name": None, "except": False, "times_lambda": None}
        )
        self.penalty_list.refresh()

    def _remove_penalty_row(self, row):
        self.penalty_rows.remove(row)
        self.penalty_list.refresh()

    def _move_penalty_row(self, row, step):
        """Move a penalty row one place up (step -1) or down (+1), which changes the row that counts where two reach the same load."""
        position = next(
            place for place, other in enumerate(self.penalty_rows) if other is row
        )  # by identity: two rows may hold the same values
        new_position = position + step
        if not 0 <= new_position < len(self.penalty_rows):
            return
        rows = self.penalty_rows
        rows[position], rows[new_position] = rows[new_position], rows[position]
        self.penalty_list.refresh()

    # -------------------- cases --------------------
    async def load_cases(self):
        """Fill the case list from Julia (kept for the session), then the form: the last run's settings, or the defaults."""
        if self.cases_loaded or self.loading_cases:
            return
        self.loading_cases = True
        self.case_list_error = ""
        self._show_wait()
        try:
            if "cases" not in self.ctx.state:
                reply = await self.ctx.worker.request({"type": "list_cases"})
                self.ctx.state["cases"] = reply["cases"]
        except WorkerError as error:
            self.case_list_error = str(error)
            return
        finally:
            self.loading_cases = False
            self._show_wait()

        cases = self.ctx.state["cases"]
        self.case.set_options({case: Path(case).name for case in cases})
        self.cases_loaded = True  # the form waits on, for its first case (write)
        first_settings = default_settings()
        if self.ctx.runs.records:
            first_settings = self.ctx.runs.records[-1]["settings"]
        elif first_settings["case"] not in cases and cases:
            first_settings["case"] = cases[0]
        await self.write(first_settings)

    async def reload_cases(self):
        """Forget what was read from Julia and read it again, keeping the form's values."""
        run_settings, _ = self.read()
        self.ctx.state.pop("cases", None)
        self.ctx.state.pop("case_infos", None)
        self.ctx.state.pop("networks", None)
        self.cases_loaded = False
        self.retry = None
        await self.load_cases()
        if self.cases_loaded and run_settings["case"]:
            await self.write(run_settings)

    def is_unanswered(self, case):
        """
        True when Julia stopped before it answered for the case (Stop, Restart Julia, a crash): the
        read is to be made again once Julia is back. An answer is the case's information, or why
        it cannot be read.
        """
        answered = case in self.ctx.state.get("case_infos", {})
        return not answered and self.ctx.worker.state in ("stopped", "crashed", "starting")

    async def find_case_info(self, case):
        """
        (case_info, error message) of a case, from the session's cache or from Julia. While Julia
        reads it the form waits, and the hint under the case says so; the History and Network
        pages ask through here too, so their wait shows on the Run page they go to.
        """
        cache = self.ctx.state.setdefault("case_infos", {})
        if case in cache:
            return cache[case]
        self.reading = case
        self._show_wait()
        try:
            cache[case] = (await self.ctx.worker.request({"type": "case_info", "case": case}), "")
        except JobError as error:  # Julia could not read the case: that stays true until the file changes
            cache[case] = ({}, str(error))
        except WorkerError as error:  # Julia is not running: ask again next time
            return {}, f"Julia did not answer: {error}"
        finally:
            if self.reading == case:  # a newer read shows its own wait
                self.reading = None
            self._show_wait()
        return cache[case]

    async def _switch_case(self, case):
        """The user chose another case: offer its zones, areas and buses, and drop what named the old case."""
        self.loaded_case = case
        self.retry = None
        case_info, case_error = await self.find_case_info(case)
        if case != self.loaded_case:  # another case was chosen meanwhile
            return
        if self.is_unanswered(case):  # read it again once Julia is back
            self.retry = lambda: self._switch_case(case)
        self.case_info, self.case_error = case_info, case_error
        self.writing = True
        try:
            self.boundary_name.set_value(None)
            self.bus_pairs.set_value("")
            self.penalty_rows = []
        finally:
            self.writing = False
        if self.modifications:  # they named the loads and groups of the other case
            self.modifications = {}
            with self.case:
                ui.notify("The network modifications were for the other case and were removed.", position="top")
        self.update_view()

    def _show_case_message(self, message, error=False, waiting=False):
        theme.show_hint(self.case_message, message, bad=error, waiting=waiting)

    # -------------------- waiting for Julia --------------------
    def is_waiting(self):
        """True while the form waits for Julia: for the case list, or for a case's zones, areas and loads."""
        return not self.cases_loaded or self.reading is not None or self.retry is not None

    def _describe_wait(self):
        """
        What the form waits for, as the hint under the case says it (one short line, so the fields
        below do not move); "" when it waits for nothing that will come.
        """
        worker = self.ctx.worker
        if worker.state in ("stopped", "crashed"):
            return ""  # nothing comes until Julia is restarted: the error says so
        if not self.cases_loaded:
            if self.case_list_error and worker.state != "starting":
                return ""
            what = "the case list"
        elif self.reading is not None or self.retry is not None:
            what = Path(self.reading or self.loaded_case or "").name or "the case"
        else:
            return ""
        if worker.state == "starting":
            return "waiting for Julia to start..."
        running = self.ctx.runs.find_running()
        if running is not None:
            return f"waiting for run {running['number']} to end..."
        return f"reading {what}..."

    def _show_wait(self):
        """Show whether the form waits: the hint under the case, the greyed settings, and (`on_wait`) the Run button."""
        theme.grey_out(self.waiting_parts, self.is_waiting())
        self._update_case_message()
        if self.on_wait is not None:
            self.on_wait()

    def julia_changed(self):
        """Julia's state or the runs changed: say what the form waits for now, and make a read Julia did not answer again."""
        if self.ctx.worker.state == "ready" and self.retry is not None and self.reading is None:
            retry, self.retry = self.retry, None
            background_tasks.create(retry(), name="read the case again")
        self._show_wait()

    # -------------------- settings <-> form --------------------
    def read(self):
        """The settings in the form (schema v1) and the problems that keep them from running."""
        form = {
            "case": self.case.value,
            "objective": self.objective.value,
            "opf_model": self.opf_model.value,
            "flow_model": self.flow_model.value,
            "lambda": self.lam.value,
            "boundary_kind": self.boundary_kind.value,
            "boundary_name": self.boundary_name.value,
            "bus_pairs_text": self.bus_pairs.value,
            "uniform": self.uniform.value,
            "uniform_value": self.uniform_value.value,
            "penalty_rows": self.penalty_rows,
            "others": self.others.value,
            "frequency_security": self.frequency_security.value,
            "voltage_security": self.voltage_security.value,
            "run_dynamic_sim": self.run_dynamic_sim.value,
            "simulator": self.simulator.value,
            "open_report": (
                self.open_report.value if self.open_report.enabled else True
            ),  # greyed: PSS®E opens it anyway, or no report
            "output_tag": self.output_tag.value,
            "modifications": self.modifications,
        }
        run_settings, problems = build_settings(form)
        if self.case_error:
            problems.append(f"the case could not be read: {self.case_error}")
        if not problems:  # a form that could not be read would only add follow-on problems
            problems.extend(validate(run_settings))
            for problem in advanced.find_problems(run_settings["modifications"], self.find_study()):
                problems.append(f"Advanced, {problem}")
        return run_settings, problems

    async def write(self, run_settings):
        """
        Fill the form from settings (of any schema), after reading the zones, areas and buses of their
        case. Returns False when they are not in the form yet: Julia stopped before it read the case
        (they go in once it is back), or another case was chosen meanwhile.
        """
        values = form_values(run_settings)
        case = values["case"]
        self.loaded_case = case
        self.retry = None
        self.writing = True  # the case shows at once, while Julia reads it
        try:
            self.case.set_value(case if case in self.case.options else None)
        finally:
            self.writing = False
        case_info, case_error = await self.find_case_info(case)
        if case != self.loaded_case:  # another case was chosen meanwhile
            return False
        self.case_info, self.case_error = case_info, case_error
        if self.is_unanswered(case):  # fill the form once Julia is back and has read the case
            self.retry = lambda: self.write(run_settings)
            self._show_wait()
            return False

        self.writing = True
        try:
            self.case.set_value(case if case in self.case.options else None)
            self.objective.set_value(values["objective"])
            self.opf_model.set_value(values["opf_model"])
            self.flow_model.set_value(values["flow_model"])
            self.lam.set_value(values["lambda"])

            # the kind first, then the names it offers
            kind = values["boundary_kind"]
            self.boundary_kind.set_options(
                self._find_boundary_kinds(), value=kind if kind in self._find_boundary_kinds() else None
            )
            names = self._find_group_options(kind) if kind in GROUP_KINDS else {}
            self.boundary_name.set_options(names, value=match_option(names, values["boundary_name"]))
            self.bus_pairs.set_value(values["bus_pairs_text"])

            self.uniform.set_value(values["uniform"])
            self.uniform_value.set_value(values["uniform_value"])
            self.penalty_rows = [dict(row) for row in values["penalty_rows"]]
            self.others.set_value(values["others"])

            self.frequency_security.set_value(values["frequency_security"])
            self.voltage_security.set_value(values["voltage_security"])
            self.run_dynamic_sim.set_value(values["run_dynamic_sim"])
            self.simulator.set_value(values["simulator"])
            self.open_report.set_value(values["open_report"])
            self.output_tag.set_value(values["output_tag"])
            self.modifications = values["modifications"]
        finally:
            self.writing = False
        self.update_view()
        return True

    async def take(self, case, *, boundary=None, penalty_rows=()):
        """
        Fill in what another page chose for `case` (the Network page): a boundary (as in the
        settings), or penalty rows ({kind, name, times_lambda}), which go to the bottom of
        the list, where they count over the rows above (a row for the same place goes, not to count
        twice). The rest of the form stays, except that a change of case drops what named the
        other case, as choosing the case by hand does.

        Returns (refused, notes): why nothing was taken ("" when it was), and what else changed
        in the form, as sentences.
        """
        run_settings, _ = self.read()
        notes = []
        if run_settings["case"] != case:
            if run_settings["modifications"]:
                notes.append("The network modifications were for the other case and were removed.")
            run_settings["case"] = case
            run_settings["boundary"] = {"kind": "bus_pairs", "name": "", "bus_pairs": []}
            run_settings["penalties"] = dict(run_settings["penalties"], rows=[])
            run_settings["modifications"] = {}
            notes.append("The form is now on this case.")
        if boundary is not None:
            run_settings["boundary"] = boundary

        # a study is by zone or by area (decision 11): a penalty for a group of the other kind does not fit
        case_info, case_error = await self.find_case_info(case)
        if case_error:
            return f"the case could not be read: {case_error}", []
        study_kind = run_settings["boundary"]["kind"]
        if study_kind not in GROUP_KINDS:
            study_kind = next((kind for kind in GROUP_KINDS if case_info.get(f"{kind}s")), None)
        penalties = run_settings["penalties"]
        for row in penalty_rows:
            if row["kind"] != "bus" and row["kind"] != study_kind:
                return (
                    f"The study in the Run form is by {study_kind}, so a penalty for {row['kind']} {row['name']} does not fit it. Use it as the target first, or select its buses.",
                    [],
                )
            is_bus = row["kind"] == "bus"
            new_row = {
                "kind": row["kind"],
                "name": int(row["name"]) if is_bus else str(row["name"]),
                "except": False,
                "times_lambda": row["times_lambda"],
            }
            penalties["rows"] = [old for old in penalties["rows"] if not is_same_target(old, new_row)]
            penalties["rows"].append(new_row)
        if penalty_rows and penalties["uniform"] is not None:
            penalties["uniform"] = None
            notes.append("Uniform shedding was switched off, because it ignores penalty rows.")
        dropped = [row for row in penalties["rows"] if row["kind"] in GROUP_KINDS and row["kind"] != study_kind]
        if dropped:
            penalties["rows"] = [row for row in penalties["rows"] if row not in dropped]
            notes.append(
                f"{len(dropped)} penalty row{'s' if len(dropped) > 1 else ''} of the other kind of group went, because the study is now by {study_kind}."
            )

        await self.write(run_settings)
        return "", notes

    # -------------------- keeping the form consistent --------------------
    def _find_boundary_kinds(self):
        """Boundary kinds the case offers: zone and area only when it has at least two of them."""
        kinds = {kind: KIND_LABELS[kind] for kind in GROUP_KINDS if self._find_groups(kind)}
        kinds["bus_pairs"] = KIND_LABELS["bus_pairs"]
        return kinds

    def update_view(self):
        """
        Bring the form in line with the case and with its own values: the kinds and names on offer,
        what is shown, and what is enabled. Safe to call at any time; it changes a value only when
        the value is no longer possible.
        """
        if self.updating:
            return
        self.updating = True
        try:
            self._show_wait()
            self._update_objective()
            self._update_boundary()
            self._update_penalties()
            self._update_security()
            self._show_modifications()  # the boundary's kind decides which groups they may name
        finally:
            self.updating = False

    def _update_case_message(self):
        """The hint under the case: what the form waits for, why there is no case, or what the case holds."""
        wait = self._describe_wait()
        if wait:
            self._show_case_message(wait, waiting=True)
        elif self.case_list_error:
            self._show_case_message(f"no case list: {self.case_list_error}", error=True)
        elif not self.cases_loaded:
            self._show_case_message("")
        elif self.case_error:
            self._show_case_message(self.case_error, error=True)
        elif self.case_info:
            groups = [f"{len(self._find_groups(kind))} {kind}s" for kind in GROUP_KINDS if self._find_groups(kind)]
            counts = [
                f"{len(self.case_info.get('loads', []))} loads",
                f"{len(self.case_info.get('gens', []))} generators",
            ]
            self._show_case_message(", ".join(groups + counts))
        else:
            self._show_case_message("")

    def _update_objective(self):
        """The objective's formula under it, and what it does not read dimmed (still editable: it is kept for another objective)."""
        objective = self.objective.value
        reads = OBJECTIVE_READS.get(objective, set())
        theme.dim_unused([self.flow_model_label, self.flow_model], "flow_model" not in reads)
        theme.dim_unused([self.lam_label, self.lam], "lambda" not in reads)
        theme.dim_unused([self.penalties_section], "penalties" not in reads)

    def _update_boundary(self):
        kinds = self._find_boundary_kinds()
        kind = self.boundary_kind.value if self.boundary_kind.value in kinds else next(iter(kinds))
        self.boundary_kind.set_options(kinds, value=kind)

        names = self._find_group_options(kind) if kind in GROUP_KINDS else {}
        name = self.boundary_name.value if self.boundary_name.value in names else None
        self.boundary_name.set_options(names, value=name)
        self.boundary_label.text = KIND_LABELS[kind]
        self.boundary_name.set_visibility(kind in GROUP_KINDS)
        self.bus_pairs.set_visibility(kind == "bus_pairs")
        if kind in GROUP_KINDS:
            self.boundary_hint.text = f"The lines leaving the {kind} open. Results are grouped by {kind}."
        else:
            self.boundary_hint.text = "The lines between each pair of buses open."

    def _update_penalties(self):
        uniform = bool(self.uniform.value)
        self.uniform_box.set_visibility(uniform)
        self.penalty_box.set_visibility(not uniform)

        # a study is by zone or by area: rows of the other kind go
        kinds = self._find_penalty_kinds()
        if any(find_row_key(row) not in kinds for row in self.penalty_rows):
            self.penalty_rows = [row for row in self.penalty_rows if find_row_key(row) in kinds]
        if self._find_penalty_signature() != self.penalty_signature:
            self.penalty_list.refresh()

    def _find_penalty_signature(self):
        """What the penalty rows are built from: the kinds on offer, the case, and the list of rows (replaced by write)."""
        return (tuple(self._find_penalty_kinds()), id(self.case_info), id(self.penalty_rows), len(self.penalty_rows))

    def _update_security(self):
        # voltage security needs bus voltages: AC only
        if self.opf_model.value == "DC":
            self.voltage_security.set_value(False)
            self.voltage_security.disable()
        else:
            self.voltage_security.enable()

        # the dynamic simulation and the frequency limits read the case's .dyr
        if self.case_info and not self.case_info.get("has_dyr", True):
            self.run_dynamic_sim.set_value(False)
            self.run_dynamic_sim.disable()
            self.frequency_security.set_value(False)
            self.frequency_security.disable()
            self.dyr_message.text = "No .dyr file in the case folder: no dynamic simulation and no frequency security."
        else:
            self.run_dynamic_sim.enable()
            self.frequency_security.enable()
            self.dyr_message.text = ""
        self.simulator.set_enabled(bool(self.run_dynamic_sim.value))

        # only the ANDES script can leave its report closed
        if not self.run_dynamic_sim.value:
            self.open_report_tooltip.text = "No dynamic simulation, so no report"
        self.open_report.set_enabled(bool(self.run_dynamic_sim.value) and self.simulator.value == "andes")


# ==================== The page ====================
def build(ctx):
    """The Run page of one browser tab: the toolbar, the settings sheet, the results, the session's runs and the status strip."""
    form = RunForm(ctx)
    ctx.client_state()["run_form"] = form  # the Network page of this browser tab fills it (RunForm.take)

    def show_summary(opened=None):
        """The toolbar's text: the chosen preset's note while the sheet is open, what the settings are while it is folded."""
        opened = settings_fold.opened if opened is None else opened
        summary.text = preset_bar.find_note() if opened else describe_settings(form.read()[0])
        summary_tooltip.text = summary.text
        summary_tooltip.set_visibility(bool(summary.text))

    with theme.panel():
        with theme.toolbar():
            settings_fold = theme.FoldButton("Settings", on_change=show_summary)
            preset_bar = PresetBar(ctx, form, on_loaded=lambda: settings_fold.open(), on_choice=lambda: show_summary())
            summary = theme.toolbar_text()
            with summary:
                summary_tooltip = ui.tooltip()  # all of it, when the line is cut
            advanced_button = theme.button("Advanced", icon="sliders", kind="ghost")
            batch_button = theme.button("Batch", icon="layers", kind="ghost")
            queue_button = theme.button("Queue", icon="list", kind="ghost").classes("btn-queue")
            stop_button = theme.button("Stop", icon="stop", kind="danger")
            run_button = theme.button("Run", icon="play", kind="primary").classes("btn-run")
            with run_button:
                run_tooltip = ui.tooltip()  # why it is off, when it is
        problems_label = ui.label("").classes("problems")
        with ui.element("div").classes("modifications") as modifications_line:
            theme.eyebrow("Network modifications")
            modifications_text = ui.label().classes("modifications-text")
            modifications_note = theme.hint()
            reset_button = theme.button("Reset", kind="ghost", small=True).tooltip("Remove every network modification")

        def show_modifications():
            """The Advanced button counts the active modifications, and the line under the toolbar lists them."""
            count = advanced.count_entries(form.modifications)
            advanced_button.text = f"Advanced ({count})" if count else "Advanced"
            modifications_line.set_visibility(count > 0)
            modifications_text.text = "  ·  ".join(advanced.describe(form.modifications))
            unfit = advanced.find_problems(form.modifications, form.find_study()) if form.case_info else []
            theme.show_hint(
                modifications_note, "some do not fit these settings: open Advanced" if unfit else "", bad=True
            )

        def open_advanced():
            if not form.case_info:
                ui.notify("Choose a case that can be read first.", position="top")
                return
            advanced_dialog.open(form.modifications, form.find_study())

        def show_problems(problems):
            problems_label.text = "\n".join(f"• {problem}" for problem in problems)

        def change_modifications(modifications):
            """Apply and Reset: the new modifications, and a problems list that no longer names the old ones."""
            form.set_modifications(modifications)
            if problems_label.text:
                show_problems(form.read()[1])

        advanced_dialog = advanced.AdvancedDialog(on_apply=change_modifications)
        advanced_button.on_click(open_advanced)
        reset_button.on_click(lambda: change_modifications({}))
        form.on_modifications = show_modifications
        with settings_fold.attach(ui.element("div")):
            form.build()

    results = ResultsView(ctx)

    with theme.panel():
        with theme.toolbar():
            theme.eyebrow("Runs in this session")

        runs_box = ui.element("div")
    strip = StatusStrip(ctx, LogDialog())  # last: it leaves room for itself at the end of the page

    shown_runs = [None]  # the runs table's signature when it was last built

    @ui.refreshable
    def runs_view():
        shown_runs[0] = find_runs_signature(ctx)
        build_runs_view(ctx, form, settings_fold, strip, results)

    with runs_box:
        runs_view()

    # -------------------- buttons --------------------
    queue_dialog = QueueDialog(ctx)

    def update_buttons():
        """Run says what a click does now (start, or wait in the queue), and Queue how many runs wait."""
        block = find_run_block(ctx, form)
        queued = is_run_queued(ctx)
        run_button.text = "Add to queue" if queued else "Run"
        run_button.props["icon"] = theme.ICONS["plus" if queued else "play"]
        run_button.update()
        run_button.set_enabled(not block)
        run_tooltip.text = block
        run_tooltip.set_visibility(bool(block))
        batch_button.set_enabled(not block)
        stop_button.set_enabled(ctx.runs.find_running() is not None)
        queue_button.text = describe_queue_button(ctx.queue)
        if ctx.queue.paused:
            queue_button.classes(add="queue-paused")
        else:
            queue_button.classes(remove="queue-paused")
        preset_bar.update_buttons()  # Save as waits with the form

    form.on_wait = update_buttons

    def read_form():
        """The form's settings, or None when something keeps them from running: the problems show, with the sheet unfolded."""
        run_settings, problems = form.read()
        show_problems(problems)
        if problems:
            settings_fold.open()  # the problems are about the settings: show them
            return None
        return run_settings

    def run_clicked():
        if find_run_block(ctx, form):  # a click that came before the button was turned off
            return
        run_settings = read_form()
        if run_settings is None:
            return
        if is_run_queued(ctx):
            ctx.queue.add(run_settings)
            ui.notify(f"Added to the queue: {describe_waiting(len(ctx.queue.entries))}.", position="top")
            return
        try:
            ctx.runs.start(run_settings)  # the runs table and the status strip show it
        except WorkerError as error:
            problems_label.text = f"• Julia is not running: {error}"

    async def stop_clicked():
        running = ctx.runs.find_running()
        if running is None:
            return
        await ctx.worker.restart()  # kills Julia with its dynamic.py, then starts a fresh one
        if ctx.queue.paused:  # the runs that wait do not start behind a run that was stopped
            ui.notify(
                f"Run {running['number']} was stopped, so the queue is paused: "
                f"{describe_waiting(len(ctx.queue.entries))}. Resume it in Queue.",
                position="top",
            )

    def add_batch(settings_list, compare):
        """The batch dialog's runs go to the end of the queue; the first starts at once when nothing is running."""
        ctx.queue.add_many(settings_list, compare)
        count = len(settings_list)
        note = f"{count} run{'s' if count > 1 else ''} added to the queue."
        if ctx.queue.paused:
            note += " The queue is paused: Resume it in Queue."
        ui.notify(note, position="top")

    batch_dialog = BatchDialog(on_add=add_batch)

    def batch_clicked():
        """Open the batch dialog on the form's settings. The form need not name the zone or area of the boundary: the dialog's targets do."""
        if find_run_block(ctx, form):  # a click that came before the button was turned off
            return
        run_settings, problems = form.read()
        missing_target = describe_missing_target(run_settings["boundary"]["kind"])
        problems = [problem for problem in problems if problem != missing_target]
        show_problems(problems)
        if problems:
            settings_fold.open()  # the problems are about the settings: show them
            return
        batch_dialog.open(run_settings, form.find_study())

    run_button.on_click(run_clicked)
    stop_button.on_click(theme.busy_handler(stop_button, stop_clicked))
    batch_button.on_click(batch_clicked)
    queue_button.on_click(queue_dialog.open)

    async def load_into_form(run_settings, note, result=None):
        """
        Settings from another page (History's Load into Run) into the form, the sheet unfolded, and
        a note saying so. `result`, the run whose results go with them (a session run, or one
        built by `build_loaded_record`), shows at once: it needs nothing from Julia.
        """
        settings_fold.open()
        if result is not None:
            results.show(result)
        if await form.write(run_settings):
            ui.notify(note, position="top")
        elif form.retry is not None:
            ui.notify(
                "Julia stopped before it read the case: the settings go into the form once Julia is back.",
                position="top",
            )

    ctx.client_state()["load_settings"] = load_into_form

    # -------------------- following the worker --------------------
    async def load_cases():
        await form.load_cases()
        update_buttons()

    def state_changed(state, message=""):
        update_buttons()
        if state == "ready" and not form.cases_loaded:  # Julia came back after the page was built
            background_tasks.create(load_cases(), name="load cases")
        else:
            form.julia_changed()

    def runs_changed():
        results.refresh()
        if find_runs_signature(ctx) != shown_runs[0]:  # a click on the table is not lost to a rebuild at each stage
            runs_view.refresh()
        strip.refresh()
        form.julia_changed()  # a read that waited for the run says so
        update_buttons()

    removers = [
        ctx.worker.on_state(state_changed),
        ctx.runs.on_change(runs_changed),
        ctx.queue.on_change(update_buttons),
    ]
    ui.context.client.on_delete(lambda: [remove() for remove in removers])
    update_buttons()
    ui.timer(0.1, load_cases, once=True)


def build_runs_view(ctx, form, settings_fold, strip, results):
    """The runs of this session, newest first: what ran, its status, and its report, folder, log, Load (settings and results) and Compare."""
    if not ctx.runs.records:
        ui.label("No run yet. Choose the settings above and press Run.").classes("empty")
        return

    def add_to_compare(record):
        """The run joins the Compare page, and a note says so, or why not."""
        refusal = ctx.compare.add(record)
        count = len(ctx.compare.records)
        added = f"Run {record['number']} is on the Compare page, with {count} run{'s' if count > 1 else ''} there now."
        ui.notify(refusal or added, position="top")

    async def load_run(record):
        """The run's settings into the form, and its results into the results panel when it has them."""
        settings_fold.open()
        if record["summary"]:
            results.show(record)
        if await form.write(record["settings"]):
            note = f"The settings of run {record['number']} are in the form."
            if not record["summary"]:
                note += " It has no results to show."
            ui.notify(note, position="top")
        elif form.retry is not None:
            ui.notify(
                "Julia stopped before it read the case: the settings go into the form once Julia is back.",
                position="top",
            )

    with ui.element("div").classes("runs-row runs-head"):
        for heading in ("Run", "Started", "Case", "Objective", "Boundary", "Tag", "Status", "", ""):
            theme.eyebrow(heading)
    for record in reversed(ctx.runs.records):
        run_settings = record["settings"]
        files = (record["summary"] or {}).get("files") or {}
        with ui.element("div").classes("runs-row"):
            ui.label(f"{record['number']}").classes("num")
            ui.label(record["started"]).classes("num muted")
            modifications = run_settings.get("modifications") or {}
            with theme.line():
                ui.label(Path(run_settings["case"]).name)
                if modifications:
                    theme.hint("modified").tooltip("; ".join(advanced.describe(modifications)))
            ui.label(run_settings["objective"])
            ui.label(describe_boundary(run_settings))
            ui.label(run_settings["output_tag"] or "-").classes("" if run_settings["output_tag"] else "muted")
            theme.State(record["status"], record["status"])

            detail = ""
            if record["error"]:
                detail = record["error"].splitlines()[0][:ERROR_PREVIEW]
            elif record["seconds"] is not None:
                detail = f"{record['seconds']:g} s"
            detail_label = ui.label(detail).classes("num " + ("bad" if record["status"] == "failed" else "muted"))
            if record["error"]:
                detail_label.tooltip(record["error"])

            with ui.element("div").classes("runs-actions"):
                report_button = theme.button(
                    "Report", kind="ghost", small=True, on_click=lambda files=files: open_report(files)
                )
                report_button.set_enabled(bool(files.get("report")))
                folder_button = theme.button(
                    "Folder", kind="ghost", small=True, on_click=lambda files=files: open_folder(files)
                )
                folder_button.set_enabled(bool(files.get("output_path")))
                theme.button("Log", kind="ghost", small=True, on_click=lambda record=record: strip.open_log(record))
                theme.button(
                    "Load", kind="ghost", small=True, on_click=lambda record=record: load_run(record), busy=True
                ).tooltip("Put its settings in the form and show its results")
                compare_button = theme.button(
                    "Compare", kind="ghost", small=True, on_click=lambda record=record: add_to_compare(record)
                )
                refusal = find_refusal(record)
                compare_button.set_enabled(not refusal)
                if refusal:
                    compare_button.tooltip(refusal)
