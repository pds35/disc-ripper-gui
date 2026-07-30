"""
Tests for Plex path construction (see plex.py).

Only covers the pure-logic path-building functions, per
BUILD-PROCESS.md's testing approach - the actual directory creation
and chown need real hardware/filesystem and are checked manually.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import plex


def test_basic_title_and_year():
    paths = plex.build_movie_paths("Batman Begins", 2005)
    assert paths["folder_path"] == "/mnt/nvme/media/movies/Batman Begins (2005)"
    assert paths["file_path"] == "/mnt/nvme/media/movies/Batman Begins (2005)/Batman Begins (2005).mkv"


def test_title_with_colon_and_apostrophe():
    paths = plex.build_movie_paths("Pirates of the Caribbean: At World's End", 2007)
    assert "Pirates of the Caribbean: At World's End (2007)" in paths["folder_path"]
    assert paths["file_path"].endswith("Pirates of the Caribbean: At World's End (2007).mkv")


def test_custom_base_dir():
    paths = plex.build_movie_paths("Some Movie", 2020, base_dir="/custom/path")
    assert paths["folder_path"] == "/custom/path/Some Movie (2020)"


def test_sanitize_strips_unsafe_characters():
    """
    Slashes especially matter - a raw slash in a title would try to
    create a nested subdirectory, which is not what we want.
    """
    cleaned = plex.sanitize_title_for_filesystem("Weird/Title*With?Bad<Chars>")
    assert "/" not in cleaned
    assert "*" not in cleaned
    assert "?" not in cleaned
    assert "<" not in cleaned
    assert ">" not in cleaned


def test_sanitize_keeps_common_movie_punctuation():
    cleaned = plex.sanitize_title_for_filesystem("Mission: Impossible - Fallout")
    assert cleaned == "Mission: Impossible - Fallout"


def test_sanitize_collapses_double_spaces():
    cleaned = plex.sanitize_title_for_filesystem("Weird!!Title")
    # "!!" isn't stripped (both chars are allowed), but a stray double
    # space from stripped characters elsewhere should collapse
    cleaned2 = plex.sanitize_title_for_filesystem("Title * With Bad Chars")
    assert "  " not in cleaned2

