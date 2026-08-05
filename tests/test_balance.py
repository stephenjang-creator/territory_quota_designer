"""Stage 1: the work-back carve is a valid, deterministic, focus-respecting
partition that packs each book toward the pipeline-coverage target and, where a
segment is short, spreads the shortfall evenly (raising the floor vs. naive)."""

from core import balance, quota
from core.potential import available_potential


def _cov(t, acc_by_id, quotas):
    avail = available_potential([acc_by_id[a] for a in t.account_ids])
    return avail / quotas[t.rep_id]


def test_partition_is_complete_and_disjoint(accounts, reps):
    qs = quota.standardized_quotas(reps)
    terrs = balance.carve(accounts, reps, qs)
    ids = [a for t in terrs for a in t.account_ids]
    assert len(ids) == len(accounts)
    assert set(ids) == {a.account_id for a in accounts}


def test_segment_focus_is_respected(accounts, reps):
    qs = quota.standardized_quotas(reps)
    terrs = balance.carve(accounts, reps, qs)
    seg_of = {a.account_id: a.segment for a in accounts}
    focus_of = {r.rep_id: r.segment_focus for r in reps}
    for t in terrs:
        assert all(seg_of[aid] == focus_of[t.rep_id] for aid in t.account_ids)


def test_carve_is_deterministic(accounts, reps):
    qs = quota.standardized_quotas(reps)
    a = balance.carve(accounts, reps, qs)
    b = balance.carve(accounts, reps, qs)
    assert [t.account_ids for t in a] == [t.account_ids for t in b]


def test_segments_with_surplus_reach_target_thin_ones_fall_short(accounts, reps):
    qs = quota.standardized_quotas(reps)
    acc = {a.account_id: a for a in accounts}
    terrs = balance.carve(accounts, reps, qs, coverage_target=3.0)
    seg = {r.rep_id: r.segment_focus for r in reps}
    ent_mm = [t for t in terrs if seg[t.rep_id] in ("Enterprise", "Mid-Market")]
    smb = [t for t in terrs if seg[t.rep_id] == "SMB"]
    assert all(_cov(t, acc, qs) >= 3.0 - 1e-6 for t in ent_mm)  # surplus -> covered
    assert smb and all(_cov(t, acc, qs) < 3.0 for t in smb)  # thin SMB book -> short


def test_work_back_raises_the_floor_vs_naive(accounts, reps):
    qs = quota.standardized_quotas(reps)
    acc = {a.account_id: a for a in accounts}
    wb = balance.carve(accounts, reps, qs)
    nv = balance.naive_carve(accounts, reps)

    def floor(terrs):
        return min(_cov(t, acc, qs) for t in terrs)

    # equalizing the short segment's shortfall lifts the worst-covered rep
    assert floor(wb) > floor(nv)


def test_higher_target_leaves_more_reps_short(accounts, reps):
    qs = quota.standardized_quotas(reps)
    acc = {a.account_id: a for a in accounts}

    def n_short(tgt):
        terrs = balance.carve(accounts, reps, qs, coverage_target=tgt)
        return sum(1 for t in terrs if _cov(t, acc, qs) < tgt - 1e-9)

    assert n_short(5.0) > n_short(3.0)


def test_home_region_tiebreaker_lowers_off_home_share(accounts, reps):
    qs = quota.standardized_quotas(reps)
    on = balance.carve(accounts, reps, qs, prefer_home_region=True)
    off = balance.carve(accounts, reps, qs, prefer_home_region=False)
    assert balance.off_home_share(on, accounts, reps) <= balance.off_home_share(off, accounts, reps)


def test_naive_carve_is_count_balanced_within_pool(accounts, reps):
    base = balance.naive_carve(accounts, reps)
    focus_of = {r.rep_id: r.segment_focus for r in reps}
    by_focus: dict[str, list[int]] = {}
    for t in base:
        by_focus.setdefault(focus_of[t.rep_id], []).append(t.account_count)
    for counts in by_focus.values():
        assert max(counts) - min(counts) <= 1  # round-robin within pool
