"""
Disc Ripper GUI — Flask entrypoint.

Phase 1: background job runner proof of concept. /api/jobs/start kicks
off a fake long-running job (see jobs.py) without blocking the request;
/api/jobs/status polls its progress. Real HandBrake/abcde jobs replace
the fake one in Phase 3+ — the request/poll pattern stays the same.
"""
import time

from flask import Flask, jsonify

import drive
import jobs
import plex

app = Flask(__name__)


@app.route("/")
def index():
    """Placeholder home route — will become the dashboard in Phase 5."""
    return "Disc Ripper GUI is running. (Phase 0 — no functionality yet.)"


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

@app.route("/api/jobs/start_rip", methods=["POST"])
def start_rip():
    """
    Start a REAL HandBrakeCLI rip job (Phase 3 live progress test).

    Hardcoded to a 90-second test clip for now (title 1, start-at 0,
    stop-at 90) - this is a manual test route, not the real rip
    endpoint the frontend will eventually use in Phase 4/5, which will
    take title/track/output-path from the request body instead.
    """
    started = jobs.start_rip_job(
        device="/dev/sr0",
        title=1,
        audio_track=1,
        sub_track=1,
        output_path="/tmp/test-clip-live.mkv",
        stderr_log_path="/tmp/test-clip-live-stderr.log",
        start_seconds=0,
        stop_seconds=90,
    )
    if not started:
        return jsonify(error="a job is already running"), 409
    return jsonify(message="rip job started"), 202



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
    (or we could add a "cancel job" endpoint later if that's needed).
    """
    if jobs.get_status()["state"] == "running":
        return jsonify(error="cannot eject while a job is running"), 409

    result = drive.eject_drive()
    status_code = 200 if result["success"] else 502
    return jsonify(result), status_code


if __name__ == "__main__":
    # debug=True gives auto-reload + a debugger during development.
    # host="0.0.0.0" so it's reachable over the LAN/Tailscale, not just
    # localhost on the Pi itself — matters since this needs to be
    # reachable remotely per the project brief.
    app.run(host="0.0.0.0", port=5000, debug=True)
