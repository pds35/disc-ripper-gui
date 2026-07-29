"""
Disc Ripper GUI — Flask entrypoint.

Phase 1: background job runner proof of concept. /api/jobs/start kicks
off a fake long-running job (see jobs.py) without blocking the request;
/api/jobs/status polls its progress. Real HandBrake/abcde jobs replace
the fake one in Phase 3+ — the request/poll pattern stays the same.
"""

from flask import Flask, jsonify

import drive
import jobs

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
