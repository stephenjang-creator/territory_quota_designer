"""
core/evaluate.py — the baseline-vs-optimized scorecard (the eval).

Runs the naive equal-count carve and the optimized carve through the *same*
quota and the same reverse waterfall, then reports how much the optimizer moved
the needle: potential balance, geo compactness, whitespace balance, and — the
one planners care about most — how many territories flipped from under-covered to
covered. That before/after is the credibility artifact.

`make plan` (``python -m core.evaluate``) prints it to stdout and the markdown
block goes straight into the README.
"""

from __future__ import annotations

import config
from core import balance, quota, waterfall
from core.dataio import load_all
from core.models import Account, Rep, Territory


def _per_segment_cov(territories: list[Territory], accounts: list[Account]) -> dict:
    """CoV of potential within each segment pool (honest view under segment focus,
    where cross-segment deal sizes dominate the whole-team CoV)."""
    seg_of = {a.account_id: a.segment for a in accounts}

    def dom_segment(t: Territory) -> str:
        if not t.account_ids:
            return "—"
        segs = [seg_of[a] for a in t.account_ids]
        return max(set(segs), key=segs.count)

    buckets: dict[str, list[float]] = {}
    for t in territories:
        buckets.setdefault(dom_segment(t), []).append(t.potential)
    return {seg: balance._cov(vals) for seg, vals in sorted(buckets.items())}


def build_scorecard(
    accounts: list[Account],
    reps: list[Rep],
    conversions: dict,
    *,
    weights: dict | None = None,
    potential_mix: dict | None = None,
    respect_segment_focus: bool | None = None,
    max_accounts_per_rep: int | None = None,
    company_target: float | None = None,
    overrides: dict | None = None,
    optimized: list[Territory] | None = None,
) -> dict:
    """Compute the full scorecard dict. `optimized` may be passed to avoid a
    recompute; otherwise it is carved here."""
    weights = weights or config.WEIGHTS

    if optimized is None:
        optimized = balance.carve(
            accounts,
            reps,
            weights=weights,
            potential_mix=potential_mix,
            respect_segment_focus=respect_segment_focus,
            max_accounts_per_rep=max_accounts_per_rep,
        )
    baseline = balance.naive_carve(
        accounts,
        reps,
        potential_mix=potential_mix,
        respect_segment_focus=respect_segment_focus,
    )

    # Same company target on both carves so coverage is compared apples-to-apples.
    target = quota.default_company_target(optimized) if company_target is None else company_target
    quota.derive_quotas(optimized, reps, target)
    quota.derive_quotas(baseline, reps, target)
    waterfall.run_waterfall(optimized, accounts, conversions, overrides)
    waterfall.run_waterfall(baseline, accounts, conversions, overrides)

    # Coverage flips: rep-by-rep, under-covered (baseline) -> covered (optimized).
    opt_by_rep = {t.rep_id: t for t in optimized}
    flips = []
    for b in baseline:
        o = opt_by_rep.get(b.rep_id)
        if o is None:
            continue
        if b.under_covered and not o.under_covered:
            flips.append(b.rep_id)
    n_under_baseline = sum(1 for t in baseline if t.under_covered)
    n_under_optimized = sum(1 for t in optimized if t.under_covered)

    return {
        "balance_score": {
            "baseline": balance.balance_score(baseline),
            "optimized": balance.balance_score(optimized),
            "metric": "CoV of territory potential (lower = fairer)",
        },
        "geo_spread": {
            "baseline": balance.geo_spread_total(baseline),
            "optimized": balance.geo_spread_total(optimized),
            "metric": "total distinct-region spread (lower = more compact)",
        },
        "whitespace_cov": {
            "baseline": balance.whitespace_cov(baseline),
            "optimized": balance.whitespace_cov(optimized),
            "metric": "CoV of territory whitespace (lower = fairer)",
        },
        "per_segment_potential_cov": {
            "baseline": _per_segment_cov(baseline, accounts),
            "optimized": _per_segment_cov(optimized, accounts),
            "metric": "within-segment CoV of potential (what the optimizer can move)",
        },
        "combined_cost": {
            "baseline": balance.combined_cost(baseline, weights, accounts, reps),
            "optimized": balance.combined_cost(optimized, weights, accounts, reps),
            "metric": "weighted Stage-1 objective (lower = better)",
        },
        "off_home_share": {
            "baseline": balance.off_home_share(baseline, accounts, reps),
            "optimized": balance.off_home_share(optimized, accounts, reps),
            "metric": "share of accounts outside their rep's home region (lower = compact)",
        },
        "coverage_flips": {
            "under_covered_baseline": n_under_baseline,
            "under_covered_optimized": n_under_optimized,
            "flips_under_to_covered": len(flips),
            "flipped_reps": flips,
        },
        "company_target": target,
    }


def _pct(before: float, after: float) -> str:
    if before == 0:
        return "n/a"
    return f"{(after - before) / before * 100:+.1f}%"


def _avg(d: dict) -> float:
    vals = list(d.values())
    return sum(vals) / len(vals) if vals else 0.0


def scorecard_markdown(scorecard: dict) -> str:
    """Render the scorecard as a markdown block for the README / dashboard.

    Leads with the metrics the optimizer actually controls under segment focus
    (within-segment balance, geo), and labels the whole-team potential CoV as the
    structural floor it is — cross-segment deal sizes dominate it and no carve can
    move it while Enterprise/SMB reps sell fundamentally different books.
    """
    seg = scorecard["per_segment_potential_cov"]
    off = scorecard["off_home_share"]
    geo = scorecard["geo_spread"]
    ws = scorecard["whitespace_cov"]
    bs = scorecard["balance_score"]
    cov = scorecard["coverage_flips"]
    seg_b, seg_o = _avg(seg["baseline"]), _avg(seg["optimized"])
    lines = [
        "| Metric | Baseline (naive) | Optimized | Change |",
        "| --- | ---: | ---: | ---: |",
        f"| **Within-segment potential balance** — mean CoV (lower better) | {seg_b:.3f} | "
        f"{seg_o:.3f} | {_pct(seg_b, seg_o)} |",
        f"| **Geo — off-home-region share** (lower = compact) | {off['baseline']:.2f} | "
        f"{off['optimized']:.2f} | {_pct(off['baseline'], off['optimized'])} |",
        f"| Geo — Σ distinct regions (lower better) | {geo['baseline']} | "
        f"{geo['optimized']} | {_pct(geo['baseline'], geo['optimized'])} |",
        f"| Whitespace balance — CoV (lower better) | {ws['baseline']:.3f} | "
        f"{ws['optimized']:.3f} | {_pct(ws['baseline'], ws['optimized'])} |",
        f"| Whole-team potential CoV *(structural floor)* | {bs['baseline']:.3f} | "
        f"{bs['optimized']:.3f} | {_pct(bs['baseline'], bs['optimized'])} |",
        f"| Under-covered territories | {cov['under_covered_baseline']} | "
        f"{cov['under_covered_optimized']} | "
        f"{cov['flips_under_to_covered']} flipped |",
    ]
    return "\n".join(lines)


def main() -> None:  # `make plan`
    accounts, reps, conversions = load_all()
    sc = build_scorecard(accounts, reps, conversions)
    print(f"Company target: ${sc['company_target']:,.0f}\n")
    print(scorecard_markdown(sc))
    print("\nWithin-segment potential CoV (optimized):")
    for seg, v in sc["per_segment_potential_cov"]["optimized"].items():
        print(f"  {seg:<12} {v:.3f}")
    print(
        f"\nCoverage: {sc['coverage_flips']['under_covered_optimized']} of "
        f"{len(reps)} territories under-covered "
        f"(baseline {sc['coverage_flips']['under_covered_baseline']}); "
        f"{sc['coverage_flips']['flips_under_to_covered']} flipped."
    )


if __name__ == "__main__":
    main()
