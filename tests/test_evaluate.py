"""The scorecard: baseline vs optimized, and the markdown block."""

from core import evaluate


def test_scorecard_has_all_sections(data):
    accounts, reps, conversions = data
    sc = evaluate.build_scorecard(accounts, reps, conversions)
    for key in [
        "balance_score",
        "geo_spread",
        "whitespace_cov",
        "per_segment_potential_cov",
        "combined_cost",
        "off_home_share",
        "coverage_flips",
        "company_target",
    ]:
        assert key in sc


def test_optimizer_is_no_worse_on_the_objective(data):
    accounts, reps, conversions = data
    sc = evaluate.build_scorecard(accounts, reps, conversions)
    assert sc["combined_cost"]["optimized"] <= sc["combined_cost"]["baseline"]
    assert sc["off_home_share"]["optimized"] <= sc["off_home_share"]["baseline"]


def test_coverage_flips_are_consistent(data):
    accounts, reps, conversions = data
    cov = evaluate.build_scorecard(accounts, reps, conversions)["coverage_flips"]
    assert cov["flips_under_to_covered"] >= 0
    assert cov["flips_under_to_covered"] <= cov["under_covered_baseline"]


def test_markdown_renders_a_table(data):
    accounts, reps, conversions = data
    sc = evaluate.build_scorecard(accounts, reps, conversions)
    md = evaluate.scorecard_markdown(sc)
    assert md.startswith("| Metric |")
    assert "Within-segment" in md
    assert md.count("\n") >= 5
