"""Hidden checks for the Database benchmark (calculator fixture). The engineer never sees this file."""
from database import calculations as db


def test_add_returns_the_stored_row():
    r = db.add_calculation(2, 3, "add", 5)
    assert isinstance(r["id"], int) and (r["a"], r["b"], r["operation"], r["result"]) == (2, 3, "add", 5)


def test_history_is_empty_first_and_newest_first():
    assert db.list_history() == []
    db.add_calculation(1, 1, "add", 2)
    db.add_calculation(6, 3, "divide", 2)
    assert [h["operation"] for h in db.list_history()] == ["divide", "add"]


def test_floats_survive_a_round_trip():
    db.add_calculation(0.1, 0.2, "add", 0.30000000000000004)
    assert db.list_history()[0]["result"] == 0.30000000000000004


def test_values_are_stored_safely():
    db.add_calculation(1, 2, "x'); DROP TABLE calculations;--", 3)
    assert db.list_history()[0]["operation"] == "x'); DROP TABLE calculations;--"
