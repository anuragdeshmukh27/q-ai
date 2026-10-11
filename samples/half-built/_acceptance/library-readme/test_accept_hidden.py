"""Hidden acceptance for the library-readme fixture: the README's planned features."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LIB_DB", str(tmp_path / "hidden.db"))


def book(title="Dune"):
    return client.post("/books", json={"title": title, "author": "Herbert"}).json()


def test_borrow_and_return():
    b = book()
    r = client.post(f"/books/{b['id']}/borrow", json={"member": "Meera"})
    assert r.status_code == 200 and r.json()["borrowed_by"] == "Meera" and r.json()["borrowed_at"]
    again = client.post(f"/books/{b['id']}/borrow", json={"member": "Rohan"})
    assert again.status_code == 409 and again.json()["detail"] == "Book is already borrowed"
    back = client.post(f"/books/{b['id']}/return")
    assert back.status_code == 200 and back.json()["borrowed_by"] is None and back.json()["borrowed_at"] is None
    not_borrowed = client.post(f"/books/{b['id']}/return")
    assert not_borrowed.status_code == 409 and not_borrowed.json()["detail"] == "Book is not borrowed"
    assert client.post("/books/999/borrow", json={"member": "A"}).status_code == 404


def test_overdue_lists_books_borrowed_more_than_14_days_ago():
    old, fresh = book("Old"), book("Fresh")
    client.post(f"/books/{old['id']}/borrow", json={"member": "A"})
    client.post(f"/books/{fresh['id']}/borrow", json={"member": "B"})
    assert client.get("/books/overdue").json() == {"items": []}
    c = sqlite3.connect(os.environ["LIB_DB"])
    c.execute("UPDATE books SET borrowed_at = '2020-01-01T00:00:00' WHERE id = ?", (old["id"],))
    c.commit()
    assert [b["title"] for b in client.get("/books/overdue").json()["items"]] == ["Old"]
