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
#     quota          = QUOTA_TO_OTE * OTE(role)                         (quarterly target)
#     company target = sum of every rep's quota                         (derived)
#
# OTE, the multiple, and the coverage target are all overridable in the API/UI.
AE_LEVELS = ["ramping", "AE", "Sr. AE", "Sr. Strategic AE"]

# On-target earnings: the AE-tier OTE per segment, times a seniority factor on top.
# (SMB OTE is set so the thin SMB book can't quite cover its reps to 3x — that
# capacity gap is the tension the tool surfaces even after an optimal carve.)
SEGMENT_OTE = {"Enterprise": 900_000, "Mid-Market": 550_000, "SMB": 300_000}
LEVEL_OTE_FACTOR = {"ramping": 0.6, "AE": 1.0, "Sr. AE": 1.2, "Sr. Strategic AE": 1.35}
QUOTA_TO_OTE = 5.0  # quota as a multiple of OTE (industry norm ~4-6x)

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
