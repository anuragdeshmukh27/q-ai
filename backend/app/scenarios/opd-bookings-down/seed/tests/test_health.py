from fastapi.testclient import TestClient

from backend.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_index_served():
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "<html" in r.text
