"""Database tests generated from the resource model. Do not edit; fix the data access functions instead."""
from database import prescriptions as m
from database.connection import connect


import itertools

_n = itertools.count(1)
UNIQ = {}


def make(pid=1, **over):
    return m.add_prescription(doctor_id=pid, **{**{'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}, **{k: t.format(n=next(_n)) for k, t in UNIQ.items()}, **over})


def test_add_returns_the_row_and_get_finds_it():
    row = make()
    assert isinstance(row, dict) and row['id'], 'add must return the new row as a dict'
    assert row['patient_name'] == 'Sample patient name', 'the stored value must come back unchanged'
    assert row['medicine'] == 'Sample medicine', 'the stored value must come back unchanged'
    assert row['dosage'] == 'Sample dosage', 'the stored value must come back unchanged'
    assert row['days'] == 1, 'the stored value must come back unchanged'
    assert row['instructions'] == 'Sample instructions', 'the stored value must come back unchanged'
    assert row['created_at'], 'the row must carry created_at: use SELECT * (every column), never a list of columns'
    assert row['doctor_id'] == 1
    assert m.get_prescription(row['id']) == row
    assert m.get_prescription(99999) is None


def test_list_is_newest_first():
    a, b = make(), make()
    make(2)  # a row of another parent must not show up
    assert [r['id'] for r in m.list_prescriptions(1)] == [b['id'], a['id']], 'newest first means ORDER BY id DESC. Not created_at: rows added in the same second share a timestamp, so their order is arbitrary'


def test_update_changes_the_user_fields_and_returns_the_row():
    row = make()
    new = m.update_prescription(row['id'], **{'patient_name': 'Sample patient name v2', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'})
    assert new is not None and all(new[k] == v for k, v in {'patient_name': 'Sample patient name v2', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}.items())
    assert m.update_prescription(99999, **{'patient_name': 'Sample patient name v2', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}) is None


def test_delete_reports_whether_the_row_existed():
    row = make()
    assert m.delete_prescription(row['id']) is True
    assert m.get_prescription(row['id']) is None
    assert m.delete_prescription(row['id']) is False
