"""The capacity scorecard: work-back carve vs. naive, and the markdown block."""

from core import evaluate


def test_scorecard_has_all_sections(data):
    accounts, reps, _ = data
    sc = evaluate.build_scorecard(accounts, reps)
    for key in [
        "coverage_target",
        "company_target",
        "reps_covered",
        "capacity_gap",
        "coverage_floor",
        "off_home_share",
        "balance_score",
        "per_segment_capacity",
    ]:
        assert key in sc


def test_work_back_beats_naive_on_gap_and_floor(data):
    accounts, reps, _ = data
    sc = evaluate.build_scorecard(accounts, reps)
    # smaller total capacity gap and a higher (fairer) coverage floor
    assert sc["capacity_gap"]["optimized"] <= sc["capacity_gap"]["baseline"]
    assert sc["coverage_floor"]["optimized"] >= sc["coverage_floor"]["baseline"]
    assert sc["off_home_share"]["optimized"] <= sc["off_home_share"]["baseline"]


def test_per_segment_capacity_flags_the_thin_segment(data):
    accounts, reps, _ = data
    per_seg = evaluate.build_scorecard(accounts, reps)["per_segment_capacity"]
    # SMB holds less pipeline than its standardized quotas need at 3x
    assert per_seg["SMB"]["coverable"] is False
    assert per_seg["Enterprise"]["coverable"] and per_seg["Mid-Market"]["coverable"]


def test_markdown_renders_a_table(data):
    accounts, reps, _ = data
    sc = evaluate.build_scorecard(accounts, reps)
    md = evaluate.scorecard_markdown(sc)
    assert md.startswith("| Metric |")
    assert "capacity gap" in md.lower()
    assert md.count("\n") >= 4
