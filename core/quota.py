"""
core/quota.py — Stage 2: derive fair quotas that sum to the company target.

Each territory's quota is proportional to its share of total opportunity
potential, then scaled by the rep's seniority-level multiplier (ramping / AE /
Sr. AE / Sr. Strategic AE — a ramping rep carries less, senior tiers carry more);
quotas are then re-normalized so the book still sums to exactly the company
target. Fairness is reported as each rep's quota/potential ratio, flagging anyone
set up to fail (high) or sandbagged (low) — with levels, that ratio varies by
tier by design, so senior tiers read "stretch" and ramping "sandbag" as expected.

The company target is a *quarterly* new-MRR bookings goal; every dollar here is
MRR (see config.UNITS).
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


def resolve_level_multipliers(overrides: dict | None = None) -> dict[str, float]:
    """The effective {level: quota multiplier} map — config defaults with any
    caller overrides layered on top."""
    mult = dict(config.LEVEL_QUOTA_MULTIPLIER)
    for level, value in (overrides or {}).items():
        try:
            mult[level] = float(value)
        except (TypeError, ValueError):
            continue  # ignore un-parseable overrides; keep the default
    return mult


def derive_quotas(
    territories: list[Territory],
    reps: list[Rep],
    company_target: float | None = None,
    *,
    level_multipliers: dict | None = None,
    ramp_haircut: float | None = None,
    fairness_tolerance: float | None = None,
) -> float:
    """Fill `quota` and `quota_to_potential` on each territory in place.

    Each raw quota is proportional to the territory's potential, then scaled by
    the rep's seniority-level multiplier (config.LEVEL_QUOTA_MULTIPLIER, override
    via `level_multipliers`), then re-normalized so the book sums to the company
    target. `ramp_haircut`, if given, overrides just the ramping level (back-compat).

    Returns the (resolved) company_target actually used.
    """
    mult = resolve_level_multipliers(level_multipliers)
    if ramp_haircut is not None:
        mult["ramping"] = float(ramp_haircut)
    tol = config.QUOTA_FAIRNESS_TOLERANCE if fairness_tolerance is None else fairness_tolerance
    target = default_company_target(territories) if company_target is None else company_target

    rep_by_id = {r.rep_id: r for r in reps}
    total_potential = sum(t.potential for t in territories)

    # Raw proportional quota, then the rep's level multiplier.
    raw: dict[str, float] = {}
    for t in territories:
        share = (t.potential / total_potential) if total_potential else 0.0
        raw[t.rep_id] = target * share * mult.get(rep_by_id[t.rep_id].level, 1.0)

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
