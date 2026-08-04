"""Shared pytest fixtures: load the synthetic data once per session."""

from __future__ import annotations

import pytest

from core.dataio import load_all
from core.plan import run_plan


@pytest.fixture(scope="session")
def data():
    return load_all()


@pytest.fixture(scope="session")
def accounts(data):
    return data[0]


@pytest.fixture(scope="session")
def reps(data):
    return data[1]


@pytest.fixture(scope="session")
def conversions(data):
    return data[2]


@pytest.fixture(scope="session")
def plan(data):
    accounts, reps, conversions = data
    return run_plan(accounts, reps, conversions)
