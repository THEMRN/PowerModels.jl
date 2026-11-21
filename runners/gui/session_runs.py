"""
The runs started in this app session: their settings, status, progress and result. They belong
to the app, not to a browser tab, so every tab shows the same runs and a reloaded page still
sees a run in progress.
"""

import copy
import time
from datetime import datetime

from julia_worker import call_listeners

# ==================== Settings ====================
STATUSES = ("running", "finished", "failed", "stopped")
LAST_LINE_LENGTH = 300          # characters kept of a run's latest log line
WARNING_WORD = "warning"        # a log line with this word, in any case, counts as a warning
IGNORED_WARNINGS = (            # lines with the word that are not warnings
    "Suppressing information and warning messages",     # PowerModels.silence(), once per Julia worker
)


def is_warning(line):
    """True for a log line that reports a warning."""
    if WARNING_WORD not in line.lower():
        return False
    return not any(phrase in line for phrase in IGNORED_WARNINGS)


def has_text(line):
    """True for a log line with a letter or a digit in it, so not for a blank line or a rule of dashes."""
    return any(character.isalnum() for character in line)


class SessionRuns:
    """
    One record (a dict) per run job, oldest first:
    - `number` (1, 2, 3, ... as shown to the user) and `id` (the worker's job id, which also
      counts the queries in between; the run's log is `worker.job_logs[id]`);
    - `settings` (schema v1, as sent) and `status` (one of STATUSES);
    - `started` (clock time as text), `started_at` and `ended_at` (s, `time.time()`; `ended_at`
      None while running) and `seconds` (Julia's own time for the job, from @@done);
    - `stage` (the latest @@stage) and `stages` (every stage reached, in order: `stage`, `label`
      and `at`, the time it started);
    - `last_line` (the latest log line with text in it) and `warnings` (the log lines that warn);
    - `summary` (the @@result summary, None without one) and `error` (the @@error message, or
      why Julia stopped).

    The records follow the worker's control lines and log lines. A run that Julia never finishes
    (Stop, Restart Julia, a crash) gets no @@done, so its status comes from the worker's state
    change.
    """

    def __init__(self, worker):
        self.worker = worker
        self.records = []
        self._listeners = []
        worker.on_control(self._handle_control)
        worker.on_log(self._handle_log)
        worker.on_state(self._handle_state)

    def on_change(self, listener):
        """
        Call `listener()` whenever a record is added or its status, stage, result or error changes.
        Not for each log line: `last_line` and `warnings` change quietly, and a view that shows
        them reads them on a timer. Returns its remover.
        """
        self._listeners.append(listener)

        def remove():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def start(self, settings):
        """Send a run job with these settings and return its record. Raises WorkerError when Julia is not running."""
        settings = copy.deepcopy(settings)
        job_id = self.worker.send({"type": "run", "settings": settings})
        record = {
            "number": len(self.records) + 1,
            "id": job_id,
            "settings": settings,
            "status": "running",
            "started": datetime.now().strftime("%H:%M:%S"),
            "started_at": time.time(),
            "ended_at": None,
            "seconds": None,
            "stage": None,
            "stages": [],
            "last_line": "",
            "warnings": [],
            "summary": None,
            "error": None,
        }
        self.records.append(record)
        call_listeners(self._listeners)
        return record

    def find(self, job_id):
        """The record of a job id, or None (queries such as ping have no record)."""
        for record in self.records:
            if record["id"] == job_id:
                return record
        return None

    def find_running(self):
        """The run in progress, or None."""
        for record in self.records:
            if record["status"] == "running":
                return record
        return None

    def _handle_control(self, kind, payload):
        record = self.find(payload.get("id"))
        if record is None:
            return
        if kind == "stage":
            stage = payload.get("stage")
            record["stage"] = stage
            record["stages"].append({"stage": stage, "label": payload.get("label", stage), "at": time.time()})
        elif kind == "result":
            record["summary"] = payload.get("summary")
        elif kind == "error":
            record["error"] = payload.get("message", "error in Julia")
        elif kind == "done":
            record["seconds"] = payload.get("seconds")
            record["ended_at"] = time.time()
            if record["status"] == "running":
                record["status"] = "finished" if payload.get("ok") else "failed"
        else:
            return
        call_listeners(self._listeners)

    def _handle_log(self, line, job_id):
        """Keep a run's latest line and its warnings. Quiet: the listeners are not called for a log line."""
        record = self.find(job_id)
        if record is None:
            return
        text = line.rsplit(chr(13), 1)[-1].strip()         # a progress line rewritten in place: its last state
        if not has_text(text):
            return
        record["last_line"] = text[:LAST_LINE_LENGTH]
        if is_warning(text):
            record["warnings"].append(text)

    def _handle_state(self, state, message=""):
        """Julia stopped or crashed: the run in progress will never report @@done."""
        if state not in ("stopped", "crashed"):
            return
        record = self.find_running()
        if record is None:
            return
        record["ended_at"] = time.time()
        if state == "stopped":
            record["status"] = "stopped"
            record["error"] = "stopped before it finished"
        else:
            record["status"] = "failed"
            record["error"] = message or "Julia exited"
        call_listeners(self._listeners)
