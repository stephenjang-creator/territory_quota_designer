"""The override hierarchy: rep > segment > global default (conversions.csv)."""

from core.overrides import resolve


def test_falls_back_to_csv_default_labeled_global(conversions):
    r = resolve("Negotiation->Won", "Enterprise", "R-101", conversions, None)
    assert r.value == conversions["Enterprise"]["Negotiation->Won"]
    assert r.level == "global"


def test_global_override_beats_csv_default():
    conv = {"Enterprise": {"Negotiation->Won": 0.30}}
    ovr = {"global": {"Negotiation->Won": 0.20}}
    r = resolve("Negotiation->Won", "Enterprise", "R-101", conv, ovr)
    assert r.value == 0.20 and r.level == "global"


def test_segment_override_beats_global():
    conv = {"Enterprise": {"Negotiation->Won": 0.30}}
    ovr = {
        "global": {"Negotiation->Won": 0.20},
        "segment": {"Enterprise": {"Negotiation->Won": 0.25}},
    }
    r = resolve("Negotiation->Won", "Enterprise", "R-101", conv, ovr)
    assert r.value == 0.25 and r.level == "segment"


def test_rep_override_wins_everything():
    conv = {"Enterprise": {"Negotiation->Won": 0.30}}
    ovr = {
        "segment": {"Enterprise": {"Negotiation->Won": 0.25}},
        "rep": {"R-101": {"Negotiation->Won": 0.40}},
    }
    r = resolve("Negotiation->Won", "Enterprise", "R-101", conv, ovr)
    assert r.value == 0.40 and r.level == "rep"
    # a different rep is unaffected -> falls to segment
    other = resolve("Negotiation->Won", "Enterprise", "R-102", conv, ovr)
    assert other.value == 0.25 and other.level == "segment"


def test_avg_deal_size_resolves_too(conversions):
    r = resolve("avg_deal_size", "SMB", "R-104", conversions, None)
    assert r.value == conversions["SMB"]["avg_deal_size"]
