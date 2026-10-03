"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = "CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL);"


def add_todo(title: str, description: str, priority: str) -> dict:
    """Insert and return the new row"""
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO todos (title, description, priority) VALUES (?, ?, ?)", (title, description, priority))
        row = conn.execute("SELECT id, title, description, priority FROM todos WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def list_todos() -> list[dict]:
    """All rows, newest first"""
    with connect(SCHEMA) as conn:
        rows = conn.execute("SELECT id, title, description, priority FROM todos ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def update_todo(todo_id: int, title: str, description: str, priority: str) -> bool:
    """True if a row was updated"""
    with connect(SCHEMA) as conn:
        cur = conn.execute("UPDATE todos SET title = ?, description = ?, priority = ? WHERE id = ?", (title, description, priority, todo_id))
        return cur.rowcount > 0


def delete_todo(todo_id: int) -> bool:
    """True if a row was deleted"""
    with connect(SCHEMA) as conn:
        cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        return cur.rowcount > 0
