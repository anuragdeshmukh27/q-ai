"""UI script test generated from the API contract. Do not edit; fix the script instead."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


def test_script_calls_every_endpoint():
    js = client.get('/static/app.js').text
    assert 'Q.mount' in js
    assert '/api/appointments' in js
    assert '/api/doctors' in js
    assert '/api/lab_tests' in js
    assert '/api/prescriptions' in js


def test_every_resource_is_a_module_with_its_own_page():
    js = client.get('/static/app.js').text
    assert '"name": "doctors"' in js and '/api/doctors/{id}' in js and '/api/doctors' in js
    assert '"name": "appointments"' in js and '/api/appointments/{id}' in js and '/api/doctors/{parent}/appointments' in js
    assert '/api/appointments/{id}/complete' in js, 'the complete button of appointments needs its endpoint in the description'
    assert '/api/appointments/{id}/cancel' in js, 'the cancel button of appointments needs its endpoint in the description'
    assert '"name": "prescriptions"' in js and '/api/prescriptions/{id}' in js and '/api/doctors/{parent}/prescriptions' in js
    assert '"name": "lab_tests"' in js and '/api/lab_tests/{id}' in js and '/api/doctors/{parent}/lab_tests' in js
    assert '/api/lab_tests/{id}/collect' in js, 'the collect button of lab_tests needs its endpoint in the description'
    assert '/api/lab_tests/{id}/report' in js, 'the report button of lab_tests needs its endpoint in the description'


def test_every_field_is_in_the_description():
    js = client.get('/static/app.js').text
    for field in ['availability', 'consultation_fee', 'cost', 'date', 'days', 'department', 'dosage', 'email', 'instructions', 'medicine', 'name', 'patient_name', 'patient_phone', 'phone', 'reason', 'room', 'status', 'test_name', 'time']:
        assert re.search(r'[\'"]' + field + r'[\'"]', js), f"the field '{field}' has dropped out of the description"


def test_categories_are_shown_as_labels_not_numbers():
    js = client.get('/static/app.js').text
    for field, labels in {'doctors.department': ['General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics', 'ENT'], 'doctors.availability': ['Available', 'On leave'], 'appointments.status': ['Booked', 'Completed', 'Cancelled'], 'lab_tests.test_name': ['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test'], 'lab_tests.status': ['Ordered', 'Collected', 'Reported']}.items():
        for label in labels:
            assert label in js, f"the label '{label}' of '{field}' is missing"


def test_every_route_renders():
    """shell.js and app.js run in a small fake browser (tests/ui/shell_smoke.mjs): the dashboard, every list page and a detail page must draw."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    r = subprocess.run([node, str(ROOT / 'tests' / 'ui' / 'shell_smoke.mjs')], cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
