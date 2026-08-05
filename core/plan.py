"""
core/plan.py — run the whole four-stage chain from one settings payload.

`run_plan` is the single entry point the API `/plan`, the MCP server, and the
evaluator all call: balance -> quota -> reverse waterfall -> comp, plus the
baseline-vs-optimized scorecard. Deterministic given the data seed and settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from core import balance, comp, evaluate, quota, waterfall
from core.models import Account, PlanResult, Rep


@dataclass
class PlanSettings:
    """Everything the dashboard can change; all optional (fall back to config)."""

    weights: dict | None = None
    potential_mix: dict | None = None
    company_target: float | None = None
    respect_segment_focus: bool | None = None
    max_accounts_per_rep: int | None = None
    overrides: dict = field(default_factory=dict)  # conversion overrides
    level_multipliers: dict | None = None  # {level: quota multiplier} overrides
    comp: dict | None = None  # comp param overrides
    attainment: float = 1.0
    attainment_scenarios: list | None = None

    def as_dict(self) -> dict:
        return {
            "weights": self.weights or config.WEIGHTS,
            "potential_mix": self.potential_mix or config.POTENTIAL_MIX,
            "company_target": self.company_target,
            "respect_segment_focus": (
                config.RESPECT_SEGMENT_FOCUS
                if self.respect_segment_focus is None
                else self.respect_segment_focus
            ),
            "max_accounts_per_rep": self.max_accounts_per_rep,
            "overrides": self.overrides,
            "level_multipliers": quota.resolve_level_multipliers(self.level_multipliers),
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
    """Run balance -> quota -> waterfall -> comp + scorecard; return a PlanResult."""
    s = settings or PlanSettings()

    # Stage 1 — balance
    territories = balance.carve(
        accounts,
        reps,
        weights=s.weights,
        potential_mix=s.potential_mix,
        respect_segment_focus=s.respect_segment_focus,
        max_accounts_per_rep=s.max_accounts_per_rep,
    )

    # Stage 2 — quota
    company_target = quota.derive_quotas(
        territories, reps, s.company_target, level_multipliers=s.level_multipliers
    )

    # Stage 3 — reverse waterfall
    waterfall.run_waterfall(territories, accounts, conversions, s.overrides)

    # Stage 4 — comp roll-up (cost-of-sale at the chosen attainment)
    sim = comp.simulate(territories, s.attainment, s.comp)

    # Scorecard (reuses the optimized carve; builds the baseline internally)
    scorecard = evaluate.build_scorecard(
        accounts,
        reps,
        conversions,
        weights=s.weights,
        potential_mix=s.potential_mix,
        respect_segment_focus=s.respect_segment_focus,
        max_accounts_per_rep=s.max_accounts_per_rep,
        company_target=company_target,
        overrides=s.overrides,
        level_multipliers=s.level_multipliers,
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
