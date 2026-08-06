"""The natural-language Ask layer: the deterministic router answers recognized
questions offline with grounded numbers, and the /ask endpoint wires it up. The live
Claude path is not exercised here (it needs a key); the router is the offline demo."""

from fastapi.testclient import TestClient

from api.main import app
from core import ask

client = TestClient(app)


def test_find_rep_by_id_name_and_ambiguous(reps):
    smb = next(r for r in reps if r.rep_id == "R-125")
    hit, cands = ask.find_rep("what does R-125 need?", reps)
    assert hit is not None and hit.rep_id == "R-125"
    hit2, _ = ask.find_rep(f"how is {smb.name} doing", reps)
    assert hit2 is not None and hit2.rep_id == "R-125"
    # First-name-only can be ambiguous across the roster; the resolver reports it.
    first = smb.name.split()[0].lower()
    shared = [r for r in reps if r.name.lower().split()[0] == first]
    if len(shared) > 1:
        hit3, cands3 = ask.find_rep(f"tell me about {first}", reps)
        assert hit3 is None and len(cands3) > 1


def test_router_segment_risk(data, plan):
    a, r, c = data
    res = ask.answer("which segment is most at risk?", a, r, c, plan=plan)
    assert res["mode"] == "demo" and "get_scorecard" in res["used"]
    assert res["grounded"]["worst"]["segment"] == "SMB"
    assert "SMB" in res["answer"] and "—" not in res["answer"]


def test_router_rep_gap_and_covered(data, plan):
    a, r, c = data
    short = ask.answer("what will R-125 need to hit quota?", a, r, c, plan=plan)
    assert short["mode"] == "demo" and "assess_territory" in short["used"]
    assert short["grounded"]["pipeline_gap"] > 0 and not short["grounded"]["covered"]
    covered = ask.answer("what does R-100 need to hit quota?", a, r, c, plan=plan)
    assert covered["grounded"]["covered"] is True


def test_router_hiring(data, plan):
    a, r, c = data
    res = ask.answer("how many reps should I hire, and in what priority?", a, r, c, plan=plan)
    assert res["mode"] == "demo" and "recommend_actions" in res["used"]
    assert res["grounded"]["total_safe_hires"] >= 1
    assert "SMB" in res["grounded"]["freeze_segments"]


def test_router_commission_delta_sign_and_math(data, plan):
    a, r, c = data
    up = ask.answer("what's the cost of increasing commissions by 10%?", a, r, c, plan=plan)
    assert up["mode"] == "demo" and up["grounded"]["comp_delta"] > 0
    # 10% of the on-target variable, and variable is the (1 - 0.5 split) slice of OTE.
    g = up["grounded"]
    assert abs(g["comp_delta"] - 0.10 * g["on_target_variable_total"]) < 1.0
    down = ask.answer("cost of cutting commissions by 5%", a, r, c, plan=plan)
    assert down["grounded"]["comp_delta"] < 0


def test_freeform_without_key_falls_back(data, plan):
    a, r, c = data
    res = ask.answer("write me a poem about quotas", a, r, c, plan=plan)
    assert res["mode"] == "demo" and res["error"] == "no_match_offline"
    assert res["answer"]  # a helpful message, not a crash


def test_ask_endpoint_shape():
    body = client.post("/ask", json={"question": "which segment is most at risk?"}).json()
    for k in ("mode", "answer", "grounded", "used", "model", "error"):
        assert k in body
    assert body["mode"] == "demo" and "SMB" in body["answer"]


def test_ask_endpoint_uses_current_settings():
    # Lowering the SMB multiple makes the segment coverable, so it's no longer "short".
    body = client.post(
        "/ask",
        json={
            "question": "which segment is most at risk?",
            "segment_overrides": {"SMB": {"quota_to_ote": 3.0}},
        },
    ).json()
    assert body["grounded"]["worst"]["coverable"] is True
