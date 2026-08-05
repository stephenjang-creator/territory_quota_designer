"""
core/models.py — the shared dataclasses that flow through the four stages.

`Account` and `Rep` mirror the CSV data contract exactly. `Territory` and
`PlanResult` accrete fields as the chain runs: balance fills the assignment +
potential, quota fills `quota`, the reverse waterfall fills the coverage block,
and comp reads from there. Every field is verifiable against an input a planner
can point at — that traceability is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Account:
    """One row of accounts.csv — a company that could be sold to."""

    account_id: str
    name: str
    industry: str
    segment: str  # Enterprise | Mid-Market | SMB
    employees: int
    annual_revenue: float
    region: str  # NA-West | NA-East | EMEA | APAC
    metro: str
    current_arr: float  # installed base
    whitespace_potential: float  # untapped upside
    open_pipeline: float  # live opportunity value
    propensity_score: float  # 0-1 fit/likelihood signal


@dataclass(frozen=True)
class Rep:
    """One row of reps.csv — a seller the book is carved across."""

    rep_id: str
    name: str
    segment_focus: str  # Enterprise | Mid-Market | SMB | Generalist
    home_region: str
    home_metro: str
    tenure_months: int
    ramp_status: str  # "ramping" | "full"
    level: str = "AE"  # ramping | AE | Sr. AE | Sr. Strategic AE (quota-load tier)

    @property
    def is_ramping(self) -> bool:
        return self.level == "ramping" or self.ramp_status == "ramping"


@dataclass
class Territory:
    """A rep's assigned book, enriched stage by stage.

    Stage 1 fills the assignment + `potential`/`geo_spread`/`whitespace`;
    Stage 2 fills `quota`/`quota_to_potential`; Stage 3 fills the coverage block
    (`required_*`, `available_potential`, `coverage_ratio`, `under_covered`,
    `funnel`, `rates_used`).
    """

    rep_id: str
    account_ids: list[str]
    potential: float  # sum of account opportunity value
    geo_spread: int  # distinct regions covered (lower = compact)
    whitespace: float  # sum of whitespace_potential

    # Stage 2
    quota: float | None = None
    quota_to_potential: float | None = None
    ote: float | None = None  # on-target earnings for the rep's role (quota = mult * ote)
    fairness: dict | None = None  # unused under standardized quotas; kept for shape compat

    # Stage 3 (reverse waterfall)
    required_pipeline: float | None = None
    required_sqls: float | None = None
    available_potential: float | None = None
    coverage_ratio: float | None = None  # available_potential / required_pipeline
    under_covered: bool | None = None
    pipeline_coverage_multiple: float | None = None  # available_potential / quota
    funnel: dict | None = None  # stage -> deal/opp count (waterfall chart)
    rates_used: dict | None = None  # key -> {"value", "level"} (override audit)
    segment_mix: dict | None = None  # segment -> account share

    @property
    def account_count(self) -> int:
        return len(self.account_ids)


@dataclass
class PlanResult:
    """The full output of one run of the chain, for a single settings payload."""

    territories: list[Territory]
    balance_score: float  # CoV of territory potential (lower = fairer)
    baseline_balance_score: float  # same metric on the naive equal-count carve
    company_target: float
    scorecard: dict  # eval metrics, baseline vs optimized

    # Convenience roll-ups (additive; keep payloads self-describing for MCP/UI).
    total_potential: float | None = None
    n_territories: int | None = None
    n_under_covered: int | None = None
    cost_of_sale: float | None = None
    settings: dict = field(default_factory=dict)
