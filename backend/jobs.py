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
  trade-off for now.
- subprocess.Popen(), not subprocess.run(). run() blocks until the
  process finishes, which would freeze the Flask request (and the whole
  dev server, since Flask's dev server is single-threaded by default).
  Popen() starts the process and returns immediately, letting us poll
  it later.
- A background thread calls Popen().wait() so we notice when the job
  finishes (and capture its exit code) without the main Flask thread
  blocking on it.
- Finished-job history is persisted to SQLite (backend/history_db.py),
  so it survives an app restart. The *current* job's live status stays
  in-memory only, deliberately — persisting live progress too would
  mean a DB write on every poll, and we decided that wasn't worth it
  for a single-user homelab dashboard (see DEVLOG).
"""
import os
import subprocess
import threading
import time

import handbrake
import history_db

# Make sure the history table exists before anything tries to write to
# it. Cheap no-op if it's already there.
history_db.init_db()

# The one and only job's state. Intentionally simple — see module
# docstring for why this isn't a database (yet).
_job_lock = threading.Lock()
_job_state = {
    "state": "idle",       # idle | running | done | error | cancelled
    "command": None,
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "percent": None,        # 0-100, set once a real rip is running
    "eta_seconds": None,
    "rate_fps": None,
    "movie_title": None,
    "movie_year": None,
    "output_path": None,    # needed so cancel_job() can clean up a partial file
}

# The currently-running subprocess, if any — kept at module level (not
# just local to _run()) so cancel_job() can reach it from outside the
# background thread. Both fields are protected by _job_lock, same as
# _job_state.
_current_process = None
_cancel_requested = False


def get_history(limit=10):
    """Return the most recent completed jobs, most recent first.
    Reads from SQLite now, not the in-memory list — see module
    docstring."""
    return history_db.get_recent(limit)


def get_status():
    """Return a snapshot of the current job's status."""
    with _job_lock:
        return dict(_job_state)  # copy, so callers can't mutate our state


def cancel_job():
    """
    Request cancellation of the current running job.

    Sends SIGTERM first, so HandBrake gets a chance to exit cleanly
    rather than being killed mid-write. A background watchdog escalates
    to SIGKILL after 5 seconds if it's still alive (stuck, or ignoring
    the signal). Either way, once the process actually dies, the job's
    own _run() thread notices — it was already blocked on
    process.wait() — and does its normal cleanup, using
    _cancel_requested to mark the final state as "cancelled" instead of
    "error" (HandBrake's exit code after SIGTERM won't be 0, but this
    wasn't a failure, we asked for it).

    Also deletes the partial output file, if there is one — a half
    -encoded .mkv sitting at the real destination filename could get
    mistaken for a finished rip (by Plex, or by us) if left behind.

    Returns True if a cancel was requested, False if there was nothing
    running to cancel.
    """
    global _cancel_requested
    with _job_lock:
        if _job_state["state"] != "running" or _current_process is None:
            return False
        _cancel_requested = True
        process = _current_process
        output_path = _job_state.get("output_path")

    process.terminate()  # SIGTERM - ask nicely first

    def _escalate():
        time.sleep(5)
        if process.poll() is None:  # still alive after 5s of asking nicely
            process.kill()  # SIGKILL - not optional this time

    threading.Thread(target=_escalate, daemon=True).start()

    if output_path and os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass  # not worth failing the cancel over a cleanup step

    return True


def start_fake_job(duration_seconds=30):
    """
    Start a fake long-running job (just `sleep`) to prove the runner
    pattern works. Returns True if started, False if a job is already
    running.
    """
    global _cancel_requested
    with _job_lock:
        if _job_state["state"] == "running":
            return False  # refuse to start a second job
        _job_state["state"] = "running"
        _job_state["command"] = f"sleep {duration_seconds}"
        _job_state["started_at"] = time.time()
        _job_state["finished_at"] = None
        _job_state["returncode"] = None
        _job_state["output_path"] = None
        _cancel_requested = False

    def _run():
        global _current_process
        process = subprocess.Popen(["sleep", str(duration_seconds)])
        with _job_lock:
            _current_process = process
        returncode = process.wait()
        with _job_lock:
            if _cancel_requested:
                _job_state["state"] = "cancelled"
            else:
                _job_state["state"] = "done" if returncode == 0 else "error"
            _job_state["finished_at"] = time.time()
            _job_state["returncode"] = returncode
            _current_process = None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return True


def start_rip_job(device, title, audio_track, sub_track, output_path,
                   stderr_log_path, start_seconds=None, stop_seconds=None,
                   movie_title=None, movie_year=None):
    """
    Start a real HandBrakeCLI rip job, with live progress parsing.

    Unlike start_fake_job, this one actually reads the subprocess's
    stdout WHILE it's running (not just waiting for it to finish),
    feeding each line through handbrake.iter_progress_blocks() as it
    arrives. That's what makes /api/jobs/status show real, moving
    progress instead of just "running" until it's suddenly "done".

    stderr is redirected to stderr_log_path, NOT merged with stdout
    (no 2>&1) - merging corrupted JSON during scan testing (see
    DEVLOG.md), and the same risk applies here to live progress JSON.

    Returns True if started, False if a job is already running.
    """
    global _cancel_requested
    with _job_lock:
        if _job_state["state"] == "running":
            return False
        command_str = (
            "HandBrakeCLI -i " + device + " -t " + str(title)
            + " -a " + str(audio_track)
            + (" -s " + str(sub_track) if sub_track is not None else "")
            + " -o " + output_path
        )
        _job_state["state"] = "running"
        _job_state["command"] = command_str
        _job_state["started_at"] = time.time()
        _job_state["finished_at"] = None
        _job_state["returncode"] = None
        _job_state["percent"] = 0.0
        _job_state["eta_seconds"] = None
        _job_state["rate_fps"] = None
        _job_state["movie_title"] = movie_title
        _job_state["movie_year"] = movie_year
        _job_state["output_path"] = output_path
        _cancel_requested = False

    def _run():
        global _current_process
        with open(stderr_log_path, "w") as stderr_file:
            handbrake_command = [
                "HandBrakeCLI",
                "-i", device,
                "-t", str(title),
                "-a", str(audio_track),
                "-o", output_path,
                "--preset", "Fast 1080p30",
                "--comb-detect",
                "--decomb",
                "--json",
            ]
            # Some discs (e.g. a Pirates of the Caribbean disc found
            # during testing) have zero subtitle tracks - passing -s
            # with a track number that doesn't exist would fail, so
            # only include it when a real sub_track was given.
            if sub_track is not None:
                handbrake_command += ["-s", str(sub_track)]
            if start_seconds is not None:
                handbrake_command += ["--start-at", "duration:" + str(start_seconds)]
            if stop_seconds is not None:
                handbrake_command += ["--stop-at", "duration:" + str(stop_seconds)]
            process = subprocess.Popen(
                handbrake_command,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                bufsize=1,
            )
            with _job_lock:
                _current_process = process
            for block in handbrake.iter_progress_blocks(process.stdout):
                summary = handbrake.summarize_progress(block)
                with _job_lock:
                    _job_state["percent"] = summary["percent"]
                    _job_state["eta_seconds"] = summary["eta_seconds"]
                    _job_state["rate_fps"] = summary["rate_fps"]
            returncode = process.wait()
        with _job_lock:
            if _cancel_requested:
                _job_state["state"] = "cancelled"
            else:
                _job_state["state"] = "done" if returncode == 0 else "error"
            _job_state["finished_at"] = time.time()
            _job_state["returncode"] = returncode
            if _job_state["state"] == "done":
                _job_state["percent"] = 100.0
            history_entry = {
                "movie_title": movie_title,
                "movie_year": movie_year,
                "output_path": output_path,
                "state": _job_state["state"],
                "started_at": _job_state["started_at"],
                "finished_at": _job_state["finished_at"],
                "duration_seconds": _job_state["finished_at"] - _job_state["started_at"],
            }
            _current_process = None
        history_db.add_entry(history_entry)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return True

