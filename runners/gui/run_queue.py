"""
The run queue: runs that wait for Julia, which does one run at a time. A run is added while
another is in progress (Run, or a batch), and the first in the queue starts when that one ends.

The queue is kept here, in Python: Julia gets one run at a time, so a run that waits can still
be cancelled or moved, and a question of a page (reading a case, placing a network) is answered
between two runs. Like the runs, the queue belongs to the app, so every browser tab shows the
same one. It is not kept when the app stops.

It pauses by itself when a run does not end by itself: Stop and Restart Julia stop the run in
progress, and Julia may exit during one. The runs that wait then stay until Resume. A run that
fails in Julia (an error, a case that does not solve) does not pause it: the next one starts.
"""

import asyncio
import copy
from datetime import datetime

from julia_worker import WorkerError, call_listeners


class RunQueue:
    """
    `entries` are the runs that wait, the first to start first. Each is a dict:
    - `key` (its own number, which stays when the queue is reordered);
    - `settings` (schema 2, as the form gave them);
    - `compare` (True for a run that goes to the Compare page once it finishes, as a batch's do);
    - `added` (clock time as text).

    `paused` is true while the queue waits for Resume, and `pause_reason` says why.
    """

    def __init__(self, runs, worker):
        self.runs = runs
        self.worker = worker
        self.entries = []
        self.paused = False
        self.pause_reason = ""
        self._next_key = 1
        self._ended = set()             # job ids of the runs seen to have ended
        self._start_planned = False     # a start is planned for the event loop's next turn
        self._listeners = []
        runs.on_change(self._runs_changed)
        worker.on_state(self._state_changed)

    def on_change(self, listener):
        """Call `listener()` whenever the queue changes: its runs, their order, or whether it is paused. Returns its remover."""
        self._listeners.append(listener)

        def remove():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    # ==================== What a page asks ====================
    def is_active(self):
        """True while runs wait and will start by themselves, so a new run has to wait behind them."""
        return bool(self.entries) and not self.paused

    def find_position(self, key):
        """The place of an entry in the queue (0 is next), or None when it is gone."""
        for position, entry in enumerate(self.entries):
            if entry["key"] == key:
                return position
        return None

    # ==================== What a page does ====================
    def add(self, settings, compare=False):
        """Put one run at the end of the queue; it starts at once when nothing is running."""
        self.add_many([settings], compare)

    def add_many(self, settings_list, compare=False):
        """Put runs at the end of the queue, in their order."""
        added = datetime.now().strftime("%H:%M:%S")
        for settings in settings_list:
            self.entries.append(
                {"key": self._next_key, "settings": copy.deepcopy(settings), "compare": compare, "added": added}
            )
            self._next_key += 1
        self._changed()

    def cancel(self, key):
        """Take a run out of the queue."""
        self.entries = [entry for entry in self.entries if entry["key"] != key]
        self._changed()

    def clear(self):
        """Take every run out of the queue. The run in progress goes on."""
        self.entries = []
        self._changed()

    def move(self, key, step):
        """Move a run one place towards the start (step -1) or the end (+1) of the queue."""
        position = self.find_position(key)
        if position is None:
            return
        new_position = position + step
        if not 0 <= new_position < len(self.entries):
            return
        entries = self.entries
        entries[position], entries[new_position] = entries[new_position], entries[position]
        self._changed()

    def pause(self, reason=""):
        """Keep the runs that wait from starting until `resume()`. The run in progress goes on."""
        if not self.entries:
            return                      # nothing waits, so there is nothing to hold
        self.paused = True
        self.pause_reason = reason
        self._changed()

    def resume(self):
        """Let the runs that wait start again, the first one now when nothing is running."""
        self.paused = False
        self.pause_reason = ""
        self._changed()

    # ==================== Following the runs and Julia ====================
    def _runs_changed(self):
        """A run that was stopped, or that Julia died in, pauses the queue; any other end lets the next run start."""
        for record in self.runs.records:
            if record["status"] == "running" or record["id"] in self._ended:
                continue
            self._ended.add(record["id"])
            if record["status"] == "stopped":
                self.pause(f"run {record['number']} was stopped")
            elif record["status"] == "failed" and self.worker.state == "crashed":
                self.pause(f"Julia exited during run {record['number']}")
        self._plan_start()

    def _state_changed(self, state, _message=""):
        if state == "ready":            # Julia is back, or has answered a question
            self._plan_start()

    def _changed(self):
        if not self.entries:            # an empty queue is not paused: the next Run starts at once
            self.paused = False
            self.pause_reason = ""
        call_listeners(self._listeners)
        self._plan_start()

    def _plan_start(self):
        """
        Start the next run on the event loop's next turn, not here: this is called from inside
        the runs' own listeners (a run has just ended), and starting a run calls them again.
        """
        if self._start_planned:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:            # no event loop (a check outside the app): start now
            self._start_next()
            return
        self._start_planned = True
        loop.call_soon(self._start_next)

    def _start_next(self):
        """Start the first run of the queue when nothing keeps it: a pause, a run in progress, or Julia not running."""
        self._start_planned = False
        if self.paused or not self.entries or self.runs.find_running() is not None:
            return
        if self.worker.state in ("stopped", "crashed") or not self.worker.is_running():
            return                      # it starts when Julia is back (_state_changed)
        entry = self.entries.pop(0)
        try:
            self.runs.start(entry["settings"], compare=entry["compare"])
        except WorkerError as error:
            self.entries.insert(0, entry)
            self.paused = True
            self.pause_reason = f"Julia did not take the run: {error}"
        call_listeners(self._listeners)
