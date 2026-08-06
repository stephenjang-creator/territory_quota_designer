"""
core — the deterministic Sales Plan Designer engine.

Four stages, each a pure, testable module:
    balance  -> quota  -> waterfall  -> comp
with `potential` + `overrides` as shared primitives, `evaluate` for the
baseline-vs-optimized scorecard, and `plan.run_plan` to run the whole chain.

The engine makes zero network calls and is reproducible given the data seed.
The (optional) LLM layer only ever *explains* these numbers — it never sets one.
"""
