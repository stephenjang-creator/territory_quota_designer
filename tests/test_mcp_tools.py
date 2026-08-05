"""
tests/test_mcp_tools.py — call each MCP tool function directly (not over the wire).

Asserts shapes, that a known under-covered territory reports coverage_ratio < 1
via assess_territory, that coverage_gaps returns only under-covered territories,
and that the what-if tools return a non-empty diff vs. the default plan.
"""

import mcp_server as S


def test_list_reps_and_segments():
    out = S.list_reps()
    reps = out["reps"]
    assert len(reps) == 12
    assert {r["rep_id"] for r in reps} >= {"R-100", "R-101"}
    # every rep carries a seniority level drawn from the advertised set
    assert out["levels"] == ["ramping", "AE", "Sr. AE", "Sr. Strategic AE"]
    assert all(r["level"] in out["levels"] for r in reps)
    segs = S.list_segments()["segments"]
    assert set(segs) == {"Enterprise", "Mid-Market", "SMB"}
    assert "Negotiation->Won" in segs["Enterprise"]
    assert "avg_deal_size" in segs["SMB"]


def test_whatif_levels_shifts_quota_and_validates():
    d = S.whatif_levels({"Sr. Strategic AE": 1.8})
    assert "error" not in d
    assert d["level_multipliers_used"]["Sr. Strategic AE"] == 1.8
    strat = [x for x in d["quota_deltas"] if x["level"] == "Sr. Strategic AE"]
    assert strat and all(x["delta_quota"] > 0 for x in strat)  # they carry more
    assert any(x["delta_quota"] < 0 for x in d["quota_deltas"])  # renormalized off others
    # validation: unknown level and non-dict are reported, never raised
    assert "error" in S.whatif_levels({"Principal AE": 2.0})
    assert "error" in S.whatif_levels("nope")
    assert "error" in S.whatif_levels({})


def test_plan_summary_shape_and_units():
    s = S.plan_summary()
    for k in (
        "company_target",
        "n_territories",
        "n_under_covered",
        "balance_score",
        "cost_of_sale",
        "units",
    ):
        assert k in s
    assert s["units"]["quota_period"] == "quarterly"
    assert s["n_territories"] == 12


def test_plan_summary_accepts_settings():
    s = S.plan_summary(
        potential_weight=0.9, geo_weight=0.05, whitespace_weight=0.05, company_target=50_000_000
    )
    assert s["company_target"] == 50_000_000
    # weights were normalized to sum 1
    assert abs(sum(s["settings"]["weights"].values()) - 1.0) < 1e-9


def test_list_territories_sorted_worst_first():
    d = S.list_territories()
    covs = [r["coverage_ratio"] for r in d["territories"]]
    assert covs == sorted(covs)  # worst-covered first
    assert len(d["territories"]) == 12
    assert "error" in S.list_territories(sort_by="not_a_field")


def test_assess_territory_known_under_covered():
    rid = S.coverage_gaps()["gaps"][0]["rep_id"]  # a known under-covered rep
    d = S.assess_territory(rid)
    assert d["coverage_ratio"] < 1.0
    assert d["under_covered"] is True
    assert "gap" in d and d["gap"]["gap_dollars"] > 0
    # the complete reverse-waterfall funnel is present
    assert set(d["waterfall"]["funnel"]) == {
        "required_sqls",
        "qualification",
        "proposal",
        "negotiation",
        "won_deals",
    }
    # override audit trail present
    assert d["rates_used"]["Negotiation->Won"]["level"] == "global"
    assert "error" in S.assess_territory("R-999")


def test_coverage_gaps_only_under_covered():
    g = S.coverage_gaps()
    assert g["n_under_covered"] >= 1
    assert all(x["coverage_ratio"] < 1.0 for x in g["gaps"])
    assert all("levers" in x and x["levers"] for x in g["gaps"])


def test_whatif_weights_returns_nonempty_diff():
    d = S.whatif_weights(0.1, 0.85, 0.05)  # geo-heavy vs default
    assert "error" not in d
    assert d["top_gainers"] and d["top_losers"]
    assert d["reps_with_potential_change"] >= 1
    # some rep actually moved potential
    assert any(g["delta_potential"] != 0 for g in d["top_gainers"] + d["top_losers"])


def test_whatif_conversions_drops_enterprise_coverage():
    d = S.whatif_conversions({"segment": {"Enterprise": {"Negotiation->Won": 0.20}}})
    assert "error" not in d
    assert d["n_under_covered"]["whatif"] >= d["n_under_covered"]["default"]
    # every affected territory's coverage dropped or held (delta <= 0)
    assert any(x["delta"] < 0 for x in d["coverage_deltas"])
    # a steeper drop flips at least one more territory under (the ramp-protected rep)
    steep = S.whatif_conversions({"segment": {"Enterprise": {"Negotiation->Won": 0.15}}})
    assert steep["n_under_covered"]["whatif"] > d["n_under_covered"]["default"]
    assert "error" in S.whatif_conversions("not-a-dict")


def test_comp_scenario_default_and_pointwise():
    default = S.comp_scenario()
    assert [r["attainment"] for r in default["scenarios"]] == [0.85, 1.0, 1.1]
    at = S.comp_scenario(0.9)
    assert 0 < at["cost_of_sale"] < 1
    assert len(at["top_earners"]) == 3 and len(at["bottom_earners"]) == 3


def test_get_scorecard():
    sc = S.get_scorecard()
    assert "coverage_flips" in sc["scorecard"]
    assert sc["markdown"].startswith("| Metric")


def test_tools_never_raise_on_bad_input():
    # errors come back as {"error": ...}, never exceptions
    assert "error" in S.plan_summary(potential_weight=-1, geo_weight=-1, whitespace_weight=-1)
    assert "error" in S.assess_territory("nope")
    assert "error" in S.whatif_conversions(42)
