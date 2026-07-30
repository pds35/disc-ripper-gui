"""
HandBrake scan-output parsing.

Phase 3 goal: turn HandBrakeCLI's --json scan output into a clean,
structured summary the Flask routes (and eventually the frontend) can
use, without the caller needing to know about HandBrake's raw output
quirks.

Design decisions:

- HandBrakeCLI's --json scan output is NOT a pure JSON file. It's the
  normal human-readable log, with a few tagged JSON blocks embedded in
  it, and finally "JSON Title Set: {...}" - the real title list we
  care about. This module finds and extracts just that final block.
- CRITICAL: stdout and stderr must be captured SEPARATELY when running
  HandBrakeCLI, never merged (no 2>&1). Confirmed via real testing:
  merging them let a stderr status message get spliced into the
  middle of a JSON key on stdout, corrupting the JSON entirely.
- MainFeature in the scan JSON is a title Index number (an int),
  pointing directly at the movie in TitleList - confirmed against a
  real Dark Knight disc, where it correctly identified the 2h14m movie
  title out of a 10-title disc.
"""

import json


class ScanParseError(Exception):
    """Raised when HandBrake's scan output can't be parsed as expected."""



def extract_title_set_json(scan_stdout):
    """
    Find and parse the "JSON Title Set: {...}" block out of raw
    HandBrakeCLI --json scan stdout.

    Takes the RAW stdout text (not stderr, not a merged stream - see
    module docstring for why that distinction matters). Returns the
    parsed dict with (at minimum) "MainFeature" and "TitleList" keys.

    Raises ScanParseError with a clear message if the marker isn't
    found or the extracted text isn't valid JSON.
    """
    marker = "JSON Title Set: "
    marker_index = scan_stdout.find(marker)
    if marker_index == -1:
        raise ScanParseError(
            "Could not find 'JSON Title Set:' marker in scan output. "
            "Either the scan failed/didn't complete, or this HandBrake "
            "version formats its --json output differently than expected."
        )

    json_text = scan_stdout[marker_index + len(marker):]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ScanParseError(
            "Found the 'JSON Title Set:' marker, but the text after it "
            "wasn't valid JSON (" + str(e) + "). If stdout and stderr "
            "were merged when this was captured, that's the likely "
            "cause - see module docstring."
        ) from e



def get_main_feature(title_set):
    """
    Given a parsed title-set dict (from extract_title_set_json), return
    just the title dict for the main feature (the movie itself).

    Raises ScanParseError if "MainFeature" is missing, or if no title
    in "TitleList" has a matching "Index".
    """
    if "MainFeature" not in title_set:
        raise ScanParseError("Scan JSON has no 'MainFeature' field.")
    if "TitleList" not in title_set:
        raise ScanParseError("Scan JSON has no 'TitleList' field.")

    main_feature_index = title_set["MainFeature"]
    for title in title_set["TitleList"]:
        if title.get("Index") == main_feature_index:
            return title

    raise ScanParseError(
        "MainFeature index " + str(main_feature_index) + " doesn't "
        "match any title's Index in TitleList."
    )



def summarize_title(title):
    """
    Pull out just the fields the GUI actually needs from a full title
    dict, in a flat, frontend-friendly shape.

    Returns a dict:
        {
            "index": int,
            "duration_seconds": int,
            "duration_display": str,   # "H:MM:SS"
            "audio_tracks": [{"track_number": int, "language": str}, ...],
            "subtitle_tracks": [{"track_number": int, "language": str}, ...],
        }
    """
    d = title.get("Duration", {})
    hours = d.get("Hours", 0)
    minutes = d.get("Minutes", 0)
    seconds = d.get("Seconds", 0)
    duration_seconds = hours * 3600 + minutes * 60 + seconds

    audio_tracks = []
    for track in title.get("AudioList", []):
        audio_tracks.append({
            "track_number": track.get("TrackNumber"),
            "language": track.get("Language"),
        })

    subtitle_tracks = []
    for track in title.get("SubtitleList", []):
        subtitle_tracks.append({
            "track_number": track.get("TrackNumber"),
            "language": track.get("Language"),
        })

    return {
        "index": title.get("Index"),
        "duration_seconds": duration_seconds,
        "duration_display": str(hours) + ":" + str(minutes).zfill(2) + ":" + str(seconds).zfill(2),
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }

def parse_scan_output(scan_stdout):
    """
    Top-level convenience function: raw scan stdout in, clean main
    feature summary out. This is what the Flask route should call.

    Returns the dict shape described in summarize_title's docstring,
    plus "title_count" (how many titles were on the disc total).
    """
    title_set = extract_title_set_json(scan_stdout)
    main_feature = get_main_feature(title_set)
    summary = summarize_title(main_feature)
    summary["title_count"] = len(title_set.get("TitleList", []))
    return summary



def iter_progress_blocks(lines):
    """
    Given an iterable of text lines (a live subprocess stdout stream,
    or a fixture file opened in text mode), yields each parsed
    "Progress: {...}" block as a dict, as soon as it's complete.

    Works incrementally, one line at a time - this is what makes it
    usable against a LIVE running rip, not just a finished log file.
    A block starts at a line that is exactly "Progress: {" and ends
    at a line that is exactly "}" with no leading whitespace (the
    closing brace of the top-level object - nested braces are always
    indented, so this is an unambiguous marker).

    Malformed blocks (shouldn't happen with split stdout/stderr, but
    just in case) are silently skipped rather than crashing the whole
    stream - one bad progress update isn't worth losing the job over.
    """
    in_block = False
    buffer = []
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not in_block:
            if line == "Progress: {":
                in_block = True
                buffer = ["{"]
            continue

        buffer.append(line)
        if line == "}":
            block_text = "\n".join(buffer)
            try:
                yield json.loads(block_text)
            except json.JSONDecodeError:
                pass
            in_block = False
            buffer = []


def summarize_progress(block):
    """
    Turn one raw Progress block dict into a flat, frontend-friendly
    summary. Handles all three states seen in real HandBrake output:
    SCANNING, WORKING, WORKDONE.

    Returns:
        {
            "state": "scanning" | "working" | "done" | "error",
            "percent": float or None,
            "eta_seconds": int or None,
            "rate_fps": float or None,
        }
    """
    state = block.get("State")

    if state == "WORKING":
        working = block.get("Working", {})
        return {
            "state": "working",
            "percent": round(working.get("Progress", 0) * 100, 1),
            "eta_seconds": working.get("ETASeconds"),
            "rate_fps": working.get("Rate"),
        }

    if state == "WORKDONE":
        work_done = block.get("WorkDone", {})
        error_code = work_done.get("Error", 0)
        return {
            "state": "done" if error_code == 0 else "error",
            "percent": 100.0 if error_code == 0 else None,
            "eta_seconds": None,
            "rate_fps": None,
        }

    if state == "SCANNING":
        return {
            "state": "scanning",
            "percent": None,
            "eta_seconds": None,
            "rate_fps": None,
        }

    return {
        "state": (state or "unknown").lower(),
        "percent": None,
        "eta_seconds": None,
        "rate_fps": None,
    }

