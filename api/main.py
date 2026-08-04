"""
api/main.py — FastAPI app exposing the four-stage engine.

One endpoint per stage plus a combined `/plan` (what the dashboard hits on every
slider change). Data is loaded once at startup and held in memory; the endpoints
are thin, stateless wrappers over `core` — every call recomputes from a settings
payload. Numbers come from `core`; JSON is coerced to built-ins via `core.views`.
The optional `/explain` is the only endpoint that can touch the Anthropic API,
and it degrades cleanly with no key.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
import narrative
from core import comp, evaluate, quota, views, waterfall
from core.dataio import load_all
from core.plan import PlanSettings, run_plan

app = FastAPI(title="Territory & Quota Designer", version="0.1.0")
_STATIC = Path(__file__).parent / "static"

ACCOUNTS, REPS, CONVERSIONS = load_all()
REP_BY_ID = {r.rep_id: r for r in REPS}
ACC_BY_ID = {a.account_id: a for a in ACCOUNTS}


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------
class PlanRequest(BaseModel):
    """Every knob the dashboard can change; all optional (fall back to config)."""

    weights: dict | None = None
    potential_mix: dict | None = None
    company_target: float | None = None
    respect_segment_focus: bool | None = None
    max_accounts_per_rep: int | None = None
    overrides: dict = Field(default_factory=dict)
    comp: dict | None = None
    attainment: float = 1.0
    attainment_scenarios: list | None = None

    def to_settings(self) -> PlanSettings:
        return PlanSettings(**self.model_dump())


class ExplainRequest(BaseModel):
    kind: str = "plan"
    payload: dict
    question: str | None = None


def _plan(req: PlanRequest):
    return run_plan(ACCOUNTS, REPS, CONVERSIONS, req.to_settings())


# ----------------------------------------------------------------------
# Root / health (so the base URL and platform probes return 200, not 404)
# ----------------------------------------------------------------------
@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def dashboard():
    """The interactive dashboard (self-contained HTML served same-origin)."""
    return FileResponse(_STATIC / "index.html")


@app.get("/api")
def api_index():
    """JSON index — the service description + endpoint map (also see /docs)."""
    return {
        "service": "Territory & Quota Designer",
        "description": "Balance territories, derive quotas, prove coverage via a "
        "reverse waterfall, and model comp — deterministic core, human-in-the-loop LLM.",
        "units": config.UNITS,
        "docs": "/docs",
        "dashboard": "/",
        "endpoints": [
            "/data/summary",
            "/balance",
            "/quota",
            "/waterfall",
            "/comp",
            "/plan",
            "/territory/{rep_id}",
            "/explain",
        ],
    }


@app.get("/health")
def health():
    """Liveness probe for the platform health check."""
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@app.get("/data/summary")
def data_summary():
    """Counts, total addressable potential, and segment/region mix."""
    from collections import Counter

    seg = Counter(a.segment for a in ACCOUNTS)
    region = Counter(a.region for a in ACCOUNTS)
    return {
        "units": config.UNITS,
        "n_accounts": len(ACCOUNTS),
        "n_reps": len(REPS),
        "segments": dict(seg),
        "regions": dict(region),
        "total_whitespace_mrr": round(sum(a.whitespace_potential for a in ACCOUNTS)),
        "total_open_pipeline_mrr": round(sum(a.open_pipeline for a in ACCOUNTS)),
        "total_current_mrr": round(sum(a.current_arr for a in ACCOUNTS)),
    }


@app.post("/balance")
def balance_endpoint(req: PlanRequest):
    """Stage 1 — territories + balance scores for the given weights."""
    plan = _plan(req)
    sc = plan.scorecard
    return {
        "territories": [
            {
                "rep_id": t.rep_id,
                "rep_name": REP_BY_ID[t.rep_id].name,
                "segment_focus": REP_BY_ID[t.rep_id].segment_focus,
                "account_count": t.account_count,
                "potential": round(t.potential),
                "whitespace": round(t.whitespace),
                "geo_spread": t.geo_spread,
            }
            for t in plan.territories
        ],
        "balance_score": plan.balance_score,
        "baseline_balance_score": plan.baseline_balance_score,
        "off_home_share": sc["off_home_share"],
        "within_segment_potential_cov": sc["per_segment_potential_cov"],
    }


@app.post("/quota")
def quota_endpoint(req: PlanRequest):
    """Stage 2 — quotas + fairness for the given company target."""
    plan = _plan(req)
    return {
        "company_target": round(plan.company_target),
        "territories": [
            {
                "rep_id": t.rep_id,
                "rep_name": REP_BY_ID[t.rep_id].name,
                "potential": round(t.potential),
                "quota": round(t.quota),
                "quota_to_potential": t.quota_to_potential,
                "fairness": t.fairness,
            }
            for t in plan.territories
        ],
        "fairness_summary": quota.fairness_summary(plan.territories),
    }


@app.post("/waterfall")
def waterfall_endpoint(req: PlanRequest):
    """Stage 3 — coverage results + under-covered roll-up."""
    plan = _plan(req)
    return {
        "company_target": round(plan.company_target),
        "n_under_covered": plan.n_under_covered,
        "territories": views.list_rows(plan, REPS, sort_by="coverage_ratio", limit=len(REPS)),
        "coverage_gaps": [
            {**views.territory_row(t, REP_BY_ID[t.rep_id]), "gap": waterfall.gap_analysis(t)}
            for t in waterfall.under_covered(plan.territories)
        ],
        "standard_coverage": waterfall.standard_coverage_flags(plan.territories),
    }


@app.post("/comp")
def comp_endpoint(req: PlanRequest):
    """Stage 4 — payouts, cost-of-sale, scenario compare, and a payout curve."""
    plan = _plan(req)
    sim = comp.simulate(plan.territories, req.attainment, req.comp)
    scenarios = comp.scenario_compare(
        plan.territories, req.attainment_scenarios or config.ATTAINMENT_SCENARIOS, req.comp
    )
    sample_quota = plan.company_target / max(len(plan.territories), 1)
    return {
        "at_attainment": req.attainment,
        "total_comp": round(sim["total_comp"]),
        "total_bookings": round(sim["total_bookings"]),
        "cost_of_sale": sim["cost_of_sale"],
        "per_rep": [
            {
                "rep_id": r["rep_id"],
                "rep_name": REP_BY_ID[r["rep_id"]].name,
                "quota": round(r["quota"]),
                "total_comp": round(r["total_comp"]),
            }
            for r in sim["per_rep"]
        ],
        "scenarios": scenarios,
        "payout_curve": comp.payout_curve(sample_quota, req.comp),
    }


@app.post("/plan")
def plan_endpoint(req: PlanRequest):
    """Run the whole chain from one settings payload (the dashboard's hot path)."""
    plan = _plan(req)
    return {
        "summary": views.plan_summary(plan),
        "scorecard": plan.scorecard,
        "scorecard_markdown": evaluate.scorecard_markdown(plan.scorecard),
        "territories": views.list_rows(plan, REPS, sort_by="coverage_ratio", limit=len(REPS)),
        "comp": comp.scenario_compare(plan.territories, req.attainment_scenarios, req.comp),
    }


@app.get("/territory/{rep_id}")
def territory_detail(rep_id: str):
    """Full single-territory view (default plan) — the `assess_territory` shape."""
    if rep_id not in REP_BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown rep_id {rep_id!r}")
    plan = run_plan(ACCOUNTS, REPS, CONVERSIONS)
    terr = next(t for t in plan.territories if t.rep_id == rep_id)
    return views.territory_detail(terr, REP_BY_ID[rep_id], ACC_BY_ID)


@app.post("/territory/{rep_id}")
def territory_detail_for_settings(rep_id: str, req: PlanRequest):
    """Full single-territory view under the given settings (dashboard funnel drill-in)."""
    if rep_id not in REP_BY_ID:
        raise HTTPException(status_code=404, detail=f"unknown rep_id {rep_id!r}")
    plan = _plan(req)
    terr = next(t for t in plan.territories if t.rep_id == rep_id)
    return views.territory_detail(terr, REP_BY_ID[rep_id], ACC_BY_ID)


@app.post("/explain")
def explain_endpoint(req: ExplainRequest):
    """Optional plain-English rationale (Anthropic API); skips cleanly with no key."""
    return narrative.explain(req.kind, req.payload, req.question)
