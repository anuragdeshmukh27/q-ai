"""SQLite helpers for the fest app."""
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    venue TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    student_name TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Registered'
);
CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0
);
"""


def db_path() -> str:
    return os.environ.get("FEST_DB", "fest.db")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def list_events():
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id DESC")]


def add_event(name, venue, capacity):
    with connect() as conn:
        cur = conn.execute("INSERT INTO events (name, venue, capacity) VALUES (?, ?, ?)", (name, venue, capacity))
        return dict(conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone())


def get_event(event_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def delete_event(event_id):
    with connect() as conn:
        conn.execute("DELETE FROM registrations WHERE event_id = ?", (event_id,))
        return conn.execute("DELETE FROM events WHERE id = ?", (event_id,)).rowcount > 0
