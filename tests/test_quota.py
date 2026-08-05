"""Stage 2: standardized quota by role, derived from OTE (quota = multiple x OTE)."""

import config
from core import balance, quota


def test_same_role_same_quota(reps):
    qs = quota.standardized_quotas(reps)
    by_role: dict[tuple, set] = {}
    for r in reps:
        by_role.setdefault((r.segment_focus, r.level), set()).add(round(qs[r.rep_id], 4))
    # every rep in a role carries the identical quota
    assert all(len(v) == 1 for v in by_role.values())
    # and roles differ (this isn't a single flat number)
    assert len({next(iter(v)) for v in by_role.values()}) > 1


def test_quota_is_the_annual_multiple_over_periods_times_ote(reps):
    qs = quota.standardized_quotas(reps)
    otes = quota.resolve_ote(reps)
    ppy = config.QUOTA_PERIODS_PER_YEAR
    for r in reps:
        # quarterly quota = (annual multiple x OTE) / periods-per-year
        assert abs(qs[r.rep_id] - config.QUOTA_TO_OTE * otes[r.rep_id] / ppy) < 1e-6


def test_company_target_is_sum_of_quotas(reps):
    qs = quota.standardized_quotas(reps)
    assert abs(quota.default_company_target(reps) - sum(qs.values())) < 1e-6


def test_ote_override_reprices_only_that_role(reps):
    base = quota.standardized_quotas(reps)
    got = quota.standardized_quotas(reps, ote_overrides={"Enterprise": {"AE": 1_000_000}})
    for r in reps:
        if (r.segment_focus, r.level) == ("Enterprise", "AE"):
            expect = config.QUOTA_TO_OTE * 1_000_000 / config.QUOTA_PERIODS_PER_YEAR
            assert abs(got[r.rep_id] - expect) < 1e-6
        else:
            assert abs(got[r.rep_id] - base[r.rep_id]) < 1e-6


def test_multiple_scales_every_quota(reps):
    a = quota.standardized_quotas(reps, quota_to_ote=5)
    b = quota.standardized_quotas(reps, quota_to_ote=6)
    for r in reps:
        assert abs(b[r.rep_id] - a[r.rep_id] * 6 / 5) < 1e-3


def test_fill_territory_quotas_writes_quota_and_ote(accounts, reps):
    qs = quota.standardized_quotas(reps)
    otes = quota.resolve_ote(reps)
    terrs = balance.carve(accounts, reps, qs)
    total = quota.fill_territory_quotas(terrs, qs, otes)
    assert abs(total - sum(qs.values())) < 1e-6
    for t in terrs:
        assert t.quota == qs[t.rep_id] and t.ote == otes[t.rep_id]
        assert t.quota_to_potential is not None
