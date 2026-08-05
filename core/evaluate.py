"""
core/evaluate.py — the capacity scorecard (the eval).

Quota is standardized by role, so "fairness" is no longer the story. The question
is now capacity: given every rep's fixed quota, can the book be carved so each rep
holds enough addressable pipeline to hit a coverage target (default 3x)? The
scorecard runs the work-back carve and a naive equal-count carve through the SAME
quotas and reports how many reps clear the target, the total capacity gap, and
where the pipeline actually is (per segment). That before/after is the artifact.

`make plan` (``python -m core.evaluate``) prints it; the markdown goes in the README.
"""

from __future__ import annotations

import config
from core import balance, quota
from core.dataio import load_all
from core.models import Account, Rep, Territory
from core.potential import available_potential


def _coverage_stats(territories: list[Territory], quotas: dict, target: float, acc_by_id) -> dict:
    covered = 0
    gap = 0.0
    mults = []
    for t in territories:
        accts = [acc_by_id[aid] for aid in t.account_ids]
        avail = available_potential(accts)
        q = quotas.get(t.rep_id, 0.0)
        mult = (avail / q) if q else None
        if mult is not None:
            mults.append(mult)
            if mult >= target:
                covered += 1
        gap += max(0.0, target * q - avail)
    return {
        "covered": covered,
        "short": len(territories) - covered,
        "total_gap": gap,
        "floor": min(mults) if mults else None,  # worst-covered rep (fairness)
    }


def build_scorecard(
    accounts: list[Account],
    reps: list[Rep],
    *,
    ote_overrides: dict | None = None,
    quota_to_ote: float | None = None,
    coverage_target: float | None = None,
    optimized: list[Territory] | None = None,
) -> dict:
    """Capacity coverage: work-back carve vs a naive equal-count carve, same quotas."""
    target = config.PIPELINE_COVERAGE_TARGET if coverage_target is None else coverage_target
    quotas = quota.standardized_quotas(reps, ote_overrides=ote_overrides, quota_to_ote=quota_to_ote)

    if optimized is None:
        optimized = balance.carve(accounts, reps, quotas, coverage_target=target)
    baseline = balance.naive_carve(accounts, reps)

    acc_by_id = {a.account_id: a for a in accounts}
    opt = _coverage_stats(optimized, quotas, target, acc_by_id)
    base = _coverage_stats(baseline, quotas, target, acc_by_id)

    # Per-segment capacity: is there enough pipeline in the segment to cover its
    # reps to target at all? (An assignment problem can't invent pipeline.)
    rep_seg = {r.rep_id: r.segment_focus for r in reps}
    per_seg = {}
    for seg in sorted(set(rep_seg.values())):
        seg_reps = [rid for rid, s in rep_seg.items() if s == seg]
        required = sum(target * quotas[rid] for rid in seg_reps)
        available = sum(
            a.whitespace_potential + a.open_pipeline for a in accounts if a.segment == seg
        )
        per_seg[seg] = {
            "reps": len(seg_reps),
            "available_pipeline": available,
            "required_pipeline": required,
            "coverable": available >= required,
        }

    return {
        "coverage_target": target,
        "company_target": sum(quotas.values()),
        "reps_covered": {"baseline": base["covered"], "optimized": opt["covered"], "of": len(reps)},
        "capacity_gap": {"baseline": base["total_gap"], "optimized": opt["total_gap"]},
        "coverage_floor": {"baseline": base["floor"], "optimized": opt["floor"]},
        "off_home_share": {
            "baseline": balance.off_home_share(baseline, accounts, reps),
            "optimized": balance.off_home_share(optimized, accounts, reps),
        },
        "balance_score": {
            "baseline": balance.balance_score(baseline),
            "optimized": balance.balance_score(optimized),
        },
        "per_segment_capacity": per_seg,
    }


def _pct(before: float, after: float) -> str:
    if before == 0:
        return "n/a"
    return f"{(after - before) / before * 100:+.1f}%"


def scorecard_markdown(scorecard: dict) -> str:
    """Render the capacity scorecard as a markdown block for the README / dashboard."""
    tgt = scorecard["coverage_target"]
    cov = scorecard["reps_covered"]
    gap = scorecard["capacity_gap"]
    flr = scorecard["coverage_floor"]
    off = scorecard["off_home_share"]
    lines = [
        f"| Metric | Naive equal-split | Work-back carve | (target {tgt:.0f}x) |",
        "| --- | ---: | ---: | ---: |",
        f"| **Total capacity gap** (pipeline short, USD) | ${gap['baseline']:,.0f} | "
        f"**${gap['optimized']:,.0f}** | {_pct(gap['baseline'], gap['optimized'])} |",
        f"| **Coverage floor** — worst-covered rep (higher = fairer) | {flr['baseline']:.2f}x | "
        f"**{flr['optimized']:.2f}x** | {_pct(flr['baseline'], flr['optimized'])} |",
        f"| Reps covered to {tgt:.0f}x pipeline (of {cov['of']}) | {cov['baseline']} | "
        f"{cov['optimized']} | evenly-spread shortfall |",
        f"| Off-home-region share (lower = compact) | {off['baseline']:.2f} | "
        f"{off['optimized']:.2f} | {_pct(off['baseline'], off['optimized'])} |",
    ]
    return "\n".join(lines)


def main() -> None:  # `make plan`
    accounts, reps, _ = load_all()
    sc = build_scorecard(accounts, reps)
    print(f"Company target (sum of standardized quotas): ${sc['company_target']:,.0f}")
    print(f"Coverage target: {sc['coverage_target']:.0f}x pipeline\n")
    print(scorecard_markdown(sc))
    print("\nPer-segment capacity (available vs required pipeline at target):")
    for seg, d in sc["per_segment_capacity"].items():
        flag = "OK" if d["coverable"] else "SHORT"
        print(
            f"  {seg:<12} avail ${d['available_pipeline']:>14,.0f}  "
            f"required ${d['required_pipeline']:>14,.0f}  [{flag}]"
        )
    print(
        f"\nReps covered to {sc['coverage_target']:.0f}x: "
        f"{sc['reps_covered']['optimized']} of {sc['reps_covered']['of']} "
        f"(naive {sc['reps_covered']['baseline']}); "
        f"capacity gap ${sc['capacity_gap']['optimized']:,.0f}."
    )


if __name__ == "__main__":
    main()
