"""
Background job runner.

Phase 1 goal: prove that a long-running subprocess can be launched from
a Flask request, keep running after that request returns, and have its
status checked later via a separate poll. This is the pattern real
HandBrake/abcde rips will use later (Phase 3+) — for now we run a fake
command (`sleep`) so we can develop and test this without touching the
drive or competing with a real rip for CPU.

Design decisions (see DEVLOG for the dated version of this):

- Single global job at a time. This app only ever drives one physical
  optical drive, so there's never a need for multiple concurrent jobs.
  Trying to start a second job while one is running is rejected rather
  than queued — keeps the state model simple.
- Job status lives in an in-memory dict, not a database. If the app
  restarts mid-job, the job's status is lost (though the underlying
  subprocess, if it's something like HandBrake, would keep running
  orphaned — worth revisiting once we're running real rips). Acceptable
  trade-off for now; SQLite is an easy upgrade later if this becomes a
  problem.
- subprocess.Popen(), not subprocess.run(). run() blocks until the
  process finishes, which would freeze the Flask request (and the whole
  dev server, since Flask's dev server is single-threaded by default).
  Popen() starts the process and returns immediately, letting us poll
  it later.
- A background thread calls Popen().wait() so we notice when the job
  finishes (and capture its exit code) without the main Flask thread
  blocking on it.
"""

import subprocess
import threading
import time

# The one and only job's state. Intentionally simple — see module
# docstring for why this isn't a database (yet).
_job_lock = threading.Lock()
_job_state = {
    "state": "idle",       # idle | running | done | error
    "command": None,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
}


def get_status():
    """Return a snapshot of the current job's status."""
    with _job_lock:
        return dict(_job_state)  # copy, so callers can't mutate our state


def start_fake_job(duration_seconds=30):
    """
    Start a fake long-running job (just `sleep`) to prove the runner
    pattern works. Returns True if started, False if a job is already
    running.

    Phase 3 will add a start_rip_job() that runs HandBrakeCLI instead —
    same underlying pattern, real command.
    """
    with _job_lock:
        if _job_state["state"] == "running":
            return False  # refuse to start a second job

        _job_state["state"] = "running"
        _job_state["command"] = f"sleep {duration_seconds}"
        _job_state["started_at"] = time.time()
        _job_state["finished_at"] = None
        _job_state["returncode"] = None

    def _run():
        # This runs in a background thread. Popen starts the process;
        # .wait() blocks THIS thread (not the Flask request thread)
        # until it finishes, then we record the result.
        process = subprocess.Popen(["sleep", str(duration_seconds)])
        returncode = process.wait()

        with _job_lock:
            _job_state["state"] = "done" if returncode == 0 else "error"
            _job_state["finished_at"] = time.time()
            _job_state["returncode"] = returncode

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return True
