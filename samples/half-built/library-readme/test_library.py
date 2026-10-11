import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LIB_DB", str(tmp_path / "lib.db"))


client = TestClient(app)


def test_add_and_list():
    client.post("/books", json={"title": "Dune", "author": "Herbert"})
    client.post("/books", json={"title": "Emma", "author": "Austen"})
    assert [b["title"] for b in client.get("/books").json()["items"]] == ["Dune", "Emma"]


def test_filter_by_title():
    client.post("/books", json={"title": "Dune", "author": "Herbert"})
    client.post("/books", json={"title": "Emma", "author": "Austen"})
    assert [b["title"] for b in client.get("/books", params={"title": "mm"}).json()["items"]] == ["Emma"]
