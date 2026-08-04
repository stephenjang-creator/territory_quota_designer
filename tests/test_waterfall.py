"""Stage 3: the reverse waterfall funnel + coverage (the flagship)."""

from core import balance, quota, waterfall


def _covered_plan(accounts, reps, conversions, target=45_000_000.0, overrides=None):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, target)
    waterfall.run_waterfall(terrs, accounts, conversions, overrides)
    return terrs


def test_required_pipeline_equals_quota_over_win_rate(accounts, reps, conversions):
    terrs = _covered_plan(accounts, reps, conversions)
    for t in terrs:
        r_neg_won = t.rates_used["Negotiation->Won"]["value"]
        assert abs(t.required_pipeline - t.quota / r_neg_won) < 1e-3


def test_funnel_widens_up_the_stages(accounts, reps, conversions):
    terrs = _covered_plan(accounts, reps, conversions)
    for t in terrs:
        f = t.funnel
        assert (
            f["required_sqls"]
            >= f["qualification"]
            >= f["proposal"]
            >= f["negotiation"]
            >= f["won_deals"]
            > 0
        )


def test_coverage_ratio_definition(accounts, reps, conversions):
    terrs = _covered_plan(accounts, reps, conversions)
    for t in terrs:
        assert abs(t.coverage_ratio - t.available_potential / t.required_pipeline) < 1e-9
        assert t.under_covered == (t.coverage_ratio < 1.0)


def test_default_plan_has_a_known_under_covered_territory(accounts, reps, conversions):
    terrs = _covered_plan(accounts, reps, conversions)
    under = waterfall.under_covered(terrs)
    assert under, "expected at least one under-covered territory at the default target"
    assert all(t.coverage_ratio < 1.0 for t in under)
    # worst-first ordering
    ratios = [t.coverage_ratio for t in under]
    assert ratios == sorted(ratios)


def test_lower_win_rate_reduces_coverage(accounts, reps, conversions):
    """Stress test: dropping Enterprise win-rate flips more territories under."""
    base = _covered_plan(accounts, reps, conversions)
    n_base = sum(1 for t in base if t.under_covered)
    stressed = _covered_plan(
        accounts,
        reps,
        conversions,
        overrides={"segment": {"Enterprise": {"Negotiation->Won": 0.20}}},
    )
    n_stressed = sum(1 for t in stressed if t.under_covered)
    assert n_stressed >= n_base


def test_gap_analysis_quantifies_the_shortfall(accounts, reps, conversions):
    terrs = _covered_plan(accounts, reps, conversions)
    t = waterfall.under_covered(terrs)[0]
    ga = waterfall.gap_analysis(t)
    assert ga["assessable"]
    assert ga["gap_dollars"] > 0
    assert ga["suggested_quota"] < t.quota  # lowering quota closes the gap
    assert len(ga["levers"]) == 3
