import pytest

from app import app as flask_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_DB", str(tmp_path / "notes.db"))
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
