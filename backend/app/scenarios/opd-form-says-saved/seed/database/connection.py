"""SQLite connection helper (locked: the Database engineer imports it, never edits it).

The database file is read from the APP_DB environment variable at call time (default data/app.db),
so tests can point every call at a temporary file.

The schema is built by the numbered files in database/migrations/: `connect()` applies the ones the file has not seen yet, in order, and records each in
`schema_migrations`. The `schema` argument is only kept so existing callers do not change.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def get_conn() -> sqlite3.Connection:
    path = Path(os.environ.get("APP_DB", "data/app.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration the database has not seen yet (0001_..., 0002_..., in order). Returns the names that were applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    seen = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for sql in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = sql.name.split("_", 1)[0]
        if version in seen:
            continue
        conn.executescript(sql.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
        applied.append(sql.name)
    return applied


@contextmanager
def connect(schema: str = ""):
    """`with connect(SCHEMA) as conn:` - brings the schema up to date (migrations), commits on success, always closes."""
    conn = get_conn()
    try:
        migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
