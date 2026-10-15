"""Double bookings through the API: a slot that is Booked cannot be booked again, and a cancelled slot is free."""
import itertools

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
_n = itertools.count(1)

DOCTOR = {'name': 'Dr. Asha Menon', 'department': 'General Medicine', 'phone': '9876500000', 'room': 'OPD 7', 'consultation_fee': 400, 'availability': 'Available'}
BOOKING = {'patient_name': 'Ravi Kumar', 'patient_phone': '9876511111', 'date': '2026-10-12', 'time': '10:30', 'reason': 'Fever for two days', 'status': 'Booked'}
OTHER = {'patient_name': 'Meena Iyer', 'patient_phone': '9876522222'}


def make_doctor() -> dict:
    r = client.post('/api/doctors', json={**DOCTOR, 'email': f'doctor{next(_n)}@example.com'})
    assert r.status_code == 201, r.text
    return r.json()


def book(doctor_id: int, **over):
    return client.post(f'/api/doctors/{doctor_id}/appointments', json={**BOOKING, **over})


def test_booking_the_same_slot_twice_returns_409_slot_already_booked():
    doctor = make_doctor()
    assert book(doctor['id']).status_code == 201
    second = book(doctor['id'], **OTHER)
    assert second.status_code == 409, second.text
    assert second.json()['detail'] == 'Slot already booked'
    assert len(client.get(f"/api/doctors/{doctor['id']}/appointments").json()['items']) == 1


def test_moving_an_appointment_onto_a_taken_slot_returns_409():
    doctor = make_doctor()
    assert book(doctor['id']).status_code == 201
    other = book(doctor['id'], time='11:00', **OTHER).json()
    r = client.put(f"/api/appointments/{other['id']}", json={**BOOKING, **OTHER, 'time': '10:30'})
    assert r.status_code == 409, r.text
    assert r.json()['detail'] == 'Slot already booked'


def test_a_cancelled_slot_can_be_booked_again():
    doctor = make_doctor()
    first = book(doctor['id']).json()
    assert client.post(f"/api/appointments/{first['id']}/cancel").status_code == 200
    again = book(doctor['id'], **OTHER)
    assert again.status_code == 201, again.text


def test_the_same_time_with_another_doctor_or_on_another_day_is_free():
    a, b = make_doctor(), make_doctor()
    assert book(a['id']).status_code == 201
    assert book(b['id']).status_code == 201
    assert book(a['id'], date='2026-10-13').status_code == 201
    assert book(a['id'], time='10:45').status_code == 201


def test_saving_an_appointment_without_moving_it_is_still_allowed():
    doctor = make_doctor()
    booked = book(doctor['id']).json()
    r = client.put(f"/api/appointments/{booked['id']}", json={**BOOKING, 'reason': 'Fever and a headache'})
    assert r.status_code == 200, r.text
