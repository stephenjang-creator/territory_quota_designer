"""
core/overrides.py — the conversion-rate resolution hierarchy.

A first-class feature: every conversion rate and avg deal size resolves as

    rep override  >  segment override  >  global default (conversions.csv)

The waterfall never reads a rate directly; it asks `resolve()` and also records
*which level* supplied the number, so `assess_territory` can show the audit trail.

Overrides payload shape (all keys optional)::

    {
      "global":  {"Negotiation->Won": 0.25, "avg_deal_size": 110000},
      "segment": {"Enterprise": {"Negotiation->Won": 0.25}},
      "rep":     {"R-104": {"avg_deal_size": 15000}},
    }
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Resolved:
    """A resolved value plus the tier of the hierarchy it came from."""

    value: float
    level: str  # "rep" | "segment" | "global"


def resolve(
    key: str,
    segment: str,
    rep_id: str,
    conversions: dict[str, dict[str, float]],
    overrides: dict | None = None,
) -> Resolved:
    """Resolve one rate/deal-size for a (segment, rep) with overrides applied.

    `key` is a transition (e.g. ``"Negotiation->Won"``) or ``"avg_deal_size"``.
    Falls back to the conversions.csv default for the segment, labeled "global".
    """
    overrides = overrides or {}

    rep_ovr = (overrides.get("rep") or {}).get(rep_id, {})
    if key in rep_ovr:
        return Resolved(float(rep_ovr[key]), "rep")

    seg_ovr = (overrides.get("segment") or {}).get(segment, {})
    if key in seg_ovr:
        return Resolved(float(seg_ovr[key]), "segment")

    glob_ovr = overrides.get("global") or {}
    if key in glob_ovr:
        return Resolved(float(glob_ovr[key]), "global")

    # Fall through to the per-segment default from the CSV.
    return Resolved(float(conversions[segment][key]), "global")
