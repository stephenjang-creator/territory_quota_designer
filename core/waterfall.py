"""
core/waterfall.py — Stage 3: the reverse waterfall (the flagship).

Units: quota is a quarterly new-MRR target and avg deal size is MRR added per
deal, so ``won_deals = quota / avg_deal_size`` is deals to close in the quarter,
and every stage of the funnel is a deal/SQL count. Required and available
pipeline are both in MRR, so coverage_ratio is a pure ratio.

For each territory we work *backward* from the quota up the funnel to the number
of SQLs the rep would have to source, then ask a blunt question: does the
territory hold enough addressable pipeline to support that?

    won_deals      = quota / avg_deal_size
    at_negotiation = won_deals      / rate(Negotiation->Won)
    at_proposal    = at_negotiation / rate(Proposal->Negotiation)
    at_qual        = at_proposal    / rate(Qualification->Proposal)
    at_discovery   = at_qual        / rate(Discovery->Qualification)   # required SQLs
    required_pipeline = at_negotiation * avg_deal_size   ( == quota / rate(Neg->Won) )

    coverage_ratio = available_potential / required_pipeline
      >= 1  -> the territory can support the quota
      <  1  -> under-covered (flag red)

Conversion rates and avg deal size resolve through the override hierarchy
(rep > segment > global; see core/overrides.py). A territory's rates come from
its segment mix — a single blended value when the book spans segments, and the
plain segment default when it doesn't.

Coverage is an **adequacy / risk** signal, not a promise of attainment: it says
the pipeline is (in)sufficient on paper, nothing about execution.
"""

from __future__ import annotations

from collections import Counter

import config
from core.dataio import AVG_DEAL_KEY, TRANSITIONS
from core.models import Account, Territory
from core.overrides import resolve
from core.potential import available_potential


def _territory_rates(accounts, rep_id, conversions, overrides):
    """Resolve blended conversion rates + avg deal size for one territory.

    Returns (segment_mix, resolved_values, rates_used_audit).
    """
    seg_counts = Counter(a.segment for a in accounts)
    total = sum(seg_counts.values())
    mix = {s: seg_counts[s] / total for s in sorted(seg_counts)}
    keys = TRANSITIONS + [AVG_DEAL_KEY]

    resolved: dict[str, float] = {}
    rates_used: dict[str, dict] = {}

    if len(seg_counts) == 1:
        seg = next(iter(seg_counts))
        for k in keys:
            r = resolve(k, seg, rep_id, conversions, overrides)
            resolved[k] = r.value
            rates_used[k] = {"value": r.value, "level": r.level, "segment": seg}
    else:
        for k in keys:
            val = 0.0
            parts = {}
            for s, share in mix.items():
                r = resolve(k, s, rep_id, conversions, overrides)
                val += share * r.value
                parts[s] = {"value": r.value, "level": r.level, "share": share}
            resolved[k] = val
            rates_used[k] = {"value": val, "level": "blend", "segments": parts}

    return mix, resolved, rates_used


def run_waterfall(
    territories: list[Territory],
    accounts: list[Account],
    conversions: dict,
    overrides: dict | None = None,
) -> list[Territory]:
    """Fill the Stage-3 coverage block on each territory in place (needs `quota`)."""
    by_id = {a.account_id: a for a in accounts}
    for t in territories:
        accts = [by_id[aid] for aid in t.account_ids]
        mix, rates, rates_used = _territory_rates(accts, t.rep_id, conversions, overrides)
        t.segment_mix = mix
        t.rates_used = rates_used

        quota = t.quota or 0.0
        avg_deal = rates[AVG_DEAL_KEY]
        r_disc_qual = rates["Discovery->Qualification"]
        r_qual_prop = rates["Qualification->Proposal"]
        r_prop_neg = rates["Proposal->Negotiation"]
        r_neg_won = rates["Negotiation->Won"]

        avail = available_potential(accts)
        t.available_potential = avail

        # Guard against zeroed-out overrides (rate/deal <= 0 -> can't assess).
        if min(avg_deal, r_disc_qual, r_qual_prop, r_prop_neg, r_neg_won) <= 0:
            t.funnel = None
            t.required_pipeline = None
            t.required_sqls = None
            t.coverage_ratio = None
            t.under_covered = None
            t.pipeline_coverage_multiple = None
            continue

        won = quota / avg_deal
        at_neg = won / r_neg_won
        at_prop = at_neg / r_prop_neg
        at_qual = at_prop / r_qual_prop
        at_disc = at_qual / r_disc_qual  # required SQLs

        required_pipeline = at_neg * avg_deal  # value sitting at Negotiation
        t.funnel = {
            "required_sqls": at_disc,
            "qualification": at_qual,
            "proposal": at_prop,
            "negotiation": at_neg,
            "won_deals": won,
        }
        t.required_pipeline = required_pipeline
        t.required_sqls = at_disc
        t.coverage_ratio = (avail / required_pipeline) if required_pipeline > 0 else None
        t.under_covered = t.coverage_ratio is not None and t.coverage_ratio < 1.0
        t.pipeline_coverage_multiple = (avail / quota) if quota > 0 else None

    return territories


def gap_analysis(t: Territory) -> dict:
    """For an under-covered territory: the size of the gap and the top levers to
    close it. All linear in the quota, so the SQL framing is exact.
    """
    if t.coverage_ratio is None or t.required_pipeline is None:
        return {"rep_id": t.rep_id, "assessable": False}
    r_neg_won = t.rates_used["Negotiation->Won"]["value"]
    gap = max(0.0, t.required_pipeline - (t.available_potential or 0.0))
    shortfall_frac = max(0.0, 1.0 - t.coverage_ratio)
    return {
        "rep_id": t.rep_id,
        "assessable": True,
        "coverage_ratio": t.coverage_ratio,
        "gap_dollars": gap,  # required - available pipeline
        "suggested_quota": (t.available_potential or 0.0) * r_neg_won,  # -> coverage 1.0
        "additional_pipeline": gap,  # reassign ~$ of addressable in
        "additional_sqls": (t.required_sqls or 0.0) * shortfall_frac,
        "levers": [
            {
                "type": "lower_quota",
                "detail": f"lower quota to ~${(t.available_potential or 0.0) * r_neg_won:,.0f}",
            },
            {
                "type": "add_pipeline",
                "detail": f"reassign ~${gap:,.0f} of addressable potential into this book",
            },
            {
                "type": "source_sqls",
                "detail": f"source ~{(t.required_sqls or 0.0) * shortfall_frac:,.0f} more SQLs",
            },
        ],
    }


def under_covered(territories: list[Territory]) -> list[Territory]:
    """Only the territories with coverage_ratio < 1 (worst first)."""
    flagged = [t for t in territories if t.under_covered]
    return sorted(
        flagged, key=lambda t: (t.coverage_ratio if t.coverage_ratio is not None else 1e9)
    )


def standard_coverage_flags(territories: list[Territory]) -> dict:
    """Second sanity signal: territories under the standard pipeline-coverage
    multiple (available_potential / quota < STANDARD_COVERAGE_MULTIPLE).
    """
    band = config.STANDARD_COVERAGE_MULTIPLE
    thin = [
        t.rep_id
        for t in territories
        if t.pipeline_coverage_multiple is not None and t.pipeline_coverage_multiple < band
    ]
    return {"standard_multiple": band, "below_band": thin}
