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
from core.plan import PlanSettings, merge_added_reps, run_plan

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

    ote_overrides: dict = Field(default_factory=dict)  # {segment: {level: ote}}
    quota_to_ote: float | None = None
    coverage_target: float | None = None
    respect_segment_focus: bool | None = None
    prefer_home_region: bool | None = None
    overrides: dict = Field(default_factory=dict)  # conversion overrides
    comp: dict | None = None
    attainment: float = 1.0
    attainment_scenarios: list | None = None
    added_reps: list = Field(default_factory=list)  # what-if hires [{name, segment, level}]

    def to_settings(self) -> PlanSettings:
        return PlanSettings(**self.model_dump())


class ExplainRequest(BaseModel):
    kind: str = "plan"
    payload: dict
    question: str | None = None


def _plan(req: PlanRequest):
    return run_plan(ACCOUNTS, REPS, CONVERSIONS, req.to_settings())


def _reps_for(req: PlanRequest) -> list:
    """The ORIGINAL roster plus this request's what-if hires (materialized Reps)."""
    return merge_added_reps(REPS, req.added_reps)


def _rep_lookup(req: PlanRequest) -> dict:
    """rep_id -> Rep including added ('NEW-*') hires, so row-rendering endpoints resolve them."""
    return {r.rep_id: r for r in _reps_for(req)}


def _sample_ote_quota(plan):
    """A representative (OTE, quota) for the 'average rep' payout curve."""
    n = max(len(plan.territories), 1)
    ote = sum(t.ote or 0 for t in plan.territories) / n
    q = sum(t.quota or 0 for t in plan.territories) / n
    return ote, q


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
            "/conversions",
            "/roles",
            "/comp/defaults",
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


@app.get("/conversions")
def conversions_defaults():
    """The global-default conversion rates + avg deal size per segment.

    Read straight from the loaded conversions.csv (the `global` tier of the
    override hierarchy). The dashboard uses this to pre-fill its editable
    override panel, so the inputs always start from the real data rather than
    hardcoded numbers.
    """
    from core.dataio import AVG_DEAL_KEY, TRANSITIONS

    # Order segments high-to-low by deal size (Enterprise, Mid-Market, SMB).
    segments = sorted(CONVERSIONS, key=lambda s: -CONVERSIONS[s][AVG_DEAL_KEY])
    return {
        "units": config.UNITS,
        "transitions": TRANSITIONS,
        "avg_deal_key": AVG_DEAL_KEY,
        "segments": segments,
        "defaults": {s: dict(CONVERSIONS[s]) for s in segments},
    }


@app.get("/comp/defaults")
def comp_defaults():
    """Default compensation-plan parameters (base/variable split, commission rate,
    decelerator + accelerator thresholds/multipliers, cap). The dashboard pre-fills
    its editable comp panel from this; POST them back on /plan or /comp as `comp`.
    """
    return {
        "defaults": comp.resolved_params(),
        "attainment_scenarios": config.ATTAINMENT_SCENARIOS,
        "note": "Variable pay is commission on bookings on a three-band curve: a "
        "reduced rate below the decelerator threshold, the standard rate up to the "
        "accelerator threshold, then the accelerated rate above it (optionally capped).",
    }


@app.get("/roles")
def role_defaults():
    """Default OTE + standardized quota per role (segment x level), plus the quota
    multiple and coverage target. The dashboard pre-fills its editable OTE-by-role
    panel from this; every rep in a role carries the same quota. `quota` is the
    QUARTERLY target (= quota_to_ote x OTE / 4); `annual_quota` is the 4-6x headline.
    """
    from collections import Counter

    ppy = config.QUOTA_PERIODS_PER_YEAR
    counts = Counter((r.segment_focus, r.level) for r in REPS)
    segments = sorted({r.segment_focus for r in REPS}, key=lambda s: -config.SEGMENT_OTE.get(s, 0))
    roles = []
    for seg in segments:
        for lvl in config.AE_LEVELS:
            n = counts.get((seg, lvl), 0)
            if n == 0:
                continue
            ote = quota.role_ote(seg, lvl)
            annual = config.QUOTA_TO_OTE * ote
            roles.append(
                {
                    "segment": seg,
                    "level": lvl,
                    "reps": n,
                    "ote": round(ote),
                    "quota": round(annual / ppy),  # quarterly
                    "annual_quota": round(annual),
                }
            )
    return {
        "units": config.UNITS,
        "segments": segments,
        "levels": config.AE_LEVELS,
        "quota_to_ote": config.QUOTA_TO_OTE,
        "periods_per_year": ppy,
        "coverage_target": config.PIPELINE_COVERAGE_TARGET,
        "roles": roles,
        "note": "Annual quota = quota_to_ote x OTE (norm 4-6x), standardized per role; "
        "the quarterly `quota` shown = annual / 4. Edit OTE per role; the company "
        "target is the sum of quarterly quotas. The carve packs each book to "
        "coverage_target x quota in addressable pipeline.",
    }


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
        "total_whitespace_acv": round(sum(a.whitespace_potential for a in ACCOUNTS)),
        "total_open_pipeline_acv": round(sum(a.open_pipeline for a in ACCOUNTS)),
        "total_current_arr": round(sum(a.current_arr for a in ACCOUNTS)),
    }


@app.post("/balance")
def balance_endpoint(req: PlanRequest):
    """Stage 1 — the work-back carve: books packed to the coverage target + capacity."""
    plan = _plan(req)
    rby = _rep_lookup(req)
    sc = plan.scorecard
    return {
        "coverage_target": sc["coverage_target"],
        "reps_covered": sc["reps_covered"],
        "capacity_gap": sc["capacity_gap"],
        "off_home_share": sc["off_home_share"],
        "per_segment_capacity": sc["per_segment_capacity"],
        "territories": [
            {
                "rep_id": t.rep_id,
                "rep_name": rby[t.rep_id].name,
                "segment_focus": rby[t.rep_id].segment_focus,
                "level": rby[t.rep_id].level,
                "account_count": t.account_count,
                "available_pipeline": round(t.available_potential or 0),
                "quota": round(t.quota or 0),
                "pipeline_coverage": t.pipeline_coverage_multiple,
                "geo_spread": t.geo_spread,
            }
            for t in plan.territories
        ],
    }


@app.post("/quota")
def quota_endpoint(req: PlanRequest):
    """Stage 2 — standardized quota by role (same role -> same quota), from OTE."""
    plan = _plan(req)
    rby = _rep_lookup(req)
    return {
        "company_target": round(plan.company_target),
        "quota_to_ote": plan.settings["quota_to_ote"],
        "territories": [
            {
                "rep_id": t.rep_id,
                "rep_name": rby[t.rep_id].name,
                "role": f"{rby[t.rep_id].segment_focus} · {rby[t.rep_id].level}",
                "ote": round(t.ote or 0),
                "quota": round(t.quota or 0),
                "quota_to_potential": t.quota_to_potential,
            }
            for t in plan.territories
        ],
    }


@app.post("/waterfall")
def waterfall_endpoint(req: PlanRequest):
    """Stage 3 — coverage results + under-covered roll-up."""
    plan = _plan(req)
    reps = _reps_for(req)
    rby = {r.rep_id: r for r in reps}
    return {
        "company_target": round(plan.company_target),
        "n_under_covered": plan.n_under_covered,
        "territories": views.list_rows(plan, reps, sort_by="coverage_ratio", limit=len(reps)),
        "coverage_gaps": [
            {**views.territory_row(t, rby[t.rep_id]), "gap": waterfall.gap_analysis(t)}
            for t in waterfall.under_covered(plan.territories)
        ],
        "standard_coverage": waterfall.standard_coverage_flags(plan.territories),
    }


@app.post("/comp")
def comp_endpoint(req: PlanRequest):
    """Stage 4 — payouts, cost-of-sale, scenario compare, and a payout curve."""
    plan = _plan(req)
    rby = _rep_lookup(req)
    sim = comp.simulate(plan.territories, req.attainment, req.comp)
    scenarios = comp.scenario_compare(
        plan.territories, req.attainment_scenarios or config.ATTAINMENT_SCENARIOS, req.comp
    )
    sample_ote, sample_quota = _sample_ote_quota(plan)
    return {
        "at_attainment": req.attainment,
        "total_comp": round(sim["total_comp"]),
        "total_bookings": round(sim["total_bookings"]),
        "cost_of_sale": sim["cost_of_sale"],
        "per_rep": [
            {
                "rep_id": r["rep_id"],
                "rep_name": rby[r["rep_id"]].name,
                "ote": round(r["ote"]),
                "quota": round(r["quota"]),
                "total_comp": round(r["total_comp"]),
            }
            for r in sim["per_rep"]
        ],
        "scenarios": scenarios,
        "payout_curve": comp.payout_curve(sample_ote, sample_quota, req.comp),
    }


@app.post("/plan")
def plan_endpoint(req: PlanRequest):
    """Run the whole chain from one settings payload (the dashboard's hot path)."""
    plan = _plan(req)
    reps = _reps_for(req)
    sample_ote, sample_quota = _sample_ote_quota(plan)
    return {
        "summary": views.plan_summary(plan),
        "scorecard": plan.scorecard,
        "scorecard_markdown": evaluate.scorecard_markdown(plan.scorecard),
        "territories": views.list_rows(plan, reps, sort_by="pipeline_coverage", limit=len(reps)),
        "comp": comp.scenario_compare(plan.territories, req.attainment_scenarios, req.comp),
        "comp_params": comp.resolved_params(req.comp),
        "payout_curve": comp.payout_curve(sample_ote, sample_quota, req.comp),
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
    rby = _rep_lookup(req)  # includes this request's what-if hires
    if rep_id not in rby:
        raise HTTPException(status_code=404, detail=f"unknown rep_id {rep_id!r}")
    plan = _plan(req)
    terr = next((t for t in plan.territories if t.rep_id == rep_id), None)
    if terr is None:
        raise HTTPException(status_code=404, detail=f"no territory for rep_id {rep_id!r}")
    return views.territory_detail(terr, rby[rep_id], ACC_BY_ID)


@app.post("/explain")
def explain_endpoint(req: ExplainRequest):
    """Optional plain-English rationale (Anthropic API); skips cleanly with no key."""
    return narrative.explain(req.kind, req.payload, req.question)
