"""
core/balance.py — Stage 1: carve the book *back* from quota.

Quota-first. Each rep's quota is fixed by role (Stage 2), so the carve's job is
capacity planning: pack every book with enough ADDRESSABLE pipeline (whitespace +
open_pipeline) to reach a pipeline-coverage target (default 3x quota). Segment
focus is respected, and the rep's home region is preferred as a tiebreaker. Reps
who can't reach the target are left short on purpose — that capacity gap is the
signal the tool exists to surface.

Algorithm (deterministic given the seed):
  Per segment pool (segment focus respected), deal accounts largest-addressable
  first to the eligible rep who is furthest from their target (lowest got/need
  ratio), preferring a rep whose home region matches the account. Once every rep
  in the pool has hit its target, remaining accounts top up the least-covered book
  (still home-region-first) as cushion — so no account is orphaned.

`naive_carve` is the baseline the scorecard compares against: round-robin equal
*account count* within each segment pool — same segment constraint, so the
before/after isolates what the capacity carve buys (more reps covered to target).
"""

from __future__ import annotations

import math

import config
from core.models import Account, Rep, Territory
from core.potential import opportunity_value


# ----------------------------------------------------------------------
# Eligibility
# ----------------------------------------------------------------------
def eligible_rep_ids(
    segment: str,
    reps: list[Rep],
    respect_focus: bool,
    generalist: str,
) -> list[str]:
    """Rep ids allowed to carry an account of `segment` (sorted, deterministic)."""
    if not respect_focus:
        return sorted(r.rep_id for r in reps)
    return sorted(
        r.rep_id for r in reps if r.segment_focus == segment or r.segment_focus == generalist
    )


def _addressable(a: Account) -> float:
    """Pipeline a rep can actually close against a new-bookings quota."""
    return a.whitespace_potential + a.open_pipeline


# ----------------------------------------------------------------------
# Work-back carve
# ----------------------------------------------------------------------
def carve(
    accounts: list[Account],
    reps: list[Rep],
    quota_by_rep: dict[str, float],
    *,
    coverage_target: float | None = None,
    target_by_rep: dict[str, float] | None = None,
    respect_segment_focus: bool | None = None,
    prefer_home_region: bool | None = None,
    generalist_focus: str | None = None,
) -> list[Territory]:
    """Carve territories back from fixed per-rep quotas. Deterministic.

    `coverage_target` is the global pack-to multiple; `target_by_rep` optionally
    overrides it per rep (so a segment can carve to its own accepted target)."""
    target_mult = config.PIPELINE_COVERAGE_TARGET if coverage_target is None else coverage_target

    def _target(rid: str) -> float:
        return target_by_rep.get(rid, target_mult) if target_by_rep else target_mult

    respect = (
        config.RESPECT_SEGMENT_FOCUS if respect_segment_focus is None else respect_segment_focus
    )
    prefer_home = config.PREFER_HOME_REGION if prefer_home_region is None else prefer_home_region
    generalist = generalist_focus or config.GENERALIST_FOCUS
    mix = config.POTENTIAL_MIX

    rep_by_id = {r.rep_id: r for r in reps}
    addr = {a.account_id: _addressable(a) for a in accounts}
    assign: dict[str, str] = {}

    for seg in sorted({a.segment for a in accounts}):
        pool = eligible_rep_ids(seg, reps, respect, generalist)
        if not pool:
            raise ValueError(
                f"No rep can carry segment {seg!r} under segment focus "
                f"(add a {generalist!r} rep or turn RESPECT_SEGMENT_FOCUS off)."
            )
        need = {rid: _target(rid) * quota_by_rep.get(rid, 0.0) for rid in pool}
        got = dict.fromkeys(pool, 0.0)

        # Largest addressable accounts first packs to target with fewer accounts and
        # keeps the assignment stable; ties break by id for determinism.
        seg_accts = sorted(
            (a for a in accounts if a.segment == seg),
            key=lambda a: (-addr[a.account_id], a.account_id),
        )
        for a in seg_accts:
            needy = [rid for rid in pool if got[rid] < need[rid]] or pool
            if prefer_home:
                home = [rid for rid in needy if rep_by_id[rid].home_region == a.region]
                cands = home or needy
            else:
                cands = needy
            # Furthest-from-target first (lowest fill ratio); tie -> rep_id.
            rid = min(cands, key=lambda rid: (got[rid] / need[rid] if need[rid] else 1e18, rid))
            assign[a.account_id] = rid
            got[rid] += addr[a.account_id]

    return _build_territories(assign, accounts, reps, mix)


def naive_carve(
    accounts: list[Account],
    reps: list[Rep],
    *,
    respect_segment_focus: bool | None = None,
    generalist_focus: str | None = None,
) -> list[Territory]:
    """Baseline: round-robin equal account *count* within each segment pool.

    Ignores pipeline entirely, so the scorecard's before/after isolates what
    packing-to-quota buys over just splitting accounts evenly.
    """
    respect = (
        config.RESPECT_SEGMENT_FOCUS if respect_segment_focus is None else respect_segment_focus
    )
    generalist = generalist_focus or config.GENERALIST_FOCUS

    assign: dict[str, str] = {}
    for seg in sorted({a.segment for a in accounts}):
        pool = eligible_rep_ids(seg, reps, respect, generalist)
        if not pool:
            raise ValueError(f"No rep can carry segment {seg!r}.")
        seg_accts = sorted((a for a in accounts if a.segment == seg), key=lambda a: a.account_id)
        for k, a in enumerate(seg_accts):
            assign[a.account_id] = pool[k % len(pool)]
    return _build_territories(assign, accounts, reps, config.POTENTIAL_MIX)


def _build_territories(assign, accounts, reps, mix) -> list[Territory]:
    acct = {a.account_id: a for a in accounts}
    by_rep: dict[str, list[str]] = {r.rep_id: [] for r in reps}
    for aid, rid in assign.items():
        by_rep[rid].append(aid)
    territories = []
    for r in sorted(reps, key=lambda r: r.rep_id):
        aids = sorted(by_rep[r.rep_id])
        accts = [acct[aid] for aid in aids]
        territories.append(
            Territory(
                rep_id=r.rep_id,
                account_ids=aids,
                potential=sum(opportunity_value(a, mix) for a in accts),
                geo_spread=len({a.region for a in accts}),
                whitespace=sum(a.whitespace_potential for a in accts),
            )
        )
    return territories


# ----------------------------------------------------------------------
# Reporting helpers (used by evaluate + API/MCP)
# ----------------------------------------------------------------------
def _cov(xs: list[float]) -> float:
    """Population coefficient of variation (sd / mean). 0 if mean is 0."""
    n = len(xs)
    if n == 0:
        return 0.0
    mean = sum(xs) / n
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in xs) / n
    return math.sqrt(var) / mean


def balance_score(territories: list[Territory]) -> float:
    """CoV of territory potential across the team (context, not the objective now)."""
    return _cov([t.potential for t in territories])


def whitespace_cov(territories: list[Territory]) -> float:
    return _cov([t.whitespace for t in territories])


def geo_spread_total(territories: list[Territory]) -> int:
    return sum(t.geo_spread for t in territories)


def off_home_share(
    territories: list[Territory],
    accounts: list[Account],
    reps: list[Rep],
) -> float:
    """Fraction of accounts assigned outside their rep's home region (0 = fully
    compact). Now a reported side effect of the home-region tiebreaker, not an
    optimized objective."""
    region_of = {a.account_id: a.region for a in accounts}
    home_of = {r.rep_id: r.home_region for r in reps}
    total = off = 0
    for t in territories:
        for aid in t.account_ids:
            total += 1
            if region_of[aid] != home_of[t.rep_id]:
                off += 1
    return (off / total) if total else 0.0
