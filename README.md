# Territory & Quota Designer

Carve a book of accounts into balanced sales territories, derive fair quotas,
**prove each territory is big enough to hit its quota via a reverse waterfall**,
and model the resulting comp cost — as one connected chain. Change anything
upstream (a balance weight, the company target, a conversion rate) and everything
downstream recomputes.

**AI-first, human-in-the-loop RevOps.** A deterministic optimizer and the
waterfall/comp math own every number a planner sees. The optional LLM layer only
*explains* — "why did rep R-101 get these accounts", "why is this territory
under-covered", "what's driving this cost-of-sale". The model never allocates an
account, sets a quota, or picks a number. The engine makes zero network calls and
is reproducible given the data seed; only the optional narrative endpoint touches
the Anthropic API, and it degrades gracefully with no key.

> All data is **synthetic** (`generate_territory_data.py`). No real customer or
> company data, ever — this is a portfolio project.

**Units.** Every dollar figure is **MRR** (monthly recurring revenue). Quota is a
**quarterly** new-MRR bookings target, so `won_deals = quota / avg_deal_size`
(MRR added per deal) reads as deals to close in the quarter. Coverage, balance,
and cost-of-sale are all ratios, so the denomination never changes an outcome.

## The four-stage chain

```
accounts + firmographics + reps
  → ① Balance     weighted multi-factor optimization (potential / geo / whitespace)
  → ② Quota       proportional to potential × the rep's seniority-level load, summed to a target
  → ③ Reverse     work backward quota → won → … → required SQLs; is there enough pipeline?
     waterfall
  → ④ Comp        payout curves, cost-of-sale, attainment scenarios
```

## Quickstart

```bash
pip install -r requirements.txt      # or: make install
make data                            # regenerate data/ (seed 42) — optional, it's committed
make test                            # pytest — the OR core is fully unit-tested
make plan                            # print the baseline-vs-optimized scorecard
make api                             # FastAPI on $PORT (default 8000); see /docs
```

Everything runs offline. To enable the optional explanations, set
`ANTHROPIC_API_KEY` (and `pip install anthropic`); without it the app runs end to
end and `/explain` returns a clear "narrative disabled" message.

## Baseline vs. optimized — the scorecard

The credibility artifact: the naive equal-account carve vs. the optimizer, run
through the **same** quota and the same waterfall. Because segment focus is
respected (an Enterprise account never goes to an SMB rep), the team is really
three segment-locked pools — so the honest headline is **within-segment**
balance, which the optimizer controls. The whole-team CoV is dominated by the
structural gap between a ~$25M Enterprise book and a ~$3.7M SMB book and is
reported as the floor it is.

Quarterly company target: **$45,487,231** in new MRR (0.27 × total opportunity
potential, all MRR).

| Metric | Baseline (naive) | Optimized | Change |
| --- | ---: | ---: | ---: |
| **Within-segment potential balance** — mean CoV (lower better) | 0.056 | 0.024 | **−57.0%** |
| **Geo — off-home-region share** (lower = compact) | 0.82 | 0.47 | **−42.7%** |
| Geo — Σ distinct regions (lower better) | 47 | 28 | −40.4% |
| Whitespace balance — CoV (lower better) | 0.609 | 0.601 | −1.4% |
| Whole-team potential CoV *(structural floor)* | 0.608 | 0.603 | −0.8% |
| Under-covered territories | 2 | 3 | 0 flipped |

The **off-home-region floor is 0.45** — 358 of 800 accounts have no rep of their
segment *in their region*, so they must be sold cross-region no matter what. The
optimizer captures nearly all of the discretionary remainder. Turn the geo weight
up and it compacts further at the cost of balance — that trade-off is the point
of the sliders.

Coverage is **segment- and seniority-structural** here: quota is proportional to
potential *scaled by the rep's level*, so a territory's coverage ratio is set
mostly by its segment's win rate and how heavily its level is loaded — not by
which accounts it holds, so re-carving doesn't flip it. At this target the three
under-covered reps are exactly the ones you'd worry about: the two **Sr. Strategic
AEs on Enterprise books** (lowest win rate, loaded ×1.30 → ~$8.6M quotas → 0.79
coverage) and a **Sr. AE** sitting right on the line, while the ramping reps sit
comfortably over-covered on their lighter load. Dial the level multipliers, the
conversion rates, or the target and watch who moves — that's what the dashboard and
the what-if tools are for.

## Worked reverse-waterfall example (R-101, a Sr. Strategic AE on Enterprise)

Work **backward** from the quota up the funnel, then ask: does the territory hold
enough addressable pipeline to support it?

```
quota (quarterly)     $8,612,153 MRR  (new-MRR target; R-101 is a Sr. Strategic AE, ×1.3)
avg deal size         $120,000 MRR    (Enterprise default, from conversions.csv)

won deals    = 8,612,153 / 120,000                    =    71.8   (deals this quarter)
at negotiation = 71.8 / 0.30  (Negotiation→Won)       =   239.2
at proposal    = 239.2 / 0.60 (Proposal→Negotiation)  =   398.7
at qualification = 398.7 / 0.55 (Qualification→Prop)  =   724.9
at discovery   = 724.9 / 0.45 (Discovery→Qual)        = 1,611.0   ← required SQLs

required_pipeline = at_negotiation × avg_deal = $28,707,178 MRR ( = quota / 0.30 )
available_pipeline = Σ (whitespace + open_pipeline)  = $22,595,100 MRR
coverage_ratio     = 22,595,100 / 28,707,178         = 0.79      → UNDER-COVERED
```

`available_pipeline` is the addressable portion (whitespace + open pipeline); it
excludes installed ARR, which isn't new pipeline you can close against a
new-bookings quota. Coverage is an **adequacy / risk** signal, not a guarantee of
attainment. Levers the engine surfaces to close this gap:

- lower quota to ~$6,778,530 (makes coverage = 1.0), or
- reassign ~$6,112,078 of addressable potential into this book, or
- source ~343 more SQLs.

## The override hierarchy (a first-class feature)

Every conversion rate and average deal size the waterfall reads resolves as:

```
rep override  >  segment override  >  global default (conversions.csv)
```

The waterfall never reads a rate directly — it asks `core.overrides.resolve()`,
which also records *which tier* supplied each number, so `assess_territory` (and
the `/territory` endpoint) can show the audit trail. Example overrides payload:

```json
{
  "global":  {"Negotiation->Won": 0.28},
  "segment": {"Enterprise": {"Negotiation->Won": 0.25}},
  "rep":     {"R-105": {"avg_deal_size": 90000}}
}
```

With this, `R-105` uses its own deal size, every other Enterprise rep uses the
0.25 win rate, and everyone else falls back to the CSV default (reported as
`global`). "If enterprise win-rates drop to 25%, who breaks?" is exactly this.

## Quota by AE seniority level (a first-class lever)

Reps aren't interchangeable. Every rep carries a **seniority level** — `ramping`,
`AE`, `Sr. AE`, or `Sr. Strategic AE` — and each level carries a different quota
load. Stage 2 makes each raw quota proportional to the territory's potential
**times the rep's level multiplier**, then re-normalizes so the book still sums to
exactly the company target:

```
ramping 0.6 · AE 1.0 · Sr. AE 1.15 · Sr. Strategic AE 1.30   (config.LEVEL_QUOTA_MULTIPLIER)
```

Dialing one level up shifts *who carries the number* — a little more onto that
level, a little less onto everyone else — without changing the total. The
multipliers are overridable per call (`level_multipliers`) and editable live in
the dashboard's "Quota by seniority level" panel; the MCP `whatif_levels` tool
answers "if we load Sr. Strategic AEs 40% heavier, who runs short on pipeline?".
Because coverage is linear in quota, loading a level heavier drops its reps'
coverage proportionally — which is why the senior tiers, not the ramping reps, are
the ones under-covered at the default target.

## Compensation: accelerators & decelerators

Stage 4 pays variable comp on a **three-band curve** in attainment, every
parameter overridable (`comp`) and editable in the dashboard's "Compensation plan"
panel (with a live payout curve):

```
below decelerator_threshold  → rate × decelerator_multiplier   (< 1: under-attainment penalty)
up to accelerator_threshold  → rate                            (standard band)
above accelerator_threshold  → rate × accelerator_multiplier   (> 1: overperformance kicker)
```

optionally frozen at `cap_attainment`. Base salary is derived from the
base/variable OTE split, so `cost_of_sale = Σ total_comp / Σ bookings` reflects
fully-loaded comp. Defaults: a decelerator at 0.5× below 70% attainment and an
accelerator at 1.5× above 100%. Set the decelerator multiplier to 1.0 (or its
threshold to 0) and the model collapses back to a plain accelerator.

## API

Load the CSVs once at startup; each endpoint recomputes from a settings payload.
Interactive docs at `/docs`.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | the **interactive dashboard** (self-contained HTML, served same-origin) |
| `GET /api` | JSON service index; `GET /health` liveness probe |
| `GET /data/summary` | counts, total potential, segment/region mix |
| `GET /conversions` | per-segment default conversion rates + avg deal size (override-panel seed) |
| `GET /levels` | AE seniority levels, default quota multipliers, rep counts per level |
| `GET /comp/defaults` | default comp parameters (split, rate, decel/accel bands, cap) |
| `POST /balance` | Stage 1 — territories + balance scores for given weights |
| `POST /quota` | Stage 2 — quotas + fairness for a company target |
| `POST /waterfall` | Stage 3 — coverage results + under-covered roll-up |
| `POST /comp` | Stage 4 — payouts, cost-of-sale, scenarios, payout curve |
| `POST /plan` | the whole chain in one call (the dashboard's hot path) |
| `GET /territory/{rep_id}` | full single-territory detail (the assess view) |
| `POST /explain` | optional LLM rationale; skips cleanly with no API key |

## Agent / MCP

The same engine is exposed as an **MCP server** (`mcp_server.py`) so an agent can
interrogate a carve conversationally — "which territories can't hit quota and
why", "if I weight geo at 85%, who wins and loses", "if enterprise win-rates drop
to 25%, who breaks", "what does this cost at 85% attainment". The tools are thin,
**read-only** wrappers over the same `core` functions (JSON in, JSON out, zero LLM
calls, nothing persists — what-ifs recompute in memory). See **[EXAMPLES.md](EXAMPLES.md)**
for natural-language questions mapped to the tools they trigger.

Eleven tools: `plan_summary`, `list_territories`, `assess_territory`, `coverage_gaps`,
`whatif_weights`, `whatif_conversions`, `whatif_levels`, `comp_scenario`,
`get_scorecard`, `list_reps`, `list_segments`.

```bash
make mcp        # stdio (for Claude Desktop / claude mcp)
make mcp-http   # HTTP on $PORT, MCP_AUTH_TOKEN bearer auth (hosted use)
```

**Register with Claude Code** (stdio):

```bash
claude mcp add territory-designer -- /abs/path/to/.venv/bin/python /abs/path/to/mcp_server.py
```

**Claude Desktop** (`claude_desktop_config.json`) — use the venv's Python and an
absolute path; point `TERRITORY_DATA` at the CSV dir:

```json
{
  "mcpServers": {
    "territory-designer": {
      "command": "/abs/path/to/.venv/bin/python",
      "args": ["/abs/path/to/mcp_server.py"],
      "env": { "TERRITORY_DATA": "/abs/path/to/data" }
    }
  }
}
```

**Hosted (HTTP):** set `MCP_TRANSPORT=http` (or pass `--http`), bind to `$PORT`,
and set `MCP_AUTH_TOKEN` to require a `Authorization: Bearer <token>` header.

## Configuration

All tunable knobs live in `config.py` (weights, potential mix, segment-focus and
cap constraints, quota target multiple, per-level quota multipliers, coverage
band, and the three-band comp parameters) or come from the loaded CSVs — nothing
is hardcoded mid-logic. Every one of them is also overridable per API/MCP call.

## Deploy (Render)

`render.yaml` is a Blueprint defining two native-Python web services — both bind
`0.0.0.0:$PORT` (nothing hardcodes a port) and read the committed `data/` CSVs, so
there's no build-time data step:

- **`territory-quota-designer-api`** — `uvicorn api.main:app`; its root URL serves
  the interactive dashboard. `ANTHROPIC_API_KEY` is declared `sync:false`
  (optional; leave unset to run offline).
- **`territory-quota-designer-mcp`** — `python mcp_server.py --http`. Render
  generates `MCP_AUTH_TOKEN`; every request needs `Authorization: Bearer <token>`.

Point Render at the repo (New → Blueprint) and it provisions both from
`render.yaml`. Pushing to `main` triggers a redeploy.

## Project layout

```
generate_territory_data.py   synthetic data generator (do not rewrite)
data/                        accounts.csv · reps.csv · conversions.csv
config.py                    all tunable knobs
core/
  models.py                  Account · Rep · Territory · PlanResult
  dataio.py                  CSV → typed models
  potential.py               per-account opportunity value + coverage numerator
  overrides.py               rep > segment > global rate resolution
  balance.py                 Stage 1 optimizer + focus-respecting baseline
  quota.py                   Stage 2 quota derivation + fairness
  waterfall.py               Stage 3 reverse waterfall + coverage + gap analysis
  comp.py                    Stage 4 comp simulation
  evaluate.py                baseline-vs-optimized scorecard (make plan)
  plan.py                    run_plan orchestrator (the whole chain)
  views.py                   JSON-safe roll-up views (shared by API + MCP)
api/main.py                  FastAPI app (serves the dashboard + JSON endpoints)
api/static/index.html        self-contained interactive dashboard (served at /)
mcp_server.py                MCP server (10 read-only tools over core)
narrative.py                 optional LLM explanations (Anthropic)
EXAMPLES.md                  natural-language questions → MCP tool calls
tests/                       one file per core module + /plan + MCP tool tests
```

## Design principles

- **Deterministic core, explainable everywhere.** Every assignment, quota, and
  ratio is traceable to inputs a planner can verify.
- **Config over magic numbers.** Weights, constraints, conversion defaults, and
  comp parameters live in `config.py` or the CSVs.
- **Override hierarchy is first-class** — built explicitly, with the resolution
  tier reported alongside every number.
- **Baseline vs. optimized is the eval** — the before/after above is the artifact.
- **Pure, testable functions.** The OR core is unit-tested; a fixed seed → a
  reproducible carve.
