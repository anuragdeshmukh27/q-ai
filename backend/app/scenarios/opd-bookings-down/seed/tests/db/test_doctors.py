"""Database tests generated from the resource model. Do not edit; fix the data access functions instead."""
from database import doctors as m
from database.connection import connect


import itertools

_n = itertools.count(1)
UNIQ = {'email': 'user{n}@example.com'}


def make(**over):
    return m.add_doctor(**{**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, **{k: t.format(n=next(_n)) for k, t in UNIQ.items()}, **over})


def test_add_returns_the_row_and_get_finds_it():
    row = make()
    assert isinstance(row, dict) and row['id'], 'add must return the new row as a dict'
    assert row['name'] == 'Sample name', 'the stored value must come back unchanged'
    assert row['department'] == 'General Medicine', 'the stored value must come back unchanged'
    assert row['phone'] == '9876500000', 'the stored value must come back unchanged'
    assert row['consultation_fee'] == 2.5, 'the stored value must come back unchanged'
    assert row['room'] == 'Sample room', 'the stored value must come back unchanged'
    assert row['availability'] == 'Available', 'the stored value must come back unchanged'
    assert row['created_at'], 'the row must carry created_at: use SELECT * (every column), never a list of columns'
    assert m.get_doctor(row['id']) == row
    assert m.get_doctor(99999) is None


def test_list_is_newest_first():
    a, b = make(), make()
    assert [r['id'] for r in m.list_doctors()] == [b['id'], a['id']], 'newest first means ORDER BY id DESC. Not created_at: rows added in the same second share a timestamp, so their order is arbitrary'


def test_update_changes_the_user_fields_and_returns_the_row():
    row = make()
    new = m.update_doctor(row['id'], **{'name': 'Sample name v2', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert new is not None and all(new[k] == v for k, v in {'name': 'Sample name v2', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}.items())
    assert m.update_doctor(99999, **{'name': 'Sample name v2', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}) is None


def test_delete_reports_whether_the_row_existed():
    row = make()
    assert m.delete_doctor(row['id']) is True
    assert m.get_doctor(row['id']) is None
    assert m.delete_doctor(row['id']) is False


def test_deleting_a_doctor_deletes_its_appointments_and_prescriptions_and_lab_tests():
    row = make()
    with connect(m.SCHEMA) as conn:
        conn.execute('INSERT INTO appointments (doctor_id, patient_name, patient_phone, date, slot_at, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?)', (row['id'], 'Sample patient name', '9876500000', '2026-01-15', '10:30', 'Sample reason', 'Booked'))
        conn.execute('INSERT INTO prescriptions (doctor_id, patient_name, medicine, dosage, days, instructions) VALUES (?, ?, ?, ?, ?, ?)', (row['id'], 'Sample patient name', 'Sample medicine', 'Sample dosage', 1, 'Sample instructions'))
        conn.execute('INSERT INTO lab_tests (doctor_id, patient_name, test_name, cost, status) VALUES (?, ?, ?, ?, ?)', (row['id'], 'Sample patient name', 'Blood test', 2.5, 'Ordered'))
    assert m.delete_doctor(row['id']) is True
    with connect(m.SCHEMA) as conn:
        left = conn.execute('SELECT COUNT(*) FROM appointments WHERE doctor_id = ?', (row['id'],)).fetchone()[0]
        assert left == 0, 'deleting a doctor must delete its appointments (DELETE FROM appointments WHERE doctor_id = ?)'
        left = conn.execute('SELECT COUNT(*) FROM prescriptions WHERE doctor_id = ?', (row['id'],)).fetchone()[0]
        assert left == 0, 'deleting a doctor must delete its prescriptions (DELETE FROM prescriptions WHERE doctor_id = ?)'
        left = conn.execute('SELECT COUNT(*) FROM lab_tests WHERE doctor_id = ?', (row['id'],)).fetchone()[0]
        assert left == 0, 'deleting a doctor must delete its lab_tests (DELETE FROM lab_tests WHERE doctor_id = ?)'
