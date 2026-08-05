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
# All monetary values are USD ACV (annual contract value). OTE is annual on-target
# earnings. The ANNUAL quota = QUOTA_TO_OTE * OTE (industry norm 4-6x); the quota
# the model plans and carves against is QUARTERLY = annual / QUOTA_PERIODS_PER_YEAR,
# and that quarterly number is what the dashboard shows. avg_deal_size is per-segment
# ACV added per deal (from conversions.csv). Coverage/balance are ratios, so they are
# denomination-invariant; comp and cost-of-sale are reported annually (see Stage 4).
QUOTA_PERIOD = "quarterly"
QUOTA_PERIODS_PER_YEAR = 4  # quarterly quota = annual quota / 4
UNITS = {
    "currency": "USD (annual contract value)",
    "quota_period": QUOTA_PERIOD,
    "note": (
        "All $ are USD ACV. OTE is annual; annual quota = QUOTA_TO_OTE x OTE "
        "(norm 4-6x); the quarterly quota shown = annual quota / 4. won_deals = "
        "quarterly quota / avg_deal_size (ACV per deal) = deals to close in the "
        "quarter. Comp and cost-of-sale are annual; coverage is a ratio."
    ),
}

# ----------------------------------------------------------------------
# Stage 1 — Territory carve (work-back from quota)
# ----------------------------------------------------------------------
# Quota-first: each rep's quota is fixed by role (Stage 2), and the carve packs
# each book with enough ADDRESSABLE pipeline (whitespace + open_pipeline) to reach
# a pipeline-coverage target. Segment focus is respected; the rep's home region is
# preferred as the tiebreaker. Reps who can't reach the target are flagged — the
# capacity gap is the headline signal.
PIPELINE_COVERAGE_TARGET = 3.0  # pack each book to >= this x quota in addressable pipeline
PREFER_HOME_REGION = True  # geo tiebreaker: fill from home-region accounts first
RESPECT_SEGMENT_FOCUS = True  # an Enterprise account never goes to an SMB rep
GENERALIST_FOCUS = "Generalist"  # a rep with this focus can take any segment

# opportunity value = whitespace + open_pipeline + 0.25*current_arr; reported as a
# territory's "opportunity" and the denominator of quota-load. (The carve packs on
# ADDRESSABLE pipeline = whitespace + open_pipeline, not this blend.)
POTENTIAL_MIX = {"whitespace": 1.0, "pipeline": 1.0, "current_arr": 0.25}

# ----------------------------------------------------------------------
# Stage 2 — Quota (standardized by role, anchored on pay)
# ----------------------------------------------------------------------
# Quota RULES here: it is set by role, not by book size, so every rep in the same
# role carries the SAME quota. A role is (segment x seniority level). Quota is
# derived backward from on-target earnings (OTE):
#
#     OTE(role)      = SEGMENT_OTE[segment] * LEVEL_OTE_FACTOR[level]   (annual OTE, $)
#     annual quota   = QUOTA_TO_OTE * OTE(role)                         (industry norm 4-6x)
#     quota          = annual quota / QUOTA_PERIODS_PER_YEAR            (quarterly target)
#     company target = sum of every rep's quarterly quota              (derived)
#
# OTE, the multiple, and the coverage target are all overridable in the API/UI.
AE_LEVELS = ["ramping", "AE", "Sr. AE", "Sr. Strategic AE"]

# On-target earnings (annual, USD) — realistic for a US SaaS company of ~$100-500M
# revenue: the AE-tier OTE per segment, times a seniority factor on top. Ramping
# reps carry a lighter effective load; senior tiers earn 25-50% more.
SEGMENT_OTE = {"Enterprise": 280_000, "Mid-Market": 175_000, "SMB": 110_000}
LEVEL_OTE_FACTOR = {"ramping": 0.8, "AE": 1.0, "Sr. AE": 1.25, "Sr. Strategic AE": 1.5}
QUOTA_TO_OTE = 4.0  # ANNUAL quota as a multiple of OTE (industry norm ~4-6x)

# Tenure (months) -> level, a dataio fallback when a reps row has no explicit level.
AE_LEVEL_TENURE_BANDS = [(6, "ramping"), (18, "AE"), (36, "Sr. AE")]
AE_LEVEL_TOP = "Sr. Strategic AE"
# Seniority tracks account size (strategic = Enterprise-only, senior tops out in
# Mid-Market, SMB is AEs + new hires): a rep's level is its tenure band capped here.
SEGMENT_MAX_LEVEL = {"Enterprise": "Sr. Strategic AE", "Mid-Market": "Sr. AE", "SMB": "AE"}


def level_for_tenure(tenure_months: int) -> str:
    """Map a rep's tenure to a seniority level (ignoring segment)."""
    for upper, level in AE_LEVEL_TENURE_BANDS:
        if tenure_months < upper:
            return level
    return AE_LEVEL_TOP


def level_for(segment: str, tenure_months: int) -> str:
    """Tenure band capped at the segment's seniority ceiling (see SEGMENT_MAX_LEVEL)."""
    base = level_for_tenure(tenure_months)
    cap = SEGMENT_MAX_LEVEL.get(segment, AE_LEVEL_TOP)
    return base if AE_LEVELS.index(base) <= AE_LEVELS.index(cap) else cap


# ----------------------------------------------------------------------
# Stage 3 — Reverse waterfall / coverage
# ----------------------------------------------------------------------
# The funnel stage that defines "pipeline $": the value sitting at Negotiation.
#   required_pipeline = at_negotiation * avg_deal_size  ( == quota / rate(Neg->Won) )
# "available_potential" = the addressable portion of a territory (whitespace +
# open_pipeline); it excludes installed ARR, which is not new pipeline to close
# against a new-bookings quota. coverage_ratio = available / required (funnel-based);
# the pipeline_coverage_multiple = available / quota is what the carve targets (3x).
COVERAGE_STAGE = "Negotiation"
STANDARD_COVERAGE_MULTIPLE = PIPELINE_COVERAGE_TARGET  # available_potential / quota target

# ----------------------------------------------------------------------
# Stage 4 — Comp (OTE-anchored; all overridable via API/UI)
# ----------------------------------------------------------------------
# Pay is anchored on the SAME OTE that sets quota. base = split * OTE (fixed), and
# the on-target variable = (1 - split) * OTE is earned in full at 100% attainment,
# scaled by a THREE-band payout curve normalized so payout_factor(1.0) = 1.0:
#   below decelerator_threshold : slope * decelerator_multiplier  (<1 = under-attain penalty)
#   up to accelerator_threshold : slope                           (standard)
#   above accelerator_threshold : slope * accelerator_multiplier  (>1 = kicker)
#   total_comp = base + (1 - split) * OTE * payout_factor(attainment)
# Comp is annual (OTE is annual). Bookings are annualized (quarterly quota x
# QUOTA_PERIODS_PER_YEAR x attainment) so cost-of-sale = annual comp / annual
# bookings lands at the usual ~20-30% of bookings, not a quarter-vs-year mismatch.
COMP = {
    "base_variable_split": 0.5,  # base as a fraction of OTE
    "decelerator_threshold": 0.7,  # below this attainment, the reduced (decel) slope
    "decelerator_multiplier": 0.5,  # slope multiple below the decel threshold (<1)
    "accelerator_threshold": 1.0,  # at/above this attainment, the accelerated slope
    "accelerator_multiplier": 1.5,  # slope multiple above the accel threshold (>1)
    "cap_attainment": None,  # optional attainment cap (None = uncapped)
}

# Default attainment scenarios for the comp scenario-compare table.
ATTAINMENT_SCENARIOS = [0.85, 1.0, 1.10]

# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
DATA_DIR_ENV = "TERRITORY_DATA"  # env var pointing at the CSV dir
DEFAULT_DATA_DIR = "data"
