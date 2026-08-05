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


def test_quota_load_scales_with_seniority_level(accounts, reps):
    import config

    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    level = {r.rep_id: r.level for r in reps}
    by_level: dict[str, list[float]] = {}
    for t in terrs:
        if t.quota_to_potential is not None:
            by_level.setdefault(level[t.rep_id], []).append(t.quota_to_potential)
    # Within a level, quota/potential is (nearly) identical after re-normalization.
    for vals in by_level.values():
        assert max(vals) - min(vals) < 1e-6
    # Across levels, the ratio orders exactly by the configured multiplier.
    order = sorted(by_level, key=lambda lv: config.LEVEL_QUOTA_MULTIPLIER[lv])
    ratios = [by_level[lv][0] for lv in order]
    assert ratios == sorted(ratios)


def test_level_multiplier_override_shifts_load_but_keeps_total(accounts, reps):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    base = {t.rep_id: t.quota for t in terrs}
    level = {r.rep_id: r.level for r in reps}
    # Load Sr. Strategic AEs much heavier; the team total is unchanged.
    quota.derive_quotas(terrs, reps, 45_000_000.0, level_multipliers={"Sr. Strategic AE": 2.0})
    assert abs(sum(t.quota for t in terrs) - 45_000_000.0) < 1e-3
    strat = [t for t in terrs if level[t.rep_id] == "Sr. Strategic AE"]
    assert strat and all(t.quota > base[t.rep_id] for t in strat)  # they carry more
    others = [t for t in terrs if level[t.rep_id] != "Sr. Strategic AE"]
    assert any(t.quota < base[t.rep_id] for t in others)  # renormalized off everyone else


def test_fairness_flags_are_populated(accounts, reps):
    terrs = balance.carve(accounts, reps)
    quota.derive_quotas(terrs, reps, 45_000_000.0)
    summary = quota.fairness_summary(terrs)
    assert summary["mean_quota_to_potential"] is not None
    # ramping reps are intentionally light -> flagged as sandbag
    assert summary["sandbag"]
