"""
core/quota.py — Stage 2: standardized quota by role, anchored on pay.

Quota RULES. Each rep's quota is fixed by ROLE (segment x seniority level), not by
book size, so every rep in the same role carries the identical number. Quota is
derived backward from on-target earnings:

    OTE(role)      = SEGMENT_OTE[segment] * LEVEL_OTE_FACTOR[level]   (overridable per role)
    quota          = QUOTA_TO_OTE * OTE(role)
    company target = sum of every rep's quota                         (derived)

The carve (Stage 1) then works back from these quotas to build books with enough
addressable pipeline; this module only sets the numbers the carve targets. All $
are the synthetic MRR-scaled units the rest of the model uses (see config.UNITS).
"""

from __future__ import annotations

import config
from core.models import Rep, Territory


def role_ote(segment: str, level: str, ote_overrides: dict | None = None) -> float:
    """On-target earnings for a (segment, level) role. Per-role overrides win, else
    the default composition SEGMENT_OTE[segment] * LEVEL_OTE_FACTOR[level]."""
    ovr = (ote_overrides or {}).get(segment, {})
    if level in ovr:
        try:
            return float(ovr[level])
        except (TypeError, ValueError):
            pass
    return config.SEGMENT_OTE.get(segment, 0.0) * config.LEVEL_OTE_FACTOR.get(level, 1.0)


def resolve_ote(reps: list[Rep], ote_overrides: dict | None = None) -> dict[str, float]:
    """rep_id -> OTE for the rep's role."""
    return {r.rep_id: role_ote(r.segment_focus, r.level, ote_overrides) for r in reps}


def standardized_quotas(
    reps: list[Rep],
    *,
    ote_overrides: dict | None = None,
    quota_to_ote: float | None = None,
) -> dict[str, float]:
    """rep_id -> standardized quota (= QUOTA_TO_OTE * role OTE). Same role -> same value."""
    mult = config.QUOTA_TO_OTE if quota_to_ote is None else float(quota_to_ote)
    return {rid: mult * ote for rid, ote in resolve_ote(reps, ote_overrides).items()}


def default_company_target(
    reps: list[Rep],
    *,
    ote_overrides: dict | None = None,
    quota_to_ote: float | None = None,
) -> float:
    """The derived company target: the sum of every rep's standardized quota."""
    quotas = standardized_quotas(reps, ote_overrides=ote_overrides, quota_to_ote=quota_to_ote)
    return sum(quotas.values())


def fill_territory_quotas(
    territories: list[Territory],
    quota_by_rep: dict[str, float],
    ote_by_rep: dict[str, float],
) -> float:
    """Write quota / ote / quota_to_potential onto each territory. Returns the sum."""
    for t in territories:
        t.quota = quota_by_rep.get(t.rep_id, 0.0)
        t.ote = ote_by_rep.get(t.rep_id)
        t.quota_to_potential = (t.quota / t.potential) if t.potential else None
    return sum(quota_by_rep.get(t.rep_id, 0.0) for t in territories)


def quota_by_role(reps: list[Rep], **kw) -> dict[tuple[str, str], float]:
    """(segment, level) -> the one standardized quota for that role (for roll-ups)."""
    quotas = standardized_quotas(reps, **kw)
    out: dict[tuple[str, str], float] = {}
    for r in reps:
        out[(r.segment_focus, r.level)] = quotas[r.rep_id]
    return out
