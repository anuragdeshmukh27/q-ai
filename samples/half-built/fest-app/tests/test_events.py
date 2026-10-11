from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_and_list_events():
    r = client.post("/api/events", json={"name": "CodeSprint", "venue": "Hall A", "capacity": 50})
    assert r.status_code == 201
    items = client.get("/api/events").json()["items"]
    assert [e["name"] for e in items] == ["CodeSprint"]


def test_delete_event():
    event = client.post("/api/events", json={"name": "Quiz", "venue": "Hall B"}).json()
    assert client.delete(f"/api/events/{event['id']}").status_code == 200
    assert client.delete(f"/api/events/{event['id']}").status_code == 404
