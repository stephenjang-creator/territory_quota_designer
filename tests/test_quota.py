"""Stage 2: quotas are proportional, ramp-adjusted, and sum to the target."""

from core import balance, quota


def test_quotas_sum_to_company_target(accounts, reps):
    terrs = balance.carve(accounts, reps)
    target = 40_000_000.0
    got = quota.derive_quotas(terrs, reps, target)
    assert got == target
    assert abs(sum(t.quota for t in terrs) - target) < 1e-3


def test_default_target_is_multiple_of_potential(accounts, reps):
    import config

    terrs = balance.carve(accounts, reps)
    total_pot = sum(t.potential for t in terrs)
    assert quota.default_company_target(terrs) == config.COMPANY_TARGET_MULTIPLE * total_pot


def test_ramp_haircut_lowers_ramping_quota_ratio(accounts, reps):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    ramp_status = {r.rep_id: r.ramp_status for r in reps}
    ramp = [t.quota_to_potential for t in terrs if ramp_status[t.rep_id] == "ramping"]
    full = [t.quota_to_potential for t in terrs if ramp_status[t.rep_id] == "full"]
    # ramping reps carry less quota per dollar of potential than any full rep
    assert max(ramp) < min(full)


def test_quota_is_proportional_among_full_reps(accounts, reps):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    ramp_status = {r.rep_id: r.ramp_status for r in reps}
    ratios = [t.quota_to_potential for t in terrs if ramp_status[t.rep_id] == "full"]
    # all full reps share (nearly) the same quota/potential ratio after re-norm
    assert max(ratios) - min(ratios) < 1e-6


def test_fairness_flags_are_populated(accounts, reps):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    summary = quota.fairness_summary(terrs)
    assert summary["mean_quota_to_potential"] is not None
    # ramping reps are intentionally light -> flagged as sandbag
    assert summary["sandbag"]
