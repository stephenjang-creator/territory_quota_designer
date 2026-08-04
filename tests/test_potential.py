"""Stage-0 primitive: opportunity value + coverage numerator."""

from core.models import Account
from core.potential import (
    available_potential,
    opportunity_value,
    territory_potential,
    territory_whitespace,
)

MIX = {"whitespace": 1.0, "pipeline": 1.0, "current_arr": 0.25}


def _acct(ws, pipe, arr, seg="Enterprise", region="NA-West", aid="A-1"):
    return Account(
        account_id=aid,
        name="X",
        industry="Software",
        segment=seg,
        employees=100,
        annual_revenue=1e7,
        region=region,
        metro="Denver",
        current_arr=arr,
        whitespace_potential=ws,
        open_pipeline=pipe,
        propensity_score=0.5,
    )


def test_opportunity_value_is_documented_blend():
    a = _acct(ws=100_000, pipe=50_000, arr=40_000)
    # 100k*1 + 50k*1 + 40k*0.25 = 160k
    assert opportunity_value(a, MIX) == 160_000


def test_available_potential_excludes_current_arr():
    a = _acct(ws=100_000, pipe=50_000, arr=999_999)
    assert available_potential([a]) == 150_000  # arr never counts as new pipeline


def test_territory_rollups_sum_over_accounts():
    accts = [_acct(10, 20, 40, aid="A-1"), _acct(30, 40, 80, aid="A-2")]
    assert territory_potential(accts, MIX) == (10 + 20 + 10) + (30 + 40 + 20)
    assert territory_whitespace(accts) == 40
    assert available_potential(accts) == (10 + 20) + (30 + 40)


def test_potential_matches_default_mix_on_real_data(accounts):
    a = accounts[0]
    expected = a.whitespace_potential + a.open_pipeline + 0.25 * a.current_arr
    assert opportunity_value(a) == expected
