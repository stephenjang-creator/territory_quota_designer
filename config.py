"""
config.py — tunable knobs for the Territory & Quota Designer.

Every weight, constraint, conversion default, and comp parameter the core reads
lives here (or comes from the loaded CSVs). Nothing downstream hardcodes a magic
number mid-logic — change a value here (or pass an override at call time) and the
whole four-stage chain recomputes. These are also the dashboard sliders/inputs.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# Units
# ----------------------------------------------------------------------
# All monetary values are MRR (monthly recurring revenue). Quota is a QUARTERLY
# new-MRR bookings target. The synthetic figures keep their generator magnitudes,
# read as MRR; avg deal size stays per-segment (from conversions.csv), read as
# MRR added per deal. Every coverage/balance/cost-of-sale figure is a ratio, so
# the denomination is a labeling choice — it does not change any outcome.
QUOTA_PERIOD = "quarterly"
UNITS = {
    "currency": "USD MRR (monthly recurring revenue)",
    "quota_period": QUOTA_PERIOD,
    "note": (
        "All $ figures are MRR. Quota is a quarterly new-MRR bookings target; "
        "won_deals = quota / avg_deal_size (MRR added per deal) = deals to close "
        "in the quarter. avg_deal_size is per-segment (Enterprise/Mid-Market/SMB)."
    ),
}

# ----------------------------------------------------------------------
# Stage 1 — Balance
# ----------------------------------------------------------------------
# Combined-imbalance weights (must sum to 1.0). Also the dashboard sliders.
#   potential  — coefficient of variation of territory opportunity value
#   geo        — normalized distinct-region spread across territories (compact = low)
#   whitespace — coefficient of variation of territory whitespace
WEIGHTS = {"potential": 0.60, "geo": 0.25, "whitespace": 0.15}

# opportunity value = whitespace * a + open_pipeline * b + current_arr * c
# (current ARR is installed base — worth less as *new* opportunity, hence 0.25.)
POTENTIAL_MIX = {"whitespace": 1.0, "pipeline": 1.0, "current_arr": 0.25}

MAX_ACCOUNTS_PER_REP = None  # optional hard cap on territory size (None = off)
RESPECT_SEGMENT_FOCUS = True  # don't give Enterprise accounts to an SMB rep
GENERALIST_FOCUS = "Generalist"  # a rep with this focus can take any segment

# Local-search improvement loop (deterministic given the seed).
MAX_LOCAL_SEARCH_PASSES = 30

# ----------------------------------------------------------------------
# Stage 2 — Quota
# ----------------------------------------------------------------------
# Default quarterly company_target = COMPANY_TARGET_MULTIPLE * total opportunity
# potential (MRR). Tuned (seed 42) so the book can *roughly* support the target
# but a few territories fall under-covered — that tension is exactly what the
# dashboard exists to surface. At 0.27 the three full-time Enterprise reps land
# ~0.91 coverage (lowest win-rate segment); the ramping Enterprise rep is rescued
# by the quota haircut. See the reverse-waterfall math in the README.
COMPANY_TARGET_MULTIPLE = 0.27

# Ramping reps carry a lighter load; quotas re-normalize to the target afterward.
RAMP_QUOTA_HAIRCUT = 0.6
# Flag reps whose quota/potential ratio deviates more than this from the mean
# (set-up-to-fail high, sandbagged low).
QUOTA_FAIRNESS_TOLERANCE = 0.15

# ----------------------------------------------------------------------
# Stage 3 — Reverse waterfall / coverage
# ----------------------------------------------------------------------
# Which funnel stage defines "pipeline $": the value sitting at Negotiation.
#   required_pipeline = at_negotiation * avg_deal_size  ( == quota / rate(Neg->Won) )
# "available_potential" = the addressable portion of a territory (whitespace +
# open_pipeline); it excludes the current_arr slice that feeds Stage-1 potential,
# because installed ARR is not new pipeline you can close against a new-bookings quota.
COVERAGE_STAGE = "Negotiation"
STANDARD_COVERAGE_MULTIPLE = 3.0  # sanity band: available_potential / quota

# ----------------------------------------------------------------------
# Stage 4 — Comp (all overridable via API/UI)
# ----------------------------------------------------------------------
# Model: variable pay is commission on bookings — commission_rate up to
# accelerator_threshold (in attainment), then commission_rate * accelerator_multiplier
# above it, optionally capped at cap_attainment. Base salary is derived from the
# base/variable OTE split so cost-of-sale reflects fully-loaded comp:
#   target_variable = commission_rate * quota            (variable earned at 100%)
#   base_salary     = target_variable * split/(1 - split)
#   total_comp      = base_salary + variable_payout(attainment)
COMP = {
    "base_variable_split": 0.5,  # base as a fraction of OTE
    "commission_rate": 0.10,  # of bookings, below the accelerator
    "accelerator_multiplier": 1.5,  # commission multiple above threshold
    "accelerator_threshold": 1.0,  # attainment at which the accelerator starts
    "cap_attainment": None,  # optional attainment cap (None = uncapped)
}

# Default attainment scenarios for the comp scenario-compare table.
ATTAINMENT_SCENARIOS = [0.85, 1.0, 1.10]

# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
DATA_DIR_ENV = "TERRITORY_DATA"  # env var pointing at the CSV dir
DEFAULT_DATA_DIR = "data"
