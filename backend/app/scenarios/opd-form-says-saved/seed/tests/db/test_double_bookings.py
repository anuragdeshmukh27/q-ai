"""Double bookings: two Booked appointments for the same doctor, date and time. The tests run on a copy of the production database (migrations up to 0007 plus the snapshot in
fixtures/prod_snapshot.sql) upgraded with whatever migrations you wrote after 0007."""
import sqlite3
from collections import defaultdict

import pytest


def double_booked(rows: list[dict]) -> dict[tuple, list[dict]]:
    """Slots that hold more than one Booked appointment, each list earliest booking first."""
    slots: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["status"] == "Booked":
            slots[(r["doctor_id"], r["date"], r["slot_at"])].append(r)
    return {k: sorted(v, key=lambda r: (r["created_at"], r["id"])) for k, v in slots.items() if len(v) > 1}


def test_the_snapshot_holds_three_double_booked_slots(production):
    assert len(double_booked(production.before)) == 3


def test_duplicate_bookings_are_cancelled_not_deleted(production):
    groups = double_booked(production.before)
    production.upgrade()  # raises when the migration cannot run on the real rows (a unique index over rows that already collide, say)
    after = {r["id"]: r for r in production.rows()}
    lost = sorted({r["id"] for r in production.before} - set(after))
    assert not lost, f"appointments {lost} were deleted: cancel the later duplicates, keep every row"
    for slot, rows in groups.items():
        assert after[rows[0]["id"]]["status"] == "Booked", f"the earliest booking {rows[0]['id']} of slot {slot} must stay Booked"
        for later in rows[1:]:
            assert after[later["id"]]["status"] == "Cancelled", f"appointment {later['id']} double-booked slot {slot} after {rows[0]['id']}: it must be Cancelled"
    assert not double_booked(list(after.values())), "a slot still holds two Booked appointments"
    cancelled_by_you = {r["id"] for rows in groups.values() for r in rows[1:]}
    for r in production.before:
        if r["id"] not in cancelled_by_you:
            assert after[r["id"]]["status"] == r["status"], f"appointment {r['id']} was not a duplicate: its status must not change"


def test_a_cancelled_duplicate_records_why(production):
    groups = double_booked(production.before)
    production.upgrade()
    for rows in groups.values():
        for later in rows[1:]:
            assert production.why(later["id"]), f"appointment {later['id']} was cancelled as a duplicate: record why, in a new column of appointments or in a new log table"


def test_the_database_refuses_a_second_booked_row_for_a_slot(production):
    production.upgrade()
    insert = "INSERT INTO appointments (doctor_id, patient_name, patient_phone, date, slot_at, reason, status) VALUES (?, 'P', '9876500000', ?, ?, 'r', ?)"
    with production.connect() as conn:
        conn.execute(insert, (1, "2027-01-04", "08:00", "Booked"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (1, "2027-01-04", "08:00", "Booked"))
        conn.execute(insert, (1, "2027-01-04", "08:00", "Cancelled"))  # a cancelled slot is free again: the rule is only about Booked
        conn.execute(insert, (1, "2027-01-04", "08:30", "Booked"))  # another time
        conn.execute(insert, (2, "2027-01-04", "08:00", "Booked"))  # another doctor
        conn.execute(insert, (1, "2027-01-05", "08:00", "Booked"))  # another day
