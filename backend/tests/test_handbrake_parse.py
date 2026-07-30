"""
Tests for HandBrake scan-JSON parsing (see handbrake.py).

Run against real fixtures captured from actual discs (see sample-logs/),
not synthetic data - see DEVLOG.md 2026-07-30 entry for how these were
captured and why stdout/stderr had to be captured separately.
"""

import os

import pytest

import handbrake

FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "sample-logs"
)


def _load_fixture(filename):
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()



def test_disc1_extracts_title_set():
    """The Disc 1 scan's JSON block should parse cleanly."""
    stdout = _load_fixture("dark-knight-disc1-scan-stdout.json")
    title_set = handbrake.extract_title_set_json(stdout)
    assert "MainFeature" in title_set
    assert "TitleList" in title_set
    assert len(title_set["TitleList"]) == 10


def test_disc1_main_feature_is_the_movie():
    """
    MainFeature should point at title Index 1, with a duration of
    2:14:17 - confirmed by hand against the real disc (see DEVLOG.md).
    This is the core assumption the whole parser is built on.
    """
    stdout = _load_fixture("dark-knight-disc1-scan-stdout.json")
    summary = handbrake.parse_scan_output(stdout)

    assert summary["index"] == 1
    assert summary["title_count"] == 10
    assert summary["duration_seconds"] > 2 * 3600
    assert summary["duration_display"] == "2:14:17"


def test_disc1_has_audio_and_subtitle_tracks():
    stdout = _load_fixture("dark-knight-disc1-scan-stdout.json")
    summary = handbrake.parse_scan_output(stdout)

    assert len(summary["audio_tracks"]) == 2
    assert len(summary["subtitle_tracks"]) == 8
    for track in summary["audio_tracks"]:
        assert track["language"]




def test_disc2_extracts_title_set():
    stdout = _load_fixture("dark-knight-scan-stdout.json")
    title_set = handbrake.extract_title_set_json(stdout)
    assert "MainFeature" in title_set
    assert len(title_set["TitleList"]) == 36


def test_disc2_main_feature_is_short_not_a_real_movie():
    """
    Disc 2 is bonus features - even its MainFeature should be nowhere
    near feature-film length. Guards against the parser silently
    "working" on the wrong kind of disc without flagging it.
    """
    stdout = _load_fixture("dark-knight-scan-stdout.json")
    summary = handbrake.parse_scan_output(stdout)

    assert summary["duration_seconds"] < 30 * 60



def test_merged_stdout_stderr_raises_clear_error():
    """
    The original (buggy) capture merged stdout+stderr with 2>&1, which
    corrupted the JSON - this is the exact failure we hit for real (see
    DEVLOG.md). The parser should fail with a clear ScanParseError.
    """
    stdout = _load_fixture("dark-knight-scan.json")
    with pytest.raises(handbrake.ScanParseError):
        handbrake.parse_scan_output(stdout)


def test_missing_marker_raises_clear_error():
    with pytest.raises(handbrake.ScanParseError):
        handbrake.extract_title_set_json("no json title set here at all")


def test_main_feature_index_not_in_title_list():
    """If MainFeature points at an Index that doesn't exist, fail loudly."""
    fake_title_set = {"MainFeature": 99, "TitleList": [{"Index": 1}]}
    with pytest.raises(handbrake.ScanParseError):
        handbrake.get_main_feature(fake_title_set)

