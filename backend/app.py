"""
Disc Ripper GUI — Flask entrypoint.

Phase 0 goal: get an empty app running and confirm the skeleton works.
No drive control, no HandBrake, no job runner yet — those come in later
phases (see BUILD-PROCESS.md).
"""

from flask import Flask, jsonify

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


if __name__ == "__main__":
    # debug=True gives auto-reload + a debugger during development.
    # host="0.0.0.0" so it's reachable over the LAN/Tailscale, not just
    # localhost on the Pi itself — matters since this needs to be
    # reachable remotely per the project brief.
    app.run(host="0.0.0.0", port=5000, debug=True)
