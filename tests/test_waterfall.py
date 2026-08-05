"""Stage 3: the reverse waterfall funnel + coverage (funnel adequacy on top of
the packed pipeline). Quotas are standardized by role; the carve packs the book."""

from core import balance, quota, waterfall


def _plan(accounts, reps, conversions, *, overrides=None, quota_to_ote=None):
    qs = quota.standardized_quotas(reps, quota_to_ote=quota_to_ote)
    otes = quota.resolve_ote(reps)
    terrs = balance.carve(accounts, reps, qs)
    quota.fill_territory_quotas(terrs, qs, otes)
    waterfall.run_waterfall(terrs, accounts, conversions, overrides)
    return terrs


def test_required_pipeline_equals_quota_over_win_rate(accounts, reps, conversions):
    for t in _plan(accounts, reps, conversions):
        r_neg_won = t.rates_used["Negotiation->Won"]["value"]
        assert abs(t.required_pipeline - t.quota / r_neg_won) < 1e-3


def test_funnel_widens_up_the_stages(accounts, reps, conversions):
    for t in _plan(accounts, reps, conversions):
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
    for t in _plan(accounts, reps, conversions):
        assert abs(t.coverage_ratio - t.available_potential / t.required_pipeline) < 1e-9
        assert t.under_covered == (t.coverage_ratio < 1.0)


def test_pipeline_coverage_multiple_is_available_over_quota(accounts, reps, conversions):
    for t in _plan(accounts, reps, conversions):
        assert abs(t.pipeline_coverage_multiple - t.available_potential / t.quota) < 1e-9


def test_lower_win_rate_reduces_funnel_coverage(accounts, reps, conversions):
    """Dropping Enterprise win-rate flips Enterprise territories under (coverage < 1)."""
    base = _plan(accounts, reps, conversions)
    n_base = sum(1 for t in base if t.under_covered)
    stressed = _plan(
        accounts,
        reps,
        conversions,
        overrides={"segment": {"Enterprise": {"Negotiation->Won": 0.15}}},
    )
    n_stressed = sum(1 for t in stressed if t.under_covered)
    assert n_stressed > n_base
    under = waterfall.under_covered(stressed)
    assert under and [t.coverage_ratio for t in under] == sorted(t.coverage_ratio for t in under)


def test_gap_analysis_quantifies_a_shortfall(accounts, reps, conversions):
    stressed = _plan(
        accounts,
        reps,
        conversions,
        overrides={"segment": {"Enterprise": {"Negotiation->Won": 0.15}}},
    )
    t = waterfall.under_covered(stressed)[0]
    ga = waterfall.gap_analysis(t)
    assert ga["assessable"] and ga["gap_dollars"] > 0
    assert ga["suggested_quota"] < t.quota
    assert len(ga["levers"]) == 3
