"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""
import itertools

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_n = itertools.count(1)  # makes unique values differ


def test_get_api_doctors_doctor_id_prescriptions_1_rejects_an_unknown_doctor():
    r = client.get('/api/doctors/99999/prescriptions')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_post_api_doctors_doctor_id_prescriptions_1_rejects_an_unknown_doctor():
    r = client.post('/api/doctors/99999/prescriptions', json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_put_api_prescriptions_id_1_rejects_an_unknown_id():
    r = client.put('/api/prescriptions/99999', json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Prescription not found'


def test_delete_api_prescriptions_id_1_rejects_an_unknown_id():
    r = client.delete('/api/prescriptions/99999')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Prescription not found'


BASE_DOCTORS = {'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}
UNIQ_DOCTORS = {'email': 'user{n}@example.com'}


def make_doctor(**over):
    r = client.post('/api/doctors', json={**BASE_DOCTORS, **{k: t.format(n=next(_n)) for k, t in UNIQ_DOCTORS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


BASE_PRESCRIPTIONS = {'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}
UNIQ_PRESCRIPTIONS = {}


def make_prescription(parent_id, **over):
    r = client.post(f'/api/doctors/{parent_id}/prescriptions', json={**BASE_PRESCRIPTIONS, **{k: t.format(n=next(_n)) for k, t in UNIQ_PRESCRIPTIONS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_prescriptions_are_created_and_listed_under_their_doctor():
    parent = make_doctor()
    item = make_prescription(parent['id'])
    assert item['doctor_id'] == parent['id']
    items = client.get(f"/api/doctors/{parent['id']}/prescriptions").json()['items']
    assert [i['id'] for i in items] == [item['id']]


def test_prescriptions_of_an_unknown_doctor_are_404():
    r = client.get(f"/api/doctors/99999/prescriptions")
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text
    r = client.post(f"/api/doctors/99999/prescriptions", json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'})
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text


def test_prescriptions_belong_to_one_doctor_only():
    a = make_doctor()
    b = make_doctor()
    item = make_prescription(a['id'])
    assert client.get(f"/api/doctors/{b['id']}/prescriptions").json()['items'] == []


def test_prescriptions_parent_id_must_be_an_integer():
    assert client.get('/api/doctors/abc/prescriptions').status_code == 422


def test_prescriptions_body_is_validated():
    parent = make_doctor()
    assert client.post(f"/api/doctors/{parent['id']}/prescriptions", json={'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/prescriptions", json={'patient_name': 'Sample patient name', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/prescriptions", json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'days': 1, 'instructions': 'Sample instructions'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/prescriptions", json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'instructions': 'Sample instructions'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/prescriptions", json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1}).status_code == 422


def test_deleting_a_doctor_deletes_its_prescriptions():
    parent = make_doctor()
    item = make_prescription(parent['id'])
    r = client.delete(f"/api/doctors/{parent['id']}")
    assert r.status_code == 200, r.text
    r = client.put(f"/api/prescriptions/{item['id']}", json={'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'})
    assert r.status_code == 404, 'deleting the doctor must delete its prescriptions too'


def test_prescriptions_blank_required_text_is_a_400_with_a_message():
    parent = make_doctor()
    item = make_prescription(parent['id'])
    for field, message in [('patient_name', 'Patient name is required'), ('medicine', 'Medicine is required'), ('dosage', 'Dosage is required'), ('instructions', 'Instructions is required')]:
        for blank in ('', '   '):
            body = {**{'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}, field: blank}
            r = client.post(f"/api/doctors/{parent['id']}/prescriptions", json=body)
            assert r.status_code == 400, f'adding with a blank {field} must be a 400, not {r.status_code}: use the request model as generated'
            assert r.json() == {'detail': message}, r.text
            r = client.put(f"/api/prescriptions/{item['id']}", json=body)
            assert r.status_code == 400 and r.json() == {'detail': message}, f'editing with a blank {field}: {r.status_code} {r.text}'
    assert len(client.get(f"/api/doctors/{parent['id']}/prescriptions").json()['items']) == 1, 'a refused request must not store anything'


def test_prescriptions_rule_values_are_checked_with_a_400_and_a_message():
    parent = make_doctor()
    item = make_prescription(parent['id'])
    body = {**{'patient_name': 'Sample patient name', 'medicine': 'Sample medicine', 'dosage': 'Sample dosage', 'days': 1, 'instructions': 'Sample instructions'}, 'days': 91.0}
    resp = client.post(f"/api/doctors/{parent['id']}/prescriptions", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Days must be between 1 and 90'}, 'adding with a bad days: ' + resp.text
    resp = client.put(f"/api/prescriptions/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Days must be between 1 and 90'}, 'editing with a bad days: ' + resp.text
