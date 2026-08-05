# Territory & Quota Designer

**Quota-first capacity planning for RevOps.** Standardize quotas by role, derive
them from pay, then carve territories *backward* from those quotas — packing each
book with enough pipeline to give the rep a fair shot at their number. Where a
segment can't cover its standardized quotas, the tool surfaces the capacity gap
instead of hiding it in an uneven carve. Change anything upstream (a role's OTE,
the quota multiple, the coverage target, a conversion rate) and everything
downstream recomputes.

**AI-first, human-in-the-loop.** A deterministic engine owns every number a
planner sees — the standardized quotas, the work-back assignment, the coverage
math, the comp. The optional LLM layer only *explains* ("why is SMB short on
pipeline", "what does this cost at 85% attainment"); it never sets a quota or
assigns an account. The engine makes zero network calls and is reproducible given
the data seed.

> All data is **synthetic** (`generate_territory_data.py`). No real customer or
> company data, ever — this is a portfolio project.

**Units.** Every dollar figure is **USD ACV** (annual contract value). OTE is
annual on-target earnings; the **annual** quota = 4–6× OTE (industry norm) and the
per-rep **quarterly** quota shown = annual ÷ 4. Comp and cost-of-sale are reported
annually; coverage is a ratio, so denomination never changes an outcome. The
dashboard shows money in thousands ($K).

## Use case: sales capacity & territory planning at scale

**Situation.** A ~$250M ARR B2B software company is planning next fiscal year's
go-to-market coverage. Leadership has a company growth target and needs to translate
it into a concrete field plan — how many reps, carrying what quotas, covering which
accounts, and whether that structure can realistically produce the number.
Compensation is governed by a **role-based OTE-and-quota model**: a tenured Enterprise
AE carries a fixed quota and OTE tied to their title band, a Mid-Market AE a different
band, ramping reps a haircut. Quotas are set by **title** — not recomputed per rep
from book size, not distributed proportionally to hit a top-down goal. That's how most
enterprises actually operate, and it's the core planning risk this tool exists to
expose.

**Complication.** Because quota is assigned by title rather than derived from
territory potential, nothing guarantees a rep's territory is big enough to support the
quota they've been handed. A $1.2M quota assumes a book that can generate enough
qualified pipeline to produce $1.2M in bookings at the team's *real* conversion rates.
If it can't, the rep is under-covered before the year begins — no amount of activity
closes the gap, attainment suffers, cost-of-sale rises, and the forecast built on
those quotas is structurally optimistic. Before the plan locks, leaders need to know:

- Given each rep's fixed, title-based quota, how much qualified pipeline and how many
  opportunities must their territory generate to hit it?
- Does the territory as carved actually hold that much addressable potential?
- Which territories are under-covered, and by how much — so coverage can be rebalanced,
  quotas adjusted, or headcount added before commitments are made?
- What does the plan cost in total comp and cost-of-sale, and how sensitive is that to
  attainment?

**How the tool answers it.** Load the account universe (segment, industry, size, geo,
current ARR, whitespace, open pipeline) and the rep roster (title-based OTE/quota
bands, ramp status); the [four-stage chain](#the-chain-quota-rules) runs quota-first.
It sets each rep's title-based quota, **carves territories backward** from those quotas
to a pipeline-coverage target, then works the quota *up the funnel* — dividing through
each stage's conversion rate (configurable, with a rep > segment > global override
hierarchy, so Enterprise, SMB, and a ramping rep each model their own reality rather
than one blended rate that lies) to compute the qualified pipeline and opportunities
the territory must produce. It compares that against the territory's available
potential, yields a **coverage ratio per rep**, and flags every territory that can't
physically support its quota — then rolls the plan up into total comp, cost-of-sale,
and payout curves across attainment scenarios. Add planned hires (or a "TBH") to test
whether more headcount closes a gap or just spreads a segment thinner.

**Outcome.** A defensible capacity plan before comp letters go out: quotas matched to
territories that can actually support them, an explicit list of under-covered
territories with each gap's size and the lever to close it, and a full cost-of-sale
picture. The optional AI layer explains each result in plain language — *"this
territory is 18% short on required Enterprise pipeline at a 30% win rate; closing it
needs either +$400K in reassigned potential or a quota cut to $1.05M"* — while every
number stays owned by deterministic, auditable math.

## The chain (quota rules)

```
OTE by role  →  ① Quota    standardized per role: annual quota = multiple × OTE, shown quarterly (same role → same number)
             →  ② Carve    work back from quota: pack each book to a pipeline-coverage target (3×)
             →  ③ Waterfall reverse-funnel adequacy on the packed pipeline (a second lens)
             →  ④ Comp      OTE-anchored payouts, cost-of-sale, attainment scenarios
```

The inversion from the usual "balance books → derive proportional quota → hope the
pipeline's there" is the point: **quota is the fixed input**, and the territory is
what you build to support it.

## Quickstart

```bash
pip install -r requirements.txt      # or: make install
make data                            # regenerate data/ (seed 42) — optional, it's committed
make test                            # pytest — the engine is fully unit-tested
make plan                            # print the capacity scorecard
make api                             # FastAPI on $PORT (default 8000); root serves the dashboard
```

Everything runs offline. To enable the optional explanations, set
`ANTHROPIC_API_KEY` (and `pip install anthropic`); without it the app runs end to
end and `/explain` returns a clear "narrative disabled" message.

## Standardized quota by role, anchored on pay

Two reps with the same title and segment carry the **same quota** — anything else
destroys morale and breaks the comp/CAC model. A "role" is `segment × seniority
level`, and quota is derived backward from on-target earnings:

```
OTE(role)    = SEGMENT_OTE[segment] × LEVEL_OTE_FACTOR[level]   (annual OTE, editable per role)
annual quota = QUOTA_TO_OTE × OTE                               (default 4×; industry norm 4–6×)
quota        = annual quota ÷ 4                                 (the quarterly target the model plans on)
company target = Σ every rep's quarterly quota                 (derived, not handed down)
```

OTE is sized for a US SaaS company of ~$100–500M revenue; the default roster
(annual quota = 4 × OTE, shown quarterly):

| Role | OTE (annual) | Annual quota (4×) | Quarterly quota |
| --- | ---: | ---: | ---: |
| Enterprise · Sr. Strategic AE | $420K | $1.68M | **$420K** |
| Enterprise · AE | $280K | $1.12M | **$280K** |
| Enterprise · ramping | $224K | $896K | **$224K** |
| Mid-Market · Sr. AE | $219K | $875K | **$219K** |
| Mid-Market · AE | $175K | $700K | **$175K** |
| Mid-Market · ramping | $140K | $560K | **$140K** |
| SMB · AE | $110K | $440K | **$110K** |
| SMB · ramping | $88K | $352K | **$88K** |

Company target ≈ **$2.86M/quarter** ($11.5M annual) — the sum of the 14-rep team's
quarterly quotas. Edit any role's OTE or the multiple in the dashboard and every rep
in that role — plus the target — moves.

## Work-back carve + the capacity scorecard

Given the fixed quotas, the carve is a capacity-planning problem: pack each book
with **addressable pipeline (whitespace + open) ≥ 3× quota**, respecting segment
focus, preferring the rep's home region as a tiebreaker. When a segment is short,
the carve spreads the shortfall **evenly** rather than starving one rep to over-fill
another — so it raises the worst-covered rep's floor.

The scorecard runs the work-back carve against a naive equal-account split under
the **same** standardized quotas:

| Metric | Naive equal-split | Work-back carve | (target 3×) |
| --- | ---: | ---: | ---: |
| **Total capacity gap** (pipeline short, USD) | $233,000 | **$233,000** | structural |
| **Coverage floor** — worst-covered rep (higher = fairer) | 2.24× | **2.43×** | +8.5% |
| Reps covered to 3× pipeline (of 14) | 10 | 10 | evenly-spread shortfall |
| Off-home-region share (lower = compact) | 0.81 | **0.47** | −41.6% |

The total gap is **identical** between the two carves — and that's the honest point:
SMB is short by $233K no matter how you slice it, so no assignment can beat it on the
total. What the work-back carve *does* is refuse to rob Peter to pay Paul — it spreads
the shortfall evenly instead of starving one SMB rep to over-fill another, which lifts
the **worst-covered rep's floor** (2.24× → 2.43×) and keeps books compact (off-home
−41.6%). The gap that remains is structural:

```
Per-segment pipeline vs. required at 3×:
  Enterprise   $5.15M available   vs   $4.03M required   → OK
  Mid-Market   $4.01M available   vs   $3.31M required   → OK
  SMB          $1.02M available   vs   $1.25M required   → SHORT by $0.23M
```

SMB simply doesn't hold enough pipeline to cover its standardized quotas to 3×.
No assignment can invent pipeline — the fix is to reassign pipeline in, lower the
SMB role's quota (OTE or the multiple), or source more. That's the decision the
tool exists to surface.

## Recommended actions — resolve, not just diagnose

The dashboard's **executive summary** turns the scorecard into a decision (a verdict
plus four tiles), and **Recommended actions** turns each finding into a fix you can
apply in one click. Every lever is computed by `core/recommend.py` and carries an
applyable settings delta — same engine, nothing invented in the UI:

| Finding | Levers (each an **Apply**) |
| --- | --- |
| **SMB short $233K** | re-tag **36 Mid-Market accounts** into SMB ($241K — every SMB rep then clears 3×, sources stay covered) · lower the SMB multiple to **3.25×** · accept a **2.44×** SMB target |
| **Hiring capacity** | apply the safe plan — **1 Enterprise + 1 Mid-Market AE**, freeze SMB |
| **Comp at 85%** | auto-tune the decelerator/base to hold cost-of-sale under a ceiling (a no-op at the default 26%) |
| **Sensitivity** | drop to a **2.43×** global target, or a **3.24×** multiple, and every rep clears |

"Re-tag" is a **true account move**: the tool picks the smallest-addressable
surplus-segment accounts, changes their segment, and re-carves — and it keeps moving
accounts, **re-carving to verify at each step, until every target-segment rep clears the
target** (not just the segment aggregate), while the source stays covered and no quota
moves. Applying a lever merges its delta into the settings and recomputes; an agent gets
the identical fixes via `recommend_actions`.

## Plan hires against capacity

The roster in the dashboard is **editable**: add a rep — a name, or **"TBH"** for an
open req — at any segment and level, and the whole chain recomputes with them in it.
Each hire takes its role's standardized quota, and the carve pulls pipeline from that
hire's segment, so the scorecard shows immediately whether the larger team still covers:

- **Add an Enterprise AE** → the segment's surplus absorbs it: reps-covered goes 10 → 11
  and Enterprise required rises $4.03M → $4.87M but still sits under its $5.15M available —
  a **safe hire**.
- **Add two SMB AEs** → the already-short SMB segment's required jumps $1.25M → $1.91M
  against the same $1.02M available, the new reps land uncovered, and the coverage floor
  drops 2.43× → 1.40× — a hire the segment **can't support without more pipeline**.

That's the question the feature answers: *which levels can I hire into without pushing a
segment below the coverage target.* Over MCP, `whatif_hire(segment, level, count)` returns
the same diff (company target, reps covered, coverage floor, segment pipeline vs. required).

## Worked example (two reps)

```
R-101 · Enterprise · Sr. Strategic AE          R-110 · SMB · AE
  OTE  (annual)         $420,000                  OTE  (annual)         $110,000
  annual quota = 4×OTE  $1,680,000                annual quota = 4×OTE  $440,000
  quarterly quota       $420,000                  quarterly quota       $110,000
  pipeline packed       $1,534,100                pipeline packed       $267,700
  pipeline coverage  1,534,100 / 420,000          pipeline coverage   267,700 / 110,000
                     = 3.65×   (≥ 3×  ✓)                              = 2.43×   (< 3×  ⚠)
  capacity gap        none                         capacity gap        $62,300 short of 3×
```

Same-role reps get the identical quota; the carve packs Enterprise books past 3×
(surplus pipeline) but can only reach ~2.43× for SMB AEs — the SMB segment is
capacity-constrained. A second lens, the **reverse waterfall**, works the quota
back up the funnel (won deals → negotiation → … → required SQLs) to sanity-check
the packed pipeline against stage win-rates; the dashboard shows both.

## The override hierarchy (conversion rates)

Every conversion rate and average deal size the waterfall reads resolves as
`rep > segment > global default (conversions.csv)`, and the engine records *which
tier* supplied each number so the drill-in can show the audit trail:

```json
{
  "global":  {"Negotiation->Won": 0.28},
  "segment": {"Enterprise": {"Negotiation->Won": 0.25}},
  "rep":     {"R-105": {"avg_deal_size": 90000}}
}
```

"If enterprise win-rates drop to 25%, whose funnel breaks?" is exactly this.

## Compensation (OTE-anchored)

Pay is anchored on the **same OTE** that sets quota, so the two are always
consistent:

```
base            = split × OTE                       (fixed, annual)
target_variable = (1 − split) × OTE                 (earned in full at 100% attainment)
variable(att)   = target_variable × payout_factor(att)   (3-band curve, normalized to 1.0 on-target)
total_comp      = base + variable(att)                   (annual)
cost_of_sale    = Σ total_comp / Σ annual bookings       (both annual; ≈ 25% at plan)
```

Comp and bookings are **annual** (OTE is annual, and bookings = quarterly quota ×
4 × attainment), so cost-of-sale lands at the usual ~20–30% rather than a quarter-
vs-year mismatch. `payout_factor` is a piecewise-linear multiplier normalized so
on-target pays exactly the target variable: a **decelerator** below a floor (reduced
slope), the standard slope up to target, and an **accelerator** above it — with an
optional cap. All parameters are editable, with a live payout curve. Because the
accelerator lifts variable faster than bookings, cost-of-sale can tick *up* above
100% attainment — which the tool shows honestly.

## API

Data is loaded once at startup; each endpoint recomputes from a settings payload.
Interactive docs at `/docs`.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | the **interactive dashboard** — executive summary + recommended actions (one-click Apply) over the config |
| `GET /api` · `GET /health` | JSON service index · liveness probe |
| `GET /roles` | default OTE + standardized quota per role (seeds the OTE panel) |
| `GET /conversions` · `GET /comp/defaults` | per-segment rate defaults · comp params |
| `POST /balance` | Stage 1 — the work-back carve + per-segment capacity |
| `POST /quota` | Stage 2 — standardized quota by role (from OTE) |
| `POST /waterfall` | Stage 3 — reverse-waterfall coverage roll-up |
| `POST /comp` | Stage 4 — payouts, cost-of-sale, scenarios, payout curve |
| `POST /plan` | the whole chain **+ recommendations** in one call (the dashboard's hot path) |
| `GET /territory/{rep_id}` | full single-territory detail (coverage + funnel) |
| `POST /explain` | optional LLM rationale; skips cleanly with no API key |

Settings a request can send: `quota_to_ote`, `coverage_target`, `ote_overrides`
(`{segment:{level:ote}}`), `prefer_home_region`, `overrides` (conversions), `comp`,
`attainment`, `added_reps` (`[{name, segment, level}]` — what-if hires),
`segment_overrides` (`{segment:{quota_to_ote?, coverage_target?}}` — per-segment), and
`account_retags` (`{account_id: segment}` — a true re-tag). A recommendation's **Apply**
just merges its delta into these and re-POSTs — no stateful endpoint.

## Agent / MCP

The same engine is an **MCP server** (`mcp_server.py`) — fifteen read-only tools so an
agent can interrogate *and resolve* a plan conversationally: `plan_summary`,
`list_territories`, `assess_territory`, `coverage_gaps`, `recommend_actions`,
`whatif_ote`, `whatif_hire`, `whatif_segment_override`, `whatif_coverage`,
`whatif_conversions`, `autotune_comp`, `comp_scenario`, `get_scorecard`, `list_reps`,
`list_segments`. `recommend_actions` returns the same applyable fixes the dashboard
shows. See **[EXAMPLES.md](EXAMPLES.md)** for natural-language questions mapped to tools.

```bash
make mcp        # stdio (Claude Desktop / claude mcp)
make mcp-http   # HTTP on $PORT, MCP_AUTH_TOKEN bearer auth (hosted use)
```

## Configuration

All tunable knobs live in `config.py` — `SEGMENT_OTE` / `LEVEL_OTE_FACTOR` /
`QUOTA_TO_OTE` (annual pay → quota multiple) / `QUOTA_PERIODS_PER_YEAR` (annual →
quarterly), `PIPELINE_COVERAGE_TARGET` (the carve's 3× target), `PREFER_HOME_REGION`,
and the OTE-anchored `COMP` params — or come from the loaded CSVs. Every one is
overridable per API/MCP call.

## Deploy (Render)

`render.yaml` defines two native-Python web services (both bind `0.0.0.0:$PORT`,
both read the committed `data/` CSVs): the FastAPI app (its root serves the
dashboard) and the MCP server over bearer-auth'd HTTP. Pushing to `main` redeploys.

## Project layout

```
generate_territory_data.py   synthetic data generator (curated 14-rep team)
data/                        accounts.csv · reps.csv · conversions.csv
config.py                    all tunable knobs (OTE, quota multiple, coverage target, comp)
core/
  models.py                  Account · Rep · Territory · PlanResult
  potential.py               per-account opportunity + addressable pipeline
  quota.py                   Stage 2 — standardized quota by role, from OTE
  balance.py                 Stage 1 — work-back coverage carve + naive baseline
  waterfall.py               Stage 3 — reverse waterfall + funnel coverage
  comp.py                    Stage 4 — OTE-anchored comp
  overrides.py               rep > segment > global conversion-rate resolution
  evaluate.py                capacity scorecard (work-back vs naive)
  recommend.py               recommended actions + applyable fixes (re-tag / overrides / autotune)
  plan.py                    run_plan orchestrator (quota → carve → waterfall → comp)
  views.py                   JSON-safe roll-up views (shared by API + MCP)
api/main.py                  FastAPI app (serves the dashboard + JSON endpoints)
api/static/index.html        self-contained interactive dashboard (served at /)
mcp_server.py                MCP server (read-only tools over core)
tests/                       one file per module + /plan + API + MCP tool tests
```

## Design principles

- **Quota rules; territory is derived.** Standardized by role, anchored on pay,
  carved backward — the inversion is the whole idea.
- **Surface the gap, don't bury it.** When a segment can't cover its quotas, the
  tool says so (and where the pipeline actually is) instead of hiding it.
- **Config over magic numbers.** OTE, the multiple, the coverage target, and comp
  live in `config.py` or the CSVs — all overridable per call.
- **Deterministic, testable core.** A fixed seed → a reproducible plan; every
  number is traceable to an input a planner can verify.
