"""Recommendations: shape, and the guarantee that applying a lever's delta actually
resolves the issue it targets (pipeline coverage, hiring safety, comp cost-of-sale)."""

import config
from core import comp, quota, recommend
from core.plan import PlanSettings, run_plan


def _smb_coverable(data, settings):
    a, r, c = data
    return run_plan(a, r, c, settings).scorecard["per_segment_capacity"]["SMB"]["coverable"]


def test_recommendation_shape(data):
    a, r, c = data
    recs = recommend.build_recommendations(a, r, c)
    cats = {x["category"] for x in recs}
    assert {"pipeline", "hiring", "comp", "sensitivity"} <= cats
    for x in recs:
        assert {"id", "category", "severity", "title", "body", "levers"} <= set(x)
        assert x["levers"] and all("label" in lv and "apply" in lv for lv in x["levers"])


def test_every_pipeline_lever_resolves_the_short_segment(data):
    a, r, c = data
    recs = recommend.build_recommendations(a, r, c)
    pipe = next(x for x in recs if x["id"] == "pipeline-SMB")
    assert pipe["severity"] == "critical"
    # retag, lower-multiple, accept-target — each must make SMB coverable when applied
    applied = 0
    for lv in pipe["levers"]:
        delta = lv["apply"]
        assert delta  # a resolving lever carries a real settings delta
        assert _smb_coverable(data, PlanSettings(**delta)) is True
        applied += 1
    assert applied >= 3


def test_retag_makes_every_rep_clear_and_keeps_sources_covered(data):
    a, r, c = data
    recs = recommend.build_recommendations(a, r, c)
    pipe = next(x for x in recs if x["id"] == "pipeline-SMB")
    retag = next(lv["apply"] for lv in pipe["levers"] if "account_retags" in lv["apply"])
    plan = run_plan(a, r, c, PlanSettings(**retag))
    sc = plan.scorecard["per_segment_capacity"]
    assert sc["SMB"]["coverable"] is True
    # the segments the accounts came from stay coverable (we don't rob Peter to pay Paul)
    assert sc["Mid-Market"]["coverable"] and sc["Enterprise"]["coverable"]
    # the re-tag GUARANTEES every rep clears the target — not just the segment aggregate
    target = plan.settings["coverage_target"]
    assert plan.scorecard["coverage_floor"]["optimized"] >= target - 1e-6
    assert plan.scorecard["reps_covered"]["optimized"] == plan.scorecard["reps_covered"]["of"]


def test_hiring_plan_lands_covered(data):
    a, r, c = data
    recs = recommend.build_recommendations(a, r, c)
    hire = next(x for x in recs if x["category"] == "hiring")
    plan_lever = next(lv["apply"] for lv in hire["levers"] if lv["apply"].get("added_reps"))
    sc = run_plan(a, r, c, PlanSettings(**plan_lever)).scorecard["per_segment_capacity"]
    # every segment we hired into is still coverable after the hire
    for spec in plan_lever["added_reps"]:
        assert sc[spec["segment"]]["coverable"] is True


def test_sensitivity_target_clears_everyone(data):
    a, r, c = data
    recs = recommend.build_recommendations(a, r, c)
    sens = next(x for x in recs if x["category"] == "sensitivity")
    lever = next(lv["apply"] for lv in sens["levers"] if "coverage_target" in lv["apply"])
    plan = run_plan(a, r, c, PlanSettings(**lever))
    rc = plan.scorecard["reps_covered"]
    assert rc["optimized"] == rc["of"]  # everyone clears at the recommended target


def test_comp_autotune_hits_ceiling_when_over(data):
    a, r, c = data
    # A fat 80% base lifts cost-of-sale at 85%; aim the tuner at a ceiling below it
    # and confirm it actually gets there (the mechanism, independent of the default).
    rich = {**config.COMP, "base_variable_split": 0.8}
    plan = run_plan(a, r, c, PlanSettings(comp=rich))
    before = comp.simulate(plan.territories, 0.85, rich)["cost_of_sale"]
    ceiling = before - 0.02  # a tighter target than the plan currently holds
    tune = comp.autotune_comp(plan.territories, ceiling, 0.85, rich)
    assert tune["feasible"] and tune["comp"]
    after = comp.simulate(plan.territories, 0.85, {**rich, **tune["comp"]})["cost_of_sale"]
    assert after <= ceiling + 1e-9


def test_segment_multiple_override_reprices_only_that_segment(reps):
    base = quota.standardized_quotas(reps)
    got = quota.standardized_quotas(reps, segment_overrides={"SMB": {"quota_to_ote": 3.0}})
    for rep in reps:
        if rep.segment_focus == "SMB":
            assert got[rep.rep_id] < base[rep.rep_id]  # SMB lowered
        else:
            assert got[rep.rep_id] == base[rep.rep_id]  # others untouched
