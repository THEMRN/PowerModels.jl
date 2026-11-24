"""
A dialog that shows log lines as plain text: a run's raw log, its warnings, or Julia's own
output. It can show only the lines that contain a text, and copy what it shows.

The dialog is opened on a list of lines and follows that list while it is open, so the log of a
run in progress grows on screen. The lines go to the browser as text, never as HTML (a log has
names such as <FRQTPAT> in it).
"""

from nicegui import ui

import theme

# ==================== Settings ====================
REFRESH_SECONDS = 0.5  # how often an open dialog looks for new lines


class LogDialog:
    """One dialog of a browser tab, reused for every log: `open(title, lines)`."""

    def __init__(self):
        self.lines = []  # the list on show; the worker may still be adding to it
        self.seen = 0  # lines of it already looked at
        self.shown = 0  # lines of it on screen: those that contain the search text
        self.dialog, box = theme.dialog()
        with box:
            with theme.toolbar():
                self.title = ui.label().classes("dialog-title")
                self.count = theme.toolbar_text()
                self.search = ui.input(placeholder="Only lines containing...", on_change=self._show_again)
                self.search.props("debounce=250").classes("log-search")
                theme.button("Copy", kind="soft", on_click=self._copy).tooltip("Copy the lines shown")
                theme.button(icon="close", kind="ghost", on_click=self.dialog.close)
            # the view starts at the end of the log and stays there while lines are added
            with ui.element("div").classes("log-view"):
                self.text = ui.element("div").classes("log-lines")
        with theme.offstage():
            self.timer = ui.timer(REFRESH_SECONDS, self._follow, active=False)
        self.dialog.on_value_change(self._opened_or_closed)

    def open(self, title, lines):
        """Show `lines` (a list of text lines, which may still grow) under `title`."""
        self.title.text = title
        self.lines = lines
        self.search.set_value("")
        self._show_again()
        self.dialog.open()

    # -------------------- what is on screen --------------------
    def _find_matching(self, lines):
        """The lines that contain the search text, in any case; all of them without one."""
        wanted = (self.search.value or "").strip().lower()
        if not wanted:
            return list(lines)
        return [line for line in lines if wanted in line.lower()]

    def _show_again(self, _event=None):
        """Start over: the list or the search text changed."""
        self.text.clear()
        self.seen = 0
        self.shown = 0
        self._follow()

    def _follow(self):
        """Add the lines that came since the last look, as one block of text."""
        new_lines = self.lines[self.seen :]
        self.seen += len(new_lines)
        matching = self._find_matching(new_lines)
        if matching:
            with self.text:
                ui.label("\n".join(matching))
            self.shown += len(matching)
        self._show_count()

    def _show_count(self):
        total = len(self.lines)
        if total == 0:
            self.count.text = "nothing yet"
        elif (self.search.value or "").strip():
            self.count.text = f"{self.shown} of {total} lines"
        else:
            self.count.text = f"{total} line" + ("" if total == 1 else "s")

    def _opened_or_closed(self, event):
        self.timer.active = bool(event.value)  # look for new lines only while open

    def _copy(self):
        shown = self._find_matching(self.lines)
        ui.clipboard.write("\n".join(shown))
        ui.notify(f"{len(shown)} line" + ("" if len(shown) == 1 else "s") + " copied.", position="top")
