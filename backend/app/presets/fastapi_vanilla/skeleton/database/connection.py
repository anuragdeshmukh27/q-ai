"""SQLite connection helper (locked: the Database engineer imports it, never edits it).

The database file is read from the APP_DB environment variable at call time (default data/app.db),
so tests can point every call at a temporary file.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def get_conn() -> sqlite3.Connection:
    path = Path(os.environ.get("APP_DB", "data/app.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect(schema: str = ""):
    """`with connect(SCHEMA) as conn:` - creates the tables (CREATE TABLE IF NOT EXISTS), commits on success, always closes."""
    conn = get_conn()
    try:
        if schema:
            conn.executescript(schema)
        yield conn
        conn.commit()
    finally:
        conn.close()
