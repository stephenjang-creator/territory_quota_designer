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
| `GET /` | the **interactive dashboard** (self-contained HTML, served same-origin) |
| `GET /api` · `GET /health` | JSON service index · liveness probe |
| `GET /roles` | default OTE + standardized quota per role (seeds the OTE panel) |
| `GET /conversions` · `GET /comp/defaults` | per-segment rate defaults · comp params |
| `POST /balance` | Stage 1 — the work-back carve + per-segment capacity |
| `POST /quota` | Stage 2 — standardized quota by role (from OTE) |
| `POST /waterfall` | Stage 3 — reverse-waterfall coverage roll-up |
| `POST /comp` | Stage 4 — payouts, cost-of-sale, scenarios, payout curve |
| `POST /plan` | the whole chain in one call (the dashboard's hot path) |
| `GET /territory/{rep_id}` | full single-territory detail (coverage + funnel) |
| `POST /explain` | optional LLM rationale; skips cleanly with no API key |

Settings a request can send: `quota_to_ote`, `coverage_target`, `ote_overrides`
(`{segment:{level:ote}}`), `prefer_home_region`, `overrides` (conversions), `comp`,
`attainment`.

## Agent / MCP

The same engine is an **MCP server** (`mcp_server.py`) — ten read-only tools so an
agent can interrogate a plan conversationally: `plan_summary`, `list_territories`,
`assess_territory`, `coverage_gaps`, `whatif_ote`, `whatif_coverage`,
`whatif_conversions`, `comp_scenario`, `get_scorecard`, `list_reps`, `list_segments`.
See **[EXAMPLES.md](EXAMPLES.md)** for natural-language questions mapped to tools.

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
generate_territory_data.py   synthetic data generator (curated 12-rep team)
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
