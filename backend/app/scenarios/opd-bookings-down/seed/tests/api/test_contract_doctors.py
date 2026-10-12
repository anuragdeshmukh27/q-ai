"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""
import itertools

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_n = itertools.count(1)  # makes unique values differ


def test_get_api_doctors_1_lists_doctors():
    r = client.get('/api/doctors')
    assert r.status_code == 200, r.text
    data = r.json()
    assert 'items' in data


def test_post_api_doctors_1_adds_a_doctor():
    r = client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code == 201, r.text
    data = r.json()
    assert 'id' in data
    assert 'name' in data
    assert 'department' in data
    assert 'phone' in data
    assert 'email' in data
    assert 'consultation_fee' in data
    assert 'room' in data
    assert 'availability' in data
    assert 'created_at' in data
    assert data['name'] == 'Sample name'
    assert data['department'] == 'General Medicine'
    assert data['phone'] == '9876500000'
    assert data['email'] == 'ada@example.com'
    assert data['consultation_fee'] == pytest.approx(2.5)
    assert data['room'] == 'Sample room'
    assert data['availability'] == 'Available'


def test_put_api_doctors_id_1_rejects_an_unknown_id():
    r = client.put('/api/doctors/99999', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_delete_api_doctors_id_1_rejects_an_unknown_id():
    r = client.delete('/api/doctors/99999')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


BASE_DOCTORS = {'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}
UNIQ_DOCTORS = {'email': 'user{n}@example.com'}


def make_doctor(**over):
    r = client.post('/api/doctors', json={**BASE_DOCTORS, **{k: t.format(n=next(_n)) for k, t in UNIQ_DOCTORS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_doctors_blank_required_text_is_a_400_with_a_message():
    item = make_doctor()
    for field, message in [('name', 'Name is required'), ('room', 'Room is required')]:
        for blank in ('', '   '):
            body = {**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, field: blank}
            r = client.post('/api/doctors', json=body)
            assert r.status_code == 400, f'adding with a blank {field} must be a 400, not {r.status_code}: use the request model as generated'
            assert r.json() == {'detail': message}, r.text
            r = client.put(f"/api/doctors/{item['id']}", json=body)
            assert r.status_code == 400 and r.json() == {'detail': message}, f'editing with a blank {field}: {r.status_code} {r.text}'
    assert len(client.get('/api/doctors').json()['items']) == 1, 'a refused request must not store anything'


def test_doctors_rule_values_are_checked_with_a_400_and_a_message():
    item = make_doctor()
    body = {**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, 'phone': '12345'}
    resp = client.post('/api/doctors', json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Phone must be a 10-digit mobile number'}, 'adding with a bad phone: ' + resp.text
    resp = client.put(f"/api/doctors/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Phone must be a 10-digit mobile number'}, 'editing with a bad phone: ' + resp.text
    body = {**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, 'email': 'not-an-email'}
    resp = client.post('/api/doctors', json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Email must be a valid email address'}, 'adding with a bad email: ' + resp.text
    resp = client.put(f"/api/doctors/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Email must be a valid email address'}, 'editing with a bad email: ' + resp.text
    body = {**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, 'consultation_fee': 0}
    resp = client.post('/api/doctors', json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Consultation fee must be greater than 0'}, 'adding with a bad consultation_fee: ' + resp.text
    resp = client.put(f"/api/doctors/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Consultation fee must be greater than 0'}, 'editing with a bad consultation_fee: ' + resp.text


def test_doctors_email_must_be_unique():
    first = make_doctor()
    body = {**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, 'email': first['email']}
    resp = client.post('/api/doctors', json=body)
    assert resp.status_code == 409 and resp.json() == {'detail': 'Email already exists'}, resp.text
    second = make_doctor()
    resp = client.put(f"/api/doctors/{second['id']}", json={**{'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}, 'email': first['email']})
    assert resp.status_code == 409, resp.text
    assert len(client.get('/api/doctors').json()['items']) == 2, 'a refused request must not store anything'
