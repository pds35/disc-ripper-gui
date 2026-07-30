# Devlog

Newest entry on top. One entry per work session, not per commit. See
`BUILD-PROCESS.md` §3 for the format this follows.

---
## 2026-07-30 - Phase 4 complete: rip to correct Plex path, ownership, real end-to-end test

Built plex.py: build_movie_paths() constructs the exact Plex-convention
path from the brief ("Title (Year)/Title (Year).mkv"), with a
sanitize function that strips filesystem-unsafe characters (slashes,
wildcards) while keeping common movie-title punctuation (colons,
apostrophes, dashes) intact - important since real titles like
"Pirates of the Caribbean: At World's End" need that punctuation
preserved for correct Plex matching. ensure_movie_directory() creates
the folder and chowns it to pauls:pauls per the brief's requirement.
Tested for real against the actual /mnt/nvme/media/movies path -
confirmed no sudo needed, since Flask already runs as pauls.

Found and fixed a real edge case along the way: the Pirates disc has
exactly ONE title and zero subtitle tracks. Two fixes needed:
get_main_feature() now treats a single-title disc as the main feature
even when HandBrake reports MainFeature as -1 (added a real unit test
for this). jobs.py's start_rip_job() now only passes HandBrakeCLI's -s
flag when a real sub_track is given, instead of always passing one -
a disc with no subtitles would otherwise get a nonsensical -s flag.

Added /api/rip/start: the real Phase 4 endpoint. Takes title/year/
track choices, builds the Plex path, creates+owns the folder, then
starts the actual rip writing straight to that path. Also accepts
optional start_seconds/stop_seconds - genuinely useful (not just a
testing hack) for previewing a short slice before committing to a
multi-hour full rip.

Tested for real, fully end-to-end: scanned the Pirates disc, hit
/api/rip/start with a 60-second slice, watched it complete via
/api/jobs/status (state done, percent 100, returncode 0), then
confirmed the actual file landed at the exact right path with correct
pauls:pauls ownership - "Pirates of the Caribbean: At World's End
(2007).mkv" inside a correctly-named folder, colon and apostrophe
intact. Deleted the test clip afterward so it doesn't confuse the real
Plex library.

Hit one real paste-corruption bug today doing a nano find-and-replace
edit in the middle of jobs.py (two separate lines got fused together,
same failure class as previous sessions, but this time during an
in-place edit rather than a big multi-line paste). Fixed with a small,
targeted Python script rather than re-pasting the whole edit. Worth
remembering: appending new code at the end of a file has been
reliable all project; editing/replacing text in the MIDDLE of an
existing file via manual nano find-replace is the riskier operation on
this terminal - prefer scripted replacements (or full-file rewrites)
for anything beyond a trivial one-line change.

Full test suite: 15 tests passing (9 handbrake.py, 6 plex.py).
Committed and tagged v0.4-rip-to-plex.

Next: Phase 5 - wire the frontend dashboard (the mockup) to this real
backend, replacing manual curl calls with an actual UI. Could also
revisit the fake /api/jobs/start test route and /api/jobs/start_rip
test route - both were useful scaffolding but may be worth removing
once the frontend calls /api/rip/start directly.

## 2026-07-30 - Phase 3 complete: live progress parsing from a real running rip

Built the second half of Phase 3: live progress parsing, not just scan
parsing. Captured a real 90-second test rip (title 1, --start-at
duration:0 --stop-at duration:90, stdout/stderr split as usual) to see
HandBrake's actual live progress JSON shape before writing any parser
code - same approach that worked well for the scan JSON.

Real shape confirmed: Progress blocks with State SCANNING, WORKING, or
WORKDONE. WORKING blocks have a Progress field (0.0-1.0 float),
ETASeconds, and Rate/RateAvg (encoding fps). WORKDONE has an Error
code (0 = success). 112 WORKING updates came through for a 90-second
clip - plenty of granularity for a real progress bar.

Added to handbrake.py: iter_progress_blocks() is a generator that
reads any line-iterable (a live subprocess stdout stream OR a fixture
file - same function works for both, since Python file objects and
Popen().stdout are both just line iterables) and yields each parsed
Progress block as soon as its closing brace is seen. summarize_progress()
turns one block into a flat state/percent/eta/rate summary. Verified
against the real 90-second-clip fixture before touching jobs.py:
correctly found all 129 real blocks (16 SCANNING, 112 WORKING, 1
WORKDONE), progress climbing 0% to 98.9% then a clean 100% done state.

Added start_rip_job() to jobs.py: launches HandBrakeCLI via Popen with
stdout=PIPE (read live) and stderr redirected to a log file (NOT
merged - same stream-separation lesson from the scan-parsing bug
applies here too, and matters even more since a real rip runs for
hours). A background thread iterates process.stdout through
iter_progress_blocks() as lines arrive, updating the shared job-status
dict on every block - this is what makes /api/jobs/status show real
moving progress instead of just "running" until it's suddenly "done".

Tested for real, end to end, through the actual API (not just unit
tests): started a live 90-second test rip via curl, polled
/api/jobs/status five times a couple seconds apart, watched percent
climb 9.6% - 28.2% - 43.3% - 57.1% - 67.3% with ETA counting down and
a real encoding rate reported each time, then confirmed a clean finish
(state done, percent 100.0, returncode 0) and a real 20MB .mkv file on
disk. This is the architecturally riskiest piece of the whole project
(per BUILD-PROCESS.md's phase ordering) and it works.

Side note: the test disc's libdvdnav title string reports
"BATMAN_BEGINS_DISC_1", not The Dark Knight - the disc in the case
labeled Dark Knight Disc 1 is actually Batman Begins. Doesn't affect
any of the code (title/duration/track logic is disc-agnostic) but
worth sorting out the physical disc mislabeling before relying on
this case for future testing.

Also continued the incremental build approach from last session
(small pastes, syntax check + functional test after each piece) -
worked smoothly this time with no stuck-heredoc or truncation issues.

Committed as: handbrake.py progress functions, jobs.py real rip
runner, app.py test route, plus the new rip-progress-stdout.log /
rip-progress-stderr.log fixtures. Tagged v0.3-handbrake.

Next: Phase 4 - rip to the correct Plex path/naming/ownership,
end-to-end for one full disc (not just a 90-second test clip).

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
