"""Contract tests generated from the API contract examples. Do not edit; fix the code instead."""
import itertools

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_n = itertools.count(1)  # makes unique values differ


def test_get_api_doctors_doctor_id_lab_tests_1_rejects_an_unknown_doctor():
    r = client.get('/api/doctors/99999/lab_tests')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_post_api_doctors_doctor_id_lab_tests_1_rejects_an_unknown_doctor():
    r = client.post('/api/doctors/99999/lab_tests', json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Doctor not found'


def test_put_api_lab_tests_id_1_rejects_an_unknown_id():
    r = client.put('/api/lab_tests/99999', json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'})
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Lab test not found'


def test_delete_api_lab_tests_id_1_rejects_an_unknown_id():
    r = client.delete('/api/lab_tests/99999')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Lab test not found'


def test_post_api_lab_tests_id_collect_1_rejects_an_unknown_id():
    r = client.post('/api/lab_tests/99999/collect')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Lab test not found'


def test_post_api_lab_tests_id_report_1_rejects_an_unknown_id():
    r = client.post('/api/lab_tests/99999/report')
    assert r.status_code == 404, r.text
    assert r.json()['detail'] == 'Lab test not found'


BASE_DOCTORS = {'name': 'Sample name', 'department': 'General Medicine', 'phone': '9876500000', 'email': 'ada@example.com', 'consultation_fee': 2.5, 'room': 'Sample room', 'availability': 'Available'}
UNIQ_DOCTORS = {'email': 'user{n}@example.com'}


def make_doctor(**over):
    r = client.post('/api/doctors', json={**BASE_DOCTORS, **{k: t.format(n=next(_n)) for k, t in UNIQ_DOCTORS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


BASE_LAB_TESTS = {'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'}
UNIQ_LAB_TESTS = {}


def make_lab_test(parent_id, **over):
    r = client.post(f'/api/doctors/{parent_id}/lab_tests', json={**BASE_LAB_TESTS, **{k: t.format(n=next(_n)) for k, t in UNIQ_LAB_TESTS.items()}, **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_lab_tests_are_created_and_listed_under_their_doctor():
    parent = make_doctor()
    item = make_lab_test(parent['id'])
    assert item['doctor_id'] == parent['id']
    items = client.get(f"/api/doctors/{parent['id']}/lab_tests").json()['items']
    assert [i['id'] for i in items] == [item['id']]


def test_lab_tests_of_an_unknown_doctor_are_404():
    r = client.get(f"/api/doctors/99999/lab_tests")
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text
    r = client.post(f"/api/doctors/99999/lab_tests", json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'})
    assert r.status_code == 404 and r.json() == {'detail': 'Doctor not found'}, r.text


def test_lab_tests_belong_to_one_doctor_only():
    a = make_doctor()
    b = make_doctor()
    item = make_lab_test(a['id'])
    assert client.get(f"/api/doctors/{b['id']}/lab_tests").json()['items'] == []


def test_lab_tests_parent_id_must_be_an_integer():
    assert client.get('/api/doctors/abc/lab_tests').status_code == 422


def test_lab_tests_body_is_validated():
    parent = make_doctor()
    assert client.post(f"/api/doctors/{parent['id']}/lab_tests", json={'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/lab_tests", json={'patient_name': 'Sample patient name', 'cost': 2.5, 'status': 'Ordered'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/lab_tests", json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'status': 'Ordered'}).status_code == 422
    assert client.post(f"/api/doctors/{parent['id']}/lab_tests", json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5}).status_code == 422


def test_deleting_a_doctor_deletes_its_lab_tests():
    parent = make_doctor()
    item = make_lab_test(parent['id'])
    r = client.delete(f"/api/doctors/{parent['id']}")
    assert r.status_code == 200, r.text
    r = client.put(f"/api/lab_tests/{item['id']}", json={'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'})
    assert r.status_code == 404, 'deleting the doctor must delete its lab_tests too'


def test_lab_tests_blank_required_text_is_a_400_with_a_message():
    parent = make_doctor()
    item = make_lab_test(parent['id'])
    for field, message in [('patient_name', 'Patient name is required')]:
        for blank in ('', '   '):
            body = {**{'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'}, field: blank}
            r = client.post(f"/api/doctors/{parent['id']}/lab_tests", json=body)
            assert r.status_code == 400, f'adding with a blank {field} must be a 400, not {r.status_code}: use the request model as generated'
            assert r.json() == {'detail': message}, r.text
            r = client.put(f"/api/lab_tests/{item['id']}", json=body)
            assert r.status_code == 400 and r.json() == {'detail': message}, f'editing with a blank {field}: {r.status_code} {r.text}'
    assert len(client.get(f"/api/doctors/{parent['id']}/lab_tests").json()['items']) == 1, 'a refused request must not store anything'


def test_lab_tests_collect_sets_status_to_collected():
    parent = make_doctor()
    item = make_lab_test(parent['id'], status='Ordered')
    r = client.post(f"/api/lab_tests/{item['id']}/collect")
    assert r.status_code == 200, r.text
    assert r.json()['id'] == item['id'], 'the action must return the updated item'
    assert r.json()['status'] == 'Collected', 'collect must set status to Collected'
    assert r.json()['patient_name'] == item['patient_name'], 'collect must not change patient_name'
    assert r.json()['test_name'] == item['test_name'], 'collect must not change test_name'
    assert r.json()['cost'] == item['cost'], 'collect must not change cost'
    listed = client.get(f"/api/doctors/{parent['id']}/lab_tests").json()['items']
    assert [i for i in listed if i['id'] == item['id']][0]['status'] == 'Collected', 'the list must show the new value'
    r = client.post("/api/lab_tests/99999/collect")
    assert r.status_code == 404, r.text


def test_lab_tests_report_sets_status_to_reported():
    parent = make_doctor()
    item = make_lab_test(parent['id'], status='Collected')
    r = client.post(f"/api/lab_tests/{item['id']}/report")
    assert r.status_code == 200, r.text
    assert r.json()['id'] == item['id'], 'the action must return the updated item'
    assert r.json()['status'] == 'Reported', 'report must set status to Reported'
    assert r.json()['patient_name'] == item['patient_name'], 'report must not change patient_name'
    assert r.json()['test_name'] == item['test_name'], 'report must not change test_name'
    assert r.json()['cost'] == item['cost'], 'report must not change cost'
    listed = client.get(f"/api/doctors/{parent['id']}/lab_tests").json()['items']
    assert [i for i in listed if i['id'] == item['id']][0]['status'] == 'Reported', 'the list must show the new value'
    r = client.post("/api/lab_tests/99999/report")
    assert r.status_code == 404, r.text


def test_lab_tests_rule_values_are_checked_with_a_400_and_a_message():
    parent = make_doctor()
    item = make_lab_test(parent['id'])
    body = {**{'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'}, 'cost': 0}
    resp = client.post(f"/api/doctors/{parent['id']}/lab_tests", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Cost must be greater than 0'}, 'adding with a bad cost: ' + resp.text
    resp = client.put(f"/api/lab_tests/{item['id']}", json=body)
    assert resp.status_code == 400 and resp.json() == {'detail': 'Cost must be greater than 0'}, 'editing with a bad cost: ' + resp.text


def test_lab_tests_status_cannot_leave_reported():
    parent = make_doctor()
    item = make_lab_test(parent['id'], status='Reported')
    resp = client.put(f"/api/lab_tests/{item['id']}", json={**{'patient_name': 'Sample patient name', 'test_name': 'Blood test', 'cost': 2.5, 'status': 'Ordered'}, 'status': 'Ordered'})
    assert resp.status_code == 409 and resp.json() == {'detail': 'That status change is not allowed'}, resp.text
    resp = client.post(f"/api/lab_tests/{item['id']}/collect")
    assert resp.status_code == 409, resp.text
    assert client.get(f"/api/doctors/{parent['id']}/lab_tests").json()['items'][0]['status'] == 'Reported', 'a refused change must leave the status as it was'
