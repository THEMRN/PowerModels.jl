"""
The status strip of the Run page: a bar fixed to the bottom of the window that says where a run
is. It shows the run in progress, and otherwise the latest run of the session:

- the stages (gui_plan.md, "Stages") as steps: done, current, not reached, not part of this run;
- the time in the current stage and in the whole run;
- "now", what the run is doing: Julia's latest note for the stage (@@activity, such as Ipopt's
  iteration), or else what the stage does; the error of a run that failed;
- the number of warnings in the log (click: the warnings) and Full log (the whole raw log).

Everything it shows is on the run's record (session_runs.py), so every browser tab shows the
same and a reloaded page picks a run up where it is.
"""

import time
from datetime import datetime

from nicegui import ui

import theme

# ==================== Settings ====================
REFRESH_SECONDS = 0.5           # how often the clock, "now" and the warning count are read during a run
STALE_SECONDS = 3               # s, from which "now" says how old Julia's note is
STAGES = [                      # (stage, label) in the order a run reaches them; as STAGE_LABELS in worker.jl
    ("load_case", "Load case"),
    ("prepare", "Prepare"),
    ("frequency_limits", "Frequency limits"),
    ("solve", "Solve"),
    ("reports", "Reports"),
    ("excel", "Excel report"),
    ("export", "Export"),
    ("dynamic_sim", "Dynamic simulation"),
    ("summary", "Summary"),
]
STAGE_ACTIVITIES = {            # stage -> what "now" says until Julia sends a note of its own
    "load_case": "reading the case file",
    "prepare": "preparing the run: network modifications, boundary lines, penalties, results folder",
    "frequency_limits": "computing each island's frequency limits from the .dyr file",
    "solve": "building the optimization model and solving it with Ipopt",
    "reports": "computing the reports of the solution",
    "excel": "writing the Excel report",
    "export": "writing the .raw, .dyr and line outage files",
    "dynamic_sim": "running the dynamic simulation",
    "summary": "putting the results together",
}
STAGES_OUTSIDE_JULIA = {"dynamic_sim"}     # stages that Julia's compiling on its first run does not slow
FIRST_RUN_HINT = "first run: Julia compiles as it goes"
STAGE_SETTINGS = {              # stage -> the setting that has to be on for a run to reach it
    "frequency_limits": "frequency_security",
    "export": "run_dynamic_sim",
    "dynamic_sim": "run_dynamic_sim",
}
STEP_HINTS = {                  # step state -> what its tooltip says
    "pending": "not reached",
    "skipped": "not part of this run",
    "current": "in progress",
    "failed": "the run failed here",
    "stopped": "the run was stopped here",
}


# ==================== What a record says ====================
def format_clock(seconds):
    """A duration as m:ss, or h:mm:ss from one hour."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_age(seconds):
    """How old something is: "12 s", or "3 min 5 s" from one minute."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes} min {seconds} s"


def calc_run_seconds(record):
    """Seconds the run has taken so far, or took: from the click on Run to its end."""
    return (record["ended_at"] or time.time()) - record["started_at"]


def find_steps(record):
    """
    The run's stages as steps, in order: a list of {stage, label, state, seconds}.
    `state` is "done", "current", "failed", "stopped", "pending" (not reached) or "skipped" (not
    part of this run, by its settings). `seconds` is the time spent in the stage, None when it
    was not reached. A stage the run reached counts as reached whatever the settings say, and a
    stage this list does not know is put after the stage reached before it.
    """
    reached = record["stages"]
    labels = dict(STAGES)
    order = [stage for stage, _ in STAGES]
    for position, entry in enumerate(reached):
        if entry["stage"] in order:
            continue
        labels[entry["stage"]] = entry["label"]
        before = order.index(reached[position - 1]["stage"]) + 1 if position > 0 else 0
        order.insert(before, entry["stage"])

    # the last stage reached is where the run is, or where it ended
    last_state = {"running": "current", "finished": "done", "failed": "failed", "stopped": "stopped"}[record["status"]]
    end = record["ended_at"] or time.time()
    reached_steps = {}
    for position, entry in enumerate(reached):
        is_last = position == len(reached) - 1
        until = end if is_last else reached[position + 1]["at"]
        reached_steps[entry["stage"]] = {"state": last_state if is_last else "done", "seconds": until - entry["at"]}

    steps = []
    for stage in order:
        step = {"stage": stage, "label": labels[stage], "state": "pending", "seconds": None}
        setting = STAGE_SETTINGS.get(stage)
        if stage in reached_steps:
            step.update(reached_steps[stage])
        elif setting is not None and not record["settings"].get(setting):
            step["state"] = "skipped"
        steps.append(step)
    return steps


def describe_now(record, first_run=False):
    """
    (title, text, is_bad) of the strip's second row: what the run is doing, or how it ended. During
    a run that is Julia's latest note for the stage, or else what the stage does (STAGE_ACTIVITIES).
    Once that is STALE_SECONDS old, a note says how old it is, and on the first run since Julia
    started (`first_run`) both say that Julia compiles, which makes every step slower that once.
    """
    status = record["status"]
    if status == "running":
        if not record["stages"]:
            return "now", "waiting for Julia to start the run...", False
        stage = record["stages"][-1]
        if record["activity"]:
            text, since = record["activity"], record["activity_at"]
        else:
            text, since = STAGE_ACTIVITIES.get(stage["stage"], stage["label"]), stage["at"]
        age = time.time() - since
        if age < STALE_SECONDS:
            return "now", text, False
        if record["activity"]:
            text = f"{text} · {format_age(age)}"
        if first_run and stage["stage"] not in STAGES_OUTSIDE_JULIA:
            text = f"{text} ({FIRST_RUN_HINT})"
        return "now", text, False
    if status == "failed":
        return "error", (record["error"] or "the run failed").splitlines()[0], True
    ended = datetime.fromtimestamp(record["ended_at"]).strftime("%H:%M:%S")
    return status, f"at {ended}", False


# ==================== The strip ====================
class StatusStrip:
    """
    The strip of one browser tab. Build it last in the page: it also leaves room for itself at the
    end of the page, so the bar never covers the page's last lines. `refresh()` after a change of
    the runs; during a run it keeps itself up to date.
    """

    def __init__(self, ctx, log_dialog):
        self.ctx = ctx
        self.log_dialog = log_dialog
        self.current_time = None        # label of the current step's clock
        with ui.element("div").classes("strip") as self.bar:
            with ui.element("div").classes("strip-row"):
                self.run_label = ui.label().classes("strip-run")
                self.state = theme.State()

                @ui.refreshable
                def steps_view():
                    self._build_steps()

                self.steps_view = steps_view
                steps_view()
            with ui.element("div").classes("strip-row"):
                self.now_title = theme.eyebrow("now")
                self.now_text = ui.label().classes("strip-now")
                with self.now_text:
                    self.now_tooltip = ui.tooltip()
                self.clock = ui.label().classes("strip-clock num")
                self.warnings_button = theme.button("0 warnings", kind="ghost", small=True, on_click=self.open_warnings)
                self.warnings_button.classes("strip-warnings").tooltip("Show the warning lines of this run")
                theme.button("Full log", small=True, on_click=lambda: self.open_log()).tooltip("The whole raw output of this run")
            with theme.offstage():
                self.timer = ui.timer(REFRESH_SECONDS, self._tick, active=False)
        self.room = ui.element("div").classes("strip-room")
        self.refresh()

    def find_record(self):
        """The run the strip shows: the one in progress, or else the latest; None before the first run."""
        running = self.ctx.runs.find_running()
        if running is not None:
            return running
        return self.ctx.runs.records[-1] if self.ctx.runs.records else None

    # -------------------- showing --------------------
    def refresh(self):
        """Bring the whole strip in line with its run: after a new run, a stage, an error or the end."""
        record = self.find_record()
        self.bar.set_visibility(record is not None)
        self.room.set_visibility(record is not None)
        if record is None:
            return
        self.run_label.text = f"Run {record['number']}"
        self.state.show(record["status"], record["status"])
        self.steps_view.refresh()
        self._tick()
        self.timer.active = record["status"] == "running"

    def _build_steps(self):
        self.current_time = None
        record = self.find_record()
        with ui.element("div").classes("steps"):
            if record is None:
                return
            for step in find_steps(record):
                with ui.element("div").classes("step").props(f"data-state={step['state']}") as box:
                    ui.element("span").classes("step-mark")
                    ui.label(step["label"]).classes("step-label")
                    if step["state"] == "current":
                        self.current_time = ui.label(format_clock(step["seconds"])).classes("step-time num")
                    hint = STEP_HINTS.get(step["state"], "")
                    if step["seconds"] is not None and step["state"] != "current":
                        hint = f"{step['seconds']:.1f} s" + (f", {hint}" if hint else "")
                    box.tooltip(f"{step['label']}: {hint}")

    def _tick(self):
        """The parts that change without a stage change: the clocks, "now" and the warning count."""
        record = self.find_record()
        if record is None:
            return
        first_run = "run" not in self.ctx.worker.answered_types     # this Julia has not finished a run yet
        title, text, is_bad = describe_now(record, first_run)
        self.now_title.text = title
        self.now_text.text = text
        self.now_text.classes(replace="strip-now bad" if is_bad else "strip-now")
        self.now_tooltip.text = (record["error"] or text) if is_bad else text
        self.clock.text = f"total {format_clock(calc_run_seconds(record))}"
        if self.current_time is not None and record["stages"]:
            self.current_time.text = format_clock(time.time() - record["stages"][-1]["at"])

        count = len(record["warnings"])
        self.warnings_button.text = f"{count} warning" + ("" if count == 1 else "s")
        self.warnings_button.set_visibility(count > 0)

    # -------------------- the logs --------------------
    def open_log(self, record=None):
        """The whole raw log of a run in the log dialog; without a record, of the run the strip shows."""
        record = record or self.find_record()
        if record is None:
            return
        lines = self.ctx.worker.job_logs.get(record["id"], [])
        self.log_dialog.open(f"Log of run {record['number']}", lines)

    def open_warnings(self):
        """The warning lines of the strip's run in the log dialog."""
        record = self.find_record()
        if record is None:
            return
        self.log_dialog.open(f"Warnings of run {record['number']}", record["warnings"])
