"""
core/comp.py — Stage 4: comp simulation, anchored on OTE.

Pay is anchored on the SAME on-target earnings (OTE) that sets quota (Stage 2), so
the two are always consistent:

    base_salary     = split * OTE                                  (fixed, annual)
    target_variable = (1 - split) * OTE                            (earned in full at 100%)
    variable(att)   = target_variable * payout_factor(att)         (3-band curve, f(1.0)=1)
    total_comp      = base_salary + variable(att)                  (annual)
    cost_of_sale    = sum(total_comp) / sum(bookings)              (both annual)

`payout_factor` is a piecewise-linear multiplier on target variable, normalized so
it equals 1.0 at the accelerator threshold (on-target). Below the decelerator
threshold the slope is reduced (under-attainment penalty); above the accelerator
threshold it is raised (kicker); an optional cap freezes it. Every parameter is
overridable via the API/UI. OTE (hence comp) is annual, so bookings are annualized
too: bookings = quarterly quota * QUOTA_PERIODS_PER_YEAR * attainment. That keeps
cost-of-sale = annual comp / annual bookings at the usual ~20-30%, rather than a
quarter-comp-vs-year-quota mismatch. cost_of_sale is a ratio, denomination-invariant.
"""

from __future__ import annotations

import config
from core.models import Territory


def _params(overrides: dict | None) -> dict:
    p = dict(config.COMP)
    if overrides:
        p.update(overrides)
    return p


def resolved_params(overrides: dict | None = None) -> dict:
    """The effective comp parameters: config.COMP with any overrides layered on."""
    return _params(overrides)


def payout_factor(attainment: float, comp: dict) -> float:
    """Multiplier on target variable at a given attainment; normalized to 1.0 at the
    accelerator threshold (on-target). Reduced below the decelerator threshold,
    raised above the accelerator threshold, optionally frozen at the cap."""
    a_thr = comp["accelerator_threshold"]
    a_mult = comp["accelerator_multiplier"]
    d_thr = comp.get("decelerator_threshold") or 0.0
    d_mult = comp.get("decelerator_multiplier")
    d_mult = 1.0 if d_mult is None else d_mult

    cap = comp.get("cap_attainment")
    att = min(attainment, cap) if cap is not None else attainment
    att = max(0.0, att)
    d_thr = max(0.0, min(d_thr, a_thr))

    # Standard slope s so that payout_factor(a_thr) == 1.0.
    denom = d_mult * d_thr + (a_thr - d_thr)
    s = (1.0 / denom) if denom > 0 else 0.0

    decel_att = min(att, d_thr)  # 0 .. decel_threshold   (reduced slope)
    std_att = max(0.0, min(att, a_thr) - d_thr)  # decel .. accel_threshold (standard)
    accel_att = max(0.0, att - a_thr)  # accel_threshold ..     (accelerated)
    return s * (decel_att * d_mult + std_att + accel_att * a_mult)


def base_salary(ote: float, comp: dict) -> float:
    """Fixed base pay: a fraction of OTE."""
    return comp["base_variable_split"] * ote


def variable_payout(ote: float, attainment: float, comp: dict) -> float:
    """Variable comp earned at a given attainment (target variable * payout curve)."""
    target_variable = (1.0 - comp["base_variable_split"]) * ote
    return target_variable * payout_factor(attainment, comp)


def rep_payout(
    ote: float,
    quota: float,
    attainment: float,
    comp: dict,
    periods_per_year: float | None = None,
) -> dict:
    """Full payout breakdown for one rep at one attainment. `quota` is quarterly;
    `bookings` is annualized (quota * periods_per_year * attainment) so it sits on
    the same annual footing as OTE-anchored comp."""
    ppy = config.QUOTA_PERIODS_PER_YEAR if periods_per_year is None else float(periods_per_year)
    base = base_salary(ote, comp)
    var = variable_payout(ote, attainment, comp)
    return {
        "ote": ote,
        "quota": quota,
        "attainment": attainment,
        "bookings": quota * ppy * attainment,  # annualized
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
        pay = rep_payout(t.ote or 0.0, t.quota, att, comp)
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
    ote: float,
    quota: float,
    comp_overrides: dict | None = None,
    lo: float = 0.0,
    hi: float = 1.5,
    step: float = 0.1,
) -> list[dict]:
    """Total comp as a function of attainment for one plan (for the UI curve)."""
    comp = _params(comp_overrides)
    curve = []
    n = int(round((hi - lo) / step))
    for i in range(n + 1):
        att = round(lo + i * step, 4)
        total = rep_payout(ote, quota, att, comp)["total_comp"]
        curve.append({"attainment": att, "total_comp": total})
    return curve
