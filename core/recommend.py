"""
core/recommend.py — turn the plan's findings into recommended ACTIONS with fixes.

The scorecard says *what* is wrong (SMB is short, comp spikes at 85%); this module
says *what to do about it* and hands back an applyable settings delta for each
lever, so the UI/agent can enact a fix with one call. Every recommendation is
computed deterministically from the same engine the rest of the tool uses — no
number originates here that a plan re-run wouldn't reproduce.

Each recommendation:
    {id, category, severity, title, body, levers: [{label, apply}]}
where `apply` is a partial settings payload (merge it into the current settings and
re-run the plan). The three headline resolutions:
  - pipeline coverage → account_retags (true re-tag), segment_overrides (multiple),
    segment_overrides (per-segment coverage target)
  - hiring capacity   → added_reps (a safe hire plan)
  - compensation      → comp (auto-tuned to a cost-of-sale ceiling)
"""

from __future__ import annotations

import math

import config
from core import comp as comp_mod
from core import quota as quota_mod
from core.plan import (
    PlanSettings,
    apply_retags,
    merge_added_reps,
    run_plan,
    segment_coverage_target,
)

TARGET_COS = 0.30  # cost-of-sale ceiling the comp auto-tune aims for
STRESS_ATT = 0.85  # the attainment scenario the comp risk is judged at


def _addr(a) -> float:
    return a.whitespace_potential + a.open_pipeline


def _floor2(x: float) -> float:
    """Round DOWN to 2 decimals — a 'lower the multiple/target' lever must land at or
    below the line it targets, never a hair over it (which wouldn't resolve)."""
    return math.floor(x * 100) / 100


def _fmt(x: float | None) -> str:
    if x is None:
        return "—"
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}M"
    return f"${round(x / 1000):,}K"


def retag_to_cover(
    accounts: list,
    reps: list,
    *,
    quotas: dict,
    target_by_rep: dict,
    target_segment: str,
) -> dict:
    """Smallest-addressable accounts from SURPLUS segments -> target_segment until it
    reaches its coverage target, keeping every source segment coverable. Returns
    {account_id: target_segment} (empty if already covered or no surplus)."""
    seg_avail: dict[str, float] = {}
    for a in accounts:
        seg_avail[a.segment] = seg_avail.get(a.segment, 0.0) + _addr(a)
    seg_req: dict[str, float] = {}
    for r in reps:
        seg_req[r.segment_focus] = seg_req.get(r.segment_focus, 0.0) + target_by_rep[
            r.rep_id
        ] * quotas.get(r.rep_id, 0.0)

    gap = seg_req.get(target_segment, 0.0) - seg_avail.get(target_segment, 0.0)
    if gap <= 0:
        return {}

    avail = dict(seg_avail)
    retags: dict[str, str] = {}
    moved = 0.0
    # smallest-addressable first: the most "target-segment-like" accounts move first
    for a in sorted(
        (a for a in accounts if a.segment != target_segment),
        key=lambda a: (_addr(a), a.account_id),
    ):
        if moved >= gap:
            break
        src = a.segment
        if avail[src] - _addr(a) < seg_req.get(src, 0.0):
            continue  # moving this would push the source below its own target
        retags[a.account_id] = target_segment
        avail[src] -= _addr(a)
        moved += _addr(a)
    return retags


def _seg_capacity(scorecard: dict) -> dict:
    return scorecard["per_segment_capacity"]


def build_recommendations(
    accounts, reps, conversions, settings: PlanSettings | None = None, plan=None
) -> list:
    """The recommended actions for a plan, each with an applyable settings delta.

    Pass `plan` to reuse an already-computed PlanResult (the /plan endpoint does)."""
    s = settings or PlanSettings()
    if plan is None:
        plan = run_plan(accounts, reps, conversions, s)
    sc = plan.scorecard

    # Re-derive the same intermediates run_plan used (pure, cheap) so we can compute
    # concrete fixes (retag sets, per-segment numbers) off the effective inputs.
    reps2 = merge_added_reps(reps, s.added_reps)
    acc2 = apply_retags(accounts, s.account_retags)
    mult = config.QUOTA_TO_OTE if s.quota_to_ote is None else float(s.quota_to_ote)
    ppy = config.QUOTA_PERIODS_PER_YEAR
    gt = config.PIPELINE_COVERAGE_TARGET if s.coverage_target is None else s.coverage_target
    tbr = {
        r.rep_id: segment_coverage_target(r.segment_focus, gt, s.segment_overrides) for r in reps2
    }
    quotas = quota_mod.standardized_quotas(
        reps2,
        ote_overrides=s.ote_overrides,
        quota_to_ote=s.quota_to_ote,
        segment_overrides=s.segment_overrides,
    )

    cap = _seg_capacity(sc)
    segments = list(cap.keys())
    short = [seg for seg in segments if not cap[seg]["coverable"]]
    out: list[dict] = []

    # ---- 1. Pipeline coverage: resolve each short segment ----
    for seg in short:
        d = cap[seg]
        gap = d["required_pipeline"] - d["available_pipeline"]
        seg_target = tbr[next(r.rep_id for r in reps2 if r.segment_focus == seg)]
        ratio = d["available_pipeline"] / d["required_pipeline"] if d["required_pipeline"] else 1.0
        new_mult = _floor2(mult * ratio)
        new_target = _floor2(seg_target * ratio)
        retags = retag_to_cover(acc2, reps2, quotas=quotas, target_by_rep=tbr, target_segment=seg)
        levers = []
        if retags:
            src_counts: dict[str, int] = {}
            for aid in retags:
                src = next(a.segment for a in acc2 if a.account_id == aid)
                src_counts[src] = src_counts.get(src, 0) + 1
            src_txt = ", ".join(f"{n} from {sg}" for sg, n in src_counts.items())
            levers.append(
                {
                    "label": f"Re-tag {len(retags)} accounts into {seg} ({src_txt}) — "
                    f"{_fmt(gap)} of pipeline, sources stay covered.",
                    "apply": {"account_retags": retags},
                }
            )
        levers.append(
            {
                "label": f"Lower the {seg} quota multiple to {new_mult}× OTE "
                f"(same coverage, a smaller number).",
                "apply": {"segment_overrides": {seg: {"quota_to_ote": new_mult}}},
            }
        )
        levers.append(
            {
                "label": f"Accept a {new_target}× coverage target for {seg} "
                "and say so in the plan.",
                "apply": {"segment_overrides": {seg: {"coverage_target": new_target}}},
            }
        )
        out.append(
            {
                "id": f"pipeline-{seg}",
                "category": "pipeline",
                "severity": "critical",
                "title": f"{seg} is short {_fmt(gap)} of pipeline against its standardized quotas",
                "body": f"{seg} holds {_fmt(d['available_pipeline'])} addressable pipeline "
                f"but needs {_fmt(d['required_pipeline'])} to cover {d['reps']} reps "
                f"at {seg_target:g}×. No carve invents pipeline — the shortfall is "
                "structural, so pick a lever below.",
                "levers": levers,
            }
        )
    if not short:
        out.append(
            {
                "id": "pipeline-ok",
                "category": "pipeline",
                "severity": "ok",
                "title": f"Every segment covers its standardized quotas at {gt:g}×",
                "body": f"All {len(reps2)} reps clear the coverage target on the "
                f"pipeline available; the floor sits at "
                f"{sc['coverage_floor']['optimized']:.2f}×.",
                "levers": [
                    {
                        "label": "Hold the plan and re-test after the next pipeline refresh.",
                        "apply": {},
                    }
                ],
            }
        )

    # ---- 2. Hiring capacity: safe reqs per surplus segment ----
    headroom = []
    for seg in segments:
        d = cap[seg]
        surplus = d["available_pipeline"] - d["required_pipeline"]
        if surplus <= 0:
            continue
        ae_quota = (
            quota_mod.role_multiple(seg, mult, s.segment_overrides)
            * config.SEGMENT_OTE[seg]
            * config.LEVEL_OTE_FACTOR["AE"]
            / ppy
        )
        heads = int(surplus // (tbr_for(tbr, reps2, seg) * ae_quota)) if ae_quota else 0
        if heads >= 1:
            headroom.append({"seg": seg, "surplus": surplus, "heads": heads, "ae_quota": ae_quota})
    if headroom:
        plan_hires = []
        for h in headroom:
            plan_hires += [
                {"name": "TBH", "segment": h["seg"], "level": "AE"} for _ in range(h["heads"])
            ]
        segs_txt = " and ".join(h["seg"] for h in headroom)
        avoid = " or ".join(short) if short else "a short segment"
        out.append(
            {
                "id": "hiring",
                "category": "hiring",
                "severity": "info",
                "title": f"Hire into {segs_txt} — not into {avoid}",
                "body": "; ".join(
                    f"{h['seg']} has {_fmt(h['surplus'])} of pipeline headroom "
                    f"({h['heads']} AE at {_fmt(h['ae_quota'])} quota)"
                    for h in headroom
                )
                + ". A req in a short segment lands uncovered and drags the floor down.",
                "levers": [
                    {
                        "label": "Apply the safe hire plan: "
                        + ", ".join(f"{h['heads']}× {h['seg']} AE" for h in headroom)
                        + ".",
                        "apply": {"added_reps": plan_hires},
                    }
                ]
                + (
                    [
                        {
                            "label": f"Freeze {' / '.join(short)} reqs until pipeline lands.",
                            "apply": {},
                        }
                    ]
                    if short
                    else []
                ),
            }
        )
    else:
        out.append(
            {
                "id": "hiring",
                "category": "hiring",
                "severity": "warn",
                "title": f"No segment has headroom for another req at {gt:g}×",
                "body": "Every segment's required pipeline is at or above what it "
                "holds, so any added req starts uncovered.",
                "levers": [
                    {
                        "label": "Add pipeline before heads, or lower the coverage target.",
                        "apply": {},
                    }
                ],
            }
        )

    # ---- 3. Compensation: hold cost-of-sale under the ceiling at the stress case ----
    sim = comp_mod.simulate(plan.territories, STRESS_ATT, s.comp)
    cos85 = sim["cost_of_sale"]
    plan_cos = comp_mod.simulate(plan.territories, 1.0, s.comp)["cost_of_sale"]
    tune = comp_mod.autotune_comp(plan.territories, TARGET_COS, STRESS_ATT, s.comp)
    over = cos85 is not None and cos85 > TARGET_COS
    comp_levers = []
    if over and tune.get("comp"):
        comp_levers.append(
            {
                "label": f"Auto-tune comp to hold cost of sale ≤ {TARGET_COS:.0%} "
                f"at {STRESS_ATT:.0%} (achieves {tune['achieved_cos']:.1%}).",
                "apply": {"comp": {**comp_mod.resolved_params(s.comp), **tune["comp"]}},
            }
        )
    comp_levers.append({"label": "Budget to the 85% case, not the plan case.", "apply": {}})
    out.append(
        {
            "id": "comp",
            "category": "comp",
            "severity": "warn" if over else "info",
            "title": (
                f"Cost of sale reaches {cos85:.1%} at {STRESS_ATT:.0%} attainment"
                if cos85 is not None
                else "Cost of sale unavailable"
            ),
            "body": f"Base pay is fixed, so a miss does not shrink the bill proportionally: "
            f"{cos85:.1%} of bookings at {STRESS_ATT:.0%} vs {plan_cos:.1%} at plan"
            + (
                f" — within the {TARGET_COS:.0%} ceiling."
                if not over
                else f", above the {TARGET_COS:.0%} ceiling."
            ),
            "levers": comp_levers,
        }
    )

    # ---- 4. Sensitivity: where does the whole plan clear? ----
    ratios = {
        seg: (
            cap[seg]["available_pipeline"] / cap[seg]["required_pipeline"]
            if cap[seg]["required_pipeline"]
            else 1.0
        )
        for seg in segments
    }
    worst = min(segments, key=lambda seg: ratios[seg])
    # "clears everywhere" is bounded by the worst individual rep (the floor), not the
    # segment aggregate — spreading a shortfall evenly leaves the floor just under it.
    floor = sc["coverage_floor"]["optimized"] or gt
    all_target = _floor2(floor)  # a global coverage target every rep clears
    all_mult = _floor2(mult * floor / gt) if gt else mult  # global multiple, every rep at gt
    out.append(
        {
            "id": "sensitivity",
            "category": "sensitivity",
            "severity": "info",
            "title": f"The plan clears everywhere at {all_target}× coverage, "
            f"or a {all_mult}× quota multiple",
            "body": f"At today's {mult:g}× / {gt:g}×, {sc['reps_covered']['optimized']} of "
            f"{sc['reps_covered']['of']} reps are covered. {worst} is the binding constraint at "
            f"{ratios[worst] * gt:.2f}×.",
            "levers": [
                {
                    "label": f"Drop the coverage target to {all_target}× "
                    "(a policy change, not a capacity one).",
                    "apply": {"coverage_target": all_target},
                },
                {
                    "label": f"Or cut the multiple to {all_mult}× OTE across the board.",
                    "apply": {"quota_to_ote": all_mult},
                },
            ],
        }
    )

    return out


def tbr_for(target_by_rep: dict, reps: list, segment: str) -> float:
    """The coverage target for a segment (from any rep in it)."""
    for r in reps:
        if r.segment_focus == segment:
            return target_by_rep[r.rep_id]
    return config.PIPELINE_COVERAGE_TARGET
