# EXAMPLES.md — talking to the Territory Designer over MCP

Natural-language questions a RevOps planner might ask, and the tool call(s) each
triggers. Tools return **structured JSON**; the agent narrates. Every number comes
from the deterministic engine. Quotas are standardized by role (annual quota = a
multiple of OTE, planned quarterly = annual ÷ 4); territories are carved back to a
pipeline-coverage target (3×). All $ are USD ACV.

---

### 1. "Which reps can't hit their number, and why?"

```
coverage_gaps()                    # → reps whose book is below the 3× pipeline target
assess_territory("R-110")          # → drill into one for the full picture
```

`coverage_gaps` returns the four **SMB reps** at ~2.43× pipeline coverage, each with
the exact pipeline gap (target × quota − available). `assess_territory("R-110")`
shows why: a standardized SMB AE quota of $110K/quarter needs $330K of pipeline at
3×, but the book holds only ~$268K — a **$62K capacity gap**. It's not a carve
mistake: the whole SMB segment holds $1.02M vs the $1.25M its quotas need at 3×. An
assignment can't invent pipeline.

---

### 2. "If we require 5× pipeline coverage instead of 3×, who comes up short?"

```
whatif_coverage(5.0)
```

Re-carves to the stiffer target and diffs. Reps covered drops from **10 → 3** — at 5×,
even the surplus Enterprise and Mid-Market segments can't pack every book that
deep — and the total capacity gap balloons. Returns the coverage floor, the gap, and
the full below-target list. Powers "how much pipeline coverage can we actually
demand before the model breaks".

---

### 3. "If we lift SMB AE OTE to $200K, what happens to quota and coverage?"

```
whatif_ote("SMB", "AE", 200000)
```

Every SMB AE's quota is re-priced to `4 × 200,000 ÷ 4 = $200K/quarter` (annual $800K;
same role → same number), the company target rises from $2.86M to **$3.13M/quarter**,
and each affected rep's pipeline coverage drops from 2.43× to ~1.48× (a richer quota
on the same thin book). Returns the before/after quota and coverage per affected rep.
Powers "we want to pay SMB more — can the segment support the quota that implies?".

---

### 4. "What does this plan cost us at 90% attainment?"

```
comp_scenario(attainment=0.90)
```

Total comp, cost-of-sale, and the top/bottom earners at 90%. Call `comp_scenario()`
with no argument for the 0.85 / 1.0 / 1.10 table. Comp is OTE-anchored and **annual**
(base = a slice of OTE, on-target variable earned in full at 100%), so at-plan
cost-of-sale sits near **25%** and can tick *up* above 100% as the accelerator kicks
in — the table shows it honestly.

---

### 5. "How much better is the work-back carve than an even split?"

```
get_scorecard()
```

The capacity eval, both carves under the **same** standardized quotas. The total
capacity gap is **identical** ($233K either way) — SMB is short no matter how you
carve, and an assignment can't invent pipeline. The work-back win is *fairness*: it
raises the coverage floor (worst rep 2.24× → 2.43×) and keeps books compact (off-home
0.81 → 0.47) by spreading the SMB shortfall evenly instead of starving one rep to
over-fill another. Includes a ready-to-paste markdown table and the per-segment
pipeline-vs-required breakdown.

---

### 6. "Is R-110 set up to fail, or is the segment just short on pipeline?"

```
assess_territory("R-110")
```

Distinguishes two things: the **quota is standardized and fair** (every SMB AE
carries the same $110K/quarter, derived from OTE — not a punishment), and the
**coverage** is 2.43× vs the 3× target. So it isn't that R-110's quota is unfair;
it's that the SMB book can't hold 3× pipeline for these quotas. The payload carries
the pipeline gap and both coverage lenses (pipeline multiple + the reverse-waterfall
funnel).

---

### 7. "Rank my territories by coverage and show me the roles and OTE."

```
list_reps()                        # discover ids, roles, OTE, standardized quota
list_territories(sort_by="pipeline_coverage", ascending=True, limit=15)
```

A compact table, worst-covered first. `list_reps` shows each rep's role
(segment × title), OTE, and standardized quarterly quota; `list_segments` gives each
segment's default conversion rates + avg deal size.

---

### 8. "So if a rep is covered to 3×, they'll hit quota, right?"

```
assess_territory("R-101")          # a covered Enterprise territory
```

**No — and the tool says so.** Coverage means the book holds *enough addressable
pipeline on paper* (3× quota) — a capacity check, not a forecast. It says nothing
about execution, timing, or win-rate variance. The reverse-waterfall funnel is a
second, stricter lens (does the pipeline survive the stage win-rates?), and even
that is adequacy, not a promise. A covered rep can still miss; a short rep can still
deliver. The engine quantifies risk; it never promises attainment.

---

### 9. "If enterprise win-rates drop to 15%, whose funnel breaks?"

```
whatif_conversions({"segment": {"Enterprise": {"Negotiation->Won": 0.15}}})
```

Re-runs the reverse waterfall with the override (rep > segment > global). Quotas and
the carve don't move — this is the funnel lens — but every Enterprise rep's
funnel-coverage drops, and the tool reports which territories cross below 1.0 and
each coverage delta. Powers "our Enterprise close rate is slipping — where does the
pipeline stop being enough".

---

### 10. "Which level can I hire into without breaking coverage?"

```
whatif_hire("Enterprise", "AE")        # absorbed by surplus?
whatif_hire("SMB", "AE", count=2)      # or does the segment run short?
```

Adds planned hires (use **"TBH"** for open reqs) at a role and diffs the plan. An
**Enterprise AE** is absorbed by the segment's pipeline surplus — reps-covered goes 10 → 11
and Enterprise stays coverable ($4.87M required vs $5.15M available). **Two SMB AEs** push
the already-short SMB segment's required pipeline $1.25M → $1.91M against the same $1.02M
available, land uncovered, and drop the coverage floor 2.43× → 1.40× — so the tool flags
SMB as the segment you can't hire into without sourcing more pipeline. Returns the
company-target delta, reps covered before/after, the coverage floor, and the segment's
pipeline vs. required. The dashboard does the same interactively: add reps in the roster
(bottom section) and watch the capacity bars.

---

### 11. "The SMB gap — what do I actually do about it?"

```
recommend_actions()                                  # every issue + a one-click fix
whatif_segment_override("SMB", quota_to_ote=3.25)    # or model one lever directly
```

`recommend_actions` returns the plan's issues, each with an **applyable settings delta**.
For the SMB shortfall it offers three fixes — **re-tag 36 Mid-Market accounts** into SMB
($241K of pipeline — every SMB rep then clears 3×, the source segment stays covered),
**lower the SMB quota multiple to 3.25×**, or **accept a 2.44× coverage target for SMB** — plus a safe hire plan (1
Enterprise + 1 Mid-Market AE), a comp-cost check, and the global target/multiple at which
every rep clears. `whatif_segment_override` models one lever directly: cutting SMB to
3.25× makes the segment coverable and drops the company target from $2.86M to
$2.79M/quarter. The dashboard renders the same actions with an **Apply** button on each.

