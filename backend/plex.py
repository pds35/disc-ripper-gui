"""
Plex library path construction and ownership handling.

Phase 4 goal: turn a movie title + year into the correct destination
path per the project brief's convention, and make sure the folder Plex
will read from is actually writable/readable by Plex once created.

Design decisions:

- Path convention is fixed by the brief and by Plex's own metadata
  matching behavior: "Movie Title (Year)/Movie Title (Year).mkv" -
  deviating from this (extra punctuation, missing year, etc.) makes
  Plex less likely to correctly match the movie's metadata/poster/etc.
- The base movies directory is configurable (not hardcoded deep in
  logic) per BUILD-PROCESS.md's config-hygiene guidance - so the same
  code could point somewhere else without editing source.
- Ownership: the brief notes new folders must be owned by pauls:pauls,
  not root, or Plex/the ripping process can't write to them. Since
  this Flask app runs as the pauls user (not root), directories it
  creates should already be pauls-owned - but we explicitly chown
  anyway as a safety net, matching the brief's "worth doing
  proactively" guidance, in case that assumption turns out wrong on
  the real system.
"""

import os
import subprocess

DEFAULT_MOVIES_BASE_DIR = "/mnt/nvme/media/movies"


def sanitize_title_for_filesystem(title):
    """
    Strip characters that are awkward or invalid in filenames, without
    being so aggressive that it mangles normal movie titles. Keeps
    letters, numbers, spaces, and a small set of common punctuation
    that shows up in real movie titles (: - ' , . & !).

    Does NOT try to handle every possible edge case (that way lies
    madness) - just enough for normal movie titles to produce sane
    folder/file names.
    """
    allowed_extra = set(":-',.&!()")
    cleaned_chars = []
    for char in title:
        if char.isalnum() or char.isspace() or char in allowed_extra:
            cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars)
    # collapse any accidental double spaces from stripped characters
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned.strip()


def build_movie_paths(title, year, base_dir=DEFAULT_MOVIES_BASE_DIR):
    """
    Given a movie title and year, return the folder and file paths
    HandBrake should write to, following the Plex naming convention
    from the project brief exactly: "Title (Year)/Title (Year).mkv".

    Returns a dict:
        {
            "folder_path": str,
            "file_path": str,
        }
    """
    clean_title = sanitize_title_for_filesystem(title)
    folder_name = clean_title + " (" + str(year) + ")"
    folder_path = os.path.join(base_dir, folder_name)
    file_path = os.path.join(folder_path, folder_name + ".mkv")

    return {
        "folder_path": folder_path,
        "file_path": file_path,
    }



def ensure_movie_directory(folder_path):
    """
    Create the movie's destination folder if it doesn't already exist,
    and make sure it's owned by the current user (pauls), not root -
    per the brief, Plex/the ripping process can't write into a
    root-owned folder.

    Since this Flask app runs as the pauls user (not root), a folder
    it creates with os.makedirs should already be pauls-owned. The
    chown call afterward is a safety net for cases where that
    assumption doesn't hold on the real system (e.g. if the parent
    directory has unusual permissions) - matches the brief's "worth
    doing proactively" guidance rather than only fixing it after
    something breaks.

    Returns a dict: {"success": bool, "created": bool, "output": str}
    """
    already_existed = os.path.isdir(folder_path)

    try:
        os.makedirs(folder_path, exist_ok=True)
    except OSError as e:
        return {
            "success": False,
            "created": False,
            "output": "Failed to create directory: " + str(e),
        }

    chown_result = subprocess.run(
        ["chown", "pauls:pauls", folder_path],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if chown_result.returncode != 0:
        return {
            "success": False,
            "created": not already_existed,
            "output": "Directory created but chown failed: "
                      + chown_result.stdout + chown_result.stderr,
        }

    return {
        "success": True,
        "created": not already_existed,
        "output": "Directory ready and owned by pauls:pauls",
    }

