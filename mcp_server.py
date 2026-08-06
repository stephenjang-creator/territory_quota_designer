"""
mcp_server.py — expose the Sales Plan Designer as an MCP server.

Thin, READ-ONLY wrappers over the deterministic core (`core.balance / quota /
waterfall / comp / evaluate`, reshaped through `core.views`). An agent can
interrogate a carve conversationally — under-covered territories, what-if weight
changes, conversion-rate stress tests, comp scenarios — and the core owns every
number; these tools only reshape and diff.

Contract: JSON-safe returns (plain built-ins), errors as ``{"error": ...}`` never
raised, small roll-ups only (never the 800-account dump), zero LLM calls, nothing
persists — what-if tools recompute in memory. All $ are USD ACV; quota is a
quarterly bookings target (annual quota = 4-6x OTE, / 4); see `config.UNITS`.

Transport: stdio by default; HTTP behind ``MCP_TRANSPORT=http`` / ``--http``,
bound to ``0.0.0.0:$PORT`` with ``MCP_AUTH_TOKEN`` bearer auth for hosted use.
The CSV dir comes from ``$TERRITORY_DATA`` (default ``data``).
"""

from __future__ import annotations

import argparse
import os

from mcp.server.fastmcp import FastMCP

import config
from core import comp, evaluate, quota, recommend, views
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
    "pipeline_coverage",
    "coverage_ratio",
    "potential",
    "quota",
    "quota_to_potential",
    "ote",
    "account_count",
    "whitespace",
    "geo_spread",
    "rep_id",
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _plan(
    quota_to_ote=None,
    coverage_target=None,
    ote_overrides=None,
    overrides=None,
    added_reps=None,
    segment_overrides=None,
    account_retags=None,
):
    """The default plan when nothing is overridden, else a fresh in-memory re-run."""
    if (
        quota_to_ote is None
        and coverage_target is None
        and not ote_overrides
        and not overrides
        and not added_reps
        and not segment_overrides
        and not account_retags
    ):
        return DEFAULT_PLAN
    return run_plan(
        ACCOUNTS,
        REPS,
        CONVERSIONS,
        PlanSettings(
            quota_to_ote=quota_to_ote,
            coverage_target=coverage_target,
            ote_overrides=ote_overrides or {},
            overrides=overrides or {},
            added_reps=added_reps or [],
            segment_overrides=segment_overrides or {},
            account_retags=account_retags or {},
        ),
    )


# ----------------------------------------------------------------------
# Tools (docstrings are how the agent selects tools — keep them crisp)
# ----------------------------------------------------------------------
@mcp.tool()
def plan_summary(
    quota_to_ote: float | None = None,
    coverage_target: float | None = None,
) -> dict:
    """Top-line health of a plan — the entry point for "how does this plan look".

    Quota-first: returns the derived company target (sum of standardized quotas),
    how many reps the work-back carve covers to the pipeline-coverage target, the
    coverage floor (worst-covered rep), total capacity gap, per-segment pipeline vs
    required, and cost-of-sale. Omit args for the default plan; pass quota_to_ote
    (quota = this x OTE) and/or coverage_target (pack each book to this x quota).
    """
    try:
        return views.plan_summary(_plan(quota_to_ote, coverage_target))
    except Exception as e:  # never raise across the wire
        return {"error": str(e)}


@mcp.tool()
def list_territories(
    sort_by: str = "pipeline_coverage", ascending: bool = True, limit: int = 15
) -> dict:
    """Compact per-territory rows for the default plan (worst-covered first).

    Each row: rep_id, rep_name, role, ote, account_count, quota, available_pipeline,
    pipeline_coverage (available / quota, target 3x), coverage_ratio (funnel).
    Sort by any of: pipeline_coverage, coverage_ratio, quota, ote,
    quota_to_potential, potential, account_count, whitespace, geo_spread, rep_id.
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
    """Reps whose book can't reach the pipeline-coverage target (available < 3x quota).

    The headline "where are my capacity problems". Each carries the pipeline gap
    (target x quota - available pipeline, USD), the pipeline_coverage multiple, and
    the funnel coverage_ratio. Under standardized quotas a gap is usually a whole
    segment running short on pipeline, not a carve mistake — an assignment can't
    invent pipeline that isn't there.
    """
    try:
        target = DEFAULT_PLAN.scorecard["coverage_target"]
        gaps = []
        for t in DEFAULT_PLAN.territories:
            m = t.pipeline_coverage_multiple
            if m is None or m >= target:
                continue
            row = views.territory_row(t, REP_BY_ID[t.rep_id])
            gaps.append(
                {
                    "rep_id": row["rep_id"],
                    "rep_name": row["rep_name"],
                    "role": row["role"],
                    "quota": row["quota"],
                    "available_pipeline": row["available_pipeline"],
                    "pipeline_coverage": row["pipeline_coverage"],
                    "coverage_ratio": row["coverage_ratio"],
                    "pipeline_gap": round(
                        max(0.0, target * (t.quota or 0) - (t.available_potential or 0))
                    ),
                }
            )
        gaps.sort(key=lambda g: (g["pipeline_coverage"] is None, g["pipeline_coverage"]))
        return {
            "units": config.UNITS,
            "coverage_target": target,
            "company_target": round(DEFAULT_PLAN.company_target),
            "n_below_target": len(gaps),
            "gaps": gaps,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_ote(segment: str, level: str, ote: float) -> dict:
    """Re-price one role's OTE and DIFF vs. the default (annual quota = quota_to_ote x OTE).

    Every rep in that (segment, level) role gets the new standardized quota; the
    derived company target and each affected rep's pipeline coverage move with it.
    Valid segments: call list_segments; levels: ramping / AE / Sr. AE / Sr. Strategic
    AE. Powers "if we lift Enterprise AE OTE, what do quota and coverage become".
    """
    try:
        if segment not in config.SEGMENT_OTE:
            return {"error": f"unknown segment {segment!r}; valid: {sorted(config.SEGMENT_OTE)}"}
        if level not in config.AE_LEVELS:
            return {"error": f"unknown level {level!r}; valid: {config.AE_LEVELS}"}
        plan = _plan(ote_overrides={segment: {level: float(ote)}})
        base = {t.rep_id: t for t in DEFAULT_PLAN.territories}
        affected = []
        for t in plan.territories:
            rep = REP_BY_ID[t.rep_id]
            if rep.segment_focus == segment and rep.level == level:
                b = base[t.rep_id]
                affected.append(
                    {
                        "rep_id": t.rep_id,
                        "rep_name": rep.name,
                        "quota_default": round(b.quota or 0),
                        "quota_whatif": round(t.quota or 0),
                        "pipeline_coverage_default": b.pipeline_coverage_multiple,
                        "pipeline_coverage_whatif": t.pipeline_coverage_multiple,
                    }
                )
        return {
            "units": config.UNITS,
            "role": f"{segment} · {level}",
            "ote": float(ote),
            "company_target": {
                "default": round(DEFAULT_PLAN.company_target),
                "whatif": round(plan.company_target),
            },
            "reps_covered": {
                "default": DEFAULT_PLAN.scorecard["reps_covered"]["optimized"],
                "whatif": plan.scorecard["reps_covered"]["optimized"],
                "of": plan.scorecard["reps_covered"]["of"],
            },
            "affected_reps": affected,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_hire(segment: str, level: str, count: int = 1, name: str = "TBH") -> dict:
    """Add `count` planned hires at a (segment, level) role and DIFF vs. the default plan.

    Each hire carries that role's standardized quota, and the carve pulls pipeline
    from its segment — so this answers "which level can I hire without dropping a
    segment below the coverage target". Returns the company-target delta, reps
    covered before/after, the coverage floor, and that segment's pipeline vs.
    required. Valid segments: call list_segments; levels: ramping / AE / Sr. AE /
    Sr. Strategic AE. Use 'TBH' as the name for an open req.
    """
    try:
        if segment not in config.SEGMENT_OTE:
            return {"error": f"unknown segment {segment!r}; valid: {sorted(config.SEGMENT_OTE)}"}
        if level not in config.AE_LEVELS:
            return {"error": f"unknown level {level!r}; valid: {config.AE_LEVELS}"}
        n = max(1, int(count))
        added = [{"name": name, "segment_focus": segment, "level": level} for _ in range(n)]
        plan = _plan(added_reps=added)
        base = DEFAULT_PLAN
        seg_cap = plan.scorecard["per_segment_capacity"].get(segment, {})
        base_cap = base.scorecard["per_segment_capacity"].get(segment, {})
        return {
            "units": config.UNITS,
            "role": f"{segment} · {level}",
            "hires_added": n,
            "company_target": {
                "default": round(base.company_target),
                "whatif": round(plan.company_target),
            },
            "reps_covered": {
                "default": base.scorecard["reps_covered"]["optimized"],
                "whatif": plan.scorecard["reps_covered"]["optimized"],
                "of": plan.scorecard["reps_covered"]["of"],
            },
            "coverage_floor": {
                "default": base.scorecard["coverage_floor"]["optimized"],
                "whatif": plan.scorecard["coverage_floor"]["optimized"],
            },
            "segment_capacity": {
                "segment": segment,
                "available_pipeline": round(seg_cap.get("available_pipeline", 0)),
                "required_default": round(base_cap.get("required_pipeline", 0)),
                "required_whatif": round(seg_cap.get("required_pipeline", 0)),
                "coverable_whatif": seg_cap.get("coverable"),
            },
            "added_reps": [
                {
                    "rep_id": t.rep_id,
                    "quota": round(t.quota or 0),
                    "pipeline_coverage": t.pipeline_coverage_multiple,
                }
                for t in plan.territories
                if t.rep_id.startswith("NEW-")
            ],
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
def whatif_coverage(coverage_target: float) -> dict:
    """Re-carve to a different pipeline-coverage target and DIFF who clears it.

    Raising the target (e.g. 4x or 5x) demands more pipeline per rep, so more reps
    fall short — usually in the thinnest-pipeline segment, which an assignment can't
    rescue. Returns reps covered, the coverage floor (worst rep), and the total
    capacity gap vs. the default 3x. Powers "if we require 5x pipeline coverage, how
    many reps come up short".
    """
    try:
        target = float(coverage_target)
        if target <= 0:
            return {"error": "coverage_target must be > 0"}
        plan = _plan(coverage_target=target)
        b, w = DEFAULT_PLAN.scorecard, plan.scorecard
        below = [
            {
                "rep_id": t.rep_id,
                "rep_name": REP_BY_ID[t.rep_id].name,
                "role": f"{REP_BY_ID[t.rep_id].segment_focus} · {REP_BY_ID[t.rep_id].level}",
                "pipeline_coverage": t.pipeline_coverage_multiple,
            }
            for t in plan.territories
            if t.pipeline_coverage_multiple is not None and t.pipeline_coverage_multiple < target
        ]
        below.sort(key=lambda x: x["pipeline_coverage"])
        return {
            "units": config.UNITS,
            "coverage_target": {"default": b["coverage_target"], "whatif": target},
            "reps_covered": {
                "default": b["reps_covered"]["optimized"],
                "whatif": w["reps_covered"]["optimized"],
                "of": b["reps_covered"]["of"],
            },
            "coverage_floor": {
                "default": round(b["coverage_floor"]["optimized"], 2),
                "whatif": round(w["coverage_floor"]["optimized"], 2),
            },
            "capacity_gap": {
                "default": round(b["capacity_gap"]["optimized"]),
                "whatif": round(w["capacity_gap"]["optimized"]),
            },
            "below_target": below,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def comp_scenario(attainment: float | None = None) -> dict:
    """Comp outputs for the default plan (annual comp + annualized bookings, USD).

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
    """The capacity scorecard for the default plan (+ a markdown table).

    Work-back carve vs. a naive equal-count carve under the same standardized quotas:
    total capacity gap, the coverage floor (worst-covered rep), reps covered to the
    target, and per-segment pipeline vs. required — so you can justify/caveat honestly.
    """
    try:
        return {
            "scorecard": DEFAULT_PLAN.scorecard,
            "markdown": evaluate.scorecard_markdown(DEFAULT_PLAN.scorecard),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def recommend_actions(
    quota_to_ote: float | None = None, coverage_target: float | None = None
) -> dict:
    """Recommended actions to RESOLVE the plan's issues — each lever carries an
    applyable settings delta you can merge and re-plan.

    Categories: pipeline (a short segment's fixes — re-tag surplus accounts into it,
    lower its quota multiple, or accept a lower coverage target), hiring (a safe hire
    plan for the segments with headroom), comp (auto-tune to a cost-of-sale ceiling),
    sensitivity (a global target/multiple at which every rep clears). Omit args for
    the default plan. Powers "what should I do about the SMB gap / who can I hire".
    """
    try:
        plan = _plan(quota_to_ote, coverage_target)
        settings = PlanSettings(quota_to_ote=quota_to_ote, coverage_target=coverage_target)
        recs = recommend.build_recommendations(ACCOUNTS, REPS, CONVERSIONS, settings, plan=plan)
        return {"units": config.UNITS, "count": len(recs), "recommendations": recs}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def whatif_segment_override(
    segment: str,
    quota_to_ote: float | None = None,
    coverage_target: float | None = None,
) -> dict:
    """Lower ONE segment's quota multiple and/or accept a per-segment coverage target,
    then DIFF vs. the default — the applyable fix for a capacity-short segment.

    Returns whether the segment becomes coverable, the company-target change, and reps
    covered before/after. Valid segments: call list_segments. Pass at least one of
    quota_to_ote / coverage_target. Powers "if I cut SMB's quota, does SMB cover?".
    """
    try:
        if segment not in config.SEGMENT_OTE:
            return {"error": f"unknown segment {segment!r}; valid: {sorted(config.SEGMENT_OTE)}"}
        ov: dict = {}
        if quota_to_ote is not None:
            ov["quota_to_ote"] = float(quota_to_ote)
        if coverage_target is not None:
            ov["coverage_target"] = float(coverage_target)
        if not ov:
            return {"error": "pass quota_to_ote and/or coverage_target"}
        plan = _plan(segment_overrides={segment: ov})
        base = DEFAULT_PLAN
        sc, bc = plan.scorecard, base.scorecard
        return {
            "units": config.UNITS,
            "segment": segment,
            "override": ov,
            "coverable": {
                "default": bc["per_segment_capacity"][segment]["coverable"],
                "whatif": sc["per_segment_capacity"][segment]["coverable"],
            },
            "company_target": {
                "default": round(base.company_target),
                "whatif": round(plan.company_target),
            },
            "reps_covered": {
                "default": bc["reps_covered"]["optimized"],
                "whatif": sc["reps_covered"]["optimized"],
                "of": sc["reps_covered"]["of"],
            },
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def autotune_comp(target_cos: float = 0.30, at_attainment: float = 0.85) -> dict:
    """Tune the comp curve to hold cost-of-sale <= target_cos at a stress attainment.

    Because base pay is fixed, cost-of-sale spikes when the team misses; this harshens
    the decelerator (then trims the base split) to cap it. Returns the applyable `comp`
    delta, the achieved cost-of-sale, and feasibility. Powers "keep cost of sale under
    30% even at 85% attainment".
    """
    try:
        res = comp.autotune_comp(DEFAULT_PLAN.territories, float(target_cos), float(at_attainment))
        return {"units": config.UNITS, **res}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_reps() -> dict:
    """Valid rep ids + metadata (name, role = segment x level, home region, tenure)
    plus each rep's standardized OTE and quota — discovery for the other tools."""
    try:
        quotas = quota.standardized_quotas(REPS)
        otes = quota.resolve_ote(REPS)
        return {
            "levels": config.AE_LEVELS,
            "quota_to_ote": config.QUOTA_TO_OTE,
            "reps": [
                {
                    "rep_id": r.rep_id,
                    "name": r.name,
                    "segment_focus": r.segment_focus,
                    "level": r.level,
                    "role": f"{r.segment_focus} · {r.level}",
                    "home_region": r.home_region,
                    "home_metro": r.home_metro,
                    "tenure_months": r.tenure_months,
                    "ote": round(otes[r.rep_id]),
                    "quota": round(quotas[r.rep_id]),
                }
                for r in REPS
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_segments() -> dict:
    """Valid segments + their default conversion rates and avg deal size (ACV) from
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
    ap = argparse.ArgumentParser(description="Sales Plan Designer MCP server")
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
