"""Booking tests of the front desk: book an appointment, move it, and ask which times of a doctor's day are taken."""
import itertools

from fastapi.testclient import TestClient

from backend.main import app
from database import appointments as appointments_db

client = TestClient(app)
_n = itertools.count(1)

DOCTOR = {'name': 'Dr. Asha Menon', 'department': 'General Medicine', 'phone': '9876500000', 'room': 'OPD 7', 'consultation_fee': 400, 'availability': 'Available'}
BOOKING = {'patient_name': 'Ravi Kumar', 'patient_phone': '9876511111', 'date': '2026-10-12', 'time': '10:30', 'reason': 'Fever for two days', 'status': 'Booked'}


def make_doctor() -> dict:
    r = client.post('/api/doctors', json={**DOCTOR, 'email': f'doctor{next(_n)}@example.com'})
    assert r.status_code == 201, r.text
    return r.json()


def test_booking_an_appointment_returns_201():
    doctor = make_doctor()
    r = client.post(f"/api/doctors/{doctor['id']}/appointments", json=BOOKING)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['doctor_id'] == doctor['id'] and body['time'] == '10:30' and body['status'] == 'Booked'
    listed = client.get(f"/api/doctors/{doctor['id']}/appointments").json()['items']
    assert [x['id'] for x in listed] == [body['id']] and listed[0]['time'] == '10:30'


def test_editing_an_appointment_moves_its_time():
    doctor = make_doctor()
    booked = client.post(f"/api/doctors/{doctor['id']}/appointments", json=BOOKING).json()
    r = client.put(f"/api/appointments/{booked['id']}", json={**BOOKING, 'time': '11:15'})
    assert r.status_code == 200, r.text
    assert r.json()['time'] == '11:15'


def test_doctor_slots_list_the_booked_times_of_the_day():
    doctor = make_doctor()
    for time in ('14:00', '09:30'):  # added straight to the database layer, so this test does not depend on the booking route
        appointments_db.add_appointment(doctor_id=doctor['id'], patient_name='Walk-in', patient_phone='9876522222', date='2026-10-12', slot_at=time, reason='Check-up', status='Booked')
    appointments_db.add_appointment(doctor_id=doctor['id'], patient_name='Cancelled', patient_phone='9876533333', date='2026-10-12', slot_at='12:00', reason='Check-up', status='Cancelled')
    appointments_db.add_appointment(doctor_id=doctor['id'], patient_name='Tomorrow', patient_phone='9876544444', date='2026-10-13', slot_at='08:00', reason='Check-up', status='Booked')
    r = client.get(f"/api/doctors/{doctor['id']}/slots", params={'date': '2026-10-12'})
    assert r.status_code == 200, r.text
    assert r.json() == {'date': '2026-10-12', 'booked': ['09:30', '14:00']}


def test_slots_of_an_unknown_doctor_is_404():
    r = client.get('/api/doctors/99999/slots', params={'date': '2026-10-12'})
    assert r.status_code == 404 and r.json()['detail'] == 'Doctor not found'
