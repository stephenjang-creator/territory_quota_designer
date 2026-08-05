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


def test_conversions_defaults_endpoint():
    body = client.get("/conversions").json()
    assert "Enterprise" in body["segments"]
    assert body["avg_deal_key"] == "avg_deal_size"
    assert "Negotiation->Won" in body["transitions"]
    # defaults carry a rate per transition + a deal size for every segment
    ent = body["defaults"]["Enterprise"]
    assert ent["avg_deal_size"] > 0 and 0 < ent["Negotiation->Won"] <= 1


def test_levels_endpoint():
    body = client.get("/levels").json()
    assert body["levels"] == ["ramping", "AE", "Sr. AE", "Sr. Strategic AE"]
    assert body["multipliers"]["AE"] == 1.0
    assert body["multipliers"]["ramping"] < 1.0 < body["multipliers"]["Sr. Strategic AE"]
    assert sum(body["counts"].values()) == 12  # every rep placed at a level


def test_comp_defaults_endpoint():
    d = client.get("/comp/defaults").json()["defaults"]
    assert 0 < d["commission_rate"] < 1
    assert d["decelerator_multiplier"] < 1 < d["accelerator_multiplier"]
    assert d["decelerator_threshold"] < d["accelerator_threshold"]


def test_plan_returns_payout_curve_and_comp_reacts_to_decelerator():
    base = client.post("/plan", json={}).json()
    assert base["payout_curve"] and "comp_params" in base

    def cos(plan, att):
        return next(r["cost_of_sale"] for r in plan["comp"] if abs(r["attainment"] - att) < 1e-9)

    # A steeper decelerator (bigger under-attainment penalty) is cheaper at 85%.
    lean = client.post("/plan", json={"comp": {"decelerator_multiplier": 0.2}}).json()
    assert cos(lean, 0.85) < cos(base, 0.85)


def test_plan_endpoint_runs_the_chain():
    body = client.post("/plan", json={}).json()
    assert body["summary"]["units"]["quota_period"] == "quarterly"
    assert body["summary"]["n_territories"] == 12
    assert len(body["territories"]) == 12
    assert len(body["comp"]) == 3
    # territory rows now carry the rep's seniority level
    assert all(t.get("level") for t in body["territories"])


def test_plan_accepts_conversion_and_level_overrides():
    # A segment conversion override + a per-level quota override both apply and the
    # chain still returns a full plan (quotas re-normalize to the same target).
    payload = {
        "overrides": {"segment": {"Enterprise": {"Negotiation->Won": 0.2}}},
        "level_multipliers": {"Sr. Strategic AE": 1.6},
    }
    base = client.post("/plan", json={}).json()
    got = client.post("/plan", json=payload).json()
    assert got["summary"]["n_territories"] == 12

    def strat_quota(rows):
        return {t["rep_id"]: t["quota"] for t in rows if t["level"] == "Sr. Strategic AE"}

    strat_base, strat_now = strat_quota(base["territories"]), strat_quota(got["territories"])
    assert strat_base and all(strat_now[r] > strat_base[r] for r in strat_base)


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
