"""
core/potential.py — per-account "opportunity value".

The single number Stage 1 balances and Stage 2 derives quota from. It is a
transparent weighted blend of the three signals in `config.POTENTIAL_MIX`, so a
planner can always decompose why a territory's potential is what it is.
"""

from __future__ import annotations

from collections.abc import Iterable

import config
from core.models import Account


def opportunity_value(account: Account, mix: dict | None = None) -> float:
    """Weighted blend of whitespace, open pipeline, and (discounted) current ARR."""
    m = mix or config.POTENTIAL_MIX
    return (
        account.whitespace_potential * m["whitespace"]
        + account.open_pipeline * m["pipeline"]
        + account.current_arr * m["current_arr"]
    )


def territory_potential(accounts: Iterable[Account], mix: dict | None = None) -> float:
    """Sum of opportunity value over a set of accounts."""
    return sum(opportunity_value(a, mix) for a in accounts)


def available_potential(accounts: Iterable[Account]) -> float:
    """Addressable pipeline a territory can actually close against a new-bookings
    quota: whitespace + open pipeline. Excludes installed ARR by design (it is not
    new pipeline) — this is the numerator of the Stage-3 coverage ratio.
    """
    return sum(a.whitespace_potential + a.open_pipeline for a in accounts)


def territory_whitespace(accounts: Iterable[Account]) -> float:
    """Sum of raw whitespace potential (the Stage-1 whitespace-balance signal)."""
    return sum(a.whitespace_potential for a in accounts)
