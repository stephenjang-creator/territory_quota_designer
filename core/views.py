"""
core/views.py — JSON-safe roll-up views over the engine's dataclasses.

Shared by the API and the MCP server so both speak the same shapes. Everything
here is a plain dict of built-in scalars (no numpy, no dataclasses), rounded for
readable, compact payloads — roll-ups and single-entity detail, never the whole
account dump. The numbers all come from `core`; these functions only reshape.
"""

from __future__ import annotations

import config
from core import waterfall
from core.models import Account, PlanResult, Rep, Territory


def _r(x, n=2):
    return round(x, n) if isinstance(x, (int, float)) else x


def territory_row(t: Territory, rep: Rep) -> dict:
    """Compact per-territory row for list/table views."""
    return {
        "rep_id": t.rep_id,
        "rep_name": rep.name,
        "segment_focus": rep.segment_focus,
        "ramp_status": rep.ramp_status,
        "level": rep.level,
        "role": f"{rep.segment_focus} · {rep.level}",
        "ote": _r(t.ote, 0),
        "account_count": t.account_count,
        "potential": _r(t.potential, 0),
        "whitespace": _r(t.whitespace, 0),
        "geo_spread": t.geo_spread,
        "quota": _r(t.quota, 0),
        "quota_to_potential": _r(t.quota_to_potential, 4),
        "available_pipeline": _r(t.available_potential, 0),
        "pipeline_coverage": _r(t.pipeline_coverage_multiple, 2),  # available / quota (target 3x)
        "coverage_ratio": _r(t.coverage_ratio, 3),  # funnel-based adequacy
        "under_covered": t.under_covered,
    }


def territory_detail(t: Territory, rep: Rep, accounts_by_id: dict[str, Account]) -> dict:
    """Full single-territory view: account mix, the complete reverse-waterfall
    funnel, required-vs-available pipeline, coverage, and the rate audit trail.
    This is the `assess_territory` payload."""
    accts = [accounts_by_id[a] for a in t.account_ids]

    by_seg: dict[str, dict] = {}
    for a in accts:
        d = by_seg.setdefault(
            a.segment,
            {"accounts": 0, "whitespace": 0.0, "open_pipeline": 0.0, "current_arr": 0.0},
        )
        d["accounts"] += 1
        d["whitespace"] += a.whitespace_potential
        d["open_pipeline"] += a.open_pipeline
        d["current_arr"] += a.current_arr
    account_mix = {
        seg: {
            "accounts": d["accounts"],
            "share": round(d["accounts"] / t.account_count, 3) if t.account_count else 0,
            "whitespace": _r(d["whitespace"], 0),
            "open_pipeline": _r(d["open_pipeline"], 0),
            "current_arr": _r(d["current_arr"], 0),
        }
        for seg, d in sorted(by_seg.items())
    }

    detail = {
        **territory_row(t, rep),
        "units": config.UNITS,
        "home_region": rep.home_region,
        "home_metro": rep.home_metro,
        "tenure_months": rep.tenure_months,
        "segment_mix": {k: round(v, 3) for k, v in (t.segment_mix or {}).items()},
        "account_mix_by_segment": account_mix,
        "potential_breakdown": {
            "opportunity_value": _r(t.potential, 0),
            "whitespace": _r(t.whitespace, 0),
            "available_pipeline": _r(t.available_potential, 0),
            "note": "all MRR. opportunity_value = whitespace + open_pipeline + "
            "0.25*current_arr; available_pipeline (coverage numerator) = "
            "whitespace + open_pipeline",
        },
        "waterfall": _waterfall_view(t),
        "rates_used": t.rates_used,
        "coverage_note": "pipeline_coverage = addressable pipeline / quota (target 3x); "
        "coverage_ratio is the funnel-based adequacy check. Neither guarantees attainment.",
    }
    if t.under_covered:
        detail["gap"] = _gap_view(t)
    return detail


def _waterfall_view(t: Territory) -> dict:
    if t.funnel is None:
        return {"assessable": False, "reason": "a conversion rate or deal size was <= 0"}
    return {
        "quota": _r(t.quota, 0),
        "avg_deal_size": _r((t.rates_used or {}).get("avg_deal_size", {}).get("value"), 0),
        "funnel": {k: _r(v, 1) for k, v in t.funnel.items()},
        "required_pipeline": _r(t.required_pipeline, 0),
        "required_sqls": _r(t.required_sqls, 0),
        "available_pipeline": _r(t.available_potential, 0),
        "coverage_ratio": _r(t.coverage_ratio, 3),
        "under_covered": t.under_covered,
        "pipeline_coverage_multiple": _r(t.pipeline_coverage_multiple, 2),
        "standard_coverage_multiple": config.STANDARD_COVERAGE_MULTIPLE,
    }


def _gap_view(t: Territory) -> dict:
    ga = waterfall.gap_analysis(t)
    if not ga.get("assessable"):
        return ga
    return {
        "gap_dollars": _r(ga["gap_dollars"], 0),
        "suggested_quota": _r(ga["suggested_quota"], 0),
        "additional_pipeline": _r(ga["additional_pipeline"], 0),
        "additional_sqls": _r(ga["additional_sqls"], 0),
        "levers": [lever["detail"] for lever in ga["levers"]],
    }


def plan_summary(plan: PlanResult) -> dict:
    """Top-line: derived target, capacity coverage, per-segment pipeline, cost-of-sale."""
    sc = plan.scorecard
    return {
        "units": config.UNITS,
        "company_target": _r(plan.company_target, 0),  # derived: sum of standardized quotas
        "coverage_target": sc["coverage_target"],
        "n_territories": plan.n_territories,
        "reps_covered": sc["reps_covered"],  # {baseline, optimized, of} at the target
        "capacity_gap": {
            "baseline": _r(sc["capacity_gap"]["baseline"], 0),
            "optimized": _r(sc["capacity_gap"]["optimized"], 0),
        },
        "coverage_floor": {
            "baseline": _r(sc["coverage_floor"]["baseline"], 2),
            "optimized": _r(sc["coverage_floor"]["optimized"], 2),
        },
        "n_under_covered": plan.n_under_covered,  # funnel-based (secondary signal)
        "total_potential": _r(plan.total_potential, 0),
        "off_home_share": {
            "baseline": _r(sc["off_home_share"]["baseline"], 3),
            "optimized": _r(sc["off_home_share"]["optimized"], 3),
        },
        "per_segment_capacity": {
            seg: {
                "reps": d["reps"],
                "available_pipeline": _r(d["available_pipeline"], 0),
                "required_pipeline": _r(d["required_pipeline"], 0),
                "coverable": d["coverable"],
            }
            for seg, d in sc["per_segment_capacity"].items()
        },
        "cost_of_sale": _r(plan.cost_of_sale, 3),
        "settings": plan.settings,
    }


def list_rows(
    plan: PlanResult, reps: list[Rep], sort_by="coverage_ratio", ascending=True, limit=15
) -> list[dict]:
    """Sorted, limited compact territory rows."""
    rep_by_id = {r.rep_id: r for r in reps}
    rows = [territory_row(t, rep_by_id[t.rep_id]) for t in plan.territories]

    def key(row):
        v = row.get(sort_by)
        return (v is None, v)

    rows.sort(key=key, reverse=not ascending)
    return rows[:limit]
