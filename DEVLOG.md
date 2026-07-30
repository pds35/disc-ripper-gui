# Devlog

Newest entry on top. One entry per work session, not per commit. See
`BUILD-PROCESS.md` §3 for the format this follows.

---

## 2026-07-30 - Phase 3: HandBrake scan-JSON parser, built and tested incrementally

Built handbrake.py in small, individually-verified chunks (syntax
check + functional test after each function) rather than pasting the
whole file at once, after two separate large-paste failures earlier
this session (a stuck heredoc, and a truncated nano paste that broke
drive.py entirely last session). This approach was slower but every
single piece was confirmed working before the next was added, and
caught nothing needing rework.

Core design: extract_title_set_json() finds and parses just the
"JSON Title Set: {...}" block out of raw --json scan stdout (confirmed
this version of HandBrake uses that exact tag, not "JSON:" as assumed
earlier). get_main_feature() and summarize_title() turn that into a
clean, frontend-friendly summary: index, duration, audio tracks,
subtitle tracks.

Verified against real fixtures, not just synthetic data:
- Disc 1 (the movie): correctly identifies title 1, duration 2:14:17,
  2 audio tracks (English/German), 8 subtitle tracks including
  non-Latin scripts (Arabic, Hebrew, Icelandic) - all decoded cleanly.
- Disc 2 (bonus features): correctly identifies its MainFeature as
  short (10:42), well under any real movie length - a genuine sanity
  check that the parser isn't just trusting HandBrake blindly.
- The corrupted merged-stdout/stderr file from last session: correctly
  rejected with a clear ScanParseError instead of a confusing raw
  JSONDecodeError.

Found one more real data quirk along the way: Disc 2's stdout contains
a literal invalid byte sequence (\xff\xff) that libdvdnav itself
writes as a placeholder when it can't find an expected language code
("Language 'en' not found, using '\xff\xff' instead"). Not a capture
bug this time - genuine non-UTF-8 output from the tool itself. Fixed
by reading files with encoding='utf-8', errors='replace' rather than
strict decoding. Worth remembering for the real jobs.py/handbrake.py
integration later: any file read of HandBrake output should use the
same lenient decoding, since real discs can trigger this.

Full pytest suite (8 tests) passes against real fixtures - see
backend/tests/test_handbrake_parse.py. Committed as two separate
commits (handbrake.py, then the test suite) rather than one, matching
the "small working commits" convention from BUILD-PROCESS.md.

Next: the harder half of Phase 3 - live progress parsing from an
actual running HandBrakeCLI rip (not just a scan). Will need to apply
today's stdout/stderr-separation lesson to a long-running subprocess
this time, not just a one-shot scan capture. Once


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

## 2026-07-30 - Phase 3 prep: HandBrake JSON scan fixtures, found a real stream-mixing bug

Grabbed a --json scan of a Dark Knight disc as a Phase 3 fixture.
First attempt merged stdout and stderr (2>&1), which produced JSON
that failed to parse - json.load choked on an invalid control
character. Root cause: HandBrake's "HandBrake has exited." status
message got interleaved mid-word into a JSON key because stdout (the
JSON) and stderr (log text) are separate streams that can get spliced
together when merged. Fix: capture them to separate files instead.
This matters for jobs.py/handbrake.py too - live progress parsing
during a real rip needs the same stream separation, or progress JSON
could get corrupted mid-object the same way.

Also found (then confirmed deliberately): the disc initially loaded
was Dark Knight Disc 2 (bonus features), not Disc 1 - obvious from
title durations all under 15 minutes. Swapped to Disc 1 and rescanned.

Confirmed against Disc 1: the scan's top-level MainFeature field gives
the movie's title Index directly (MainFeature: 1, matching Index 1,
duration 2:14:17). Simpler and more robust than parsing a per-title
text label. Cross-checked against sorting all titles by duration -
MainFeature was also the longest title.

Fixtures now in sample-logs/: original manual completion log, Disc 2
scan (json + split stdout/stderr), Disc 1 scan (clean json + split
stdout/stderr).

Next: write handbrake.py's scan-JSON parser against these fixtures as
real unit tests. Then live progress parsing from a running rip.
