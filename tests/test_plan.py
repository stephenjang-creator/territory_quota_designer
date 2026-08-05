"""Integration: run_plan wires the quota-first chain into a JSON-safe PlanResult."""

import json
from dataclasses import asdict

import config
from core.plan import PlanSettings, run_plan


def test_plan_fills_every_stage(plan):
    assert plan.n_territories == 12
    for t in plan.territories:
        assert t.quota is not None and t.ote is not None
        assert t.pipeline_coverage_multiple is not None
        assert t.coverage_ratio is not None
        assert t.funnel is not None and t.rates_used is not None


def test_company_target_is_derived_sum(plan):
    assert abs(plan.company_target - sum(t.quota for t in plan.territories)) < 1e-2


def test_plan_is_deterministic(data):
    accounts, reps, conversions = data
    a = run_plan(accounts, reps, conversions)
    b = run_plan(accounts, reps, conversions)
    assert [t.account_ids for t in a.territories] == [t.account_ids for t in b.territories]


def test_plan_result_is_json_serializable(plan):
    assert len(json.dumps(asdict(plan))) > 0


def test_quota_multiple_scales_the_target(data):
    accounts, reps, conversions = data
    base = run_plan(accounts, reps, conversions)
    up = run_plan(accounts, reps, conversions, PlanSettings(quota_to_ote=config.QUOTA_TO_OTE * 1.2))
    assert abs(up.company_target - base.company_target * 1.2) < 1e-2


def test_higher_coverage_target_covers_fewer_reps(data):
    accounts, reps, conversions = data
    lo = run_plan(accounts, reps, conversions, PlanSettings(coverage_target=3.0))
    hi = run_plan(accounts, reps, conversions, PlanSettings(coverage_target=5.0))
    assert hi.scorecard["reps_covered"]["optimized"] < lo.scorecard["reps_covered"]["optimized"]
