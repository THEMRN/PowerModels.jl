"""
Python client for the GUI's Julia worker (runners/gui/worker.jl). The protocol is in
runners/gui/gui_plan.md ("Contracts: Worker protocol").

One long-lived `julia --project=. runners/gui/worker.jl`, started from the repo root. Jobs are
JSON lines on its stdin. Its stdout and stderr are merged and read line by line: ordinary log
lines, and control lines "@@<kind> <json>". Listeners get every log line, every control message
and every state change. Everything here runs on the asyncio event loop of the GUI.
"""

import asyncio
import json
import os
import subprocess
import traceback
from pathlib import Path

# ==================== Settings ====================
JULIA = "julia"
WORKER_SCRIPT = "runners/gui/worker.jl"         # relative to the repo root
LINE_LIMIT = 16 * 1024 * 1024                   # bytes, longest output line (asyncio's 64 KiB default is too short for @@result)
STOP_TIMEOUT = 10.0                             # s, wait for the process to exit after taskkill
# own process group: Ctrl+Break in the app's console reaches only the app, which then stops the
# worker with its children. (A keyboard Ctrl+C still reaches Julia, which handles it itself.)
CREATION_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
STATES = ("starting", "ready", "busy", "stopped", "crashed")


class WorkerError(Exception):
    """A job that got no reply: it failed in Julia (JobError), or the worker is not running."""


class JobError(WorkerError):
    """A job that failed in Julia: the message of its @@error."""


def parse_control(line):
    """(kind, payload) of a control line "@@kind {json}", or None for an ordinary log line."""
    if not line.startswith("@@"):
        return None
    kind, _, payload_text = line[2:].partition(" ")
    if not payload_text.strip():
        return kind, {}
    try:
        return kind, json.loads(payload_text)
    except json.JSONDecodeError:
        return None


def call_listeners(listeners, *args):
    """Call every listener; one that fails is reported on the console and does not stop the others."""
    for listener in list(listeners):
        try:
            listener(*args)
        except Exception:
            traceback.print_exc()


class JuliaWorker:
    """
    The Julia worker process and its job protocol.

    `state` is one of STATES: "starting" until @@ready, "ready", "busy" while jobs are pending,
    "stopped" after stop(), "crashed" when the process exits by itself (or cannot start); `message`
    says why. Job ids keep counting across restarts. `job_logs` holds each job's log lines and
    `worker_log` the lines printed outside any job (startup, precompilation). `job_types` gives
    each job's type, `current_type()` the type of the job Julia is on, and `answered_types` the
    types of job this Julia has finished since it started (the first of a type compiles, so it is
    slower).
    """

    def __init__(self, repo_root):
        self.repo_root = Path(repo_root)
        self.state = "stopped"
        self.message = ""                       # why the worker stopped or crashed
        self.julia_version = ""
        self.pid = None
        self.job_logs = {}                      # job id -> log lines
        self.job_types = {}                     # job id -> its type ("run", "case_info", "network", ...)
        self.answered_types = set()             # types of job this Julia process has finished
        self.worker_log = []
        self._process = None
        self._next_id = 1
        self._pending = {}                      # job id -> future of a request's reply, or None for send()
        self._current_job = None                # job between its @@start and @@done
        self._stopping = False
        self._watcher = None
        self._lifecycle_lock = asyncio.Lock()   # start, stop and restart one at a time
        self._log_listeners = []
        self._control_listeners = []
        self._state_listeners = []

    # ==================== Listeners ====================
    def on_log(self, listener):
        """Call `listener(line, job_id)` for each log line (`job_id` None outside a job). Returns its remover."""
        return self._add_listener(self._log_listeners, listener)

    def on_control(self, listener):
        """Call `listener(kind, payload)` for each control line. Returns its remover."""
        return self._add_listener(self._control_listeners, listener)

    def on_state(self, listener):
        """Call `listener(state, message)` on each state change. Returns its remover."""
        return self._add_listener(self._state_listeners, listener)

    @staticmethod
    def _add_listener(listeners, listener):
        listeners.append(listener)

        def remove():
            if listener in listeners:
                listeners.remove(listener)

        return remove

    def _set_state(self, state, message=""):
        self.state = state
        self.message = message
        call_listeners(self._state_listeners, state, message)

    # ==================== Lifecycle ====================
    async def start(self):
        """Start the worker process: "starting" now, "ready" when Julia sends @@ready."""
        async with self._lifecycle_lock:
            await self._start()

    async def stop(self):
        """Kill the worker with its child processes (dynamic.py) and wait until it has exited."""
        async with self._lifecycle_lock:
            await self._stop()

    async def restart(self):
        """Stop the worker, then start a fresh one."""
        async with self._lifecycle_lock:
            await self._stop()
            await self._start()

    def is_running(self):
        return self._process is not None and self._process.returncode is None

    async def _start(self):
        if self.is_running():
            return
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"   # dynamic.py output streams instead of arriving in blocks
        environment["PYTHONIOENCODING"] = "utf-8"
        self.julia_version = ""
        self.answered_types = set()
        self._stopping = False
        self._set_state("starting")
        try:
            process = await asyncio.create_subprocess_exec(
                JULIA, "--project=.", WORKER_SCRIPT,
                cwd=self.repo_root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=environment,
                limit=LINE_LIMIT,
                creationflags=CREATION_FLAGS,
            )
        except OSError as error:
            self._process = None
            self.pid = None
            self._set_state("crashed", f"could not start {JULIA}: {error}")
            return
        self._process = process
        self.pid = process.pid
        asyncio.create_task(self._read_output(process))
        self._watcher = asyncio.create_task(self._watch_exit(process))

    async def _stop(self):
        process = self._process
        if process is None or process.returncode is not None:
            if self.state != "crashed":
                self._set_state("stopped")
            return
        self._stopping = True
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(process.pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
        try:
            await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
        except TimeoutError:
            process.kill()
        await self._watcher                     # sets "stopped" and fails the pending jobs

    async def _watch_exit(self, process):
        """Wait for the process to exit; without stop() that is a crash. Pending jobs fail either way."""
        return_code = await process.wait()
        if process is not self._process:
            return
        self._current_job = None
        self._fail_pending(f"Julia exited (code {return_code})")
        if self._stopping:
            self._set_state("stopped")
        else:
            self._set_state("crashed", f"Julia exited by itself (code {return_code})")

    # ==================== Output ====================
    async def _read_output(self, process):
        """Read the worker's output line by line until the pipe closes, or until a newer process replaces it."""
        while True:
            try:
                raw_line = await process.stdout.readline()
            except ValueError:                  # longer than LINE_LIMIT; asyncio has dropped it
                raw_line = b"[output line longer than LINE_LIMIT skipped]\n"
            if not raw_line or process is not self._process:
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            try:
                self._handle_line(line)
            except Exception:
                traceback.print_exc()           # keep reading: a full pipe would block Julia

    def _handle_line(self, line):
        control = parse_control(line)
        if control is None:
            if self._current_job is None:
                self.worker_log.append(line)
            else:
                self.job_logs.setdefault(self._current_job, []).append(line)
            call_listeners(self._log_listeners, line, self._current_job)
            return

        kind, payload = control
        self._handle_control(kind, payload)
        call_listeners(self._control_listeners, kind, payload)

    def _handle_control(self, kind, payload):
        """Follow the job protocol: state, current job, and the replies of requests."""
        job_id = payload.get("id")
        if kind == "ready":
            self.julia_version = payload.get("julia", "")
            self._set_state("busy" if self._pending else "ready")
        elif kind == "start":
            self._current_job = job_id
            self.job_logs.setdefault(job_id, [])
        elif kind == "data":
            self._resolve(job_id, payload)
        elif kind == "error":
            self._reject(job_id, payload.get("message", "error in Julia"), JobError)
        elif kind == "done":
            self._current_job = None
            self.answered_types.add(self.job_types.get(job_id))
            self._reject(job_id, "the job finished without a reply")    # only a request still waiting
            self._pending.pop(job_id, None)
            if not self._pending and self.state == "busy":
                self._set_state("ready")

    def _resolve(self, job_id, payload):
        future = self._pending.get(job_id)
        if future is not None and not future.done():
            future.set_result(payload)

    def _reject(self, job_id, message, error_type=WorkerError):
        future = self._pending.get(job_id)
        if future is not None and not future.done():
            future.set_exception(error_type(message))

    def _fail_pending(self, message):
        for job_id in list(self._pending):
            self._reject(job_id, message)
        self._pending.clear()

    # ==================== Jobs ====================
    def current_type(self):
        """The type of the job Julia is on (between its @@start and @@done), or None."""
        return self.job_types.get(self._current_job) if self._current_job is not None else None

    def send(self, job):
        """
        Send a job (a dict with "type") and return the id it was given, before any of its output
        can arrive; the output comes through the listeners. Raises WorkerError when Julia is not running.
        """
        return self._send(job, None)

    async def request(self, job):
        """Send a query job (ping, list_cases, case_info) and return its @@data payload. Raises WorkerError on @@error."""
        future = asyncio.get_running_loop().create_future()
        self._send(job, future)
        return await future

    def _send(self, job, future):
        if not self.is_running() or self.state in ("stopped", "crashed"):
            raise WorkerError(f"Julia is {self.state}")
        job_id = self._next_id
        self._next_id += 1
        message = dict(job)
        message["id"] = job_id
        self._pending[job_id] = future
        self.job_logs[job_id] = []
        self.job_types[job_id] = job["type"]
        if self.state == "ready":
            self._set_state("busy")
        # a job is one short line, so the write is not awaited; a worker that died is caught by its exit watcher
        self._process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        return job_id
