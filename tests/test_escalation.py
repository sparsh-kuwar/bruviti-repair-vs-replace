"""Rule D5 triggers and their precedence over D3/D1/D2 (D6)."""

import pytest

from .conftest import case, ratio_case, run

# ------------------------------------------------------------------ D5a repeat repairs + negative sentiment


@pytest.mark.parametrize("prior,sentiment,expected", [
    (2, "negative", "escalate"),
    (5, "negative", "escalate"),
    (1, "negative", "repair"),
    (2, "neutral", "repair"),
    (2, "positive", "repair"),
    (0, "negative", "repair"),
])
def test_d5a(prior, sentiment, expected):
    assert run(case(prior_repairs_12m=prior, customer_sentiment=sentiment)).decision == expected


def test_d5a_needs_positive_evidence_for_both_halves():
    # Missing sentiment with 2 repairs: trigger not confirmed -> decide, lower confidence.
    r = run(case(prior_repairs_12m=2, customer_sentiment=None))
    assert r.decision == "repair" and r.confidence < 0.90
    r = run(case(prior_repairs_12m=None, customer_sentiment="negative"))
    assert r.decision == "repair" and r.confidence < 0.90


# ------------------------------------------------------------------ D5b cost cannot be computed


def test_null_part_price_escalates_with_null_cost():
    r = run(case(parts=[{"sku": "X-1", "price": None, "lead_time_days": 3}]))
    assert r.decision == "escalate" and r.estimated_repair_cost is None
    assert "X-1" in r.reason


def test_null_labour_hours_escalates_with_null_cost():
    r = run(case(labour_hours=None))
    assert r.decision == "escalate" and r.estimated_repair_cost is None and "labour hours" in r.reason


def test_d5b_wins_even_when_d1b_would_replace():
    data = case(warranty_status="in_warranty",
                parts=[{"sku": "X", "price": None, "lead_time_days": 40}])
    assert run(data).decision == "escalate"


# ------------------------------------------------------------------ D5d safety hazard


def test_hazard_escalates_but_keeps_computable_cost():
    r = run(case(symptom_text="smoke coming from the back of the machine"))
    assert r.decision == "escalate" and r.estimated_repair_cost == 8150.0
    assert "smoke" in r.reason and "D5" in r.reason


def test_negated_hazard_does_not_escalate():
    assert run(case(symptom_text="no sparks or smoke, drum does not turn")).decision == "repair"


# ------------------------------------------------------------------ D5e contradiction


def test_brief_contradiction_example():
    r = run(case(product_category="refrigerator", fault_category="not_cooling",
                 symptom_text="the door will not close properly"))
    assert r.decision == "escalate" and "contradicts" in r.reason
    assert r.confidence == pytest.approx(0.60)


def test_unfamiliar_text_does_not_escalate():
    assert run(case(symptom_text="customer called twice about the unit, please visit")).decision == "repair"


def test_empty_and_long_text_do_not_escalate():
    assert run(case(symptom_text="")).decision == "repair"
    long_text = "drum does not turn and the motor hums loudly. " * 400
    assert run(case(symptom_text=long_text)).decision == "repair"


# ------------------------------------------------------------------ precedence


def test_escalation_beats_d3():
    r = run(ratio_case(5000, warranty_status="in_warranty", technician_travel_minutes=200,
                       labour_rate_per_hour=0, prior_repairs_12m=3, customer_sentiment="negative"))
    assert r.decision == "escalate"


def test_escalation_beats_d1b():
    data = case(warranty_status="in_warranty", symptom_text="sparks from the plug")
    data["parts"][0]["lead_time_days"] = 40
    assert run(data).decision == "escalate"


def test_escalation_beats_d2_replace():
    assert run(case(product_age_months=150, symptom_text="caught fire last night")).decision == "escalate"


def test_multiple_triggers_are_all_named_in_one_sentence():
    r = run(case(prior_repairs_12m=2, customer_sentiment="negative", labour_hours=None,
                 symptom_text="burning smell"))
    assert r.reason.count(".") == 1
    for fragment in ("safety hazard", "negative sentiment", "labour hours"):
        assert fragment in r.reason


def test_normal_cases_are_not_escalated():
    # Guard against the "escalate everything" failure mode the brief warns about.
    decisions = [run(ratio_case(p, warranty_status=s)).decision
                 for p in (1000, 4000, 5500, 7000) for s in ("in_warranty", "out_of_warranty")]
    assert "escalate" not in decisions


@pytest.mark.parametrize("text", ["sparkes from the plug point", "body mein current lag raha hai",
                                  "dhuaan nikal raha hai"])
def test_new_hazard_wording_beats_every_rule(text):
    # Would otherwise be: D2 repair, D1b replace, D3 replace.
    assert run(case(symptom_text=text)).decision == "escalate"
    d1b = case(warranty_status="in_warranty", symptom_text=text)
    d1b["parts"][0]["lead_time_days"] = 40
    assert run(d1b).decision == "escalate"
    assert run(ratio_case(5000, warranty_status="in_warranty", technician_travel_minutes=200,
                          labour_rate_per_hour=0, symptom_text=text)).decision == "escalate"


def test_negated_new_wording_keeps_normal_decision():
    assert run(case(symptom_text="dhuan nahi, chingari bhi nahi, drum does not turn")).decision == "repair"
