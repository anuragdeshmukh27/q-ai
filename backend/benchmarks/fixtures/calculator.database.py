"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = "CREATE TABLE IF NOT EXISTS calculations (id INTEGER PRIMARY KEY AUTOINCREMENT, a REAL, b REAL, operation TEXT, result REAL);"


def add_calculation(a: float, b: float, operation: str, result: float) -> dict:
    """Stores a row"""
    with connect(SCHEMA) as conn:
        cur = conn.execute('INSERT INTO calculations (a, b, operation, result) VALUES (?, ?, ?, ?)', (a, b, operation, result))
        return dict(conn.execute('SELECT * FROM calculations WHERE id = ?', (cur.lastrowid,)).fetchone())


def list_history() -> list[dict]:
    """All rows, newest first"""
    with connect(SCHEMA) as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM calculations ORDER BY id DESC')]
