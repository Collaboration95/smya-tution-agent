from fastapi.testclient import TestClient
from backend.app.main import app

def test_root():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    j = r.json()
    assert "name" in j
    assert "version" in j

def test_health():
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j["db"] in ("ok", "unavailable")
    assert j["model_provider"] == "fake"
    assert "version" in j
