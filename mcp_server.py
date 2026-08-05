"""
mcp_server.py — expose the Territory & Quota Designer as an MCP server.

Thin, READ-ONLY wrappers over the deterministic core (`core.balance / quota /
waterfall / comp / evaluate`, reshaped through `core.views`). An agent can
interrogate a carve conversationally — under-covered territories, what-if weight
changes, conversion-rate stress tests, comp scenarios — and the core owns every
number; these tools only reshape and diff.

Contract: JSON-safe returns (plain built-ins), errors as ``{"error": ...}`` never
raised, small roll-ups only (never the 800-account dump), zero LLM calls, nothing
persists — what-if tools recompute in memory. All $ are MRR; quota is a quarterly
new-MRR target (see `config.UNITS`).

Transport: stdio by default; HTTP behind ``MCP_TRANSPORT=http`` / ``--http``,
bound to ``0.0.0.0:$PORT`` with ``MCP_AUTH_TOKEN`` bearer auth for hosted use.
The CSV dir comes from ``$TERRITORY_DATA`` (default ``data``).
"""

from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

import config
from core import comp, evaluate, views, waterfall
from core.dataio import load_all
from core.plan import PlanSettings, run_plan

mcp = FastMCP("territory-quota-designer")

# Load the synthetic data and compute a default plan ONCE at startup, so
# single-entity lookups are instant. Tools that accept settings recompute.
ACCOUNTS, REPS, CONVERSIONS = load_all()
REP_BY_ID = {r.rep_id: r for r in REPS}
ACC_BY_ID = {a.account_id: a for a in ACCOUNTS}
DEFAULT_PLAN = run_plan(ACCOUNTS, REPS, CONVERSIONS)

_SORT_KEYS = {
    "coverage_ratio",
    "potential",
    "quota",
    "quota_to_potential",
    "account_count",
    "whitespace",
    "geo_spread",
    "rep_id",
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _weights(pw, gw, ww):
    """Normalized weights dict from any provided components, or None (use default)."""
    if pw is None and gw is None and ww is None:
        return None
    base = config.WEIGHTS
    w = {
        "potential": base["potential"] if pw is None else float(pw),
        "geo": base["geo"] if gw is None else float(gw),
        "whitespace": base["whitespace"] if ww is None else float(ww),
    }
    if min(w.values()) < 0:
        raise ValueError("weights must be non-negative")
    total = sum(w.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return {k: v / total for k, v in w.items()}


def _plan(pw=None, gw=None, ww=None, company_target=None, overrides=None, level_multipliers=None):
    """The default plan when nothing is overridden, else a fresh in-memory re-run."""
    w = _weights(pw, gw, ww)
    if w is None and company_target is None and not overrides and not level_multipliers:
        return DEFAULT_PLAN
    return run_plan(
        ACCOUNTS,
        REPS,
        CONVERSIONS,
        PlanSettings(
            weights=w,
            company_target=company_target,
            overrides=overrides or {},
            level_multipliers=level_multipliers,
        ),
    )


def _avg(d: dict) -> float:
    vals = list(d.values())
    return sum(vals) / len(vals) if vals else 0.0


# ----------------------------------------------------------------------
# Tools (docstrings are how the agent selects tools — keep them crisp)
# ----------------------------------------------------------------------
@mcp.tool()
def plan_summary(
    potential_weight: float | None = None,
    geo_weight: float | None = None,
    whitespace_weight: float | None = None,
    company_target: float | None = None,
) -> dict:
    """Top-line health of a plan — the entry point for "how does this plan look".

    Returns balance vs. baseline, # territories, # under-covered, the quarterly
    company target (new MRR), cost-of-sale, within-segment balance, and geo
    compactness. Omit all args for the default plan; pass any subset of weights
    (auto-normalized to sum 1) and/or a company_target to re-run in memory.
    """
    try:
        return views.plan_summary(
            _plan(potential_weight, geo_weight, whitespace_weight, company_target)
        )
    except Exception as e:  # never raise across the wire
        return {"error": str(e)}


@mcp.tool()
def list_territories(
    sort_by: str = "coverage_ratio", ascending: bool = True, limit: int = 15
) -> dict:
    """Compact per-territory rows for the default plan (worst-covered first).

    Each row: rep_id, rep_name, segment_focus, account_count, potential, quota,
    quota_to_potential, coverage_ratio, under_covered. Sort by any of:
    coverage_ratio, potential, quota, quota_to_potential, account_count,
    whitespace, geo_spread, rep_id.
    """
    try:
        if sort_by not in _SORT_KEYS:
            return {"error": f"sort_by must be one of {sorted(_SORT_KEYS)}"}
        limit = max(1, min(int(limit), len(REPS)))
        rows = views.list_rows(
            DEFAULT_PLAN, REPS, sort_by=sort_by, ascending=ascending, limit=limit
        )
        return {"units": config.UNITS, "sort_by": sort_by, "count": len(rows), "territories": rows}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def assess_territory(rep_id: str) -> dict:
    """One territory in full — the "why is this rep under-covered" workhorse.

    Account mix by segment, potential breakdown, quota, the COMPLETE
    reverse-waterfall funnel (required SQLs → qual → proposal → negotiation → won
    deals), required vs. available pipeline, coverage_ratio, the conversion rates
    used and at what override level (rep/segment/global), quota fairness, and — if
    under-covered — the gap size and the top levers to close it.
    """
    try:
        if rep_id not in REP_BY_ID:
            return {"error": f"unknown rep_id {rep_id!r}; call list_reps for valid ids"}
        terr = next(t for t in DEFAULT_PLAN.territories if t.rep_id == rep_id)
        return views.territory_detail(terr, REP_BY_ID[rep_id], ACC_BY_ID)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def coverage_gaps() -> dict:
    """Only the under-covered territories (coverage_ratio < 1), worst first.

    Each carries the gap size (required − available pipeline, MRR), the quota that
    would make coverage 1.0, and the top levers to close it. The roll-up for
    "where are my problems". Coverage is adequacy/risk, not an attainment guarantee.
    """
    try:
        gaps = []
        for t in waterfall.under_covered(DEFAULT_PLAN.territories):
            row = views.territory_row(t, REP_BY_ID[t.rep_id])
            gaps.append(
                {
                    "rep_id": row["rep_id"],
                    "rep_name": row["rep_name"],
                    "segment_focus": row["segment_focus"],
                    "quota": row["quota"],
                    "coverage_ratio": row["coverage_ratio"],
                    **views._gap_view(t),
                }
            )
        return {
            "units": config.UNITS,
            "company_target": round(DEFAULT_PLAN.company_target),
            "n_under_covered": len(gaps),
            "gaps": gaps,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_weights(potential_weight: float, geo_weight: float, whitespace_weight: float) -> dict:
    """Re-carve with new balance weights (auto-normalized) and DIFF vs. the default.

    Returns the change in within-segment balance and geo compactness, the change
    in # under-covered, and which reps gained/lost the most potential (MRR).
    Powers "what happens if I prioritize geography over potential".
    """
    try:
        plan = _plan(potential_weight, geo_weight, whitespace_weight)
        base_pot = {t.rep_id: t.potential for t in DEFAULT_PLAN.territories}
        deltas = [
            {
                "rep_id": t.rep_id,
                "rep_name": REP_BY_ID[t.rep_id].name,
                "delta_potential": round(t.potential - base_pot.get(t.rep_id, 0.0)),
                "potential": round(t.potential),
            }
            for t in plan.territories
        ]
        moved = sorted(deltas, key=lambda x: x["delta_potential"])
        base_sc, new_sc = DEFAULT_PLAN.scorecard, plan.scorecard
        return {
            "units": config.UNITS,
            "weights_used": plan.settings["weights"],
            "within_segment_cov": {
                "default": round(_avg(base_sc["per_segment_potential_cov"]["optimized"]), 4),
                "whatif": round(_avg(new_sc["per_segment_potential_cov"]["optimized"]), 4),
            },
            "off_home_share": {
                "default": round(base_sc["off_home_share"]["optimized"], 3),
                "whatif": round(new_sc["off_home_share"]["optimized"], 3),
            },
            "n_under_covered": {
                "default": DEFAULT_PLAN.n_under_covered,
                "whatif": plan.n_under_covered,
            },
            "reps_with_potential_change": sum(1 for d in deltas if abs(d["delta_potential"]) > 0.5),
            "top_gainers": list(reversed(moved[-3:])),
            "top_losers": moved[:3],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_conversions(overrides: dict) -> dict:
    """Re-run the waterfall with conversion / deal-size overrides and report flips.

    `overrides` is layered rep > segment > global, e.g.
    ``{"segment": {"Enterprise": {"Negotiation->Won": 0.25}}}`` or
    ``{"rep": {"R-104": {"avg_deal_size": 15000}}}``. Returns which territories
    flip covered↔under-covered and each territory's coverage_ratio delta vs. the
    default plan. Powers "if enterprise win-rates drop to 25%, who breaks".
    """
    try:
        if not isinstance(overrides, dict):
            return {
                "error": "overrides must be an object, "
                "e.g. {'segment': {'Enterprise': {'Negotiation->Won': 0.25}}}"
            }
        plan = _plan(overrides=overrides)
        base = {t.rep_id: t for t in DEFAULT_PLAN.territories}
        to_under, to_covered, deltas = [], [], []
        for t in plan.territories:
            b = base.get(t.rep_id)
            if b is None or t.coverage_ratio is None or b.coverage_ratio is None:
                continue
            deltas.append(
                {
                    "rep_id": t.rep_id,
                    "rep_name": REP_BY_ID[t.rep_id].name,
                    "coverage_default": round(b.coverage_ratio, 3),
                    "coverage_whatif": round(t.coverage_ratio, 3),
                    "delta": round(t.coverage_ratio - b.coverage_ratio, 3),
                }
            )
            if not b.under_covered and t.under_covered:
                to_under.append(t.rep_id)
            if b.under_covered and not t.under_covered:
                to_covered.append(t.rep_id)
        deltas.sort(key=lambda x: x["delta"])
        return {
            "units": config.UNITS,
            "n_under_covered": {
                "default": DEFAULT_PLAN.n_under_covered,
                "whatif": plan.n_under_covered,
            },
            "flipped_to_under_covered": to_under,
            "flipped_to_covered": to_covered,
            "coverage_deltas": deltas,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_levels(level_multipliers: dict) -> dict:
    """Re-derive quotas with new AE-level quota multipliers and DIFF vs. the default.

    `level_multipliers` maps a seniority level to its quota-load multiplier, e.g.
    ``{"ramping": 0.5, "Sr. Strategic AE": 1.4}``. Valid levels: ramping, AE,
    Sr. AE, Sr. Strategic AE (call list_reps for the defaults + who sits where).
    Quota is proportional to potential × the rep's multiplier, re-normalized to the
    same company target — so raising one level's load lowers everyone else's.
    Returns each rep's quota + coverage change and any covered↔under-covered flips.
    Powers "if we load Sr. Strategic AEs 40% heavier, who runs short on pipeline".
    """
    try:
        if not isinstance(level_multipliers, dict) or not level_multipliers:
            return {
                "error": "level_multipliers must be a non-empty object, "
                "e.g. {'Sr. Strategic AE': 1.4}"
            }
        unknown = [lvl for lvl in level_multipliers if lvl not in config.LEVEL_QUOTA_MULTIPLIER]
        if unknown:
            return {"error": f"unknown level(s) {unknown}; valid: {config.AE_LEVELS}"}
        plan = _plan(level_multipliers=level_multipliers)
        base = {t.rep_id: t for t in DEFAULT_PLAN.territories}
        to_under, to_covered, deltas = [], [], []
        for t in plan.territories:
            b = base.get(t.rep_id)
            if b is None:
                continue
            deltas.append(
                {
                    "rep_id": t.rep_id,
                    "rep_name": REP_BY_ID[t.rep_id].name,
                    "level": REP_BY_ID[t.rep_id].level,
                    "quota_default": round(b.quota or 0),
                    "quota_whatif": round(t.quota or 0),
                    "delta_quota": round((t.quota or 0) - (b.quota or 0)),
                    "coverage_default": (
                        round(b.coverage_ratio, 3) if b.coverage_ratio is not None else None
                    ),
                    "coverage_whatif": (
                        round(t.coverage_ratio, 3) if t.coverage_ratio is not None else None
                    ),
                }
            )
            if not b.under_covered and t.under_covered:
                to_under.append(t.rep_id)
            if b.under_covered and not t.under_covered:
                to_covered.append(t.rep_id)
        deltas.sort(key=lambda x: x["delta_quota"])
        return {
            "units": config.UNITS,
            "level_multipliers_used": plan.settings["level_multipliers"],
            "n_under_covered": {
                "default": DEFAULT_PLAN.n_under_covered,
                "whatif": plan.n_under_covered,
            },
            "flipped_to_under_covered": to_under,
            "flipped_to_covered": to_covered,
            "quota_deltas": deltas,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def comp_scenario(attainment: float | None = None) -> dict:
    """Comp outputs for the default plan (quarterly MRR).

    With an `attainment` (e.g. 0.85): total comp, cost-of-sale, and the per-rep
    payout for the top/bottom few. With no attainment: the default scenario-compare
    table (0.85 / 1.0 / 1.10). Powers "what does this plan cost us at 85%
    attainment".
    """
    try:
        if attainment is None:
            return {
                "units": config.UNITS,
                "scenarios": comp.scenario_compare(DEFAULT_PLAN.territories),
            }
        sim = comp.simulate(DEFAULT_PLAN.territories, float(attainment))
        ranked = sorted(sim["per_rep"], key=lambda r: r["total_comp"], reverse=True)

        def fmt(r):
            return {
                "rep_id": r["rep_id"],
                "rep_name": REP_BY_ID[r["rep_id"]].name,
                "quota": round(r["quota"]),
                "bookings": round(r["bookings"]),
                "total_comp": round(r["total_comp"]),
            }

        return {
            "units": config.UNITS,
            "attainment": float(attainment),
            "total_comp": round(sim["total_comp"]),
            "total_bookings": round(sim["total_bookings"]),
            "cost_of_sale": sim["cost_of_sale"],
            "top_earners": [fmt(r) for r in ranked[:3]],
            "bottom_earners": [fmt(r) for r in ranked[-3:]],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_scorecard() -> dict:
    """The baseline-vs-optimized eval for the default plan (+ a markdown table).

    Within-segment balance, geo compactness, whitespace, the whole-team CoV floor,
    and coverage flips — so you can caveat/justify the optimization honestly.
    """
    try:
        return {
            "scorecard": DEFAULT_PLAN.scorecard,
            "markdown": evaluate.scorecard_markdown(DEFAULT_PLAN.scorecard),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_reps() -> dict:
    """Valid rep ids + metadata (name, segment_focus, home_region/metro, tenure,
    ramp_status, level) — discovery for the other tools."""
    try:
        return {
            "levels": config.AE_LEVELS,
            "level_multipliers": dict(config.LEVEL_QUOTA_MULTIPLIER),
            "reps": [
                {
                    "rep_id": r.rep_id,
                    "name": r.name,
                    "segment_focus": r.segment_focus,
                    "home_region": r.home_region,
                    "home_metro": r.home_metro,
                    "tenure_months": r.tenure_months,
                    "ramp_status": r.ramp_status,
                    "level": r.level,
                }
                for r in REPS
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_segments() -> dict:
    """Valid segments + their default conversion rates and avg deal size (MRR) from
    conversions.csv — the global-tier defaults the override hierarchy falls back to."""
    try:
        return {
            "units": config.UNITS,
            "segments": {seg: CONVERSIONS[seg] for seg in sorted(CONVERSIONS)},
        }
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------
# Transport
# ----------------------------------------------------------------------
def _http_app():
    """The streamable-HTTP ASGI app wrapped with optional bearer auth."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    token = os.environ.get("MCP_AUTH_TOKEN")
    app = mcp.streamable_http_app()

    class BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if token and request.headers.get("authorization", "") != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(BearerAuth)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Territory & Quota Designer MCP server")
    ap.add_argument(
        "--http", action="store_true", help="serve over streamable HTTP instead of stdio"
    )
    args, _ = ap.parse_known_args()

    if args.http or os.environ.get("MCP_TRANSPORT", "").lower() == "http":
        import uvicorn

        port = int(os.environ.get("PORT", "8000"))
        mcp.settings.host, mcp.settings.port = "0.0.0.0", port
        uvicorn.run(_http_app(), host="0.0.0.0", port=port)
    else:
        mcp.run()  # stdio (the default)


if __name__ == "__main__":
    main()
