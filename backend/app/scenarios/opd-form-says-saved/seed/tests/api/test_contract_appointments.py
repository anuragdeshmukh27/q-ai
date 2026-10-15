"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""
import itertools

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_n = itertools.count(1)  # makes unique values differ


def test_get_api_doctors_doctor_id_appointments_1_rejects_an_unknown_doctor():
    r = client.get('/api/doctors/99999/appointments')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_post_api_doctors_doctor_id_appointments_1_rejects_an_unknown_doctor():
    r = client.post('/api/doctors/99999/appointments', json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_put_api_appointments_id_1_rejects_an_unknown_id():
    r = client.put('/api/appointments/99999', json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Appointment not found'


def test_delete_api_appointments_id_1_rejects_an_unknown_id():
    r = client.delete('/api/appointments/99999')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Appointment not found'


def test_post_api_appointments_id_complete_1_rejects_an_unknown_id():
    r = client.post('/api/appointments/99999/complete')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Appointment not found'


def test_post_api_appointments_id_cancel_1_rejects_an_unknown_id():
    r = client.post('/api/appointments/99999/cancel')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Appointment not found'


BASE_DOCTORS = {'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}
UNIQ_DOCTORS = {'email': 'user{n}@example.com'}


def make_doctor(**over):
    r = client.post('/api/doctors', json={**BASE_DOCTORS, **{k: t.format(n=next(_n)) for k, t in UNIQ_DOCTORS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


BASE_APPOINTMENTS = {'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}
UNIQ_APPOINTMENTS = {}


def make_appointment(parent_id, **over):
    r = client.post(f'/api/doctors/{parent_id}/appointments', json={**BASE_APPOINTMENTS, **{k: t.format(n=next(_n)) for k, t in UNIQ_APPOINTMENTS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_appointments_are_created_and_listed_under_their_doctor():
    parent = make_doctor()
    item = make_appointment(parent['id'])
    assert item['doctor_id'] == parent['id']
    items = client.get(f"/api/doctors/{parent['id']}/appointments").json()['items']
    assert [i['id'] for i in items] == [item['id']]


def test_appointments_of_an_unknown_doctor_are_404():
    r = client.get(f"/api/doctors/99999/appointments")
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text
    r = client.post(f"/api/doctors/99999/appointments", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'})
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text


def test_appointments_belong_to_one_doctor_only():
    a = make_doctor()
    b = make_doctor()
    item = make_appointment(a['id'])
    assert client.get(f"/api/doctors/{b['id']}/appointments").json()['items'] == []


def test_appointments_parent_id_must_be_an_integer():
    assert client.get('/api/doctors/abc/appointments').status_code == 422


def test_appointments_body_is_validated():
    parent = make_doctor()
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_name': 'Sample patient name', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'reason': 'Sample reason', 'status': 'Booked'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'status': 'Booked'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/appointments", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason'}).status_code == 422


def test_deleting_a_doctor_deletes_its_appointments():
    parent = make_doctor()
    item = make_appointment(parent['id'])
    r = client.delete(f"/api/doctors/{parent['id']}")
    assert r.status_code == 200, r.text
    r = client.put(f"/api/appointments/{item['id']}", json={'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'})
    assert r.status_code == 404, 'deleting the doctor must delete its appointments too'


def test_appointments_blank_required_text_is_a_400_with_a_message():
    parent = make_doctor()
    item = make_appointment(parent['id'])
    for field, message in [('patient_name', 'Patient name is required'), ('time', 'Time is required')]:
        for blank in ('', '   '):
            body = {**{'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}, field: blank}
            r = client.post(f"/api/doctors/{parent['id']}/appointments", json=body)
            assert r.status_code == 400, f'adding with a blank {field} must be a 400, not {r.status_code}: use the request model as generated'
            assert r.json() == {'detail': message}, r.text
            r = client.put(f"/api/appointments/{item['id']}", json=body)
            assert r.status_code == 400 and r.json() == {'detail': message}, f'editing with a blank {field}: {r.status_code} {r.text}'
    assert len(client.get(f"/api/doctors/{parent['id']}/appointments").json()['items']) == 1, 'a refused request must not store anything'


def test_appointments_complete_sets_status_to_completed():
    parent = make_doctor()
    item = make_appointment(parent['id'], status='Booked')
    r = client.post(f"/api/appointments/{item['id']}/complete")
    assert r.status_code == 200, r.text
    assert r.json()['id'] == item['id'], 'the action must return the updated item'
    assert r.json()['status'] == 'Completed', 'complete must set status to Completed'
    assert r.json()['patient_name'] == item['patient_name'], 'complete must not change patient_name'
    assert r.json()['patient_phone'] == item['patient_phone'], 'complete must not change patient_phone'
    assert r.json()['date'] == item['date'], 'complete must not change date'
    assert r.json()['time'] == item['time'], 'complete must not change time'
    assert r.json()['reason'] == item['reason'], 'complete must not change reason'
    listed = client.get(f"/api/doctors/{parent['id']}/appointments").json()['items']
    assert [i for i in listed if i['id'] == item['id']][0]['status'] == 'Completed', 'the list must show the new value'
    r = client.post("/api/appointments/99999/complete")
    assert r.status_code == 404, r.text


def test_appointments_cancel_sets_status_to_cancelled():
    parent = make_doctor()
    item = make_appointment(parent['id'], status='Booked')
    r = client.post(f"/api/appointments/{item['id']}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()['id'] == item['id'], 'the action must return the updated item'
    assert r.json()['status'] == 'Cancelled', 'cancel must set status to Cancelled'
    assert r.json()['patient_name'] == item['patient_name'], 'cancel must not change patient_name'
    assert r.json()['patient_phone'] == item['patient_phone'], 'cancel must not change patient_phone'
    assert r.json()['date'] == item['date'], 'cancel must not change date'
    assert r.json()['time'] == item['time'], 'cancel must not change time'
    assert r.json()['reason'] == item['reason'], 'cancel must not change reason'
    listed = client.get(f"/api/doctors/{parent['id']}/appointments").json()['items']
    assert [i for i in listed if i['id'] == item['id']][0]['status'] == 'Cancelled', 'the list must show the new value'
    r = client.post("/api/appointments/99999/cancel")
    assert r.status_code == 404, r.text


def test_appointments_rule_values_are_checked_with_a_400_and_a_message():
    parent = make_doctor()
    item = make_appointment(parent['id'])
    body = {**{'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}, 'patient_phone': '12345'}
    resp = client.post(f"/api/doctors/{parent['id']}/appointments", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Patient phone must be a 10-digit mobile number'}, 'adding with a bad patient_phone: ' + resp.text
    resp = client.put(f"/api/appointments/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Patient phone must be a 10-digit mobile number'}, 'editing with a bad patient_phone: ' + resp.text


def test_appointments_status_cannot_leave_completed():
    parent = make_doctor()
    item = make_appointment(parent['id'], status='Completed')
    resp = client.put(f"/api/appointments/{item['id']}", json={**{'patient_name': 'Sample patient name', 'patient_phone': '9876500000', 'date': '2026-01-15', 'time': '10:30', 'reason': 'Sample reason', 'status': 'Booked'}, 'status': 'Booked'})
    assert resp.status_code == 409 and resp.json() == {'detail': 'That status change is not allowed'}, resp.text
    resp = client.post(f"/api/appointments/{item['id']}/cancel")
    assert resp.status_code == 409, resp.text
    assert client.get(f"/api/doctors/{parent['id']}/appointments").json()['items'][0]['status'] == 'Completed', 'a refused change must leave the status as it was'
