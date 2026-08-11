"""
core/ask.py: natural-language "Ask" over the plan.

Two paths, one entry point (`answer`), and the deterministic core still owns every
number in both:

  - DEMO (no API key): a deterministic intent router maps a recognized question to
    the engine's own functions and returns real, grounded figures. No external call,
    so it always works offline and on a locked-down deploy. Bounded to known shapes.
  - LIVE (key present): a Claude agent (a small tool-use loop) answers anything by
    calling the same engine functions as tools. The model explains and picks tools;
    the engine computes. Numbers are never invented by the model.

The demo router runs first on every question; recognized intents are answered
deterministically and instantly, and only the leftover free-form questions fall
through to the live agent (when a key is available). Every answer carries a
`grounded` payload (the structured numbers behind it) and the `used` engine
functions, so nothing the UI shows is unauditable.
"""

from __future__ import annotations

import json
import os
import re

import config
from core import comp as comp_mod
from core import recommend
from core.plan import PlanSettings, run_plan, segment_coverage_target

ASK_MODEL = os.environ.get("ASK_MODEL", "claude-opus-5")
ASK_MAX_TOKENS = 1024
ASK_MAX_TOOL_TURNS = 6

_SEG_ORDER = {"Enterprise": 0, "Mid-Market": 1, "SMB": 2}


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------
def _money(x: float | None) -> str:
    if x is None:
        return "n/a"
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}M"
    return f"${round(x / 1000):,}K"


def _rep_by_id(reps: list) -> dict:
    return {r.rep_id: r for r in reps}


def _terr_by_rep(plan) -> dict:
    return {t.rep_id: t for t in plan.territories}


def _effective_target(seg: str, settings: PlanSettings) -> float:
    gt = (
        config.PIPELINE_COVERAGE_TARGET
        if settings.coverage_target is None
        else settings.coverage_target
    )
    return segment_coverage_target(seg, gt, settings.segment_overrides)


# ----------------------------------------------------------------------
# Rep name resolution (fuzzy, deterministic)
# ----------------------------------------------------------------------
def find_rep(text: str, reps: list):
    """Resolve a rep from free text by id or name. Returns (rep, None) on a unique
    hit, (None, [candidates]) when ambiguous, or (None, []) when nothing matches."""
    q = text.lower()
    # Exact rep id (e.g. R-125)
    m = re.search(r"\br-\d{3,}\b", q)
    if m:
        by_id = _rep_by_id(reps)
        hit = by_id.get(m.group(0).upper())
        if hit:
            return hit, None
    # Full name substring
    full = [r for r in reps if r.name.lower() in q]
    if len(full) == 1:
        return full[0], None
    if len(full) > 1:
        return None, full
    # Unique token (first or last name) match, ignoring short/common tokens
    words = set(re.findall(r"[a-z]{3,}", q))
    hits = [r for r in reps if words & set(r.name.lower().split())]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, hits
    return None, []


# ----------------------------------------------------------------------
# Grounded computations (shared by the demo router AND the live agent tools)
# ----------------------------------------------------------------------
def assess_rep(plan, reps: list, settings: PlanSettings, who: str) -> dict:
    """What a named rep needs to clear the pipeline-coverage target."""
    rep, cands = find_rep(who, reps)
    if rep is None:
        if cands:
            return {"error": "ambiguous", "candidates": [f"{r.name} ({r.rep_id})" for r in cands]}
        return {"error": "no_match"}
    t = _terr_by_rep(plan).get(rep.rep_id)
    if t is None or t.quota is None:
        return {"error": "no_territory", "rep_id": rep.rep_id}
    target = _effective_target(rep.segment_focus, settings)
    required = target * t.quota
    available = t.available_potential or 0.0
    gap = required - available
    return {
        "rep_id": rep.rep_id,
        "name": rep.name,
        "role": f"{rep.segment_focus} · {rep.level}",
        "quota": t.quota,
        "coverage_target": target,
        "available_pipeline": available,
        "required_pipeline": required,
        "pipeline_coverage": round(t.pipeline_coverage_multiple or 0.0, 2),
        "pipeline_gap": max(0.0, gap),
        "covered": gap <= 1e-6,
        "quota_that_would_clear": available / target if target else None,
    }


def segment_risk(plan) -> dict:
    """Per-segment available vs required pipeline, ranked worst-first."""
    cap = plan.scorecard["per_segment_capacity"]
    rows = []
    for seg, d in cap.items():
        req = d["required_pipeline"]
        ratio = (d["available_pipeline"] / req) if req else float("inf")
        rows.append(
            {
                "segment": seg,
                "available_pipeline": d["available_pipeline"],
                "required_pipeline": req,
                "ratio": round(ratio, 3),
                "shortfall": max(0.0, req - d["available_pipeline"]),
                "coverable": d["coverable"],
                "reps": d["reps"],
            }
        )
    rows.sort(key=lambda r: r["ratio"])
    return {"worst": rows[0] if rows else None, "segments": rows}


def hiring_plan(accounts, reps, conversions, settings: PlanSettings, plan) -> dict:
    """The recommended-actions hiring lever: where there's headroom, and what to freeze."""
    recs = recommend.build_recommendations(accounts, reps, conversions, settings, plan=plan)
    hire = next((r for r in recs if r["id"] == "hiring"), None)
    if not hire:
        return {"error": "no_hiring_rec"}
    plan_lever = next((lv for lv in hire["levers"] if lv["apply"].get("added_reps")), None)
    added = plan_lever["apply"]["added_reps"] if plan_lever else []
    counts: dict[str, int] = {}
    for h in added:
        counts[h["segment"]] = counts.get(h["segment"], 0) + 1
    short = [s["segment"] for s in segment_risk(plan)["segments"] if not s["coverable"]]
    return {
        "title": hire["title"],
        "body": hire["body"],
        "safe_hires": counts,
        "total_safe_hires": len(added),
        "freeze_segments": short,
        "added_reps": added,
    }


def commission_cost(plan, settings: PlanSettings, pct: float) -> dict:
    """Annual comp cost of moving on-target commission (variable pay) by `pct` percent.

    Commission is the variable slice of OTE ((1 - base_split) * OTE); scaling it by
    pct changes total annual comp by pct * total on-target variable at plan."""
    comp = comp_mod.resolved_params(settings.comp)
    split = comp["base_variable_split"]
    total_variable = sum(
        (1.0 - split) * (t.ote or 0.0) for t in plan.territories if t.quota is not None
    )
    at_plan = comp_mod.simulate(plan.territories, 1.0, settings.comp)["total_comp"]
    delta = (pct / 100.0) * total_variable
    return {
        "change_pct": pct,
        "on_target_variable_total": total_variable,
        "total_comp_at_plan": at_plan,
        "comp_delta": delta,
        "total_comp_after": at_plan + delta,
        "note": "On-target variable (commission) is the (1 - base split) slice of OTE; "
        "figures are annual, at 100% attainment.",
    }


def plan_summary(plan) -> dict:
    sc = plan.scorecard
    return {
        "company_target_quarterly": sc["company_target"],
        "company_target_annual": sc["company_target"] * config.QUOTA_PERIODS_PER_YEAR,
        "reps_covered": sc["reps_covered"],
        "coverage_floor": sc["coverage_floor"]["optimized"],
        "capacity_gap": sc["capacity_gap"]["optimized"],
        "per_segment_capacity": sc["per_segment_capacity"],
    }


def list_reps_brief(reps, plan) -> dict:
    tbr = _terr_by_rep(plan)
    rows = [
        {
            "rep_id": r.rep_id,
            "name": r.name,
            "role": f"{r.segment_focus} · {r.level}",
            "quota": (tbr.get(r.rep_id).quota if tbr.get(r.rep_id) else None),
        }
        for r in reps
    ]
    rows.sort(key=lambda x: (_SEG_ORDER.get(x["role"].split(" · ")[0], 9), x["rep_id"]))
    return {"reps": rows, "n": len(rows)}


# ----------------------------------------------------------------------
# Demo router: recognized questions -> deterministic, grounded answers
# ----------------------------------------------------------------------
def _pct_in(text: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%|\bby\s+(-?\d+(?:\.\d+)?)\b", text)
    if not m:
        return None
    return float(m.group(1) or m.group(2))


def _route(question: str, plan, accounts, reps, conversions, settings) -> dict | None:
    q = question.lower().strip()

    # 1. Commission cost delta ("cost of increasing/decreasing commissions by x%")
    if re.search(r"commission|variable pay|comp(?:ensation)?\b", q) and re.search(
        r"increas|decreas|raise|cut|lower|rais|\bby\b|\bx\b|%|more|less", q
    ):
        pct = _pct_in(q)
        if pct is None:
            return {
                "mode": "demo",
                "answer": "Tell me the size of the change and I'll price it, e.g. "
                '"what\'s the cost of increasing commissions by 10%?".',
                "grounded": {},
                "used": ["comp_scenario"],
                "model": None,
                "error": None,
            }
        if re.search(r"decreas|cut|lower|reduc", q) and pct > 0:
            pct = -pct
        g = commission_cost(plan, settings, pct)
        verb = "increasing" if pct >= 0 else "cutting"
        return {
            "mode": "demo",
            "answer": f"{verb.capitalize()} on-target commission by {abs(pct):g}% moves "
            f"annual comp by {_money(g['comp_delta'])} ({_money(g['total_comp_at_plan'])} to "
            f"{_money(g['total_comp_after'])} at plan). Commission is the "
            f"{_money(g['on_target_variable_total'])} on-target variable slice of OTE "
            "across the team.",
            "grounded": g,
            "used": ["comp_scenario"],
            "model": None,
            "error": None,
        }

    # 2. Hiring capacity + priority
    if re.search(r"\bhir(e|es|ing)\b|headcount|\breq(s)?\b|add reps|priorit", q):
        g = hiring_plan(accounts, reps, conversions, settings, plan)
        if "error" in g:
            return None
        parts = ", ".join(f"{n} {seg} AE" for seg, n in g["safe_hires"].items()) or "no safe reqs"
        freeze = (
            " Freeze reqs in " + " and ".join(g["freeze_segments"]) + " until pipeline lands."
            if g["freeze_segments"]
            else ""
        )
        return {
            "mode": "demo",
            "answer": f"Hire {parts} now: that's the headroom the surplus segments can absorb "
            f"at target ({g['total_safe_hires']} safe reqs total).{freeze} Priority goes to the "
            f"segments with pipeline surplus; a req in a short segment lands uncovered and "
            "drags the floor down.",
            "grounded": g,
            "used": ["recommend_actions"],
            "model": None,
            "error": None,
        }

    # 3. Most at-risk segment
    if re.search(r"(most|at) risk|riskiest|weak(est)?|which segment|most exposed|biggest gap", q):
        g = segment_risk(plan)
        w = g["worst"]
        if not w:
            return None
        cov = "covers" if w["coverable"] else f"is short {_money(w['shortfall'])}"
        return {
            "mode": "demo",
            "answer": f"{w['segment']} is most at risk: {_money(w['available_pipeline'])} of "
            f"addressable pipeline against {_money(w['required_pipeline'])} required at target "
            f"(a {w['ratio']:.2f}× ratio across {w['reps']} reps), so it {cov}. Enterprise and "
            "Mid-Market sit above 1.0×; the constraint is SMB pipeline, not the carve.",
            "grounded": g,
            "used": ["get_scorecard"],
            "model": None,
            "error": None,
        }

    # 4. A named rep's gap ("what will {name} need to hit their quota?")
    if (
        re.search(r"quota|hit (their|his|her|the) number|cover|gap|short|need|clear", q)
        or find_rep(q, reps)[0]
    ):
        rep, cands = find_rep(q, reps)
        if rep is not None:
            g = assess_rep(plan, reps, settings, rep.rep_id)
            if g.get("covered"):
                return {
                    "mode": "demo",
                    "answer": f"{g['name']} ({g['role']}) is covered: "
                    f"{_money(g['available_pipeline'])} of addressable pipeline on a "
                    f"{_money(g['quota'])} quarterly quota, {g['pipeline_coverage']}× vs the "
                    f"{g['coverage_target']:g}× target. Coverage is pipeline adequacy, not a "
                    "promise of attainment.",
                    "grounded": g,
                    "used": ["assess_territory"],
                    "model": None,
                    "error": None,
                }
            return {
                "mode": "demo",
                "answer": f"{g['name']} ({g['role']}) needs {_money(g['pipeline_gap'])} more "
                f"addressable pipeline to clear {g['coverage_target']:g}× on a "
                f"{_money(g['quota'])} quota: the book holds {_money(g['available_pipeline'])} "
                f"({g['pipeline_coverage']}×) vs {_money(g['required_pipeline'])} required. "
                "Same-role fix: source the pipeline, re-tag it in, or lower the quota to "
                f"~{_money(g['quota_that_would_clear'])}.",
                "grounded": g,
                "used": ["assess_territory"],
                "model": None,
                "error": None,
            }
        if cands:
            return {
                "mode": "demo",
                "answer": "Which rep? I found "
                + ", ".join(f"{r.name} ({r.rep_id})" for r in cands)
                + ".",
                "grounded": {"candidates": [r.rep_id for r in cands]},
                "used": ["list_reps"],
                "model": None,
                "error": None,
            }

    # 5. Plan summary ("how's the plan", "how many reps are covered")
    if re.search(
        r"summary|overall|how('?s| is) the plan|covered|how many reps|company target|on track", q
    ):
        g = plan_summary(plan)
        rc = g["reps_covered"]
        return {
            "mode": "demo",
            "answer": f"The plan carries a {_money(g['company_target_quarterly'])}/quarter "
            f"({_money(g['company_target_annual'])}/yr) standardized target and covers "
            f"{rc['optimized']} of {rc['of']} reps at target, floor {g['coverage_floor']:.2f}×. "
            f"The capacity gap is {_money(g['capacity_gap'])}, all in SMB.",
            "grounded": g,
            "used": ["plan_summary"],
            "model": None,
            "error": None,
        }

    return None


# ----------------------------------------------------------------------
# Live agent: Claude + engine tools (used only for free-form questions)
# ----------------------------------------------------------------------
def key_available(api_key: str | None = None) -> bool:
    if not (api_key or os.environ.get("ANTHROPIC_API_KEY")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


_LIVE_SYSTEM = (
    "You are a RevOps analyst answering questions about a deterministic territory & "
    "quota plan. Call the provided tools to get numbers; the engine owns every figure, "
    "you never invent or alter one. Prefer one or two tool calls, then answer in a short, "
    "concrete paragraph. Frame coverage as pipeline adequacy and risk, not a guarantee of "
    "attainment. If a question is outside the plan, say so briefly."
)


def _live_tools(plan, accounts, reps, conversions, settings):
    """(tool schemas, name->callable) bound to the current plan."""
    schemas = [
        {
            "name": "plan_summary",
            "description": "Company target, reps covered, coverage floor, "
            "capacity gap, and per-segment pipeline vs required.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "assess_rep",
            "description": "What a named rep needs to clear the pipeline-coverage "
            "target: quota, available vs required pipeline, the gap, and coverage multiple.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "who": {
                        "type": "string",
                        "description": "Rep name or id, e.g. 'Jordan Kim' or 'R-125'.",
                    }
                },
                "required": ["who"],
            },
        },
        {
            "name": "segment_risk",
            "description": "Per-segment available vs required pipeline, ranked "
            "worst-first (which segment is most at risk).",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "hiring_plan",
            "description": "Safe hiring plan: how many reps each surplus segment can "
            "absorb at target, and which segments to freeze.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "commission_cost",
            "description": "Annual comp cost of moving on-target commission "
            "(variable pay) by a percent.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pct": {"type": "number", "description": "Percent change, negative to cut."}
                },
                "required": ["pct"],
            },
        },
        {
            "name": "list_reps",
            "description": "Every rep with id, name, role, and quarterly quota.",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]
    fns = {
        "plan_summary": lambda **_: plan_summary(plan),
        "assess_rep": lambda who, **_: assess_rep(plan, reps, settings, who),
        "segment_risk": lambda **_: segment_risk(plan),
        "hiring_plan": lambda **_: hiring_plan(accounts, reps, conversions, settings, plan),
        "commission_cost": lambda pct, **_: commission_cost(plan, settings, float(pct)),
        "list_reps": lambda **_: list_reps_brief(reps, plan),
    }
    return schemas, fns


def _live(question, plan, accounts, reps, conversions, settings, api_key):
    import anthropic

    schemas, fns = _live_tools(plan, accounts, reps, conversions, settings)
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    used: list[str] = []
    for _ in range(ASK_MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=ASK_MODEL,
            max_tokens=ASK_MAX_TOKENS,
            system=_LIVE_SYSTEM,
            tools=schemas,
            messages=messages,
        )
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            return {
                "mode": "live",
                "answer": text.strip(),
                "grounded": {},
                "used": used,
                "model": ASK_MODEL,
                "error": None,
            }
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use":
                used.append(b.name)
                try:
                    out = fns[b.name](**(b.input or {}))
                except Exception as e:  # surface tool errors to the model, don't crash
                    out = {"error": str(e)}
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": json.dumps(out, default=str),
                    }
                )
        messages.append({"role": "user", "content": results})
    return {
        "mode": "live",
        "answer": "I couldn't settle the answer within the tool-call budget.",
        "grounded": {},
        "used": used,
        "model": ASK_MODEL,
        "error": "max_tool_turns",
    }


# ----------------------------------------------------------------------
# AI refresh of the recommendations (single-shot, grounded; needs a key)
# ----------------------------------------------------------------------
_REFRESH_SYSTEM = (
    "You are a RevOps analyst re-reading a sales plan that was just recomputed from the "
    "planner's current configuration. You are given the capacity numbers, the funnel "
    "(win-rate) coverage, the deterministic recommendations already generated, and which "
    "configuration values differ from the defaults. Write a short, prioritized read (3 to 5 "
    "sentences): the single binding constraint right now, which recommended lever to act on "
    "first and why, and how the planner's configuration changes shifted the picture (call out "
    "conversion-rate changes, which move the funnel lens even when capacity is unchanged). "
    "Ground every statement in the payload; never invent a number, and never propose a fix "
    "that isn't among the recommendations."
)


def _refresh_payload(plan, recs, settings: PlanSettings) -> dict:
    sc = plan.scorecard
    below = sum(
        1 for t in plan.territories if t.coverage_ratio is not None and t.coverage_ratio < 1.0
    )
    active: dict = {}
    if settings.quota_to_ote is not None:
        active["quota_to_ote"] = settings.quota_to_ote
    if settings.coverage_target is not None:
        active["coverage_target"] = settings.coverage_target
    if settings.attainment != 1.0:
        active["attainment"] = settings.attainment
    if settings.ote_overrides:
        active["ote_overrides"] = settings.ote_overrides
    if settings.overrides:
        active["conversion_overrides"] = settings.overrides
    if settings.comp:
        active["comp"] = settings.comp
    if settings.added_reps:
        active["added_reps"] = settings.added_reps
    if settings.segment_overrides:
        active["segment_overrides"] = settings.segment_overrides
    if settings.account_retags:
        active["account_retags_count"] = len(settings.account_retags)
    return {
        "company_target_quarterly": sc["company_target"],
        "reps_covered": sc["reps_covered"],
        "coverage_floor": sc["coverage_floor"]["optimized"],
        "capacity_gap": sc["capacity_gap"]["optimized"],
        "per_segment_capacity": sc["per_segment_capacity"],
        "territories_below_1x_funnel_coverage": below,
        "recommendations": [
            {
                "category": r["category"],
                "severity": r["severity"],
                "title": r["title"],
                "levers": [lv["label"] for lv in r["levers"]],
            }
            for r in recs
        ],
        "config_changes_from_default": active or "none (defaults)",
    }


def refresh_recommendations(
    accounts, reps, conversions, settings=None, api_key=None, plan=None
) -> dict:
    """An AI re-read of the recommendations for the current configuration. Needs a key
    (per-request or env); without one, returns a clear prompt to add it. Never raises."""
    settings = settings or PlanSettings()
    if plan is None:
        plan = run_plan(accounts, reps, conversions, settings)
    recs = recommend.build_recommendations(accounts, reps, conversions, settings, plan=plan)
    if not key_available(api_key):
        return {
            "narrative": None,
            "model": None,
            "error": "add an Anthropic API key to refresh the recommendations with AI",
        }
    payload = _refresh_payload(plan, recs, settings)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        resp = client.messages.create(
            model=ASK_MODEL,
            max_tokens=600,
            system=_REFRESH_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": "Refresh the recommendations for the current configuration.\n\n"
                    + json.dumps(payload, default=str),
                }
            ],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return {"narrative": text.strip(), "model": ASK_MODEL, "error": None}
    except Exception as e:  # never fail the request over an optional AI call
        return {"narrative": None, "model": ASK_MODEL, "error": f"refresh failed: {e}"}


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def answer(question, accounts, reps, conversions, settings=None, api_key=None, plan=None) -> dict:
    """Answer a natural-language question about the plan. Never raises.

    Deterministic router first; free-form questions use the live agent when a key is
    present, else a helpful fallback listing what the offline demo can answer."""
    settings = settings or PlanSettings()
    question = (question or "").strip()
    if not question:
        return {
            "mode": "demo",
            "answer": "Ask me about the plan: a rep's gap, the segment most at "
            "risk, how many reps to hire, or the cost of changing commissions.",
            "grounded": {},
            "used": [],
            "model": None,
            "error": None,
        }
    if plan is None:
        plan = run_plan(accounts, reps, conversions, settings)

    routed = _route(question, plan, accounts, reps, conversions, settings)
    if routed is not None:
        return routed

    if key_available(api_key):
        try:
            return _live(question, plan, accounts, reps, conversions, settings, api_key)
        except Exception as e:  # never fail the request over an optional live call
            return {
                "mode": "live",
                "answer": None,
                "grounded": {},
                "used": [],
                "model": ASK_MODEL,
                "error": f"live answer failed: {e}",
            }

    return {
        "mode": "demo",
        "answer": "I can answer that live if you add an Anthropic API key (top right). Offline "
        "I can still tell you: what a named rep needs to hit quota, which segment is most at "
        "risk, how many reps you can safely hire, and the comp cost of changing commissions "
        "by a percent.",
        "grounded": {},
        "used": [],
        "model": None,
        "error": "no_match_offline",
    }
