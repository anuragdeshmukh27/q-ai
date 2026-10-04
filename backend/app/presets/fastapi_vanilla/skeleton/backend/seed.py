"""Seed data for a freshly opened app (locked: generated apps never edit it).

`seed.json` is written by Q from the skill pack of the app: realistic rows (names, places, amounts) so the app does not open empty. It is loaded only when the app
is started to be looked at (Q_SEED=1, set by Q's port manager), and only while every table is still empty; tests never see it.
Format: {"table": [{"column": value, ..., "_of": "parent_table", "_idx": 0, "_fk": "parent_id"}]}: `_of`, `_idx` and `_fk` link a child to the row of its parent
that was inserted at that position.
"""
import importlib
import json
import pkgutil
from pathlib import Path

from database.connection import connect

ROOT = Path(__file__).resolve().parent.parent


def _schema() -> str:
    import database

    for mod in pkgutil.iter_modules(database.__path__):
        if mod.name != "connection":
            schema = getattr(importlib.import_module(f"database.{mod.name}"), "SCHEMA", "")
            if schema:
                return schema
    return ""


def load(path: Path = ROOT / "seed.json") -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def seed(force: bool = False, path: Path = ROOT / "seed.json") -> dict:
    """Insert the rows; returns {table: number of rows}. Nothing happens when a table already has rows (unless force)."""
    data = load(path)
    if not data:
        return {}
    done: dict[str, list[int]] = {}
    with connect(_schema()) as conn:
        if not force and any(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in data):
            return {}
        for table, rows in data.items():
            ids = done.setdefault(table, [])
            for row in rows:
                row = dict(row)
                parent, idx, fk = row.pop("_of", None), row.pop("_idx", 0), row.pop("_fk", None)
                if parent is not None and fk:
                    row[fk] = done[parent][idx]
                cur = conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
                ids.append(cur.lastrowid)
    return {t: len(ids) for t, ids in done.items()}
