"""
tests/test_mcp_tools.py — call each MCP tool function directly (not over the wire).

Asserts shapes, that standardized quotas come back per role, that coverage_gaps
returns the capacity-short reps, and that the what-if tools return a non-empty diff.
"""

import mcp_server as S


def test_list_reps_and_segments():
    out = S.list_reps()
    reps = out["reps"]
    assert len(reps) == 14
    assert out["quota_to_ote"] == 4.0
    assert all({"role", "ote", "quota"} <= set(r) for r in reps)
    # same role -> same quota
    by_role: dict[str, set] = {}
    for r in reps:
        by_role.setdefault(r["role"], set()).add(r["quota"])
    assert all(len(v) == 1 for v in by_role.values())
    segs = S.list_segments()["segments"]
    assert set(segs) == {"Enterprise", "Mid-Market", "SMB"}


def test_plan_summary_shape():
    s = S.plan_summary()
    for k in ("company_target", "coverage_target", "reps_covered", "coverage_floor", "units"):
        assert k in s
    assert s["reps_covered"]["of"] == 14


def test_plan_summary_accepts_settings():
    s = S.plan_summary(quota_to_ote=6.0, coverage_target=4.0)
    assert s["coverage_target"] == 4.0
    assert s["settings"]["quota_to_ote"] == 6.0


def test_list_territories_sorted_worst_first():
    d = S.list_territories()
    covs = [r["pipeline_coverage"] for r in d["territories"]]
    assert covs == sorted(covs)
    assert d["sort_by"] == "pipeline_coverage" and len(d["territories"]) == 14
    assert "error" in S.list_territories(sort_by="not_a_field")


def test_coverage_gaps_returns_capacity_short_reps():
    g = S.coverage_gaps()
    assert g["n_below_target"] >= 1
    assert all(x["pipeline_coverage"] < g["coverage_target"] for x in g["gaps"])
    assert all(x["pipeline_gap"] > 0 for x in g["gaps"])
    # under standardized quotas the shortfall is the thin SMB segment
    assert all("SMB" in x["role"] for x in g["gaps"])


def test_assess_territory():
    d = S.assess_territory("R-101")
    assert d["role"] == "Enterprise · Sr. Strategic AE"
    assert d["quota"] > 0 and d["pipeline_coverage"] is not None
    assert set(d["waterfall"]["funnel"]) == {
        "required_sqls",
        "qualification",
        "proposal",
        "negotiation",
        "won_deals",
    }
    assert d["rates_used"]["Negotiation->Won"]["level"] == "global"
    assert "error" in S.assess_territory("R-999")


def test_whatif_ote_reprices_a_role():
    d = S.whatif_ote("Enterprise", "AE", 1_100_000)
    assert "error" not in d
    assert d["company_target"]["whatif"] > d["company_target"]["default"]
    assert d["affected_reps"] and all(
        r["quota_whatif"] > r["quota_default"] for r in d["affected_reps"]
    )
    assert "error" in S.whatif_ote("Nope", "AE", 1e6)
    assert "error" in S.whatif_ote("Enterprise", "Principal", 1e6)


def test_whatif_coverage_raises_the_bar():
    d = S.whatif_coverage(5.0)
    assert "error" not in d
    # a stiffer target covers fewer reps and widens the gap
    assert d["reps_covered"]["whatif"] <= d["reps_covered"]["default"]
    assert d["capacity_gap"]["whatif"] >= d["capacity_gap"]["default"]
    assert d["below_target"]
    assert "error" in S.whatif_coverage(-1)


def test_whatif_conversions_drops_enterprise_coverage():
    d = S.whatif_conversions({"segment": {"Enterprise": {"Negotiation->Won": 0.15}}})
    assert "error" not in d
    assert any(x["delta"] < 0 for x in d["coverage_deltas"])
    assert "error" in S.whatif_conversions("not-a-dict")


def test_comp_scenario_default_and_pointwise():
    default = S.comp_scenario()
    assert [r["attainment"] for r in default["scenarios"]] == [0.85, 1.0, 1.1]
    at = S.comp_scenario(0.9)
    assert 0 < at["cost_of_sale"] < 1
    assert len(at["top_earners"]) == 3 and len(at["bottom_earners"]) == 3


def test_get_scorecard():
    sc = S.get_scorecard()
    assert "capacity_gap" in sc["scorecard"] and "coverage_floor" in sc["scorecard"]
    assert sc["markdown"].startswith("| Metric")


def test_tools_never_raise_on_bad_input():
    assert "error" in S.list_territories(sort_by="nope")
    assert "error" in S.assess_territory("nope")
    assert "error" in S.whatif_conversions(42)
    assert "error" in S.whatif_coverage(0)
