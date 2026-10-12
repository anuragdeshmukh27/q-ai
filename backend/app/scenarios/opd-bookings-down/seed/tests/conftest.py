import pytest


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own empty SQLite database."""
    monkeypatch.setenv("APP_DB", str(tmp_path / "test.db"))
