"""Stage 1: the carve is a valid, deterministic, focus-respecting partition that
beats the naive baseline on within-segment balance."""

from core import balance
from core.evaluate import _per_segment_cov


def _all_ids(territories):
    ids = []
    for t in territories:
        ids.extend(t.account_ids)
    return ids


def test_partition_is_complete_and_disjoint(accounts, reps):
    terrs = balance.carve(accounts, reps)
    ids = _all_ids(terrs)
    assert len(ids) == len(accounts)  # every account placed
    assert len(set(ids)) == len(ids)  # exactly once
    assert set(ids) == {a.account_id for a in accounts}


def test_segment_focus_is_respected(accounts, reps):
    terrs = balance.carve(accounts, reps)
    seg_of = {a.account_id: a.segment for a in accounts}
    focus_of = {r.rep_id: r.segment_focus for r in reps}
    for t in terrs:
        for aid in t.account_ids:
            assert seg_of[aid] == focus_of[t.rep_id]  # no cross-segment leakage


def test_carve_is_deterministic(accounts, reps):
    a = balance.carve(accounts, reps)
    b = balance.carve(accounts, reps)
    assert [t.account_ids for t in a] == [t.account_ids for t in b]


def test_optimizer_beats_baseline_within_segment(accounts, reps):
    opt = balance.carve(accounts, reps)
    base = balance.naive_carve(accounts, reps)
    seg_opt = _per_segment_cov(opt, accounts)
    seg_base = _per_segment_cov(base, accounts)
    # tighter (or equal) within-segment potential balance in every segment
    for seg in seg_opt:
        assert seg_opt[seg] <= seg_base[seg] + 1e-9


def test_optimizer_lowers_combined_cost(accounts, reps):
    import config

    opt = balance.carve(accounts, reps)
    base = balance.naive_carve(accounts, reps)
    c_opt = balance.combined_cost(opt, config.WEIGHTS, accounts, reps)
    c_base = balance.combined_cost(base, config.WEIGHTS, accounts, reps)
    assert c_opt <= c_base


def test_naive_carve_is_count_balanced_within_pool(accounts, reps):
    base = balance.naive_carve(accounts, reps)
    focus_of = {r.rep_id: r.segment_focus for r in reps}
    by_focus: dict[str, list[int]] = {}
    for t in base:
        by_focus.setdefault(focus_of[t.rep_id], []).append(t.account_count)
    for counts in by_focus.values():
        assert max(counts) - min(counts) <= 1  # round-robin within pool


def test_weights_shift_the_tradeoff(accounts, reps):
    # potential-heavy should balance potential at least as tightly as geo-heavy
    pot_heavy = balance.carve(
        accounts, reps, weights={"potential": 0.9, "geo": 0.05, "whitespace": 0.05}
    )
    geo_heavy = balance.carve(
        accounts, reps, weights={"potential": 0.1, "geo": 0.85, "whitespace": 0.05}
    )
    seg_pot = sum(_per_segment_cov(pot_heavy, accounts).values())
    seg_geo = sum(_per_segment_cov(geo_heavy, accounts).values())
    assert seg_pot <= seg_geo
