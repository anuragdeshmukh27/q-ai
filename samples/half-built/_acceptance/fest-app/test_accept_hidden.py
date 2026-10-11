"""Hidden acceptance for the fest-app fixture: what a person would check by hand. Q never sees this file."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def event():
    return client.post("/api/events", json={"name": "CodeSprint", "venue": "Hall A", "capacity": 10}).json()


def test_the_registration_flow():
    ev = event()
    r = client.post(f"/api/events/{ev['id']}/registrations", json={"student_name": "Asha", "email": "asha@example.com"})
    assert r.status_code == 201
    reg = r.json()
    assert reg["status"] == "Registered" and reg["student_name"] == "Asha"
    items = client.get(f"/api/events/{ev['id']}/registrations").json()["items"]
    assert [i["student_name"] for i in items] == ["Asha"]
    assert client.post(f"/api/registrations/{reg['id']}/check_in").json()["status"] == "Checked in"
    assert client.post(f"/api/registrations/{reg['id']}/cancel").json()["status"] == "Cancelled"


def test_unknown_things_are_404():
    assert client.get("/api/events/999/registrations").status_code == 404
    assert client.post("/api/events/999/registrations", json={"student_name": "A", "email": "a@x.in"}).status_code == 404
    assert client.post("/api/registrations/999/check_in").status_code == 404
    assert client.post("/api/registrations/999/cancel").status_code == 404


def test_stats_and_sponsors():
    assert client.get("/api/sponsors").json() == {"items": []}
    assert client.get("/api/stats").json() == {"events": 0, "registrations": 0}
    ev = event()
    client.post(f"/api/events/{ev['id']}/registrations", json={"student_name": "Asha", "email": "asha@example.com"})
    assert client.get("/api/stats").json() == {"events": 1, "registrations": 1}
