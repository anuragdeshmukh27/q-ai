"""Hidden checks for the Database benchmark (todo fixture). The engineer never sees this file."""
from database import todos as db


def test_add_returns_the_stored_row():
    r = db.add_todo("Buy milk", "two litres", "high")
    assert isinstance(r["id"], int) and (r["title"], r["description"], r["priority"]) == ("Buy milk", "two litres", "high")


def test_list_is_empty_on_first_use_and_newest_first():
    assert db.list_todos() == []
    db.add_todo("first", "a", "low")
    db.add_todo("second", "b", "medium")
    assert [t["title"] for t in db.list_todos()] == ["second", "first"]


def test_update_changes_the_row_and_reports_whether_it_existed():
    r = db.add_todo("old", "d", "low")
    assert db.update_todo(r["id"], "new", "e", "high") is True
    row = db.list_todos()[0]
    assert (row["title"], row["description"], row["priority"]) == ("new", "e", "high")
    assert db.update_todo(9999, "x", "y", "low") is False


def test_delete_removes_the_row_and_reports_whether_it_existed():
    r = db.add_todo("gone", "d", "low")
    assert db.delete_todo(r["id"]) is True and db.list_todos() == []
    assert db.delete_todo(r["id"]) is False


def test_values_are_stored_safely():
    r = db.add_todo("x'); DROP TABLE todos;--", "it's", "low")
    assert db.list_todos()[0]["title"] == "x'); DROP TABLE todos;--" and r["description"] == "it's"
