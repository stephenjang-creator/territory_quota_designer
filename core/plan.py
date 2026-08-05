"""
core/plan.py — run the whole quota-first chain from one settings payload.

`run_plan` is the single entry point the API `/plan`, the MCP server, and the
evaluator all call. The order is now quota-first:

    quota (standardized by role) -> carve (work-back to a pipeline-coverage target)
      -> reverse waterfall (funnel adequacy) -> comp (OTE-anchored) + scorecard.

Deterministic given the data seed and settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from core import balance, comp, evaluate, quota, waterfall
from core.models import Account, PlanResult, Rep


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
        }


def run_plan(
    accounts: list[Account],
    reps: list[Rep],
    conversions: dict,
    settings: PlanSettings | None = None,
) -> PlanResult:
    """Run quota -> carve -> waterfall -> comp + scorecard; return a PlanResult."""
    s = settings or PlanSettings()

    # Stage 2 (first now) — standardized quota by role, from OTE.
    quotas = quota.standardized_quotas(
        reps, ote_overrides=s.ote_overrides, quota_to_ote=s.quota_to_ote
    )
    otes = quota.resolve_ote(reps, s.ote_overrides)

    # Stage 1 — carve back from quota to a pipeline-coverage target.
    territories = balance.carve(
        accounts,
        reps,
        quotas,
        coverage_target=s.coverage_target,
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
