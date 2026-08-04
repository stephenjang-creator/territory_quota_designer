"""API smoke tests — the root/health endpoints (deploy probes) + one stage call."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_root_returns_200_index():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "Territory & Quota Designer"
    assert body["docs"] == "/docs"
    assert "/plan" in body["endpoints"]


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_favicon_no_content():
    assert client.get("/favicon.ico").status_code == 204


def test_plan_endpoint_runs_the_chain():
    r = client.post("/plan", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["units"]["quota_period"] == "quarterly"
    assert body["summary"]["n_territories"] == 12
    assert len(body["territories"]) == 12


def test_territory_detail_and_404():
    assert client.get("/territory/R-101").status_code == 200
    assert client.get("/territory/R-999").status_code == 404
