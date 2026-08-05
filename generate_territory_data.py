"""
generate_territory_data.py
--------------------------
Synthetic data generator for the Territory & Quota Designer.

Produces three internally-consistent datasets so the whole four-stage chain
(balance -> quota -> reverse waterfall -> comp) has realistic inputs:

  accounts.csv     one row per account, with firmographics + potential signals
  reps.csv         the selling team, with segment focus, geo home, ramp status
  conversions.csv  per-segment stage-conversion rates + avg deal size (defaults
                   the reverse-waterfall reads; every value is overridable in-app)

Design goal: potentials and conversion rates are generated so that, in
aggregate, the territory *can* roughly support a sensible company target -- but
with enough variance that some carves leave territories under-covered. That
tension is what the dashboard exists to surface.

No production data is used. Runtime deps: pandas (required), faker (optional --
falls back to a built-in pool).

Usage:
    python generate_territory_data.py --accounts 800 --reps 14 --seed 42 --outdir data
"""

import argparse
import random

import pandas as pd

# ----------------------------------------------------------------------
# Optional Faker
# ----------------------------------------------------------------------
try:
    from faker import Faker
    _fake = Faker()
    def _company(): return _fake.company()
    def _person():  return _fake.name()
    def _seed_faker(s): Faker.seed(s)
except ImportError:  # pragma: no cover
    _C = ["Acme", "Northwind", "Globex", "Initech", "Umbra", "Contoso",
          "Vandelay", "Soylent", "Hooli", "Stark", "Wayne", "Wonka",
          "Cyberdyne", "Tyrell", "Aperture", "Nakatomi", "Gekko", "Prestige",
          "Oscorp", "Massive", "Pied Piper", "Dunder", "Sterling", "Cogswell"]
    _S = ["Systems", "Labs", "Group", "Holdings", "Partners", "Industries",
          "Technologies", "Solutions", "Digital", "Networks", "Analytics", "Cloud"]
    _F = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Jamie",
          "Avery", "Quinn", "Drew", "Cameron", "Reese", "Skyler", "Devin", "Blake"]
    _L = ["Nguyen", "Patel", "Garcia", "Kim", "Rossi", "Haddad", "Okafor", "Silva",
          "Novak", "Ivanov", "Chen", "Muller", "Sato", "Adeyemi", "Kowalski", "Reyes"]
    def _company(): return f"{random.choice(_C)} {random.choice(_S)}"
    def _person():  return f"{random.choice(_F)} {random.choice(_L)}"
    def _seed_faker(s): pass

# ----------------------------------------------------------------------
# Domain constants
# ----------------------------------------------------------------------
SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
SEG_WEIGHTS = [0.20, 0.45, 0.35]

INDUSTRIES = ["Software", "Financial Services", "Healthcare", "Manufacturing",
              "Retail", "Media", "Telecom", "Energy", "Logistics", "Education"]

# Region -> metros. Geo compactness in Stage 1 uses region + metro.
REGIONS = {
    "NA-West":  ["San Francisco", "Los Angeles", "Seattle", "Denver", "Phoenix"],
    "NA-East":  ["New York", "Boston", "Atlanta", "Chicago", "Austin"],
    "EMEA":     ["London", "Paris", "Berlin", "Madrid", "Amsterdam"],
    "APAC":     ["Sydney", "Singapore", "Tokyo", "Bangalore", "Seoul"],
}
REGION_WEIGHTS = [0.40, 0.35, 0.15, 0.10]

# Firmographic ranges by segment: employees, annual_revenue ($), and the potential
# envelope that drives whitespace + pipeline. All $ are ACV. The envelopes are sized
# so total addressable pipeline lands near ~3x the (much smaller, OTE-anchored)
# standardized quotas: Enterprise/Mid-Market carry a surplus, SMB stays a touch
# short — the capacity gap the dashboard exists to surface.
SEG_PROFILE = {
    "Enterprise": dict(emp=(2000, 50000), rev=(5e8, 2e10),
                       whitespace=(12_000, 30_000), pipe=(6_000, 18_000),
                       arr=(5_000, 40_000)),
    "Mid-Market": dict(emp=(200, 2000), rev=(5e7, 5e8),
                       whitespace=(5_000, 10_000), pipe=(2_000, 6_000),
                       arr=(2_000, 12_000)),
    "SMB":        dict(emp=(10, 200), rev=(1e6, 5e7),
                       whitespace=(1_000, 3_400), pipe=(600, 2_200),
                       arr=(300, 4_000)),
}

STAGES = ["Discovery", "Qualification", "Proposal", "Negotiation", "Won"]
# Stage transitions used by the reverse waterfall (from -> to).
TRANSITIONS = ["Discovery->Qualification", "Qualification->Proposal",
               "Proposal->Negotiation", "Negotiation->Won"]

# Baseline per-segment conversion rates + avg deal size. The app treats these
# as defaults; users override at global / segment / rep level.
SEG_CONVERSIONS = {
    "Enterprise": dict(rates=[0.45, 0.55, 0.60, 0.30], avg_deal=120_000),
    "Mid-Market": dict(rates=[0.50, 0.55, 0.62, 0.33], avg_deal=45_000),
    "SMB":        dict(rates=[0.55, 0.60, 0.65, 0.38], avg_deal=12_000),
}


# ----------------------------------------------------------------------
# Generators
# ----------------------------------------------------------------------
def _accounts(n):
    rows = []
    for i in range(n):
        seg = random.choices(SEGMENTS, weights=SEG_WEIGHTS)[0]
        p = SEG_PROFILE[seg]
        region = random.choices(list(REGIONS), weights=REGION_WEIGHTS)[0]
        metro = random.choice(REGIONS[region])
        propensity = round(random.betavariate(2, 2), 3)  # 0-1, centered mid
        # potential scales a little with propensity so "good fit" ~ more upside
        ws = random.uniform(*p["whitespace"]) * (0.6 + 0.8 * propensity)
        pipe = random.uniform(*p["pipe"]) * (0.5 + propensity)
        rows.append({
            "account_id": f"A-{10000 + i}",
            "name": _company(),
            "industry": random.choice(INDUSTRIES),
            "segment": seg,
            "employees": int(random.uniform(*p["emp"])),
            "annual_revenue": round(random.uniform(*p["rev"]), -3),
            "region": region,
            "metro": metro,
            "current_arr": round(random.uniform(*p["arr"]), -2),
            "whitespace_potential": round(ws, -2),
            "open_pipeline": round(pipe, -2),
            "propensity_score": propensity,
        })
    return pd.DataFrame(rows)


# Tenure (months) -> AE seniority level. Upper-exclusive bands, ascending; mirrors
# config.AE_LEVEL_TENURE_BANDS (the generator stays import-light on purpose).
LEVEL_BANDS = [(6, "ramping"), (18, "AE"), (36, "Sr. AE")]
LEVEL_TOP = "Sr. Strategic AE"
LEVEL_ORDER = ["ramping", "AE", "Sr. AE", "Sr. Strategic AE"]
# Seniority tracks account size: the strategic tier is Enterprise-only, senior reps
# top out in Mid-Market, and SMB is covered by AEs and new hires. A rep's level is
# its tenure band capped at its segment's ceiling -- so a tenured SMB rep is a
# (senior-paid) AE, never a "Sr. Strategic AE" sitting on a small book.
SEGMENT_MAX_LEVEL = {"Enterprise": "Sr. Strategic AE", "Mid-Market": "Sr. AE", "SMB": "AE"}


def _level_for_tenure(tenure):
    for upper, level in LEVEL_BANDS:
        if tenure < upper:
            return level
    return LEVEL_TOP


def _level_for(segment, tenure):
    """Tenure band, capped at the segment's seniority ceiling."""
    base = _level_for_tenure(tenure)
    cap = SEGMENT_MAX_LEVEL.get(segment, LEVEL_TOP)
    return base if LEVEL_ORDER.index(base) <= LEVEL_ORDER.index(cap) else cap


# The default 14-rep demo team, curated so seniority tracks account size (see
# above): strategic reps sell Enterprise, senior reps the larger Mid-Market books,
# SMB is AEs + a new hire. The mix (4 Enterprise / 6 Mid-Market / 4 SMB) sizes the
# derived company target into the ~$2.5-3M/quarter range for a $100-500M SaaS co.
# (segment, level, tenure)
DEFAULT_TEAM = [
    ("Enterprise", "Sr. Strategic AE", 48),  # R-100
    ("Enterprise", "Sr. Strategic AE", 42),  # R-101
    ("Enterprise", "AE", 14),                # R-102
    ("Enterprise", "ramping", 4),            # R-103
    ("Mid-Market", "Sr. AE", 30),            # R-104
    ("Mid-Market", "Sr. AE", 36),            # R-105
    ("Mid-Market", "AE", 14),                # R-106
    ("Mid-Market", "AE", 12),                # R-107
    ("Mid-Market", "AE", 9),                 # R-108
    ("Mid-Market", "ramping", 4),            # R-109
    ("SMB", "AE", 30),                        # R-110
    ("SMB", "AE", 24),                        # R-111
    ("SMB", "AE", 20),                        # R-112
    ("SMB", "ramping", 2),                    # R-113
]


def _reps(n):
    # Weight the team toward the segments that have the most accounts.
    focus_pool = (["Enterprise"] * 2 + ["Mid-Market"] * 3 + ["SMB"] * 3
                  + ["Mid-Market"])  # a blended/generalist lean
    rows = []
    regions = list(REGIONS)
    for i in range(n):
        # Draw name/region/metro from the pools (and a random focus/tenure so the
        # RNG stream is stable); the default team below then curates seniority.
        focus = random.choice(focus_pool)
        region = random.choice(regions)
        tenure = random.choice([2, 4, 6, 9, 14, 20, 30, 48])
        row = {
            "rep_id": f"R-{100 + i}",
            "name": _person(),
            "segment_focus": focus,
            "home_region": region,
            "home_metro": random.choice(REGIONS[region]),
            "tenure_months": tenure,
            "ramp_status": "ramping" if tenure < 6 else "full",
            "level": _level_for(focus, tenure),
        }
        if i < len(DEFAULT_TEAM):  # curate the default team for realism
            seg, level, ten = DEFAULT_TEAM[i]
            row.update(
                segment_focus=seg,
                tenure_months=ten,
                level=level,
                ramp_status="ramping" if level == "ramping" else "full",
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _conversions():
    rows = []
    for seg, cfg in SEG_CONVERSIONS.items():
        for t, r in zip(TRANSITIONS, cfg["rates"]):
            rows.append({"segment": seg, "transition": t, "rate": r})
        rows.append({"segment": seg, "transition": "avg_deal_size",
                     "rate": cfg["avg_deal"]})
    return pd.DataFrame(rows)


def build(n_accounts=800, n_reps=14, seed=42):
    random.seed(seed)
    _seed_faker(seed)
    return _accounts(n_accounts), _reps(n_reps), _conversions()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", type=int, default=800)
    ap.add_argument("--reps", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()

    acc, reps, conv = build(args.accounts, args.reps, args.seed)
    acc.to_csv(f"{args.outdir}/accounts.csv", index=False)
    reps.to_csv(f"{args.outdir}/reps.csv", index=False)
    conv.to_csv(f"{args.outdir}/conversions.csv", index=False)

    tot_pot = (acc.whitespace_potential + acc.open_pipeline).sum()
    print(f"Wrote {len(acc)} accounts, {len(reps)} reps, "
          f"{len(conv)} conversion rows to {args.outdir}/")
    print(f"  Total addressable potential (whitespace + pipeline): ${tot_pot:,.0f}")
    print(f"  Implied per-rep potential at even split: "
          f"${tot_pot / len(reps):,.0f}")
    print("  Segment mix:")
    for seg, k in acc.segment.value_counts().items():
        print(f"    {seg:<12} {k}")


if __name__ == "__main__":
    main()
