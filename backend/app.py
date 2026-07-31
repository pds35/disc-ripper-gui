"""
Disc Ripper GUI — Flask entrypoint.

Phase 1: background job runner proof of concept. /api/jobs/start kicks
off a fake long-running job (see jobs.py) without blocking the request;
/api/jobs/status polls its progress. Real HandBrake/abcde jobs replace
the fake one in Phase 3+ — the request/poll pattern stays the same.
"""
import time

from flask import Flask, jsonify, render_template

import drive
import handbrake
import jobs
import plex

# templates/static live in ../frontend, not the default ./templates
# next to this file - point Flask at the right place explicitly.
app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static",
)

@app.route("/")
def index():
    """Phase 5: the real dashboard page."""
    return render_template("index.html")

@app.route("/api/health")
def health():
    """
    Simple health check endpoint.

    Useful now to confirm the app is alive, and later as something
    systemd/Docker health checks (Phase 7) or the frontend's polling
    loop can hit to confirm the backend is reachable.
    """
    return jsonify(status="ok")


@app.route("/api/jobs/start", methods=["POST"])
def start_job():
    """
    Start a fake job (Phase 1 proof of concept — just `sleep 30`).

    Returns immediately even though the "job" keeps running for 30
    seconds in the background. That's the whole point: proving the
    request doesn't block on the job's duration.
    """
    started = jobs.start_fake_job(duration_seconds=30)
    if not started:
        # 409 Conflict: there's already a job running, refuse to start
        # a second one rather than queuing it (see jobs.py docstring).
        return jsonify(error="a job is already running"), 409
    return jsonify(message="fake job started"), 202


@app.route("/api/rip/start", methods=["POST"])
def rip_start():
    """
    Phase 4: the real rip endpoint. Takes movie title/year and track
    choices from the request body, builds the correct Plex path,
    creates and owns the destination folder, then starts the actual
    HandBrakeCLI rip job writing straight to that path.

    Expects JSON body:
        {
            "title": "Batman Begins",
            "year": 2005,
            "handbrake_title": 1,
            "audio_track": 1,
            "sub_track": 1
        }
    """
    from flask import request

    data = request.get_json(force=True)
    movie_title = data.get("title")
    movie_year = data.get("year")
    handbrake_title = data.get("handbrake_title")
    audio_track = data.get("audio_track")
    sub_track = data.get("sub_track")

    if not all([movie_title, movie_year, handbrake_title, audio_track]):
        return jsonify(error="title, year, handbrake_title, and audio_track are required"), 400

    paths = plex.build_movie_paths(movie_title, movie_year)

    dir_result = plex.ensure_movie_directory(paths["folder_path"])
    if not dir_result["success"]:
        return jsonify(error="Could not prepare destination folder: " + dir_result["output"]), 500
    
    stderr_log_path = "/tmp/rip-" + str(int(time.time())) + "-stderr.log"

    # Optional - lets us test the pipeline against a short slice instead
    # of committing to a full 1-3 hour rip every time we test something.
    start_seconds = data.get("start_seconds")
    stop_seconds = data.get("stop_seconds")

    started = jobs.start_rip_job(
        device="/dev/sr0",
        title=handbrake_title,
        audio_track=audio_track,
        sub_track=sub_track,
        output_path=paths["file_path"],
        stderr_log_path=stderr_log_path,
        start_seconds=start_seconds,
        stop_seconds=stop_seconds,
        movie_title=movie_title,
        movie_year=movie_year,
    )

    if not started:
        return jsonify(error="a job is already running"), 409

    return jsonify(
        message="rip started",
        output_path=paths["file_path"],
        stderr_log_path=stderr_log_path,
    ), 202

@app.route("/api/jobs/status")
def job_status():
    """Poll this to see the current job's state."""
    return jsonify(jobs.get_status())

@app.route("/api/jobs/cancel", methods=["POST"])
def cancel_job():
    """
    Cancel the currently running job (rip or fake job).
    Sends SIGTERM to the subprocess (escalating to SIGKILL after 5s if
    it doesn't exit), deletes any partial output file, and marks the
    job "cancelled" once it actually stops — see jobs.cancel_job() for
    the full sequence.
    """
    cancelled = jobs.cancel_job()
    if not cancelled:
        return jsonify(error="no job is currently running"), 409
    return jsonify(message="cancel requested"), 202


@app.route("/api/drive/wake", methods=["POST"])
def wake_drive():
    """Send the SuperDrive wake-up command. Safe to call any time."""
    result = drive.wake_drive()
    status_code = 200 if result["success"] else 502
    return jsonify(result), status_code


@app.route("/api/drive/eject", methods=["POST"])
def eject_drive():
    """
    Run the eject fallback chain.

    Refuses to eject while a job is actively running — pulling the disc
    mid-rip would corrupt the rip and likely confuse HandBrake rather
    than cleanly failing. The person has to wait for the job to finish
    or hit "cancel" firstsee /api/jobs/cancel) if they want the disc back sooner.
    """
    if jobs.get_status()["state"] == "running":
        return jsonify(error="cannot eject while a job is running"), 409

    result = drive.eject_drive()
    status_code = 200 if result["success"] else 502
    return jsonify(result), status_code


@app.route("/api/stats")
def stats():
    """
    Quick stats + recent activity for the dashboard (Phase 5).

    drive_status is a simplification for now: "busy" if a job is
    running, "idle" otherwise. A real drive-presence check (is a disc
    even in the tray) would need udev/lsusb work - worth revisiting
    later, not needed for the dashboard to be useful today.
    """
    import shutil

    job_status = jobs.get_status()
    drive_status = "busy" if job_status["state"] == "running" else "idle"

    history = jobs.get_history(limit=50)
    today_start = time.time() - (time.time() % 86400)
    discs_ripped_today = sum(
        1 for entry in history
        if entry["state"] == "done" and entry["finished_at"] >= today_start
    )

    try:
        usage = shutil.disk_usage(plex.DEFAULT_MOVIES_BASE_DIR)
        free_space_gb = round(usage.free / (1024 ** 3), 1)
    except OSError:
        free_space_gb = None

    return jsonify(
        drive_status=drive_status,
        discs_ripped_today=discs_ripped_today,
        free_space_gb=free_space_gb,
        recent_activity=jobs.get_history(limit=5),
    )
@app.route("/api/scan", methods=["POST"])
def scan_disc():
    """
    Phase 5: run a real disc scan and return the main feature's info
    (duration, audio/subtitle tracks) so the dashboard can show a
    track picker before starting a rip.

    This can take anywhere from ~10 seconds to ~60 seconds depending
    on the disc (see DEVLOG.md) - that's why threaded=True matters for
    the dev server, and why this is a manual "Scan Disc" button rather
    than something that runs automatically on every page load.
    """
    import subprocess as scan_subprocess

    wake_result = drive.wake_drive()
    if not wake_result["success"]:
        return jsonify(error="Could not wake drive: " + wake_result["output"]), 502

    scan_result = scan_subprocess.run(
        ["HandBrakeCLI", "-i", "/dev/sr0", "-t", "0", "--scan", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    try:
        summary = handbrake.parse_scan_output(scan_result.stdout)
    except handbrake.ScanParseError as e:
        return jsonify(error="Scan failed: " + str(e)), 502

    return jsonify(success=True, **summary)

if __name__ == "__main__":
    # debug=True gives auto-reload + a debugger during development.
    # host="0.0.0.0" so it's reachable over the LAN/Tailscale, not just
    # localhost on the Pi itself — matters since this needs to be
    # reachable remotely per the project brief.

    # threaded=True: without this, Flask's dev server handles one
    # request at a time - a slow disc scan (can take up to ~60s, see
    # DEVLOG.md) would freeze the dashboard's live status polling for
    # its whole duration. threaded=True lets requests run concurrently.
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
