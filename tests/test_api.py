"""API smoke tests — dashboard, health probes, and the quota-first endpoints."""

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
    body = client.get("/api").json()
    assert body["service"] == "Territory & Quota Designer"
    assert body["dashboard"] == "/"
    assert "/plan" in body["endpoints"] and "/roles" in body["endpoints"]


def test_health_and_favicon():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/favicon.ico").status_code == 204


def test_roles_endpoint():
    body = client.get("/roles").json()
    assert body["quota_to_ote"] == 4.0 and body["coverage_target"] == 3.0
    assert body["periods_per_year"] == 4
    assert {r["segment"] for r in body["roles"]} == {"Enterprise", "Mid-Market", "SMB"}
    ppy = body["periods_per_year"]
    # quarterly quota = annual (multiple x OTE) / periods; annual_quota is the 4-6x headline
    assert all(abs(r["quota"] - body["quota_to_ote"] * r["ote"] / ppy) < 1 for r in body["roles"])
    assert all(abs(r["annual_quota"] - body["quota_to_ote"] * r["ote"]) < 1 for r in body["roles"])


def test_conversions_and_comp_defaults():
    conv = client.get("/conversions").json()
    assert "Enterprise" in conv["segments"] and conv["avg_deal_key"] == "avg_deal_size"
    comp = client.get("/comp/defaults").json()["defaults"]
    assert "commission_rate" not in comp  # OTE-anchored now
    assert comp["decelerator_multiplier"] < 1 < comp["accelerator_multiplier"]


def test_plan_endpoint_shape():
    body = client.post("/plan", json={}).json()
    sm = body["summary"]
    assert sm["units"]["quota_period"] == "quarterly"
    assert sm["n_territories"] == 14
    assert sm["reps_covered"]["of"] == 14
    assert sm["coverage_target"] == 3.0
    assert set(sm["per_segment_capacity"]) == {"Enterprise", "Mid-Market", "SMB"}
    assert "coverage_floor" in sm and "capacity_gap" in sm
    assert len(body["territories"]) == 14
    row = body["territories"][0]
    for k in ("role", "ote", "quota", "pipeline_coverage", "available_pipeline"):
        assert k in row
    assert len(body["payout_curve"]) == 16 and len(body["comp"]) == 3


def test_same_role_same_quota_over_the_wire():
    rows = client.post("/plan", json={}).json()["territories"]
    by_role: dict[str, set] = {}
    for r in rows:
        by_role.setdefault(r["role"], set()).add(r["quota"])
    assert all(len(v) == 1 for v in by_role.values())


def test_plan_accepts_ote_and_coverage_overrides():
    base = client.post("/plan", json={}).json()["summary"]
    got = client.post(
        "/plan",
        json={"ote_overrides": {"Enterprise": {"AE": 1_100_000}}, "coverage_target": 4.0},
    ).json()["summary"]
    assert got["coverage_target"] == 4.0
    assert got["company_target"] > base["company_target"]  # richer Enterprise AE OTE
    # a stiffer coverage target covers no more reps than 3x
    assert got["reps_covered"]["optimized"] <= base["reps_covered"]["optimized"]


def test_balance_and_quota_endpoints():
    bal = client.post("/balance", json={}).json()
    assert bal["coverage_target"] == 3.0 and "capacity_gap" in bal
    assert bal["per_segment_capacity"]["SMB"]["coverable"] is False
    q = client.post("/quota", json={}).json()
    assert q["quota_to_ote"] == 4.0
    assert all("role" in t and "ote" in t for t in q["territories"])


def test_territory_detail_get_and_post():
    assert client.get("/territory/R-101").status_code == 200
    assert client.get("/territory/R-999").status_code == 404
    d = client.post("/territory/R-101", json={"coverage_target": 4.0}).json()
    assert set(d["waterfall"]["funnel"]) == {
        "required_sqls",
        "qualification",
        "proposal",
        "negotiation",
        "won_deals",
    }
    assert client.post("/territory/R-999", json={}).status_code == 404


def test_plan_accepts_added_reps():
    base = client.post("/plan", json={}).json()["summary"]
    body = {"added_reps": [{"name": "TBH", "segment": "SMB", "level": "AE"}]}
    got = client.post("/plan", json=body).json()
    assert got["summary"]["n_territories"] == base["n_territories"] + 1
    assert got["summary"]["company_target"] > base["company_target"]
    planned = [r for r in got["territories"] if r["rep_id"].startswith("NEW-")]
    assert planned and planned[0]["rep_name"] == "TBH" and planned[0]["role"] == "SMB · AE"
    # the added rep's territory resolves under the same settings (dashboard drill-in)
    d = client.post("/territory/NEW-1", json=body).json()
    assert d["role"] == "SMB · AE" and d["quota"] > 0


def test_plan_returns_recommendations_and_a_lever_resolves_over_the_wire():
    recs = client.post("/plan", json={}).json()["recommendations"]
    cats = {x["category"] for x in recs}
    assert {"pipeline", "hiring", "comp", "sensitivity"} <= cats
    pipe = next(x for x in recs if x["id"] == "pipeline-SMB")
    # send a lever's apply-delta back to /plan; SMB should come back coverable
    delta = next(lv["apply"] for lv in pipe["levers"] if "account_retags" in lv["apply"])
    got = client.post("/plan", json=delta).json()["summary"]
    assert got["per_segment_capacity"]["SMB"]["coverable"] is True


def test_plan_accepts_segment_override():
    base = client.post("/plan", json={}).json()["summary"]
    got = client.post("/plan", json={"segment_overrides": {"SMB": {"quota_to_ote": 3.25}}}).json()[
        "summary"
    ]
    assert got["per_segment_capacity"]["SMB"]["coverable"] is True
    assert got["company_target"] < base["company_target"]
