"""
Persistent job history, backed by SQLite.

Why a separate module: jobs.py already has a lot going on (live job
state, subprocess management, cancel logic). Keeping "where did the
history go" as its own small file with its own job (open a connection,
run a query, close it) keeps that logic easy to find and easy to test
on its own later.

Why open/close a connection every call instead of keeping one open:
sqlite3 connections aren't safe to share across threads by default,
and jobs.py already juggles a background thread per rip. Opening a
short-lived connection per call avoids that whole class of bug, and
at homelab scale (a handful of rips a day) the overhead is irrelevant.
"""
import os
import sqlite3

# data/history.db, relative to the repo root (one level up from backend/).
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.db")


def init_db():
    """Create the history table if it doesn't exist yet. Safe to call
    every time the app starts - CREATE TABLE IF NOT EXISTS is a no-op
    once the table's already there."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_title TEXT,
            movie_year TEXT,
            output_path TEXT,
            state TEXT NOT NULL,
            started_at REAL,
            finished_at REAL,
            duration_seconds REAL
        )
    """)
    conn.commit()
    conn.close()


def add_entry(entry):
    """Insert one completed job. `entry` is the same dict shape jobs.py
    was already building for the in-memory history list."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO job_history
            (movie_title, movie_year, output_path, state,
             started_at, finished_at, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry["movie_title"],
            entry["movie_year"],
            entry["output_path"],
            entry["state"],
            entry["started_at"],
            entry["finished_at"],
            entry["duration_seconds"],
        ),
    )
    conn.commit()
    conn.close()


def get_recent(limit=10):
    """Return the most recently finished jobs, most recent first."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us read rows like dicts
    rows = conn.execute(
        """
        SELECT movie_title, movie_year, output_path, state,
               started_at, finished_at, duration_seconds
        FROM job_history
        ORDER BY finished_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

