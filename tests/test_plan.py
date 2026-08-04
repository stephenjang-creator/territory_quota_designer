"""Integration: run_plan wires the whole chain into one JSON-safe PlanResult."""

import json
from dataclasses import asdict

from core.plan import PlanSettings, run_plan


def test_plan_fills_every_stage(plan):
    assert plan.n_territories == 12
    for t in plan.territories:
        assert t.quota is not None
        assert t.coverage_ratio is not None
        assert t.funnel is not None
        assert t.rates_used is not None


def test_plan_has_under_covered_territories(plan):
    assert plan.n_under_covered >= 1


def test_plan_is_deterministic(data):
    accounts, reps, conversions = data
    a = run_plan(accounts, reps, conversions)
    b = run_plan(accounts, reps, conversions)
    assert [t.account_ids for t in a.territories] == [t.account_ids for t in b.territories]
    assert a.balance_score == b.balance_score


def test_plan_result_is_json_serializable(plan):
    s = json.dumps(asdict(plan))  # raises on numpy / non-serializable types
    assert len(s) > 0


def test_settings_override_company_target(data):
    accounts, reps, conversions = data
    pr = run_plan(accounts, reps, conversions, PlanSettings(company_target=99_000_000))
    assert pr.company_target == 99_000_000
    assert abs(sum(t.quota for t in pr.territories) - 99_000_000) < 1e-2


def test_weight_change_changes_the_carve(data):
    accounts, reps, conversions = data
    a = run_plan(
        accounts,
        reps,
        conversions,
        PlanSettings(weights={"potential": 0.9, "geo": 0.05, "whitespace": 0.05}),
    )
    b = run_plan(
        accounts,
        reps,
        conversions,
        PlanSettings(weights={"potential": 0.1, "geo": 0.85, "whitespace": 0.05}),
    )
    assert [t.account_ids for t in a.territories] != [t.account_ids for t in b.territories]
