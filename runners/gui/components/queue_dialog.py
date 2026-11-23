"""
The run queue as a dialog: the runs that wait, in the order they start, each with what it is,
the arrows that move it and a button that cancels it; then Clear queue, and Pause or Resume.
The queue itself is run_queue.py's business (`ctx.queue`).

The dialog follows the queue while it is open: a run that starts leaves the list, and a queue
changed in another browser tab changes here too.
"""

from pathlib import Path

from nicegui import ui

import results_index
import theme

# ==================== Settings ====================
HEADINGS = ("Next", "Case", "Objective", "Boundary", "Tag", "Penalties", "Added", "", "")


def describe_queue(queue, runs):
    """The queue in a few words, for the dialog's title row: how many runs wait, and behind which run or why not."""
    count = len(queue.entries)
    if count == 0:
        return "no run waits"
    waiting = f"{count} run" + (" waits" if count == 1 else "s wait")
    running = runs.find_running()
    if queue.paused:
        return f"{waiting} · paused"
    if running is not None:
        return f"{waiting} behind run {running['number']}"
    return waiting


def describe_pause(queue):
    """What the line over a paused queue says: why it is paused, and what Resume does."""
    reason = f", because {queue.pause_reason}" if queue.pause_reason else ""
    return f"The queue is paused{reason}. The runs below wait until Resume."


class QueueDialog:
    """One dialog of a browser tab: `open()`. It builds its rows again whenever the queue or the runs change."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.queue = ctx.queue
        self.shown = None               # keys of the runs the rows were last built from
        self.dialog, box = theme.dialog()
        box.classes("queue-dialog")
        with box:
            with theme.toolbar():
                ui.label("Run queue").classes("dialog-title")
                self.subtitle = theme.toolbar_text()
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close)
            self.note = ui.label().classes("queue-note")

            @ui.refreshable
            def rows():
                self._build_rows()

            self.rows = rows
            with ui.element("div").classes("queue-body"):
                rows()
            with ui.element("div").classes("dialog-foot"):
                self.clear_button = theme.button("Clear queue", kind="ghost", on_click=self.queue.clear)
                ui.element("div").classes("grow")
                self.pause_button = theme.button("Pause", on_click=self._pause_or_resume)
                theme.button("Close", kind="primary", on_click=self.dialog.close)
        removers = [self.queue.on_change(self.refresh), ctx.runs.on_change(self.refresh)]
        ui.context.client.on_delete(lambda: [remove() for remove in removers])
        self.refresh()

    def open(self):
        self.refresh()
        self.dialog.open()

    # -------------------- showing --------------------
    def refresh(self):
        """Bring the dialog in line with the queue; the rows are built again only when the runs that wait changed."""
        queue = self.queue
        self.subtitle.text = describe_queue(queue, self.ctx.runs)
        self.note.text = describe_pause(queue) if queue.paused else ""
        self.clear_button.set_enabled(bool(queue.entries))
        self.pause_button.text = "Resume" if queue.paused else "Pause"
        self.pause_button.set_enabled(bool(queue.entries))
        signature = [entry["key"] for entry in queue.entries]
        if signature != self.shown:
            self.rows.refresh()

    def _build_rows(self):
        entries = self.queue.entries
        self.shown = [entry["key"] for entry in entries]
        if not entries:
            ui.label(
                "No run waits. Run adds a run here while another is in progress, and Batch adds several at once."
            ).classes("queue-empty")
            return
        with ui.element("div").classes("queue-row queue-head"):
            for heading in HEADINGS:
                theme.eyebrow(heading)
        last = len(entries) - 1
        for position, entry in enumerate(entries):
            run_settings = entry["settings"]
            record = {"gui_settings": run_settings}             # as results_index reads a run's record
            boundary, _group = results_index.describe_boundary(record)
            penalties = results_index.describe_penalties(record)
            key = entry["key"]
            with ui.element("div").classes("queue-row"):
                ui.label(f"{position + 1}").classes("num")
                ui.label(Path(run_settings["case"]).name)
                ui.label(run_settings["objective"])
                ui.label(boundary)
                # the tag and the penalties may be cut with "...": their tooltip has all of them
                tag_label = ui.label(run_settings["output_tag"] or theme.NO_VALUE)
                if run_settings["output_tag"]:
                    tag_label.tooltip(run_settings["output_tag"])
                ui.label(penalties).tooltip(penalties)
                ui.label(entry["added"]).classes("num muted")
                with ui.element("div").classes("move-buttons"):
                    up = theme.button(
                        icon="chevron_up", kind="ghost", small=True, on_click=lambda key=key: self.queue.move(key, -1)
                    )
                    up.set_enabled(position > 0)
                    down = theme.button(
                        icon="chevron_down", kind="ghost", small=True, on_click=lambda key=key: self.queue.move(key, 1)
                    )
                    down.set_enabled(position < last)
                theme.button(icon="close", kind="ghost", small=True, on_click=lambda key=key: self.queue.cancel(key))

    # -------------------- actions --------------------
    def _pause_or_resume(self):
        if self.queue.paused:
            self.queue.resume()
        else:
            self.queue.pause()
