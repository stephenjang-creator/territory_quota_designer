"""
core/comp.py — Stage 4: comp simulation.

Variable pay is commission on bookings: `commission_rate` up to the accelerator
threshold (in attainment), then `commission_rate * accelerator_multiplier` above
it, optionally capped. Base salary is derived from the base/variable OTE split so
cost-of-sale reflects fully-loaded comp, not just commission::

    target_variable = commission_rate * quota          # variable earned at 100%
    base_salary     = target_variable * split/(1 - split)
    total_comp      = base_salary + variable_payout(attainment)
    cost_of_sale    = sum(total_comp) / sum(bookings)

Quota is a quarterly new-MRR target, so payouts, bookings, and cost-of-sale are
all per-quarter; cost_of_sale is a ratio and so is denomination-invariant. Every
parameter is overridable via the API/UI; nothing here is hardcoded.
"""

from __future__ import annotations

import config
from core.models import Territory


def _params(overrides: dict | None) -> dict:
    p = dict(config.COMP)
    if overrides:
        p.update(overrides)
    return p


def variable_payout(quota: float, attainment: float, comp: dict) -> float:
    """Commission earned at a given attainment (with accelerator + optional cap)."""
    thr = comp["accelerator_threshold"]
    rate = comp["commission_rate"]
    mult = comp["accelerator_multiplier"]
    cap = comp.get("cap_attainment")
    att = min(attainment, cap) if cap is not None else attainment
    base_att = min(att, thr)
    accel_att = max(0.0, att - thr)
    return quota * rate * base_att + quota * rate * mult * accel_att


def base_salary(quota: float, comp: dict) -> float:
    """Fixed salary implied by the OTE split (0 if split is 0 = pure commission)."""
    split = comp["base_variable_split"]
    if split <= 0:
        return 0.0
    if split >= 1:
        raise ValueError("base_variable_split must be < 1.0")
    target_variable = comp["commission_rate"] * quota
    return target_variable * split / (1 - split)


def rep_payout(quota: float, attainment: float, comp: dict) -> dict:
    """Full payout breakdown for one rep at one attainment."""
    var = variable_payout(quota, attainment, comp)
    base = base_salary(quota, comp)
    bookings = quota * attainment
    return {
        "quota": quota,
        "attainment": attainment,
        "bookings": bookings,
        "base_salary": base,
        "variable_payout": var,
        "total_comp": base + var,
    }


def _attainment_for(rep_id: str, attainment) -> float:
    """A single float applies to everyone; a dict is per-rep (missing -> 1.0)."""
    if isinstance(attainment, dict):
        return float(attainment.get(rep_id, 1.0))
    return float(attainment)


def simulate(
    territories: list[Territory],
    attainment=1.0,
    comp_overrides: dict | None = None,
) -> dict:
    """Portfolio comp at a given attainment (float, or per-rep dict)."""
    comp = _params(comp_overrides)
    rows = []
    total_comp = 0.0
    total_bookings = 0.0
    for t in territories:
        if t.quota is None:
            continue
        att = _attainment_for(t.rep_id, attainment)
        pay = rep_payout(t.quota, att, comp)
        pay["rep_id"] = t.rep_id
        rows.append(pay)
        total_comp += pay["total_comp"]
        total_bookings += pay["bookings"]
    cost_of_sale = (total_comp / total_bookings) if total_bookings else None
    return {
        "attainment": attainment,
        "total_comp": total_comp,
        "total_bookings": total_bookings,
        "cost_of_sale": cost_of_sale,
        "per_rep": rows,
        "comp_params": comp,
    }


def scenario_compare(
    territories: list[Territory],
    scenarios: list[float] | None = None,
    comp_overrides: dict | None = None,
) -> list[dict]:
    """Total comp + cost-of-sale across a set of attainment scenarios."""
    scenarios = scenarios or config.ATTAINMENT_SCENARIOS
    comp = _params(comp_overrides)
    out = []
    for att in scenarios:
        sim = simulate(territories, att, comp)
        out.append(
            {
                "attainment": att,
                "total_comp": sim["total_comp"],
                "total_bookings": sim["total_bookings"],
                "cost_of_sale": sim["cost_of_sale"],
            }
        )
    return out


def payout_curve(
    quota: float,
    comp_overrides: dict | None = None,
    lo: float = 0.0,
    hi: float = 1.5,
    step: float = 0.1,
) -> list[dict]:
    """Payout as a function of attainment for a single plan (for the UI curve)."""
    comp = _params(comp_overrides)
    curve = []
    n = int(round((hi - lo) / step))
    for i in range(n + 1):
        att = round(lo + i * step, 4)
        curve.append({"attainment": att, "total_comp": rep_payout(quota, att, comp)["total_comp"]})
    return curve
