"""Rules D1-D4 and D6: thresholds, inclusivity, precedence, near-threshold confidence.

Ratio cases use ``ratio_case`` (labour and travel zeroed) so the cost ratio is
exactly part_price / 10000 and every boundary is hit exactly.
"""

import pytest

from app.policy import EXPECTED_LIFE_YEARS

from .conftest import case, ratio_case, run

# ------------------------------------------------------------------ D1a (60%, strict "exceeds")


@pytest.mark.parametrize("status", ["in_warranty", "extended"])
@pytest.mark.parametrize("price,expected", [
    (5000, "repair"), (6000, "repair"),   # exactly 60% is not "exceeds"
    (6001, "replace"), (9000, "replace"),
])
def test_d1a_threshold(status, price, expected):
    r = run(ratio_case(price, warranty_status=status))
    assert r.decision == expected
    assert r.trace["rule"] == "D1a"


# ------------------------------------------------------------------ D1b (21 days, strict "over")


@pytest.mark.parametrize("lead,expected,rule", [(21, "repair", "D1a"), (22, "replace", "D1b")])
def test_d1b_boundary(lead, expected, rule):
    data = ratio_case(1000, warranty_status="in_warranty")
    data["parts"][0]["lead_time_days"] = lead
    r = run(data)
    assert (r.decision, r.trace["rule"]) == (expected, rule)


def test_d1b_any_part_triggers():
    data = ratio_case(1000, warranty_status="extended")
    data["parts"].append({"sku": "SLOW", "price": 10, "lead_time_days": 40})
    r = run(data)
    assert r.decision == "replace" and "40 days" in r.reason and "D1b" in r.reason


def test_d1b_wins_regardless_of_cost():
    data = ratio_case(100, warranty_status="in_warranty")
    data["parts"][0]["lead_time_days"] = 30
    assert run(data).decision == "replace"


def test_d1b_does_not_apply_out_of_warranty():
    data = ratio_case(1000, warranty_status="out_of_warranty")
    data["parts"][0]["lead_time_days"] = 60
    assert run(data).decision == "repair"


def test_null_lead_time_does_not_fire_d1b_but_lowers_confidence():
    data = ratio_case(1000, warranty_status="in_warranty")
    data["parts"][0]["lead_time_days"] = None
    r = run(data)
    assert r.decision == "repair"
    assert r.confidence < 0.90
    assert any("lead time" in m for m in r.trace["missing_inputs"])


# ------------------------------------------------------------------ D2 (50% and 70% of life, "at most")


@pytest.mark.parametrize("price,expected", [(5000, "repair"), (5001, "replace")])
def test_d2_cost_boundary(price, expected):
    assert run(ratio_case(price)).decision == expected


@pytest.mark.parametrize("category,years", sorted(EXPECTED_LIFE_YEARS.items()))
def test_d2_age_boundary_every_category(category, years):
    limit = years * 12 * 0.7  # e.g. 84 months for a 10-year product
    at = run(ratio_case(1000, product_category=category, product_age_months=limit, fault_category="other"))
    over = run(ratio_case(1000, product_category=category, product_age_months=limit + 1, fault_category="other"))
    assert at.decision == "repair", category
    assert over.decision == "replace", category


def test_d2_non_integer_age_limit_is_exact():
    # dishwasher: 9 * 12 * 0.7 = 75.6 months -> 75 ok, 76 over
    assert run(ratio_case(1000, product_category="dishwasher", product_age_months=75, fault_category="other")).decision == "repair"
    assert run(ratio_case(1000, product_category="dishwasher", product_age_months=76, fault_category="other")).decision == "replace"


def test_d2_reason_mentions_age_when_age_decides():
    r = run(ratio_case(1000, product_age_months=100))
    assert r.decision == "replace" and "age" in r.reason and "D2" in r.reason


# ------------------------------------------------------------------ D3 (120 min and 40%, strict)


@pytest.mark.parametrize("status", ["in_warranty", "extended", "out_of_warranty", "unknown"])
def test_d3_replaces_whatever_the_warranty(status):
    r = run(ratio_case(4500, warranty_status=status, technician_travel_minutes=121, labour_rate_per_hour=0,
                       product_age_months=10))
    assert (r.decision, r.trace["rule"]) == ("replace", "D3")


@pytest.mark.parametrize("minutes,price,expected_rule", [
    (120, 4500, "D1a"),   # 120 is not "over 120"
    (121, 4000, "D1a"),   # exactly 40% is not "over 40%"
    (121, 4001, "D3"),
])
def test_d3_boundaries(minutes, price, expected_rule):
    r = run(ratio_case(price, warranty_status="in_warranty", technician_travel_minutes=minutes, labour_rate_per_hour=0))
    assert r.trace["rule"] == expected_rule


def test_d3_ratio_includes_travel_cost():
    # 3000 parts + 180 min at 600/h = 4800 -> 48% of 10000 and travel > 120 -> D3
    r = run(ratio_case(3000, warranty_status="in_warranty", technician_travel_minutes=180, labour_rate_per_hour=600))
    assert r.estimated_repair_cost == 4800.0 and r.trace["rule"] == "D3"


def test_d3_beats_d1_repair():
    r = run(ratio_case(5000, warranty_status="in_warranty", technician_travel_minutes=200, labour_rate_per_hour=0))
    assert r.decision == "replace" and r.trace["rule"] == "D3"


def test_null_travel_does_not_fire_d3():
    r = run(ratio_case(4500, warranty_status="in_warranty", technician_travel_minutes=None))
    assert r.decision == "repair" and r.trace["rule"] == "D1a"
    assert r.confidence < 0.90


# ------------------------------------------------------------------ D4 (unknown warranty, 24 months)


@pytest.mark.parametrize("age,path_rule,expected", [
    (24, "D1a", "repair"),     # 55%: in-warranty reading repairs (<= 60%)
    (25, "D2", "replace"),     # 55%: out-of-warranty reading replaces (> 50%)
])
def test_d4_mapping_boundary(age, path_rule, expected):
    r = run(ratio_case(5500, warranty_status="unknown", product_age_months=age))
    assert (r.decision, r.trace["rule"]) == (expected, path_rule)
    assert "D4" in r.reason


def test_d4_always_lowers_confidence():
    known = run(ratio_case(1000, warranty_status="out_of_warranty"))
    unknown = run(ratio_case(1000, warranty_status="unknown"))
    assert known.decision == unknown.decision == "repair"
    assert unknown.confidence < known.confidence


def test_missing_warranty_field_is_treated_as_unknown():
    data = ratio_case(1000)
    del data["warranty_status"]
    r = run(data)
    assert "D4" in r.reason and r.confidence < 0.90


def test_d4_with_missing_age_escalates_when_readings_disagree():
    r = run(ratio_case(1000, warranty_status="unknown", product_age_months=None))
    assert r.decision == "escalate" and "D4" in r.reason


def test_d4_with_missing_age_decides_when_both_readings_agree():
    r = run(ratio_case(7000, warranty_status="unknown", product_age_months=None))
    assert r.decision == "replace"   # 70% > 60% (D1a) and > 50% (D2)
    assert "both give replace" in r.reason


# ------------------------------------------------------------------ D6 near-threshold confidence


@pytest.mark.parametrize("price,status", [
    (5900, "in_warranty"), (6100, "in_warranty"),         # 59% / 61% around 60
    (4800, "out_of_warranty"), (5200, "out_of_warranty"),  # 48% / 52% around 50
])
def test_within_two_points_lowers_confidence_but_keeps_rule(price, status):
    r = run(ratio_case(price, warranty_status=status))
    assert r.trace["near_threshold"]
    assert r.confidence < (0.90 if r.decision == "repair" else 0.85)


@pytest.mark.parametrize("price,status", [(5700, "in_warranty"), (4700, "out_of_warranty")])
def test_three_points_away_is_not_near(price, status):
    assert not run(ratio_case(price, warranty_status=status)).trace["near_threshold"]


def test_two_points_means_absolute_percentage_points_not_relative():
    # 58.5% is 1.5 pp from 60% -> near. A "2% relative" reading would put the band
    # at 58.8-61.2% and wrongly call it not near.
    assert run(ratio_case(5850, warranty_status="in_warranty")).trace["near_threshold"]
    # 62.1% is 2.1 pp away -> not near, even though it is only 3.5% relative.
    assert not run(ratio_case(6210, warranty_status="in_warranty")).trace["near_threshold"]


def test_age_near_70_percent_lowers_confidence():
    # washing machine: 70% of 120 months = 84. 83 months = 69.2% -> near.
    r = run(ratio_case(1000, product_age_months=83))
    assert r.decision == "repair" and r.trace["near_threshold"]


def test_d3_threshold_only_counts_when_travel_is_over_120():
    # 41% sits near the 40% D3 threshold, but D3 is irrelevant at 30 minutes.
    r = run(ratio_case(4100, warranty_status="in_warranty", technician_travel_minutes=30))
    assert not r.trace["near_threshold"]


# ------------------------------------------------------------------ D5c replacement price


def test_null_replacement_price_escalates_when_ratio_decides():
    r = run(ratio_case(1000, replacement_price=None, warranty_status="in_warranty"))
    assert r.decision == "escalate" and "replacement price" in r.reason
    assert r.estimated_repair_cost == 1000.0   # cost is still computable and reported


def test_null_replacement_price_with_d1b_still_replaces():
    data = ratio_case(1000, replacement_price=None, warranty_status="in_warranty")
    data["parts"][0]["lead_time_days"] = 30
    r = run(data)
    assert (r.decision, r.trace["rule"]) == ("replace", "D1b")


def test_null_replacement_price_with_old_product_still_replaces():
    r = run(ratio_case(1000, replacement_price=None, product_age_months=110))
    assert (r.decision, r.trace["rule"]) == ("replace", "D2")


def test_zero_replacement_price_is_treated_as_unusable():
    r = run(ratio_case(1000, replacement_price=0, warranty_status="in_warranty"))
    assert r.decision == "escalate"


def test_null_age_out_of_warranty_cheap_repair_escalates():
    r = run(ratio_case(1000, product_age_months=None))
    assert r.decision == "escalate" and "age" in r.reason


def test_null_age_out_of_warranty_expensive_repair_replaces():
    r = run(ratio_case(8000, product_age_months=None))
    assert r.decision == "replace"


def test_missing_product_category_matters_only_for_d2_age():
    assert run(ratio_case(1000, product_category=None)).decision == "escalate"
    assert run(ratio_case(8000, product_category=None)).decision == "replace"
    assert run(ratio_case(1000, product_category=None, warranty_status="in_warranty")).decision == "repair"


# ------------------------------------------------------------------ general


def test_every_product_category_decides_a_plain_case():
    for category in EXPECTED_LIFE_YEARS:
        r = run(case(product_category=category, fault_category="other", symptom_text=""))
        assert r.decision == "repair", category


def test_confidence_always_in_unit_interval():
    for price in range(0, 20001, 250):
        for status in ("in_warranty", "extended", "out_of_warranty", "unknown"):
            c = run(ratio_case(price, warranty_status=status)).confidence
            assert 0.0 <= c <= 1.0


def test_identical_input_gives_identical_output():
    a, b = run(case()), run(case())
    assert a.public() == b.public() and a.trace == b.trace
