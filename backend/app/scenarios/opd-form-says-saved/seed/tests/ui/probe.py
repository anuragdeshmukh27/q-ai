"""Helpers for the tests that run the pages in Node (tests/ui/refusals.mjs). `live_answers` asks the real API what it answers when a request is refused (or succeeds):
the page tests feed those real answers to the page, so a failure is about what the page does with a correct answer."""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINNED = Path(__file__).with_name("answers.json")  # the answers below, as they were when this app was finished (a test keeps them honest)
BOOKING = {"patient_name": "Sana Sheikh", "patient_phone": "9812345678", "date": "2026-10-15", "time": "11:00", "reason": "Follow-up", "status": "Booked"}


def run_node(case: dict, root: Path = ROOT) -> dict:
    """Runs one case of tests/ui/refusals.mjs on the pages under `root`/static and returns what it printed. Fails (it does not skip) when Node is missing."""
    node = shutil.which("node")
    assert node, "node is not installed: the page tests need it"
    r = subprocess.run([node, str(root / "tests" / "ui" / "refusals.mjs"), json.dumps(case)], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def live_answers(client) -> dict:
    """What the real API answers, case by case: {name: {"case": how the request is made on the page, "status": ..., "body": ...}}."""
    doctor = client.post("/api/doctors", json={"name": "Dr. Farhan Ali", "department": "Pediatrics", "phone": "8408975520", "email": "farhan@example.com", "consultation_fee": 250, "room": "OPD 305", "availability": "Available"}).json()
    book = lambda **change: client.post(f"/api/doctors/{doctor['id']}/appointments", json={**BOOKING, **change})
    first = book()
    second = book(time="12:00")
    taken = book()
    bad_phone = book(patient_phone="98765", time="13:00")
    moved = client.put(f"/api/appointments/{second.json()['id']}", json={**BOOKING, "time": "11:00"})
    edited = client.put(f"/api/appointments/{second.json()['id']}", json={**BOOKING, "time": "14:00"})
    completed = client.post(f"/api/appointments/{first.json()['id']}/complete")
    refused = client.post(f"/api/appointments/{first.json()['id']}/cancel")
    removed = client.delete(f"/api/appointments/{second.json()['id']}")
    missing = client.delete("/api/appointments/9999")
    same_email = client.post("/api/doctors", json={"name": "Dr. Other", "department": "Pediatrics", "phone": "8408975521", "email": "farhan@example.com", "consultation_fee": 250, "room": "OPD 306", "availability": "Available"})
    long_course = client.post(f"/api/doctors/{doctor['id']}/prescriptions", json={"patient_name": "Sana Sheikh", "medicine": "Paracetamol", "dosage": "500 mg", "days": 200, "instructions": "After food"})
    answer = lambda case, r, **more: {"case": case, "status": r.status_code, "body": r.json(), **more}
    return {
        "create_taken": answer("create", taken),
        "create_bad_phone": answer("create", bad_phone, phone="98765"),
        "edit_taken": answer("edit", moved),
        "action_refused": answer("action", refused),
        "board_refused": answer("board", refused),
        "delete_missing": answer("delete", missing),
        "create_doctor_email_taken": answer("create", same_email, page="#/doctors", fill={"email": "farhan@example.com"}),  # the same mistake on another module: not only appointments
        "create_prescription_bad_days": answer("create", long_course, page="#/prescriptions", fill={"days": "200"}),
        "create_ok": answer("create", first),
        "edit_ok": answer("edit", edited),
        "action_ok": answer("action", completed),
        "delete_ok": answer("delete", removed),
        "no_json": {"case": "create", "status": 502, "text": "<html><body>502 Bad Gateway</body></html>"},
    }


def pinned_answers() -> dict:
    return json.loads(PINNED.read_text(encoding="utf-8"))
