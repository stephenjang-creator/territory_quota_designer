"""API smoke tests — dashboard, health probes, and the stage endpoints."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_root_serves_dashboard_html():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert b"<title>Territory" in r.content
    assert client.head("/").status_code == 200


def test_api_index_json():
    r = client.get("/api")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "Territory & Quota Designer"
    assert body["dashboard"] == "/"
    assert "/plan" in body["endpoints"]


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_favicon_no_content():
    assert client.get("/favicon.ico").status_code == 204


def test_plan_endpoint_runs_the_chain():
    body = client.post("/plan", json={}).json()
    assert body["summary"]["units"]["quota_period"] == "quarterly"
    assert body["summary"]["n_territories"] == 12
    assert len(body["territories"]) == 12
    assert len(body["comp"]) == 3


def test_territory_detail_get_and_post_settings():
    assert client.get("/territory/R-101").status_code == 200
    assert client.get("/territory/R-999").status_code == 404
    # POST with settings recomputes the funnel under those weights
    r = client.post(
        "/territory/R-101", json={"weights": {"potential": 10, "geo": 85, "whitespace": 5}}
    )
    assert r.status_code == 200
    d = r.json()
    assert set(d["waterfall"]["funnel"]) == {
        "required_sqls",
        "qualification",
        "proposal",
        "negotiation",
        "won_deals",
    }
    assert client.post("/territory/R-999", json={}).status_code == 404
