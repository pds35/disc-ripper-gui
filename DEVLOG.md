# Devlog

Newest entry on top. One entry per work session, not per commit. See
`BUILD-PROCESS.md` §3 for the format this follows.

---

## 2026-07-29 — Phase 0: repo scaffold

Set up the repo structure: `backend/`, `frontend/`, `sample-logs/`,
`docs/`, `deploy/`, plus README/DEVLOG/BUILD-PROCESS/.gitignore/.env.example.

Decision: Flask over FastAPI. Simpler mental model for a background
subprocess + polling pattern (Phase 1), no async/await concepts required
up front. Can revisit if a real need for async shows up later.

Decision: `app.run(host="0.0.0.0")` from the start, not `localhost` —
this needs to be reachable over Tailscale/LAN, not just from the Pi's
own desktop, so may as well bind correctly from day one.

Saved the first real HandBrake completion log (from a manual rip,
`2026-07-29 17:27:13`) into `sample-logs/` — plain text format, not
`--json` yet. Still useful as a first fixture; a `--json` run is needed
before Phase 3 (progress parsing).

Next: Phase 1 — background job runner. Prove a subprocess can be
launched from a Flask route and survive the request returning, with
status pollable via a separate endpoint.

Dead end: pasting `app.py`'s content via a `cat > file << 'EOF'` heredoc got
silently truncated partway through (46 of ~63 lines), leaving the shell stuck
waiting at a `>` prompt and the file syntactically broken. Not a WiFi issue
this time — on the Pi's own desktop, so likely just a large-paste buffering
quirk with that particular terminal. Fixed by using `nano` instead — pastes
into an editor buffer proved more reliable than a heredoc for large blocks.
