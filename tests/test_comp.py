"""Stage 4: OTE-anchored comp — base, the normalized payout curve, cost-of-sale."""

import config
from core import comp

OTE = 500_000.0
QUOTA = config.QUOTA_TO_OTE * OTE / config.QUOTA_PERIODS_PER_YEAR  # quarterly


def test_payout_factor_is_one_on_target():
    assert abs(comp.payout_factor(1.0, config.COMP) - 1.0) < 1e-9


def test_payout_factor_is_monotonic():
    prev = -1.0
    for att in [0.0, 0.5, 0.8, 1.0, 1.2, 1.5]:
        f = comp.payout_factor(att, config.COMP)
        assert f >= prev
        prev = f


def test_base_is_a_slice_of_ote():
    assert comp.base_salary(OTE, config.COMP) == config.COMP["base_variable_split"] * OTE


def test_on_target_total_comp_equals_ote():
    # base + variable at 100% attainment = OTE (that's what "on-target" means)
    pay = comp.rep_payout(OTE, QUOTA, 1.0, config.COMP)
    assert abs(pay["total_comp"] - OTE) < 1e-6


def test_accelerator_faster_above_decelerator_slower_below():
    c = config.COMP
    below = comp.payout_factor(1.0, c) - comp.payout_factor(0.8, c)
    above = comp.payout_factor(1.2, c) - comp.payout_factor(1.0, c)
    assert above > below  # accelerator_multiplier > 1
    decel_step = comp.payout_factor(0.6, c) - comp.payout_factor(0.5, c)  # decel band
    std_step = comp.payout_factor(0.9, c) - comp.payout_factor(0.8, c)  # standard band
    assert decel_step < std_step  # decelerator_multiplier < 1


def test_cap_freezes_variable():
    capped = {**config.COMP, "cap_attainment": 1.0}
    assert comp.variable_payout(OTE, 1.5, capped) == comp.variable_payout(OTE, 1.0, capped)


def test_cost_of_sale_is_a_sane_fraction(plan):
    sim = comp.simulate(plan.territories, 1.0)
    assert sim["cost_of_sale"] is not None
    assert 0 < sim["cost_of_sale"] < 1
    assert len(sim["per_rep"]) == len(plan.territories)


def test_scenario_compare_shape(plan):
    rows = comp.scenario_compare(plan.territories, [0.85, 1.0, 1.1])
    assert [r["attainment"] for r in rows] == [0.85, 1.0, 1.1]
    assert all(0 < r["cost_of_sale"] < 1 for r in rows)
