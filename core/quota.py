"""
core/quota.py — Stage 2: derive fair quotas that sum to the company target.

Each territory's quota is proportional to its share of total opportunity
potential. Ramping reps carry a haircut; quotas are then re-normalized so the
book still sums to exactly the company target. Fairness is reported as each rep's
quota/potential ratio, flagging anyone set up to fail (high) or sandbagged (low).
"""

from __future__ import annotations

import config
from core.models import Rep, Territory


def default_company_target(
    territories: list[Territory],
    multiple: float | None = None,
) -> float:
    """A sensible default target: a multiple of total opportunity potential.

    Tuned (via `config.COMPANY_TARGET_MULTIPLE`) so the book can roughly support
    the number while leaving a few territories under-covered — the tension the
    reverse waterfall exists to surface.
    """
    m = config.COMPANY_TARGET_MULTIPLE if multiple is None else multiple
    return m * sum(t.potential for t in territories)


def derive_quotas(
    territories: list[Territory],
    reps: list[Rep],
    company_target: float | None = None,
    *,
    ramp_haircut: float | None = None,
    fairness_tolerance: float | None = None,
) -> float:
    """Fill `quota` and `quota_to_potential` on each territory in place.

    Returns the (resolved) company_target actually used.
    """
    haircut = config.RAMP_QUOTA_HAIRCUT if ramp_haircut is None else ramp_haircut
    tol = config.QUOTA_FAIRNESS_TOLERANCE if fairness_tolerance is None else fairness_tolerance
    target = default_company_target(territories) if company_target is None else company_target

    rep_by_id = {r.rep_id: r for r in reps}
    total_potential = sum(t.potential for t in territories)

    # Raw proportional quota, then the ramp haircut.
    raw: dict[str, float] = {}
    for t in territories:
        share = (t.potential / total_potential) if total_potential else 0.0
        q = target * share
        if rep_by_id[t.rep_id].is_ramping:
            q *= haircut
        raw[t.rep_id] = q

    # Re-normalize so quotas sum back to the company target.
    total_raw = sum(raw.values())
    scale = (target / total_raw) if total_raw else 0.0
    for t in territories:
        t.quota = raw[t.rep_id] * scale
        t.quota_to_potential = (t.quota / t.potential) if t.potential else None

    _flag_fairness(territories, tol)
    return target


def _flag_fairness(territories: list[Territory], tol: float) -> None:
    """Fill each territory's `fairness`: deviation of quota/potential from the
    team mean. Deviation beyond `tol` marks set-up-to-fail (high) / sandbag (low).
    """
    ratios = [t.quota_to_potential for t in territories if t.quota_to_potential is not None]
    if not ratios:
        return
    mean = sum(ratios) / len(ratios)
    for t in territories:
        if t.quota_to_potential is None or mean == 0:
            continue
        dev = (t.quota_to_potential - mean) / mean
        flag = "fair"
        if dev > tol:
            flag = "stretch"  # quota high relative to potential
        elif dev < -tol:
            flag = "sandbag"  # quota low relative to potential
        t.fairness = {"deviation": dev, "flag": flag, "mean_ratio": mean}


def fairness_summary(territories: list[Territory]) -> dict:
    """Roll-up for the API/MCP: mean ratio + any stretched/sandbagged reps."""
    ratios = [t.quota_to_potential for t in territories if t.quota_to_potential is not None]
    if not ratios:
        return {"mean_quota_to_potential": None, "stretch": [], "sandbag": []}
    mean = sum(ratios) / len(ratios)
    stretch, sandbag = [], []
    for t in territories:
        f = t.fairness
        if not f:
            continue
        if f["flag"] == "stretch":
            stretch.append(t.rep_id)
        elif f["flag"] == "sandbag":
            sandbag.append(t.rep_id)
    return {"mean_quota_to_potential": mean, "stretch": stretch, "sandbag": sandbag}
