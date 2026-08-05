"""
core/plan.py — run the whole quota-first chain from one settings payload.

`run_plan` is the single entry point the API `/plan`, the MCP server, and the
evaluator all call. The order is now quota-first:

    quota (standardized by role) -> carve (work-back to a pipeline-coverage target)
      -> reverse waterfall (funnel adequacy) -> comp (OTE-anchored) + scorecard.

Deterministic given the data seed and settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import config
from core import balance, comp, evaluate, quota, waterfall
from core.models import Account, PlanResult, Rep


def apply_retags(accounts: list[Account], account_retags: dict | None) -> list[Account]:
    """Return `accounts` with segment replaced per {account_id: segment} — a TRUE
    re-tag that moves an account (and its pipeline) into another segment's pool, so
    that segment's reps can carve it. Frozen Accounts, so replace() makes copies;
    unknown segments/ids are ignored."""
    if not account_retags:
        return accounts
    out = []
    for a in accounts:
        seg = account_retags.get(a.account_id)
        out.append(replace(a, segment=seg) if seg in config.SEGMENT_OTE and seg != a.segment else a)
    return out


def segment_coverage_target(
    segment: str, global_target: float, segment_overrides: dict | None
) -> float:
    """Per-segment coverage target: an override wins, else the global target."""
    if segment_overrides:
        v = (segment_overrides.get(segment) or {}).get("coverage_target")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return global_target


# Nominal tenure per level for a planned hire (level is explicit, so this only
# feeds display; it never changes quota or OTE, which come from the role).
_LEVEL_TENURE = {"ramping": 3, "AE": 12, "Sr. AE": 24, "Sr. Strategic AE": 48}
ADDED_REP_PREFIX = "NEW-"
MAX_ADDED_REPS = 40  # a sane ceiling on what-if hires per plan


def merge_added_reps(reps: list[Rep], added: list | None) -> list[Rep]:
    """Return `reps` plus materialized what-if hires (for capacity/hiring planning).

    Each `added` entry is a dict {name, segment_focus (or segment), level,
    home_region?, home_metro?}. A hire carries the standardized quota for its role
    exactly like a real rep, and the carve pulls pipeline from its segment — so the
    scorecard shows whether the larger team still covers. Invalid or excess entries
    are skipped, never raised (the API/UI must stay robust to partial input)."""
    out = list(reps)
    for i, spec in enumerate(added or []):
        if i >= MAX_ADDED_REPS or not isinstance(spec, dict):
            continue
        seg = spec.get("segment_focus") or spec.get("segment")
        level = spec.get("level")
        if seg not in config.SEGMENT_OTE or level not in config.AE_LEVELS:
            continue
        name = str(spec.get("name") or "TBH").strip() or "TBH"
        out.append(
            Rep(
                rep_id=f"{ADDED_REP_PREFIX}{i + 1}",
                name=name,
                segment_focus=seg,
                home_region=str(spec.get("home_region") or ""),
                home_metro=str(spec.get("home_metro") or ""),
                tenure_months=int(spec.get("tenure_months") or _LEVEL_TENURE.get(level, 0)),
                ramp_status="ramping" if level == "ramping" else "full",
                level=level,
            )
        )
    return out


@dataclass
class PlanSettings:
    """Everything the dashboard can change; all optional (fall back to config)."""

    ote_overrides: dict = field(default_factory=dict)  # {segment: {level: ote}}
    quota_to_ote: float | None = None  # quota = this * OTE
    coverage_target: float | None = None  # pack each book to this x quota in pipeline
    respect_segment_focus: bool | None = None
    prefer_home_region: bool | None = None
    overrides: dict = field(default_factory=dict)  # conversion overrides
    comp: dict | None = None  # comp param overrides
    attainment: float = 1.0
    attainment_scenarios: list | None = None
    added_reps: list = field(default_factory=list)  # what-if hires [{name, segment, level}]
    segment_overrides: dict = field(
        default_factory=dict
    )  # {seg: {quota_to_ote?, coverage_target?}}
    account_retags: dict = field(default_factory=dict)  # {account_id: segment} true re-tag

    def as_dict(self) -> dict:
        return {
            "ote_overrides": self.ote_overrides,
            "quota_to_ote": config.QUOTA_TO_OTE if self.quota_to_ote is None else self.quota_to_ote,
            "coverage_target": (
                config.PIPELINE_COVERAGE_TARGET
                if self.coverage_target is None
                else self.coverage_target
            ),
            "respect_segment_focus": (
                config.RESPECT_SEGMENT_FOCUS
                if self.respect_segment_focus is None
                else self.respect_segment_focus
            ),
            "prefer_home_region": (
                config.PREFER_HOME_REGION
                if self.prefer_home_region is None
                else self.prefer_home_region
            ),
            "overrides": self.overrides,
            "comp": self.comp or config.COMP,
            "attainment": self.attainment,
            "attainment_scenarios": self.attainment_scenarios or config.ATTAINMENT_SCENARIOS,
            "added_reps": self.added_reps,
            "segment_overrides": self.segment_overrides,
            "account_retags": self.account_retags,
        }


def run_plan(
    accounts: list[Account],
    reps: list[Rep],
    conversions: dict,
    settings: PlanSettings | None = None,
) -> PlanResult:
    """Run quota -> carve -> waterfall -> comp + scorecard; return a PlanResult."""
    s = settings or PlanSettings()

    # Fold in any what-if hires so the whole chain (quota, carve, coverage, comp,
    # scorecard) sees the larger team — the point of the hiring-plan feature.
    reps = merge_added_reps(reps, s.added_reps)
    # True re-tag: move accounts into another segment's pool BEFORE anything reads
    # segment, so the carve/coverage/per-segment math all see the effective segment.
    accounts = apply_retags(accounts, s.account_retags)

    # Per-rep coverage target (a segment can accept its own lower target).
    global_target = (
        config.PIPELINE_COVERAGE_TARGET if s.coverage_target is None else s.coverage_target
    )
    target_by_rep = {
        r.rep_id: segment_coverage_target(r.segment_focus, global_target, s.segment_overrides)
        for r in reps
    }

    # Stage 2 (first now) — standardized quota by role, from OTE (per-segment multiple).
    quotas = quota.standardized_quotas(
        reps,
        ote_overrides=s.ote_overrides,
        quota_to_ote=s.quota_to_ote,
        segment_overrides=s.segment_overrides,
    )
    otes = quota.resolve_ote(reps, s.ote_overrides)

    # Stage 1 — carve back from quota to a pipeline-coverage target.
    territories = balance.carve(
        accounts,
        reps,
        quotas,
        coverage_target=s.coverage_target,
        target_by_rep=target_by_rep,
        respect_segment_focus=s.respect_segment_focus,
        prefer_home_region=s.prefer_home_region,
    )
    company_target = quota.fill_territory_quotas(territories, quotas, otes)

    # Stage 3 — reverse waterfall (funnel adequacy on top of the packed pipeline).
    waterfall.run_waterfall(territories, accounts, conversions, s.overrides)

    # Stage 4 — comp roll-up (cost-of-sale at the chosen attainment).
    sim = comp.simulate(territories, s.attainment, s.comp)

    # Scorecard: capacity coverage vs a naive equal-count carve (same quotas).
    scorecard = evaluate.build_scorecard(
        accounts,
        reps,
        ote_overrides=s.ote_overrides,
        quota_to_ote=s.quota_to_ote,
        coverage_target=s.coverage_target,
        optimized=territories,
        segment_overrides=s.segment_overrides,
        target_by_rep=target_by_rep,
    )

    n_under = sum(1 for t in territories if t.under_covered)
    return PlanResult(
        territories=territories,
        balance_score=balance.balance_score(territories),
        baseline_balance_score=scorecard["balance_score"]["baseline"],
        company_target=company_target,
        scorecard=scorecard,
        total_potential=sum(t.potential for t in territories),
        n_territories=len(territories),
        n_under_covered=n_under,
        cost_of_sale=sim["cost_of_sale"],
        settings=s.as_dict(),
    )
