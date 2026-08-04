"""
core/balance.py — Stage 1: carve the book into balanced territories.

Objective: assign every account to exactly one rep to minimize a combined
imbalance cost across territories:

    cost = w_pot * CoV(potential) + w_geo * geo_norm + w_ws * CoV(whitespace)

where geo_norm is the normalized distinct-region spread (compact = low). Weights
come from `config.WEIGHTS`.

Algorithm (v1, no solver dependency, deterministic given the seed):
  1. Seed — greedy: within each segment pool (segment focus is respected), deal
     accounts largest-opportunity-first to the eligible rep with the least
     potential so far, breaking ties toward a geographic match then rep_id.
  2. Improve — local search: repeatedly move the account whose reassignment most
     reduces the combined cost, until no move helps or a pass cap is hit. Swaps
     are added only when an accounts-per-rep cap is set (moves alone can deadlock
     under a cap); with no cap, moves reach the same optimum.

`naive_carve` is the baseline the scorecard compares against: round-robin equal
*account count* within each segment pool — same constraints as the optimizer, so
the before/after isolates what the optimizer actually buys.
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
    ids = sorted(
        r.rep_id for r in reps if r.segment_focus == segment or r.segment_focus == generalist
    )
    return ids


# ----------------------------------------------------------------------
# Internal territory aggregate (mutated during local search)
# ----------------------------------------------------------------------
class _Agg:
    """Mutable per-rep aggregate. `off` counts accounts assigned outside the rep's
    home region — a smooth, single-move-optimizable proxy for geo compactness (it
    also drags the reported distinct-region spread down as a side effect)."""

    __slots__ = ("pot", "ws", "cnt", "home", "off")

    def __init__(self, home: str) -> None:
        self.pot = 0.0
        self.ws = 0.0
        self.cnt = 0
        self.home = home
        self.off = 0

    def add(self, a: Account, o: float) -> None:
        self.pot += o
        self.ws += a.whitespace_potential
        self.cnt += 1
        if a.region != self.home:
            self.off += 1

    def remove(self, a: Account, o: float) -> None:
        self.pot -= o
        self.ws -= a.whitespace_potential
        self.cnt -= 1
        if a.region != self.home:
            self.off -= 1


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


def _off_home_share(aggs: dict[str, _Agg]) -> float:
    """Fraction of all accounts assigned outside their rep's home region."""
    total = sum(a.cnt for a in aggs.values())
    if total == 0:
        return 0.0
    return sum(a.off for a in aggs.values()) / total


def _cost(aggs: dict[str, _Agg], weights: dict) -> float:
    pots = [a.pot for a in aggs.values()]
    wss = [a.ws for a in aggs.values()]
    return (
        weights["potential"] * _cov(pots)
        + weights["geo"] * _off_home_share(aggs)
        + weights["whitespace"] * _cov(wss)
    )


# ----------------------------------------------------------------------
# Carve
# ----------------------------------------------------------------------
def carve(
    accounts: list[Account],
    reps: list[Rep],
    *,
    weights: dict | None = None,
    potential_mix: dict | None = None,
    respect_segment_focus: bool | None = None,
    max_accounts_per_rep: int | None = None,
    generalist_focus: str | None = None,
    max_passes: int | None = None,
) -> list[Territory]:
    """Optimized carve. Deterministic; identical inputs → identical territories."""
    weights = weights or config.WEIGHTS
    mix = potential_mix or config.POTENTIAL_MIX
    respect = (
        config.RESPECT_SEGMENT_FOCUS if respect_segment_focus is None else respect_segment_focus
    )
    cap = config.MAX_ACCOUNTS_PER_REP if max_accounts_per_rep is None else max_accounts_per_rep
    generalist = generalist_focus or config.GENERALIST_FOCUS
    passes = config.MAX_LOCAL_SEARCH_PASSES if max_passes is None else max_passes

    opp = {a.account_id: opportunity_value(a, mix) for a in accounts}
    acct = {a.account_id: a for a in accounts}

    aggs: dict[str, _Agg] = {r.rep_id: _Agg(r.home_region) for r in reps}
    assign: dict[str, str] = {}
    elig: dict[str, list[str]] = {}

    # ---- 1. Greedy seed, per segment pool ----
    segments = sorted({a.segment for a in accounts})
    for seg in segments:
        pool = eligible_rep_ids(seg, reps, respect, generalist)
        if not pool:
            raise ValueError(
                f"No rep can carry segment {seg!r} under segment focus "
                f"(add a {generalist!r} rep or turn RESPECT_SEGMENT_FOCUS off)."
            )
        seg_accts = sorted(
            (a for a in accounts if a.segment == seg),
            key=lambda a: (-opp[a.account_id], a.account_id),
        )
        for a in seg_accts:
            elig[a.account_id] = pool
            o = opp[a.account_id]
            cands = [rid for rid in pool if cap is None or aggs[rid].cnt < cap]
            if not cands:  # every eligible rep at cap
                raise ValueError(f"accounts-per-rep cap {cap} too small for segment {seg!r}")

            # Greedy on the true objective: place the account where it least
            # increases the combined cost (so the seed already honors the weights,
            # incl. geo). Tie -> rep_id, for determinism.
            best, best_key = None, None
            for rid in cands:
                aggs[rid].add(a, o)
                key = (_cost(aggs, weights), rid)
                aggs[rid].remove(a, o)
                if best_key is None or key < best_key:
                    best, best_key = rid, key
            aggs[best].add(a, o)
            assign[a.account_id] = best

    # ---- 2. Local search: move sweeps (the smooth off-home geo term makes single
    #         moves effective). Swap sweeps only when a cap binds — moves can
    #         deadlock there — since swaps are O(n^2) and hurt interactivity. ----
    order = sorted(assign)
    for _ in range(passes):
        improved = _move_pass(aggs, assign, acct, opp, elig, weights, cap, order)
        if cap is not None:
            improved = _swap_pass(aggs, assign, acct, opp, elig, weights, order) or improved
        if not improved:
            break

    return _build_territories(assign, accounts, reps, mix)


def _move_pass(aggs, assign, acct, opp, elig, weights, cap, order) -> bool:
    improved = False
    base = _cost(aggs, weights)
    for aid in order:
        i = assign[aid]
        a = acct[aid]
        o = opp[aid]
        cands = [rid for rid in elig[aid] if rid != i and (cap is None or aggs[rid].cnt < cap)]
        best_j, best_cost = None, base
        for j in cands:
            aggs[i].remove(a, o)
            aggs[j].add(a, o)
            c = _cost(aggs, weights)
            aggs[j].remove(a, o)
            aggs[i].add(a, o)
            if c < best_cost - 1e-12:
                best_cost, best_j = c, j
        if best_j is not None:
            aggs[i].remove(a, o)
            aggs[best_j].add(a, o)
            assign[aid] = best_j
            base = best_cost
            improved = True
    return improved


def _swap_pass(aggs, assign, acct, opp, elig, weights, order) -> bool:
    """Swap two accounts across reps when it lowers cost — escapes local minima
    that single moves can't reach (e.g. under an accounts-per-rep cap, or when two
    reps each hold one of the other's better-fit accounts)."""
    improved = False
    base = _cost(aggs, weights)
    for x in range(len(order)):
        aid = order[x]
        i = assign[aid]
        a = acct[aid]
        oa = opp[aid]
        for y in range(x + 1, len(order)):
            bid = order[y]
            j = assign[bid]
            if j == i:
                continue
            b = acct[bid]
            ob = opp[bid]
            # both must be able to sit in the other's rep
            if j not in elig[aid] or i not in elig[bid]:
                continue
            aggs[i].remove(a, oa)
            aggs[j].remove(b, ob)
            aggs[i].add(b, ob)
            aggs[j].add(a, oa)
            c = _cost(aggs, weights)
            aggs[i].remove(b, ob)
            aggs[j].remove(a, oa)
            aggs[i].add(a, oa)
            aggs[j].add(b, ob)
            if c < base - 1e-12:
                aggs[i].remove(a, oa)
                aggs[j].remove(b, ob)
                aggs[i].add(b, ob)
                aggs[j].add(a, oa)
                assign[aid], assign[bid] = j, i
                base = c
                improved = True
                break  # account `aid` moved; restart its comparisons next pass
    return improved


def naive_carve(
    accounts: list[Account],
    reps: list[Rep],
    *,
    potential_mix: dict | None = None,
    respect_segment_focus: bool | None = None,
    generalist_focus: str | None = None,
) -> list[Territory]:
    """Baseline: round-robin equal account *count* within each segment pool.

    Deliberately ignores potential/geo/whitespace — it is the naive version of the
    *same* constrained problem, so the scorecard's before/after isolates the
    optimizer's contribution rather than the segment-focus structure.
    """
    mix = potential_mix or config.POTENTIAL_MIX
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
    return _build_territories(assign, accounts, reps, mix)


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
def balance_score(territories: list[Territory]) -> float:
    """CoV of territory potential across the team (lower = fairer)."""
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
    """Fraction of accounts assigned outside their rep's home region (the geo
    term in the Stage-1 objective; 0 = every account sits in its rep's region)."""
    region_of = {a.account_id: a.region for a in accounts}
    home_of = {r.rep_id: r.home_region for r in reps}
    total = off = 0
    for t in territories:
        for aid in t.account_ids:
            total += 1
            if region_of[aid] != home_of[t.rep_id]:
                off += 1
    return (off / total) if total else 0.0


def combined_cost(
    territories: list[Territory],
    weights: dict,
    accounts: list[Account],
    reps: list[Rep],
) -> float:
    """The Stage-1 objective evaluated on finished territories (for reporting)."""
    pots = [t.potential for t in territories]
    wss = [t.whitespace for t in territories]
    return (
        weights["potential"] * _cov(pots)
        + weights["geo"] * off_home_share(territories, accounts, reps)
        + weights["whitespace"] * _cov(wss)
    )
