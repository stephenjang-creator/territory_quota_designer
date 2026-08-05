"""
core/dataio.py — load the synthetic CSVs into typed models.

Pure I/O: read `accounts.csv`, `reps.csv`, `conversions.csv` from the data
directory (env `TERRITORY_DATA`, default `data/`) and return `Account`/`Rep`
objects plus a nested conversions dict. No business logic lives here.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import config
from core.models import Account, Rep

# transition -> next; the four rungs the reverse waterfall climbs.
TRANSITIONS = [
    "Discovery->Qualification",
    "Qualification->Proposal",
    "Proposal->Negotiation",
    "Negotiation->Won",
]
AVG_DEAL_KEY = "avg_deal_size"


def data_dir(path: str | os.PathLike | None = None) -> Path:
    """Resolve the CSV directory: explicit arg > env var > config default."""
    if path is not None:
        return Path(path)
    return Path(os.environ.get(config.DATA_DIR_ENV, config.DEFAULT_DATA_DIR))


def load_accounts(path: str | os.PathLike | None = None) -> list[Account]:
    p = data_dir(path) / "accounts.csv"
    with open(p, newline="") as fh:
        return [
            Account(
                account_id=r["account_id"],
                name=r["name"],
                industry=r["industry"],
                segment=r["segment"],
                employees=int(r["employees"]),
                annual_revenue=float(r["annual_revenue"]),
                region=r["region"],
                metro=r["metro"],
                current_arr=float(r["current_arr"]),
                whitespace_potential=float(r["whitespace_potential"]),
                open_pipeline=float(r["open_pipeline"]),
                propensity_score=float(r["propensity_score"]),
            )
            for r in csv.DictReader(fh)
        ]


def load_reps(path: str | os.PathLike | None = None) -> list[Rep]:
    p = data_dir(path) / "reps.csv"
    with open(p, newline="") as fh:
        return [
            Rep(
                rep_id=r["rep_id"],
                name=r["name"],
                segment_focus=r["segment_focus"],
                home_region=r["home_region"],
                home_metro=r["home_metro"],
                tenure_months=int(r["tenure_months"]),
                ramp_status=r["ramp_status"],
                # `level` is the seniority/quota-load tier; older data without the
                # column falls back to a segment-capped, tenure-derived default.
                level=(
                    r.get("level") or config.level_for(r["segment_focus"], int(r["tenure_months"]))
                ),
            )
            for r in csv.DictReader(fh)
        ]


def load_conversions(path: str | os.PathLike | None = None) -> dict[str, dict[str, float]]:
    """Return ``{segment: {transition: rate, ..., "avg_deal_size": float}}``.

    This is the *global default* tier of the override hierarchy; segment and rep
    overrides layer on top of it (see core/overrides.py).
    """
    p = data_dir(path) / "conversions.csv"
    out: dict[str, dict[str, float]] = {}
    with open(p, newline="") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r["segment"], {})[r["transition"]] = float(r["rate"])
    return out


def load_all(path: str | os.PathLike | None = None):
    """Convenience: ``(accounts, reps, conversions)`` in one call."""
    return load_accounts(path), load_reps(path), load_conversions(path)
