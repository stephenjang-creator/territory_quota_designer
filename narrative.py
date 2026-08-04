"""
narrative.py — optional LLM explanations (the ONLY component that touches the
Anthropic API).

Human-in-the-loop: the deterministic core owns every number. This layer only
*explains* a result the core already computed — "why is this rep under-covered",
"what drives this cost-of-sale" — grounded strictly in the result dict it is
handed. It never allocates an account, sets a quota, or invents/changes a number.

Degrades gracefully: with no `ANTHROPIC_API_KEY` (or no `anthropic` package),
`available()` is False and `explain()` returns a clear, non-fatal message so the
whole app still runs end to end offline.
"""

from __future__ import annotations

import json
import os

# Per SPEC.md; overridable. claude-sonnet-4-6 is a current, valid model id.
NARRATIVE_MODEL = os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 350

SYSTEM = (
    "You are a RevOps analyst explaining the output of a deterministic territory & "
    "quota planner to a sales planner. You will be given a JSON result the engine "
    "already computed. Explain it in plain English: what the numbers say and why, "
    "and — when relevant — what lever would change them.\n\n"
    "Hard rules:\n"
    "- Ground every statement ONLY in the provided JSON. Never invent or alter a "
    "number; quote the figures that are there.\n"
    "- You do not allocate accounts, set quotas, or pick numbers — the engine owns "
    "those. You only explain.\n"
    "- Be concrete and concise (a short paragraph). Frame coverage as pipeline "
    "adequacy/risk, not a guarantee of attainment."
)


def available() -> bool:
    """True if an explanation call could succeed (key present + SDK importable)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def explain(kind: str, payload: dict, question: str | None = None) -> dict:
    """Return a plain-English explanation of `payload` (a core result dict).

    `kind` is a short tag (e.g. "territory", "coverage_gaps", "comp") used only to
    frame the prompt. Never raises — returns ``{"error": ...}`` when disabled.
    """
    if not available():
        return {
            "narrative": None,
            "model": None,
            "error": "narrative disabled (set ANTHROPIC_API_KEY and install `anthropic` "
            "to enable); all numbers above are computed offline by the engine.",
        }

    import anthropic

    ask = question or f"Explain this {kind} result for a sales planner."
    user = f"{ask}\n\nResult JSON:\n{json.dumps(payload, default=str)}"

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=NARRATIVE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return {"narrative": text.strip(), "model": NARRATIVE_MODEL, "error": None}
    except Exception as e:  # never fail the request over an optional narrative
        return {"narrative": None, "model": NARRATIVE_MODEL, "error": f"narrative call failed: {e}"}
