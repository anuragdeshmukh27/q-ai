"""QA edge cases generated from the API contract. Do not edit; fix the code instead."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_post_api_doctors_rejects_empty_body():
    assert client.post('/api/doctors', json={}).status_code == 422


def test_post_api_doctors_rejects_missing_name():
    assert client.post('/api/doctors', json={'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_department():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_phone():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_email():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_consultation_fee():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_non_numeric_consultation_fee():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 'not a number', 'room': 'Sample room', 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_room():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'availability': 'Available'}).status_code == 422


def test_post_api_doctors_rejects_missing_availability():
    assert client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room'}).status_code == 422


def test_posted_item_shows_up_in_the_list():
    r = client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code < 300, r.text
    items = client.get('/api/doctors').json()['items']
    assert len(items) == 1
    for k, v in {'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}.items():
        if k in items[0]:
            assert items[0][k] == (pytest.approx(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)


def test_put_api_doctors_id_updates_the_item():
    r = client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code < 300, r.text
    seed = r.json()
    r = client.put(f"/api/doctors/{seed['id']}", json={'name': 'Sample name v2', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code == 200, r.text
    items = client.get('/api/doctors').json()['items']
    assert len(items) == 1
    assert items[0]['name'] == 'Sample name v2'


def test_delete_api_doctors_id_removes_the_item():
    r = client.post('/api/doctors', json={'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'})
    assert r.status_code < 300, r.text
    seed = r.json()
    r = client.delete(f"/api/doctors/{seed['id']}")
    assert r.status_code == 200, r.text
    assert client.get('/api/doctors').json()['items'] == []
