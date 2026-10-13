"""Offline text heuristics: safety hazards (with negation) and contradictions."""

import pytest

from app.text import detect_fault_topics, find_contradictions, find_safety_hazards, normalise

# ------------------------------------------------------------------ hazards: positives


@pytest.mark.parametrize("text,kind", [
    ("sparks from outlet", "sparks"),
    ("Sparking near the plug!!", "sparks"),
    ("it sparked when switched on", "sparks"),
    ("arcing inside the cavity", "sparks"),
    ("burning smell and smoke", "smoke"),
    ("SMOKE coming from the back", "smoke"),
    ("unit was smoking", "smoke"),
    ("gas smell in the kitchen", "gas smell"),
    ("smells of gas near the hob", "gas smell"),
    ("strong smell like gas", "gas smell"),
    ("electric shock when touching the door", "electric shock"),
    ("it shocked me", "electric shock"),
    ("I got a mild shock from the tap", "electric shock"),
    ("getting current from the body of the machine", "electric shock"),
    ("caught fire", "fire"),
    ("caught on fire last night", "fire"),
    ("flames at the back", "fire"),
    ("smells like something burning", "fire"),
    ("burnt odour from the vents", "fire"),
])
def test_hazard_detected(text, kind):
    assert kind in [h.kind for h in find_safety_hazards(text)]


# ------------------------------------------------------------------ hazards: negatives / negation


@pytest.mark.parametrize("text", [
    "no sparks or smoke",
    "No sparks, smoke or burning smell.",
    "There was NO SMOKE",
    "did not see any smoke",
    "customer says it isn't sparking",
    "without any sparks",
    "never caught fire",
    "no gas smell",
    "smoke: none",
    "fireplace model next to the unit",
    "shock absorbers worn, loud banging",
    "ignition clicks but burner will not light",
    "drum does not turn, motor hums",
    "",
])
def test_no_hazard(text):
    assert find_safety_hazards(text) == []


@pytest.mark.parametrize("text,kind", [
    ("not cooling, sparks from plug", "sparks"),        # negation scoped to "cooling"
    ("no smoke but there are sparks", "sparks"),         # "but" ends the scope
    ("no smoke, burning smell from the back", "fire"),   # comma without "or" ends scope
    ("will not start and smokes", "smoke"),
    ("no power and sparks at the socket", "sparks"),
])
def test_negation_does_not_leak_to_other_clauses(text, kind):
    assert kind in [h.kind for h in find_safety_hazards(text)]


def test_gas_leak_means_refrigerant_for_cooling_appliances():
    assert find_safety_hazards("gas leak, needs refill", "air_conditioner") == []
    assert [h.kind for h in find_safety_hazards("gas leak from pipe", "oven_or_cooktop")] == ["gas leak"]
    # A gas *smell* is a hazard for every category.
    assert find_safety_hazards("smell of gas", "refrigerator")


def test_normalise_contractions():
    assert normalise("Won't start, doesn't heat, can't open") == "will not start, does not heat, cannot open"
    assert normalise("wont start, doesnt heat") == "will not start, does not heat"
    assert normalise("element") == "element"  # words ending in -nt are untouched


# ------------------------------------------------------------------ contradictions: fault family
# One clearly-matching and one clearly-conflicting text for each of the 12 categories.

MATCHING = {
    "no_power": "completely dead, will not turn on",
    "not_heating": "water stays cold, element not heating",
    "not_cooling": "fridge warm, food spoiled",
    "water_leak": "puddle of water under the machine, leaking",
    "drainage_or_blockage": "water will not drain, filter clogged",
    "noise_or_vibration": "loud rattling noise and vibration",
    "door_seal_or_latch": "door will not close, latch broken",
    "control_panel_or_display": "display blank and buttons unresponsive",
    "electrical_or_control_board": "control board fault, breaker trips",
    "motor_or_drive": "drum does not spin, motor hums",
    "installation_or_setup": "new unit not installed correctly, hose connection loose",
    "other": "customer reports an odd issue",
}
CONFLICTING = {
    "no_power": "door will not close",
    "not_heating": "door seal torn",
    "not_cooling": "door will not close",
    "water_leak": "display blank and buttons unresponsive",
    "drainage_or_blockage": "door latch broken",
    "noise_or_vibration": "door latch broken",
    "door_seal_or_latch": "loud grinding noise",
    "control_panel_or_display": "puddle of water on the floor",
    "electrical_or_control_board": "door seal torn",
    "motor_or_drive": "display flickering",
    "installation_or_setup": None,  # wildcard: installation faults surface as anything
    "other": None,                  # wildcard
}


@pytest.mark.parametrize("fault", sorted(MATCHING))
def test_matching_text_is_consistent(fault):
    assert find_contradictions(MATCHING[fault], fault, None, None) == []


@pytest.mark.parametrize("fault", sorted(CONFLICTING))
def test_conflicting_text_is_flagged(fault):
    text = CONFLICTING[fault]
    if text is None:
        assert find_contradictions("door will not close", fault, None, None) == []
    else:
        found = find_contradictions(text, fault, None, None)
        assert [c.field for c in found] == ["fault_category"], (fault, text)


def test_brief_example_not_cooling_vs_door():
    found = find_contradictions("door won't close", "not_cooling", "refrigerator", "in_warranty")
    assert found and found[0].field == "fault_category"


def test_related_symptoms_are_not_contradictions():
    # door problem that ALSO mentions the declared symptom
    assert find_contradictions("door will not close so the fridge is warm", "not_cooling", None, None) == []
    # physically linked families
    assert find_contradictions("water will not drain", "water_leak", None, None) == []
    assert find_contradictions("loud grinding from the motor", "noise_or_vibration", None, None) == []
    assert find_contradictions("display dead, nothing happens", "no_power", None, None) == []


def test_unfamiliar_wording_is_not_a_contradiction():
    assert find_contradictions("customer unhappy, please call back", "not_cooling", None, None) == []
    assert detect_fault_topics(normalise("asdf qwerty")) == []


# ------------------------------------------------------------------ contradictions: product and warranty


def test_text_naming_another_appliance_contradicts_product():
    found = find_contradictions("dishwasher will not drain", "drainage_or_blockage", "washing_machine", None)
    assert [c.field for c in found] == ["product_category"]


def test_text_naming_the_same_appliance_is_fine():
    assert find_contradictions("microwave oven sparks", "other", "microwave", None) == []
    assert find_contradictions("my fridge freezer is warm", "not_cooling", "refrigerator", None) == []
    assert find_contradictions("geyser not heating", "not_heating", "water_heater", None) == []


def test_warranty_text_contradicts_field():
    assert find_contradictions("warranty expired last year", "other", None, "in_warranty")[0].field == "warranty_status"
    assert find_contradictions("still under warranty", "other", None, "out_of_warranty")[0].field == "warranty_status"
    assert find_contradictions("not under warranty", "other", None, "out_of_warranty") == []
    assert find_contradictions("warranty expired", "other", None, "unknown") == []
