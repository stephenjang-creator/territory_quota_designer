# EXAMPLES.md — talking to the Territory Designer over MCP

Natural-language questions a RevOps planner might ask, and the tool call(s) each
one triggers. The tools return **structured JSON**; the agent narrates. Every
number comes from the deterministic core — the model only explains it. All dollar
figures are **MRR**; quota is a **quarterly** new-MRR target.

---

### 1. "Which territories can't hit their quota, and why?"

```
coverage_gaps()                    # → the under-covered reps, worst first
assess_territory("R-105")          # → drill into the worst one for the full funnel
```

`coverage_gaps` returns the three full-time Enterprise reps (e.g. R-101, R-102,
R-105) at ~0.91 coverage, each with a gap size and levers. `assess_territory`
then shows *why*: the reverse-waterfall funnel (quota → 62 won deals → … → ~1,388
required SQLs), `required_pipeline` ≈ $24.7M MRR vs `available_pipeline` ≈ $22.6M
MRR, and that Enterprise's 30% Negotiation→Won rate is what makes the book hardest.

---

### 2. "If I weight potential at 70% and geo at 10%, who wins and loses?"

```
whatif_weights(potential_weight=0.70, geo_weight=0.10, whitespace_weight=0.20)
```

Returns a diff vs. the default carve: the change in within-segment balance and
off-home-region share, the change in # under-covered, and the reps who gained /
lost the most potential (MRR). Weighting potential up tightens balance; weighting
geo up compacts territories at the cost of balance — the diff quantifies the trade.

---

### 3. "Enterprise win rates are really 25%, not 30% — what breaks?"

```
whatif_conversions({"segment": {"Enterprise": {"Negotiation->Won": 0.25}}})
```

Re-runs the waterfall with the override (rep > segment > global). The three
full-time Enterprise reps drop from ~0.91 to ~0.76 coverage — deeper gaps, not new
ones — while the *ramping* Enterprise rep stays covered because the quota haircut
already lightened its load. Push the rate to ~0.19 and that rep flips under too;
the tool reports exactly which territories cross the line and each coverage delta.

---

### 4. "What does this plan cost us at 90% attainment?"

```
comp_scenario(attainment=0.90)
```

Returns total comp, cost-of-sale, and the top/bottom earners at 90% attainment
(all quarterly MRR). Call `comp_scenario()` with no argument for the standard
0.85 / 1.0 / 1.10 scenario-compare table — cost-of-sale *falls* as attainment
rises, because base salary is fixed while bookings grow.

---

### 5. "How much better is the optimized carve than an even split?"

```
get_scorecard()
```

The baseline-vs-optimized eval: within-segment potential balance −57%, off-home
geo share −43%, distinct-region spread −40%, plus a ready-to-paste markdown table.
It also labels the whole-team potential CoV as a **structural floor** — under
segment focus, Enterprise reps carry ~$25M books and SMB reps ~$3.7M, a gap no
carve can close — so the agent can caveat the headline honestly.

---

### 6. "Is territory R-101 set up to fail, or just light on pipeline?"

```
assess_territory("R-101")
```

Distinguishes two things the planner conflates: **fairness** (`quota_to_potential`
vs. the team mean — is the quota itself unfair?) and **coverage** (does the book
hold enough pipeline?). R-101's quota is fair (near the mean), but its coverage is
0.91 — the issue is pipeline adequacy, and the `gap` block lists the levers (lower
quota to ~$6.78M MRR, add ~$2.15M MRR of pipeline, or source ~120 more SQLs).

---

### 7. "Rank my territories by coverage and show me the reps and segments."

```
list_reps()                        # discover valid ids / metadata
list_territories(sort_by="coverage_ratio", ascending=True, limit=15)
```

A compact table, worst-covered first. `list_reps` / `list_segments` are the
discovery tools — valid rep ids, and each segment's default conversion rates + avg
deal size (the global-tier defaults the override hierarchy falls back to).

---

### 8. "So if coverage is ≥ 1, the rep will hit quota, right?"

```
assess_territory("R-108")          # a covered SMB territory
```

**No — and the tool says so.** Every coverage payload carries
`"coverage_note": "coverage_ratio reflects pipeline adequacy / risk, not a
guarantee of attainment."` Coverage means the territory holds *enough addressable
pipeline on paper* to support the quota (a stock-vs-required check). It says
nothing about execution, timing, or win-rate variance. A covered rep can still
miss; an under-covered rep is carrying structural risk before the quarter even
starts. The engine quantifies risk; it never promises attainment.
