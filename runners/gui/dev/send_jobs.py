"""Send jobs to the GUI worker from the command line, to test worker.jl without the GUI.

Usage, from the repo root:
    python runners/gui/dev/send_jobs.py [--full] runners/gui/dev/job_savnw.json [more job files ...]

Each job file holds one job or a list of jobs ({"type": "run", "settings": {...}}; the id is
added here). The worker is started the way the GUI starts it, every line it prints is shown,
control lines (@@...) are marked with ">>" and cut to CONTROL_PREVIEW characters unless
--full is given, and the script ends after the last job's @@done with a summary of the jobs.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ==================== Settings ====================
REPO_ROOT = Path(__file__).resolve().parents[3]
JULIA = "julia"
WORKER = "runners/gui/worker.jl"
CONTROL_PREVIEW = 300      # characters of a control line shown without --full


def load_jobs(job_files):
    """Jobs from the job files, in order, each with an id (1, 2, ...)."""
    jobs = []
    for job_file in job_files:
        content = json.loads(Path(job_file).read_text(encoding="utf-8"))
        file_jobs = content if isinstance(content, list) else [content]
        jobs.extend(file_jobs)
    for job_id, job in enumerate(jobs, start=1):
        job["id"] = job_id
    return jobs


def start_worker():
    """The worker process, started from the repo root with its output merged into one pipe."""
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"      # dynamic.py output streams instead of arriving in blocks
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        [JULIA, "--project=.", WORKER],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )


def read_line(worker):
    """Next output line of the worker without its line ending, or None when the worker has exited."""
    raw_line = worker.stdout.readline()
    if not raw_line:
        return None
    return raw_line.decode("utf-8", errors="replace").rstrip("\r\n")


def parse_control(line):
    """(kind, payload) of a control line "@@kind {json}", or None for an ordinary log line."""
    if not line.startswith("@@"):
        return None
    kind, _, payload = line[2:].partition(" ")
    return kind, (json.loads(payload) if payload.strip() else {})


def wait_for_control(worker, wanted_kind, job_id=None, full=False):
    """Print the worker's output until the control line `wanted_kind` (for `job_id`) arrives; return its payload."""
    while True:
        line = read_line(worker)
        if line is None:
            sys.exit(f"worker exited with code {worker.wait()}")
        control = parse_control(line)
        if control is None:
            print(line)
            continue
        kind, payload = control
        shown = json.dumps(payload)
        if not full:
            shown = shown[:CONTROL_PREVIEW]
        print(f">> @@{kind} {shown}")
        if kind == wanted_kind and (job_id is None or payload.get("id") == job_id):
            return payload


def main():
    full = "--full" in sys.argv[1:]
    job_files = [arg for arg in sys.argv[1:] if arg != "--full"]
    if not job_files:
        sys.exit(__doc__)
    jobs = load_jobs(job_files)

    # start the worker
    started = time.time()
    worker = start_worker()
    wait_for_control(worker, "ready")
    print(f">> worker ready after {time.time() - started:.1f} s")

    # send the jobs one at a time
    finished_jobs = []
    for job in jobs:
        worker.stdin.write((json.dumps(job) + "\n").encode("utf-8"))
        worker.stdin.flush()
        done = wait_for_control(worker, "done", job["id"], full)
        finished_jobs.append((job, done))

    # stop the worker
    worker.stdin.close()
    worker.wait()

    print("---------------------------")
    for job, done in finished_jobs:
        status = "ok" if done.get("ok") else "FAILED"
        print(f"job {job['id']} ({job.get('type')}): {status} in {done.get('seconds')} s")


if __name__ == "__main__":
    main()
