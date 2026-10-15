"""Database tests generated from the resource model. Do not edit; fix the data access functions instead."""
from database import appointments as m
from database.connection import connect


import itertools

_n = itertools.count(1)
UNIQ = {}


def make(pid=1, **over):
    return m.add_appointment(doctor_id=pid, **{**{'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'slot_at': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}, **{k: t.format(n=next(_n)) for k, t in UNIQ.items()}, **over})


def test_add_returns_the_row_and_get_finds_it():
    row = make()
    assert isinstance(row, dict) and row['id'], 'add must return the new row as a dict'
    assert row['patient_name'] == 'Sample patient name', 'the stored value must come back unchanged'
    assert row['patient_phone'] == '9876500000', 'the stored value must come back unchanged'
    assert row['date'] == '2026-01-15', 'the stored value must come back unchanged'
    assert row['slot_at'] == '10:30', 'the stored value must come back unchanged'
    assert row['reason'] == 'Sample reason', 'the stored value must come back unchanged'
    assert row['status'] == 'Booked', 'the stored value must come back unchanged'
    assert row['created_at'], 'the row must carry created_at: use SELECT * (every column), never a list of columns'
    assert row['doctor_id'] == 1
    assert m.get_appointment(row['id']) == row
    assert m.get_appointment(99999) is None


def test_list_is_newest_first():
    a, b = make(slot_at='10:30'), make(slot_at='10:45')  # two Booked rows of one doctor on one day need two different times
    make(2)  # a row of another parent must not show up
    assert [r['id'] for r in m.list_appointments(1)] == [b['id'], a['id']], 'newest first means ORDER BY id DESC. Not created_at: rows added in the same second share a timestamp, so their order is arbitrary'


def test_update_changes_the_user_fields_and_returns_the_row():
    row = make()
    new = m.update_appointment(row['id'], **{'patient_name': 'Sample patient name v2', 'patient_phone': '9876500000', 'date': '2026-01-15', 'slot_at': '10:30', 'reason': 'Sample reason', 'status': 'Booked'})
    assert new is not None and all(new[k] == v for k, v in {'patient_name': 'Sample patient name v2', 'patient_phone': '9876500000', 'date': '2026-01-15', 'slot_at': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}.items())
    assert m.update_appointment(99999, **{'patient_name': 'Sample patient name v2', 'patient_phone': '9876500000', 'date': '2026-01-15', 'slot_at': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}) is None


def test_delete_reports_whether_the_row_existed():
    row = make()
    assert m.delete_appointment(row['id']) is True
    assert m.get_appointment(row['id']) is None
    assert m.delete_appointment(row['id']) is False


def test_complete_appointment():
    row = make(status='Booked')
    r = m.complete_appointment(row['id'])
    assert r['status'] == 'Completed', 'the action must set status to Completed'
    assert m.complete_appointment(row['id'])['status'] == 'Completed'
    assert m.complete_appointment(99999) is None


def test_cancel_appointment():
    row = make(status='Booked')
    r = m.cancel_appointment(row['id'])
    assert r['status'] == 'Cancelled', 'the action must set status to Cancelled'
    assert m.cancel_appointment(row['id'])['status'] == 'Cancelled'
    assert m.cancel_appointment(99999) is None
