# Disc Ripper GUI

A web-based dashboard for ripping DVDs/CDs on a Raspberry Pi 5 homelab,
wrapping a manual HandBrakeCLI/abcde workflow that's already proven to
work. Built as a learning project — see `BUILD-PROCESS.md` for how this
gets developed, and `DEVLOG.md` for a running log of decisions and dead
ends.

## Status

**Phase 0 — scaffold.** Empty Flask app runs. No drive control, no
ripping, no dashboard yet.

## Running it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python backend/app.py
```

Then visit `http://<pi-address>:5000/` (or `http://localhost:5000/` if
running directly on the Pi's desktop).

## Project docs

- `BUILD-PROCESS.md` — repo conventions, git workflow, phased milestones
- `DEVLOG.md` — dated log of what was tried, what worked, what didn't
- `docs/manual-test-checklist.md` — hardware checks to run before tagging
  a release (added once there's something to check)
