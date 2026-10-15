import os
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "database" / "migrations"
SNAPSHOT = ROOT / "fixtures" / "prod_snapshot.sql"
PRODUCTION_HAS = "0007"  # the last migration the production database has run; the snapshot was taken from it


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite database."""
    monkeypatch.setenv("APP_DB", str(tmp_path / "test.db"))


class Production:
    """The production database as it is today: migrations 0001 to 0007 applied, then the snapshot (fixtures/prod_snapshot.sql). `upgrade()` runs every migration after 0007,
    the way the app does when it starts (`database.connection.migrate`), so a migration you write is tried on the real rows, not on an empty database."""

    def __init__(self, path: str):
        self.path = path
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        for sql in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = sql.name.split("_", 1)[0]
            if version <= PRODUCTION_HAS:
                conn.executescript(sql.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.executescript(SNAPSHOT.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        self.before = self.rows()
        self.columns_before = self._columns()
        self.tables_before = self._tables()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM appointments ORDER BY id")]

    def _columns(self) -> set[str]:
        with self.connect() as conn:
            return {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")}

    def _tables(self) -> set[str]:
        with self.connect() as conn:
            return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def upgrade(self) -> None:
        from database.connection import migrate

        conn = sqlite3.connect(self.path)
        try:
            migrate(conn)
        finally:
            conn.close()

    def why(self, appointment_id: int) -> str:
        """The reason recorded for an appointment: a value in a column the upgrade added to `appointments`, or in a row of a table it added that names the appointment."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
            for column in self._columns() - self.columns_before:
                if row is not None and str(row[column] or "").strip():
                    return str(row[column])
            for table in self._tables() - self.tables_before - {"sqlite_sequence"}:
                for logged in conn.execute(f'SELECT * FROM "{table}"'):
                    values = list(logged)
                    if appointment_id in [v for v in values if isinstance(v, int)] or str(appointment_id) in [str(v) for v in values]:
                        text = [str(v) for v in values if isinstance(v, str) and len(v.strip()) > 3]
                        if text:
                            return text[0]
        return ""


@pytest.fixture
def production(temp_db):
    return Production(os.environ["APP_DB"])
