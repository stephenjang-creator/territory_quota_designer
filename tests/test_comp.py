"""Stage 4: comp payouts, accelerator, cap, and cost-of-sale."""

import config
from core import comp


def test_payout_is_monotonic_in_attainment():
    prev = -1.0
    for att in [0.0, 0.5, 0.8, 1.0, 1.2, 1.5]:
        p = comp.variable_payout(1_000_000, att, config.COMP)
        assert p >= prev
        prev = p


def test_accelerator_pays_faster_above_threshold():
    q = 1_000_000
    below = comp.variable_payout(q, 1.0, config.COMP) - comp.variable_payout(q, 0.8, config.COMP)
    above = comp.variable_payout(q, 1.2, config.COMP) - comp.variable_payout(q, 1.0, config.COMP)
    assert above > below  # accelerator_multiplier > 1


def test_decelerator_pays_slower_below_threshold():
    q = 1_000_000  # default decel: below 0.7 attainment, 0.5x the commission rate
    pay = lambda att: comp.variable_payout(q, att, config.COMP)  # noqa: E731
    decel_step = pay(0.6) - pay(0.5)  # both inside the decel band
    std_step = pay(0.9) - pay(0.8)  # both inside the standard band
    assert decel_step < std_step  # decelerator_multiplier < 1


def test_decelerator_disabled_reduces_to_flat_standard_band():
    q = 1_000_000
    no_decel = {**config.COMP, "decelerator_multiplier": 1.0}
    # with the decel penalty off, everything below the accelerator pays the flat rate
    expected = q * no_decel["commission_rate"] * 0.8
    assert abs(comp.variable_payout(q, 0.8, no_decel) - expected) < 1e-6


def test_cap_freezes_payout():
    capped = {**config.COMP, "cap_attainment": 1.0}
    assert comp.variable_payout(1_000_000, 1.5, capped) == comp.variable_payout(
        1_000_000, 1.0, capped
    )


def test_base_salary_from_split():
    # split 0.5 -> base equals target variable (commission_rate * quota)
    q = 1_000_000
    assert comp.base_salary(q, config.COMP) == config.COMP["commission_rate"] * q
    assert comp.base_salary(q, {**config.COMP, "base_variable_split": 0.0}) == 0.0


def test_cost_of_sale_is_a_sane_fraction(plan):
    sim = comp.simulate(plan.territories, 1.0)
    assert sim["cost_of_sale"] is not None
    assert 0 < sim["cost_of_sale"] < 1
    assert len(sim["per_rep"]) == len(plan.territories)


def test_scenario_compare_shape(plan):
    rows = comp.scenario_compare(plan.territories, [0.85, 1.0, 1.1])
    assert [r["attainment"] for r in rows] == [0.85, 1.0, 1.1]
    # higher attainment -> lower cost-of-sale (fixed base spread over more bookings)
    cos = [r["cost_of_sale"] for r in rows]
    assert cos[0] > cos[1] > cos[2]
