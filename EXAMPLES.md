# EXAMPLES.md — talking to the Territory Designer over MCP

Natural-language questions a RevOps planner might ask, and the tool call(s) each
one triggers. The tools return **structured JSON**; the agent narrates. Every
number comes from the deterministic core — the model only explains it. All dollar
figures are **MRR**; quota is a **quarterly** new-MRR target.

---

### 1. "Which territories can't hit their quota, and why?"

```
coverage_gaps()                    # → the under-covered reps, worst first
assess_territory("R-101")          # → drill into the worst one for the full funnel
```

`coverage_gaps` returns three under-covered reps, worst first: the two **Sr.
Strategic AEs on Enterprise books** — R-101 and R-102 at 0.79 — and a **Sr. AE**
(R-100, Mid-Market) sitting right on the line at 0.99, each with a gap size and
levers. `assess_territory("R-101")` shows *why*: the reverse-waterfall funnel
(quota → 72 won deals → … → ~1,611 required SQLs), `required_pipeline` ≈ $28.7M MRR
vs `available_pipeline` ≈ $22.6M MRR. It's a normal Enterprise book — but it's
**loaded as a Sr. Strategic AE (×1.30) → an $8.6M quota** on the lowest-win-rate
segment, and that's what pulls coverage to 0.79.

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

Re-runs the waterfall with the override (rep > segment > global). Every Enterprise
rep drops: the two Sr. Strategic AEs (R-101, R-102) from ~0.79 to ~0.66, and the
Enterprise AE (R-105) from 1.02 to 0.85 — a *new* gap — while the *ramping*
Enterprise rep (R-109) stays covered at ~1.41 because its lighter load protects it.
Under-covered goes 3 → 4; push the rate lower still and even the ramping rep's
cushion goes. The tool reports exactly which territories cross the line and each
coverage delta.

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
and how it compares across peers — is the quota load reasonable for this rep?) and
**coverage** (does the book hold enough pipeline?). R-101's quota load is high **by
design** — it's a Sr. Strategic AE (×1.30) on a big Enterprise book → an $8.6M
quota — which is appropriate, not a carve error. The real signal is **coverage:
0.79** — that heavy senior quota outruns the territory's addressable pipeline. The
`gap` block lists the levers (lower quota to ~$6.78M MRR, add ~$6.11M MRR of
pipeline, or source ~343 more SQLs).

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

---

### 9. "If we load our Sr. Strategic AEs 40% heavier, who runs short on pipeline?"

```
whatif_levels({"Sr. Strategic AE": 1.4})
```

Quota is proportional to potential × the rep's **seniority-level multiplier**, then
re-normalized to the same company target — so loading one level up shifts quota onto
it and off everyone else. Here the two Sr. Strategic AEs on Enterprise (R-101, R-102)
deepen from 0.79→0.75 and 0.79→0.76 as their quota climbs ~$8.6M → ~$9.0M, while the
rest of the team eases just enough that the Sr. AE (R-100) tips back over 1.0 — so
total under-covered actually drops 3 → 2. The tool returns each rep's quota +
coverage delta and any flips. `list_reps` shows who sits at each level and the
default multipliers, and the dashboard's "Quota by seniority level" panel is the
same lever with sliders.
