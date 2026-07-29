# Disc Ripper GUI — Build Process

How we'll work through this project: repo setup, git workflow, devlog
technique, and phased milestones. Written for a solo learning project with
real hardware dependencies (Pi, SuperDrive, USB hub) — so testing and
documentation habits matter more than they would on a pure web app.

---

## 1. Repo structure

```
disc-ripper-gui/
├── README.md              # what this is, how to run it, current status
├── DEVLOG.md               # dated entries — decisions, dead ends, why
├── BUILD-PROCESS.md        # this file
├── .gitignore
├── .env.example             # documents required env vars, no real values
├── backend/
│   ├── app.py               # Flask/FastAPI entrypoint
│   ├── jobs.py               # background job runner
│   ├── handbrake.py           # subprocess wrapper + progress parsing
│   ├── abcde.py                # CD ripping wrapper
│   ├── drive.py                  # wake/eject/device detection
│   └── tests/
│       └── test_handbrake_parse.py
├── frontend/
│   ├── templates/
│   └── static/
├── sample-logs/              # real HandBrake output, for parser dev/tests
│   └── dvd-rip-2026-07-29.log
├── docs/
│   └── mockup.png             # the dashboard mockup, checked in
└── deploy/
    ├── Dockerfile
    └── disc-ripper.service        # systemd unit, if not using Docker
```

**Why check in `sample-logs/`:** you already have one real completed rip
transcript. Real HandBrake output — including a `--json` run once you grab
one — becomes your test fixture. Parsing logic gets developed and tested
against actual output, not guesses, and regressions get caught if a
HandBrake update changes the format.

---

## 2. GitHub setup

- **One repo**, public or private — your call, nothing here is sensitive
  as long as `.env` (real values) never gets committed.
- **`main` branch only, direct commits, for now.** Feature branches and PRs
  add process overhead that doesn't pay off solo until the codebase has
  multiple moving parts you're actively juggling. Revisit if you get to a
  point where you're maintaining two things in parallel (e.g. a stable
  version running on the Pi while developing a risky change).
- **Commit early, commit often.** Small, working commits beat big
  batched ones — easier to bisect if something breaks, easier to see
  progress in the log, and lower stakes per commit (less "am I ready to
  commit this?" hesitation).
- **Tag milestones**, not just commits: `v0.1-drive-control`,
  `v0.2-handbrake-scan`, etc. Cheap to do, gives you restore points, and
  turns the tag list into a second, higher-level project history.

### Commit message convention

Keep it simple — a short prefix, then plain description:

```
feat: add HandBrake JSON progress parser
fix: eject fallback chain wasn't retrying step 2
docs: update devlog with subprocess threading decision
chore: add sample HandBrake json log for tests
```

Doesn't need to be strict conventional-commits tooling — just consistent
enough that `git log --oneline` reads like a story.

---

## 3. Devlog technique

This is the part that pays off most for a learning project — six months
from now, "why did I do it this way" is a real question, and commit
messages alone won't answer it.

**`DEVLOG.md`, newest entry on top, one entry per work session** (not per
commit). Loose format:

```markdown
## 2026-07-29 — Background job runner proof of concept

Got a subprocess launched from Flask that survives the request returning.
Tried threading first — simplest option for single-user/single-job.

Decision: storing job status in an in-memory dict, not SQLite yet. If the
app restarts mid-rip, the job is lost — acceptable for now, revisit if it
becomes annoying.

Dead end: tried using subprocess.run() (blocking) before realizing I
needed Popen() + polling. Should've been obvious from the start but wasted
~30 min.

Next: parse HandBrake --json progress output instead of scraping percent
from the text log.
```

Three things worth capturing every time: **what you decided**, **why**
(even one line), and **what didn't work** — the dead ends are often more
useful in six months than the successes, since you won't remember why you
*didn't* do the obvious thing.

This can live entirely in the repo (no separate tool needed) and doubles
as your project memory when we pick things back up in a new conversation —
paste in recent DEVLOG entries and I'll have the context immediately.

---

## 4. Phased milestones

Building in an order that front-loads the riskiest/least-known piece
(background job + progress streaming), since getting that wrong costs the
most rework later. Everything else is comparatively self-contained and
slots in once the skeleton works.

| Phase | Goal | Tag |
|---|---|---|
| 0 | Repo scaffolded, `.gitignore`, empty Flask/FastAPI app runs | `v0.0-scaffold` |
| 1 | Background job runner: launch a long subprocess, poll status via HTTP, survives browser disconnect | `v0.1-job-runner` |
| 2 | Drive wake + eject (with fallback chain) exposed as endpoints | `v0.2-drive-control` |
| 3 | HandBrake scan + `--json` progress parsing, tested against real logs | `v0.3-handbrake` |
| 4 | Rip → correct Plex path/naming/ownership, end-to-end for one disc | `v0.4-rip-to-plex` |
| 5 | Frontend dashboard wired to real backend (replacing the static mockup) | `v0.5-dashboard` |
| 6 | abcde/CD audio path | `v0.6-cd-audio` |
| 7 | systemd unit or Docker container, runs unattended | `v0.7-deploy` |
| 8 | (stretch) udev auto-detect, auth if needed | `v1.0` |

Each phase should end in something you can actually run and see work on
the Pi — not just code that compiles. That's the natural checkpoint for a
commit, a tag, and a devlog entry.

---

## 5. Testing approach

Hardware-in-the-loop means you can't unit-test everything, so split by
what actually needs the Pi + drive attached:

- **Needs real hardware** (manual test each time, checklist-style):
  drive wake, eject fallback chain, actual rip end-to-end. Keep a short
  checklist in the repo (`docs/manual-test-checklist.md`) you run through
  before tagging a release.
- **Pure logic, testable without hardware** (real unit tests):
  HandBrake JSON progress parsing, path/filename construction for Plex,
  job-status state transitions. These are the functions most likely to
  have subtle bugs and least likely to need a live disc to test — write
  these against the `sample-logs/` fixtures.

If you want, a lightweight GitHub Actions workflow can run the pure-logic
tests on every push — catches regressions in the parser without needing
the Pi. Not essential for phase 0-1, worth adding once phase 3 lands.

---

## 6. Secrets / config hygiene

Nothing in the current brief is sensitive (IPs are LAN/Tailscale-only), but
good habit to start now:

- `.env` for anything that might become sensitive later (paths, ports,
  future auth tokens) — `.gitignore`'d.
- `.env.example` checked in, showing the required keys with dummy values.
- Never hardcode absolute paths like `/mnt/nvme/media/...` deep in logic —
  pull from config so the same code could point elsewhere without editing
  source.

---

## Next step

Start with **Phase 0** — scaffold the repo with this structure, get an
empty app running and committed, tag `v0.0-scaffold`. That's a clean,
low-stakes first commit to build on, and from there Phase 1 (the job
runner) is the real first engineering problem to solve.
