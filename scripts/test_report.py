"""Generate the tester-facing sections of TESTING.md from a real pytest run.

    python scripts/test_report.py                 # run pytest, rewrite generated sections of TESTING.md
    python scripts/test_report.py --junit j.xml   # use an existing JUnit file instead of running pytest
    python scripts/test_report.py --junit j.xml --summary   # print a Markdown summary (CI step summary)
    python scripts/test_report.py --with-e2e      # also run the browser tests (needs requirements-e2e.txt)
    python scripts/test_report.py --e2e-junit e.xml --summary-e2e   # browser summary for CI

The test-case catalogue and the traceability matrix below are maintained by
hand; their "Actual" and "Status" columns are filled from the JUnit results, so
the document can never claim a pass that did not happen. The script exits
non-zero if any test failed, or if a catalogue row points at a test that does
not exist (so the catalogue cannot silently rot).
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
TESTING_MD = ROOT / "TESTING.md"

# ---------------------------------------------------------------------- requirements
# (id, requirement, source, node-id substrings that cover it)
REQUIREMENTS: List[Tuple[str, str, str, List[str]]] = [
    ("R01", "POST /decide accepts one JSON case and returns JSON", "Brief §3",
     ["test_api.py::test_response_has_exactly_the_contract_fields", "test_examples.py"]),
    ("R02", "Response has exactly case_id, decision, estimated_repair_cost, confidence, reason", "Brief §3",
     ["test_api.py::test_response_has_exactly_the_contract_fields", "test_api.py::test_each_field_missing"]),
    ("R03", "case_id is echoed unchanged", "Brief §3", ["test_api.py::test_case_id_echoed_unchanged"]),
    ("R04", "decision is one of repair / replace / escalate", "Brief §3",
     ["test_api.py::test_response_has_exactly_the_contract_fields", "test_corpora.py"]),
    ("R05", "confidence is a number in [0, 1]", "Brief §3",
     ["test_rules.py::test_confidence_always_in_unit_interval", "test_api.py::test_each_field_missing"]),
    ("R06", "reason is one sentence naming the deciding rule", "Brief §3",
     ["test_examples.py::test_c200", "test_escalation.py::test_multiple_triggers_are_all_named"]),
    ("R07", "GET /health returns 200 {\"status\": \"ok\"}", "Brief §4", ["test_api.py::test_health"]),
    ("R08", "Single page served at / by the same process; no remote assets", "Brief §4–5",
     ["test_api.py::test_index_serves_the_ui", "test_api.py::test_ui_has_no_remote_assets"]),
    ("R09", "Works with the network off; tests run offline", "Brief §4–5", ["tests/"]),
    ("R10", "Each request answered in under 1 second", "Brief §4", ["test_api.py::test_latency"]),
    ("R11", "D0 repair-cost formula; null only when it cannot be computed", "Appendix D0",
     ["test_cost.py", "test_escalation.py::test_null_part_price", "test_escalation.py::test_null_labour"]),
    ("R12", "D1a in/extended warranty: replace if cost > 60% of replacement", "Appendix D1",
     ["test_rules.py::test_d1a_threshold"]),
    ("R13", "D1b replace if any required part lead time > 21 days", "Appendix D1",
     ["test_rules.py::test_d1b", "test_rules.py::test_null_lead_time"]),
    ("R14", "D2 out of warranty: repair iff cost <= 50% and age <= 70% of life", "Appendix D2, E",
     ["test_rules.py::test_d2_"]),
    ("R15", "D3 travel > 120 min and cost > 40% -> replace, any warranty", "Appendix D3",
     ["test_rules.py::test_d3_", "test_rules.py::test_null_travel"]),
    ("R16", "D4 unknown warranty mapped by age (> 24 months), lower confidence", "Appendix D4",
     ["test_rules.py::test_d4_", "test_rules.py::test_missing_warranty_field"]),
    ("R17", "D5 escalate: >= 2 repairs and negative sentiment", "Appendix D5", ["test_escalation.py::test_d5a"]),
    ("R18", "D5 escalate: null part price or labour hours", "Appendix D5",
     ["test_escalation.py::test_null_", "test_escalation.py::test_d5b"]),
    ("R19", "D5 escalate: replacement price null and the decision depends on it", "Appendix D5",
     ["test_rules.py::test_null_replacement", "test_rules.py::test_zero_replacement",
      "test_rules.py::test_null_age", "test_rules.py::test_missing_product_category"]),
    ("R20", "D5 escalate: safety hazard in symptom text (negation-aware)", "Appendix D5",
     ["test_text.py::test_hazard_detected", "test_text.py::test_no_hazard", "test_text.py::test_negation",
      "test_text.py::test_spelling", "test_text.py::test_variants", "test_text.py::test_mixed",
      "test_escalation.py::test_hazard", "test_escalation.py::test_negated", "test_escalation.py::test_new_hazard"]),
    ("R21", "D5 escalate: symptom text contradicts structured fields", "Appendix D5",
     ["test_text.py::test_matching", "test_text.py::test_conflicting", "test_text.py::test_brief_example",
      "test_text.py::test_related", "test_text.py::test_unfamiliar", "test_text.py::test_text_naming",
      "test_text.py::test_warranty_text", "test_escalation.py::test_brief_contradiction"]),
    ("R22", "D6 precedence: D5 > D3 > D1/D2", "Appendix D6",
     ["test_escalation.py::test_escalation_beats", "test_rules.py::test_d3_beats",
      "test_api.py::test_trace_stages"]),
    ("R23", "D6 within 2 percentage points: decide by rule, lower confidence", "Appendix D6",
     ["test_rules.py::test_within_two_points", "test_rules.py::test_three_points",
      "test_rules.py::test_two_points", "test_rules.py::test_age_near", "test_rules.py::test_d3_threshold_only"]),
    ("R24", "Invalid input rejected cleanly (422), never a 500", "Design (NOTES 9)",
     ["test_api.py::test_invalid_input", "test_api.py::test_nan_and", "test_api.py::test_malformed",
      "test_api.py::test_array_body", "test_api.py::test_unknown_abbreviations"]),
    ("R25", "Tolerant of format: enum spelling, synonyms, abbreviations, numeric strings", "Design (NOTES 9)",
     ["test_api.py::test_enum_spelling", "test_api.py::test_numbers_as_strings", "test_api.py::test_us_spelling",
      "test_api.py::test_extra_fields", "test_api.py::test_warranty_abbreviations", "test_api.py::test_oow"]),
    ("R26", "Missing fields never crash; escalate only when the answer depends on them", "Brief §3, NOTES 3",
     ["test_api.py::test_each_field_missing", "test_api.py::test_minimal_payload"]),
    ("R27", "The three worked examples match the brief", "Brief §3", ["test_examples.py"]),
    ("R28", "Deterministic: identical input gives identical output", "Design", [
        "test_rules.py::test_identical_input", "test_api.py::test_deterministic", "test_corpora.py::test_generator"]),
    ("R29", "Does not escalate everything", "Brief §3 (metric)",
     ["test_escalation.py::test_normal_cases", "test_escalation.py::test_unfamiliar", "test_corpora.py"]),
    ("R30", "Behaviour on unseen styles of data (challenge set)", "Brief §4 ('will not look like yours')",
     ["test_challenge.py"]),
    ("R31", "Starts from a fresh clone with one command; /health ready within a bounded time; Python 3.9-3.14",
     "Brief §4 ('runs from a fresh clone')", ["test_startup.py"]),
    ("R32", "Correct under concurrent requests; capacity and breaking point measured (TESTING §6)", "Design",
     ["test_concurrency.py"]),
]

# ---------------------------------------------------------------------- catalogue
# (id, requirement, technique, title, input, expected, node id)
CATALOGUE: List[Tuple[str, str, str, str, str, str, str]] = [
    # API contract
    ("TC-001", "R07", "Smoke", "Health check", "GET /health", "200, {\"status\":\"ok\"}", "tests/test_api.py::test_health"),
    ("TC-002", "R08", "Smoke", "UI served at /", "GET /, /static/app.js, /static/app.css", "200, HTML page with the case form", "tests/test_api.py::test_index_serves_the_ui"),
    ("TC-003", "R08", "Static check", "No remote assets in the UI", "all files in app/static", "no http(s) src/href, @import or remote fetch", "tests/test_api.py::test_ui_has_no_remote_assets"),
    ("TC-004", "R02", "Contract", "Exact response fields", "valid case", "keys = the 5 contract fields; reason ends with '.'", "tests/test_api.py::test_response_has_exactly_the_contract_fields"),
    ("TC-005", "R03", "Equivalence", "case_id echo: unicode", "case_id 'ünïcode-✓'", "same value returned", "tests/test_api.py::test_case_id_echoed_unchanged[unicode]"),
    ("TC-006", "R03", "Equivalence", "case_id echo: integer", "case_id 12345", "12345 returned as a number", "tests/test_api.py::test_case_id_echoed_unchanged[integer]"),
    ("TC-007", "R10", "Performance", "Latency under load-ish input", "200 parts, long text, 20 requests", "< 0.25 s per request", "tests/test_api.py::test_latency_well_under_one_second"),
    ("TC-008", "R28", "Repeatability", "Deterministic over HTTP", "same case x20", "one distinct response", "tests/test_api.py::test_deterministic_over_http"),
    # brief examples
    ("TC-010", "R27", "Oracle (brief)", "Example C-2001", "examples/C-2001.request.json", "repair, 8150.0, 0.9", "tests/test_examples.py::test_brief_example_matches_expected[C-2001]"),
    ("TC-011", "R27", "Oracle (brief)", "Example C-2002", "examples/C-2002.request.json", "replace, 16675.0, 0.85", "tests/test_examples.py::test_brief_example_matches_expected[C-2002]"),
    ("TC-012", "R27", "Oracle (brief)", "Example C-2003", "examples/C-2003.request.json", "escalate, null, 0.7", "tests/test_examples.py::test_brief_example_matches_expected[C-2003]"),
    ("TC-013", "R06", "Oracle (brief)", "C-2001 reason text", "C-2001", "identical to the brief's reason (rule D2)", "tests/test_examples.py::test_c2001_reason_names_d2"),
    # cost
    ("TC-020", "R11", "Oracle (brief)", "D0 formula, example 1", "6200 + 1.5h x 900 + 40 min", "8150.0", "tests/test_cost.py::test_formula_example_1"),
    ("TC-021", "R11", "Spec ambiguity", "Travel not doubled", "60 min travel at 900/h, no parts/labour", "900.0 (not 1800)", "tests/test_cost.py::test_travel_is_not_doubled"),
    ("TC-022", "R11", "Equivalence", "Duplicate SKUs summed", "A 100, A 100, B 50.5", "250.5", "tests/test_cost.py::test_multiple_parts_and_duplicate_skus_are_all_summed"),
    ("TC-023", "R11", "Boundary", "Zero vs null", "no parts, 0 labour, 0 travel", "0.0 (computable, not null)", "tests/test_cost.py::test_zero_everything_is_zero_not_null"),
    ("TC-024", "R11", "Negative", "Null part price", "part price null", "cost null; SKU named", "tests/test_cost.py::test_null_part_price_makes_cost_uncomputable"),
    ("TC-025", "R11", "Negative", "Null travel", "travel null", "cost computed without travel", "tests/test_cost.py::test_null_travel_still_computes_without_travel_component"),
    ("TC-026", "R11", "Precision", "No float drift", "prices 0.1 + 0.2", "exactly 3/10", "tests/test_cost.py::test_exact_arithmetic_has_no_float_drift"),
    # D1
    ("TC-030", "R12", "Boundary", "D1a exactly 60%", "in_warranty, cost 6000 / 10000", "repair (60% is not 'exceeds')", "tests/test_rules.py::test_d1a_threshold[6000-repair-in_warranty]"),
    ("TC-031", "R12", "Boundary", "D1a just over 60%", "in_warranty, cost 6001 / 10000", "replace", "tests/test_rules.py::test_d1a_threshold[6001-replace-in_warranty]"),
    ("TC-032", "R12", "Equivalence", "D1a for extended warranty", "extended, 60.01%", "replace", "tests/test_rules.py::test_d1a_threshold[6001-replace-extended]"),
    ("TC-033", "R13", "Boundary", "D1b lead time 21 days", "in_warranty, lead 21", "repair (D1a)", "tests/test_rules.py::test_d1b_boundary[21-repair-D1a]"),
    ("TC-034", "R13", "Boundary", "D1b lead time 22 days", "in_warranty, lead 22", "replace (D1b)", "tests/test_rules.py::test_d1b_boundary[22-replace-D1b]"),
    ("TC-035", "R13", "Decision table", "D1b not applied out of warranty", "out_of_warranty, lead 60", "repair", "tests/test_rules.py::test_d1b_does_not_apply_out_of_warranty"),
    ("TC-036", "R13", "Negative", "Null lead time", "in_warranty, lead null, 10%", "repair, lower confidence", "tests/test_rules.py::test_null_lead_time_does_not_fire_d1b_but_lowers_confidence"),
    # D2
    ("TC-040", "R14", "Boundary", "D2 exactly 50%", "out_of_warranty, 50.00%", "repair", "tests/test_rules.py::test_d2_cost_boundary[5000-repair]"),
    ("TC-041", "R14", "Boundary", "D2 just over 50%", "out_of_warranty, 50.01%", "replace", "tests/test_rules.py::test_d2_cost_boundary[5001-replace]"),
    ("TC-042", "R14", "Boundary", "D2 age at 70% of life (washer)", "84 months vs 85 months", "repair at 84, replace at 85", "tests/test_rules.py::test_d2_age_boundary_every_category[washing_machine-10]"),
    ("TC-043", "R14", "Boundary", "D2 non-integer age limit (dishwasher)", "75 vs 76 months (limit 75.6)", "repair, then replace", "tests/test_rules.py::test_d2_non_integer_age_limit_is_exact"),
    # D3
    ("TC-050", "R15", "Boundary", "D3 travel 120 min", "120 min, 45%", "D3 not applied (D1a)", "tests/test_rules.py::test_d3_boundaries[120-4500-D1a]"),
    ("TC-051", "R15", "Boundary", "D3 cost exactly 40%", "121 min, 40.00%", "D3 not applied (D1a)", "tests/test_rules.py::test_d3_boundaries[121-4000-D1a]"),
    ("TC-052", "R15", "Boundary", "D3 fires", "121 min, 40.01%", "replace (D3)", "tests/test_rules.py::test_d3_boundaries[121-4001-D3]"),
    ("TC-053", "R15", "Decision table", "D3 regardless of warranty", "unknown warranty, 121 min, 45%", "replace (D3)", "tests/test_rules.py::test_d3_replaces_whatever_the_warranty[unknown]"),
    ("TC-054", "R15", "Negative", "Null travel does not fire D3", "travel null, 45%", "repair (D1a), lower confidence", "tests/test_rules.py::test_null_travel_does_not_fire_d3"),
    # D4
    ("TC-060", "R16", "Boundary", "D4 age 24 months", "unknown, 24 months, 55%", "in-warranty reading: repair (D1a)", "tests/test_rules.py::test_d4_mapping_boundary[24-D1a-repair]"),
    ("TC-061", "R16", "Boundary", "D4 age 25 months", "unknown, 25 months, 55%", "out-of-warranty reading: replace (D2)", "tests/test_rules.py::test_d4_mapping_boundary[25-D2-replace]"),
    ("TC-062", "R16", "Negative", "D4 with no age, readings disagree", "unknown, age null, 10%", "escalate", "tests/test_rules.py::test_d4_with_missing_age_escalates_when_readings_disagree"),
    ("TC-063", "R16", "Negative", "D4 with no age, readings agree", "unknown, age null, 70%", "replace", "tests/test_rules.py::test_d4_with_missing_age_decides_when_both_readings_agree"),
    # D5
    ("TC-070", "R17", "Boundary", "D5a two repairs + negative", "prior 2, negative", "escalate", "tests/test_escalation.py::test_d5a[2-negative-escalate]"),
    ("TC-071", "R17", "Boundary", "D5a one repair + negative", "prior 1, negative", "repair", "tests/test_escalation.py::test_d5a[1-negative-repair]"),
    ("TC-072", "R17", "Decision table", "D5a two repairs + neutral", "prior 2, neutral", "repair", "tests/test_escalation.py::test_d5a[2-neutral-repair]"),
    ("TC-073", "R18", "Negative", "D5b null labour hours", "labour_hours null", "escalate, cost null", "tests/test_escalation.py::test_null_labour_hours_escalates_with_null_cost"),
    ("TC-074", "R18", "Precedence", "D5b beats D1b", "part price null, lead 40", "escalate", "tests/test_escalation.py::test_d5b_wins_even_when_d1b_would_replace"),
    ("TC-075", "R19", "Negative", "Replacement null, ratio decides", "in_warranty, replacement null", "escalate; cost still reported", "tests/test_rules.py::test_null_replacement_price_escalates_when_ratio_decides"),
    ("TC-076", "R19", "Decision table", "Replacement null, D1b decides", "replacement null, lead 30", "replace (D1b)", "tests/test_rules.py::test_null_replacement_price_with_d1b_still_replaces"),
    ("TC-077", "R19", "Decision table", "Replacement null, age decides", "replacement null, age 110 months", "replace (D2)", "tests/test_rules.py::test_null_replacement_price_with_old_product_still_replaces"),
    ("TC-078", "R20", "Equivalence", "Hazard: sparks", "'sparks from outlet'", "sparks detected", "tests/test_text.py::test_hazard_detected[sparks from outlet-sparks]"),
    ("TC-079", "R20", "Equivalence", "Hazard: gas smell variant", "'smells of gas near the hob'", "gas smell detected", "tests/test_text.py::test_hazard_detected[smells of gas near the hob-gas smell]"),
    ("TC-080", "R20", "Regression (DEF-02)", "Hazard: verb + words + shock", "'the casing gave my son a shock'", "electric shock detected", "tests/test_text.py::test_hazard_detected[the casing gave my son a shock-electric shock]"),
    ("TC-081", "R20", "Negative", "Negated hazard list", "'No sparks, smoke or burning smell.'", "no hazard", "tests/test_text.py::test_no_hazard[No sparks, smoke or burning smell.]"),
    ("TC-082", "R20", "Negative", "False friend: shock absorber", "'shock absorbers worn, loud banging'", "no hazard", "tests/test_text.py::test_no_hazard[shock absorbers worn, loud banging]"),
    ("TC-083", "R20", "Negative", "False friend: fireplace", "'fireplace model next to the unit'", "no hazard", "tests/test_text.py::test_no_hazard[fireplace model next to the unit]"),
    ("TC-084", "R20", "Scope", "Negation does not cross clauses", "'not cooling, sparks from plug'", "sparks detected", "tests/test_text.py::test_negation_does_not_leak_to_other_clauses[not cooling, sparks from plug-sparks]"),
    ("TC-085", "R20", "Regression (DEF-04)", "Misspelt hazard", "'sparkes from the plug point'", "sparks detected", "tests/test_text.py::test_spelling_variant_and_hinglish_hazards[sparkes from the plug point-sparks]"),
    ("TC-086", "R20", "Regression (DEF-05)", "Hinglish shock", "'body mein current lag raha hai'", "electric shock detected", "tests/test_text.py::test_spelling_variant_and_hinglish_hazards[body mein current lag raha hai-electric shock]"),
    ("TC-087", "R20", "Regression (DEF-07)", "Hinglish negation", "'koi dhuan nahi, chingari bhi nahi'", "no hazard", "tests/test_text.py::test_variants_do_not_create_false_hazards[koi dhuan nahi, chingari bhi nahi]"),
    ("TC-088", "R20", "Negative", "False friend: 'current bill'", "'current bill is very high'", "no hazard", "tests/test_text.py::test_variants_do_not_create_false_hazards[current bill is very high]"),
    ("TC-089", "R20", "System", "Hazard escalates, cost kept", "'smoke coming from the back…'", "escalate, cost 8150.0", "tests/test_escalation.py::test_hazard_escalates_but_keeps_computable_cost"),
    ("TC-090", "R21", "Oracle (brief)", "Brief contradiction example", "not_cooling + 'door will not close'", "escalate, confidence 0.60", "tests/test_escalation.py::test_brief_contradiction_example"),
    ("TC-091", "R21", "Negative", "Related symptoms not contradictory", "'door will not close so the fridge is warm'", "no contradiction", "tests/test_text.py::test_related_symptoms_are_not_contradictions"),
    ("TC-092", "R21", "Negative", "Unfamiliar wording", "'customer unhappy, please call back'", "no contradiction", "tests/test_text.py::test_unfamiliar_wording_is_not_a_contradiction"),
    ("TC-093", "R21", "Equivalence", "Text names another appliance", "washing_machine + 'dishwasher will not drain'", "product contradiction", "tests/test_text.py::test_text_naming_another_appliance_contradicts_product"),
    ("TC-094", "R21", "Equivalence", "Warranty stated in text", "in_warranty + 'warranty expired'", "warranty contradiction", "tests/test_text.py::test_warranty_text_contradicts_field"),
    # D6
    ("TC-100", "R22", "Precedence", "Escalation beats D3", "D3 conditions + D5a", "escalate", "tests/test_escalation.py::test_escalation_beats_d3"),
    ("TC-101", "R22", "Precedence", "Escalation beats D1b", "lead 40 + 'sparks from the plug'", "escalate", "tests/test_escalation.py::test_escalation_beats_d1b"),
    ("TC-102", "R22", "Precedence", "D3 beats D1 repair", "in_warranty 50%, travel 200", "replace (D3)", "tests/test_rules.py::test_d3_beats_d1_repair"),
    ("TC-103", "R23", "Boundary", "Near threshold (absolute pp)", "58.5% and 62.1% vs 60%", "near flagged at 58.5% only", "tests/test_rules.py::test_two_points_means_absolute_percentage_points_not_relative"),
    ("TC-104", "R23", "Boundary", "Near threshold lowers confidence", "in_warranty 59%", "repair, confidence < 0.90", "tests/test_rules.py::test_within_two_points_lowers_confidence_but_keeps_rule[5900-in_warranty]"),
    # validation / robustness
    ("TC-110", "R24", "Negative", "Unknown enum", "product_category 'toaster'", "422 with field location", "tests/test_api.py::test_invalid_input_is_a_clean_422[unknown-product]"),
    ("TC-111", "R24", "Negative", "Negative price", "replacement_price -1", "422", "tests/test_api.py::test_invalid_input_is_a_clean_422[negative-replacement-price]"),
    ("TC-112", "R24", "Regression (DEF-01)", "NaN input", "raw JSON with NaN", "422 (was 500)", "tests/test_api.py::test_nan_and_infinity_rejected[nan]"),
    ("TC-113", "R24", "Negative", "Malformed JSON", "'{not json'", "422", "tests/test_api.py::test_malformed_json_is_422"),
    ("TC-114", "R24", "Negative", "Missing case_id", "body without case_id", "422", "tests/test_api.py::test_invalid_input_is_a_clean_422[missing-case-id]"),
    ("TC-115", "R25", "Format", "Enum spelling variants", "'Washing Machine', 'Out-of-Warranty'", "normalised; repair", "tests/test_api.py::test_enum_spelling_and_synonyms_are_normalised"),
    ("TC-116", "R25", "Format", "Numbers as strings", "'36,000', 'Rs 900'", "accepted; cost 8150.0", "tests/test_api.py::test_numbers_as_strings_are_accepted"),
    ("TC-117", "R25", "Regression (DEF-06)", "Warranty abbreviation", "warranty 'OOW'", "out_of_warranty (was 422)", "tests/test_api.py::test_warranty_abbreviations[OOW-out_of_warranty]"),
    ("TC-118", "R24", "Negative", "Unknown abbreviation stays invalid", "warranty 'OOWX'", "422", "tests/test_api.py::test_unknown_abbreviations_stay_invalid[OOWX]"),
    ("TC-119", "R26", "Robustness", "Only case_id present", "{\"case_id\": \"MIN\"}", "200, escalate, cost null", "tests/test_api.py::test_minimal_payload_does_not_crash"),
    ("TC-120", "R29", "Guard", "Normal cases not escalated", "8 plain cases across ratios", "no escalate", "tests/test_escalation.py::test_normal_cases_are_not_escalated"),
    # data-driven
    ("TC-130", "R29", "Data-driven", "Synthetic corpus (seed 2026)", "570 cases, 19 scenarios", "0 misses; macro-F1 1.0", "tests/test_corpora.py::test_engine_matches_every_synthetic_scenario[2026]"),
    ("TC-131", "R30", "Data-driven", "Hand-labelled adversarial set", "35 cases", "0 misses", "tests/test_corpora.py::test_handwritten_fixtures"),
    ("TC-132", "R30", "Exploratory -> regression", "Challenge: Hinglish shock", "'body mein current lag raha hai'", "escalate", "tests/test_challenge.py::test_challenge_case[Hinglish 'current lag raha']"),
    ("TC-133", "R30", "Exploratory -> regression", "Challenge: OOW", "warranty 'OOW'", "repair", "tests/test_challenge.py::test_challenge_case[unusual enum 'OOW']"),
    # start-up
    ("TC-140", "R31", "System", "Real server start passes the grader check", "uvicorn child process + smoke check", "healthy, / served, 3 examples match", "tests/test_startup.py::test_server_stays_up_and_passes_the_grader_check"),
    ("TC-141", "R31", "Negative (DEF-16)", "Launcher crash fails fast", "launcher exits with code 3", "fails in < 20 s with exit code and output", "tests/test_startup.py::test_launcher_that_exits_fails_fast_with_its_output"),
    ("TC-142", "R31", "Negative (DEF-17)", "No listener: bounded wait", "launcher never binds, 3 s deadline", "fails in < 20 s with process and port diagnostics", "tests/test_startup.py::test_launcher_that_never_listens_fails_at_the_deadline_with_diagnostics"),
    ("TC-143", "R07", "Contract", "Health body must be exact", "{\"status\":\"starting\"}", "not ready", "tests/test_startup.py::test_health_contract_is_exact[200-{\"status\":\"starting\"}-False]"),
    ("TC-144", "R31", "Regression (DEF-15)", "Pins have Python 3.14 wheels", "requirements.txt", "pydantic >= 2.12", "tests/test_startup.py::test_requirements_have_wheels_for_supported_pythons"),
    ("TC-145", "R32", "Concurrency", "Parallel /decide = sequential", "49 fixture cases x 5, 16 threads", "every answer identical to the sequential one", "tests/test_concurrency.py::test_parallel_requests_get_the_same_answers_as_sequential[False]"),
    ("TC-146", "R32", "Concurrency", "Parallel /decide?explain=true = sequential", "49 fixture cases x 5, 16 threads, with trace", "every answer and trace identical", "tests/test_concurrency.py::test_parallel_requests_get_the_same_answers_as_sequential[True]"),
]

START = "<!-- GENERATED:{name}:START -->"
END = "<!-- GENERATED:{name}:END -->"


# ---------------------------------------------------------------------- junit
def run_pytest(junit: Path) -> None:
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", f"--junitxml={junit}"],
                   cwd=ROOT, check=False)


def parse_junit(path: Path) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for tc in ET.parse(path).getroot().iter("testcase"):
        classname, name = tc.get("classname", ""), tc.get("name", "")
        node = classname.replace(".", "/") + ".py::" + name
        status, message = "passed", ""
        for tag in ("failure", "error"):
            el = tc.find(tag)
            if el is not None:
                status, message = "failed", (el.get("message") or "").splitlines()[0][:120]
        if tc.find("skipped") is not None:
            status = "skipped"
        results[node] = {"status": status, "message": message, "time": float(tc.get("time", 0))}
    return results


def matches(node: str, pattern: str) -> bool:
    return pattern in node if "::" in pattern or pattern.endswith("/") else f"/{pattern}::" in node or node.startswith(pattern)


# ---------------------------------------------------------------------- rendering
def esc(s: str) -> str:
    return s.replace("|", "\\|")


def render_traceability(results) -> str:
    rows = ["| Req | Requirement | Source | Automated tests | Passed | Catalogue cases |",
            "|---|---|---|---|---|---|"]
    for rid, text, source, patterns in REQUIREMENTS:
        nodes = [n for n in results if any(matches(n, p) for p in patterns)]
        passed = sum(results[n]["status"] == "passed" for n in nodes)
        cases = ", ".join(c[0] for c in CATALOGUE if c[1] == rid) or "—"
        mark = "✅" if nodes and passed == len(nodes) else "❌"
        rows.append(f"| {rid} | {esc(text)} | {source} | {len(nodes)} | {mark} {passed}/{len(nodes)} | {cases} |")
    return "\n".join(rows)


def render_catalogue(results) -> Tuple[str, List[str]]:
    rows = ["| ID | Req | Technique | Test case | Input | Expected | Actual | Status |",
            "|---|---|---|---|---|---|---|---|"]
    missing = []
    for cid, rid, tech, title, inp, expected, node in CATALOGUE:
        r = results.get(node)
        if r is None:
            missing.append(f"{cid}: {node}")
            actual, status = "test not found", "❌ missing"
        elif r["status"] == "passed":
            actual, status = "as expected", "✅ pass"
        else:
            actual, status = esc(str(r["message"]) or r["status"]), f"❌ {r['status']}"
        rows.append(f"| {cid} | {rid} | {tech} | {esc(title)} | {esc(inp)} | {esc(expected)} | {actual} | {status} |")
    return "\n".join(rows), missing


def render_latest_run(results) -> str:
    per_file = defaultdict(lambda: {"tests": 0, "passed": 0, "failed": 0, "skipped": 0, "time": 0.0})
    for node, r in results.items():
        f = per_file[node.split("::")[0]]
        f["tests"] += 1
        f[r["status"]] += 1
        f["time"] += r["time"]
    total = {k: sum(f[k] for f in per_file.values()) for k in ("tests", "passed", "failed", "skipped", "time")}

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    import fastapi, pydantic  # noqa: E401
    from evaluate import evaluate
    from generate_cases import generate
    import json
    synthetic = evaluate(generate())
    hand = evaluate(json.loads((ROOT / "tests" / "fixtures" / "handwritten_cases.json").read_text(encoding="utf-8")))
    challenge = evaluate([{**r, "expected": {**r["expected"], "estimated_repair_cost": None}}
                          for r in json.loads((ROOT / "tests" / "fixtures" / "challenge_cases.json").read_text(encoding="utf-8"))])
    # The challenge set has no expected costs, so count decision matches only.
    challenge_ok = challenge["n"] - sum(
        1 for m in challenge["misses"] if m["expected"]["decision"] != m["got"]["decision"])

    lines = [
        f"- **Run at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Environment:** Python {platform.python_version()} on {platform.system()} {platform.machine()}; "
        f"FastAPI {fastapi.__version__}, Pydantic {pydantic.__version__}; network blocked by `tests/conftest.py`",
        f"- **Result:** {'✅ PASS' if total['failed'] == 0 else '❌ FAIL'}: {total['passed']} passed, "
        f"{total['failed']} failed, {total['skipped']} skipped, {total['tests']} total, {total['time']:.1f} s",
        "",
        "| Test file | Tests | Passed | Failed | Time (s) |",
        "|---|---|---|---|---|",
    ]
    for name in sorted(per_file):
        f = per_file[name]
        lines.append(f"| `{name}` | {f['tests']} | {f['passed']} | {f['failed']} | {f['time']:.2f} |")
    lines += [
        "",
        "Metric self-checks on our own data (the brief's metrics; **not** evidence of hidden-set accuracy):",
        "",
        "| Data set | Cases | Macro-F1 | Cost within 10% | Decision matches |",
        "|---|---|---|---|---|",
        f"| Synthetic corpus (seed 2026) | {synthetic['n']} | {synthetic['macro_f1']} | {synthetic['cost_within_10pct']} | {synthetic['n'] - len(synthetic['misses'])}/{synthetic['n']} |",
        f"| Hand-labelled fixtures | {hand['n']} | {hand['macro_f1']} | {hand['cost_within_10pct']} | {hand['n'] - len(hand['misses'])}/{hand['n']} |",
        f"| Challenge set (decision only) | {challenge['n']} | {challenge['macro_f1']} | n/a | {challenge_ok}/{challenge['n']} |",
    ]
    return "\n".join(lines)


def render_e2e(results) -> str:
    """Browser-test results per engine, from the e2e JUnit file."""
    engines = ("chromium", "firefox", "webkit")
    per = {e: {"tests": 0, "passed": 0, "failed": 0} for e in engines}
    by_test: Dict[str, Dict[str, str]] = defaultdict(dict)
    for node, r in results.items():
        params = node.split("[", 1)[1].rstrip("]") if "[" in node else ""
        engine = params.split("-", 1)[0]
        if engine not in per:
            continue
        per[engine]["tests"] += 1
        per[engine][r["status"] if r["status"] in ("passed", "failed") else "failed"] += 1
        base = node.split("::")[1].split("[")[0]
        variant = params.split("-", 1)[1] if "-" in params else ""
        key = base + (f" [{variant}]" if variant else "")
        by_test[key][engine] = "✅" if r["status"] == "passed" else "❌"
    import playwright
    from importlib.metadata import version
    total_failed = sum(v["failed"] for v in per.values())
    lines = [
        f"- **Run at:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} on {platform.system()} {platform.machine()}, "
        f"Playwright {version('playwright')}, axe-core via axe-playwright-python {version('axe-playwright-python')}",
        f"- **Result:** {'✅ PASS' if total_failed == 0 and results else '❌ FAIL'}: "
        + ", ".join(f"{e} {per[e]['passed']}/{per[e]['tests']}" for e in engines),
        "",
        "| Browser test | Chromium | Firefox | WebKit |",
        "|---|---|---|---|",
    ]
    for key in sorted(by_test):
        row = by_test[key]
        lines.append(f"| `{esc(key)}` | {row.get('chromium', '—')} | {row.get('firefox', '—')} | {row.get('webkit', '—')} |")
    return "\n".join(lines)


def replace_section(text: str, name: str, body: str) -> str:
    start, end = START.format(name=name), END.format(name=name)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"TESTING.md is missing the {name} markers")
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text)


def main() -> int:
    # Windows consoles default to cp1252, which cannot print the status marks.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", type=Path, help="existing JUnit XML (skip running pytest)")
    ap.add_argument("--summary", action="store_true", help="print a Markdown summary instead of editing TESTING.md")
    ap.add_argument("--with-e2e", action="store_true", help="also run the browser tests and update their section")
    ap.add_argument("--e2e-junit", type=Path, help="existing JUnit XML from the browser tests")
    ap.add_argument("--summary-e2e", action="store_true", help="print only the browser-test summary")
    args = ap.parse_args()

    if args.summary_e2e:
        e2e = parse_junit(args.e2e_junit)
        print("## Browser test report\n\n" + render_e2e(e2e))
        return 1 if any(r["status"] == "failed" for r in e2e.values()) or not e2e else 0

    if args.junit:
        results = parse_junit(args.junit)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "junit.xml"
            run_pytest(junit)
            results = parse_junit(junit)

    catalogue, missing = render_catalogue(results)
    latest = render_latest_run(results)
    trace = render_traceability(results)
    failed = [n for n, r in results.items() if r["status"] == "failed"]

    e2e_failed = []
    sections = [("LATEST-RUN", latest), ("TRACEABILITY", trace), ("CATALOGUE", catalogue)]
    if args.with_e2e or args.e2e_junit:
        if args.e2e_junit:
            e2e = parse_junit(args.e2e_junit)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                junit = Path(tmp) / "e2e.xml"
                subprocess.run([sys.executable, "-m", "pytest", "e2e", "-q", "-p", "no:warnings",
                                f"--junitxml={junit}"], cwd=ROOT, check=False)
                e2e = parse_junit(junit)
        e2e_failed = [n for n, r in e2e.items() if r["status"] == "failed"]
        sections.append(("E2E", render_e2e(e2e)))

    if args.summary:
        print("## Test report\n\n" + latest + "\n\n### Requirements traceability\n\n" + trace)
    else:
        text = TESTING_MD.read_text(encoding="utf-8")
        for name, body in sections:
            text = replace_section(text, name, body)
        TESTING_MD.write_text(text, encoding="utf-8")
        print(f"TESTING.md updated: {len(results)} tests, {len(failed)} failed, "
              f"{len(CATALOGUE)} catalogue cases, {len(missing)} missing")

    for m in missing:
        print(f"MISSING catalogue test: {m}", file=sys.stderr)
    return 1 if failed or missing or e2e_failed else 0


if __name__ == "__main__":
    sys.exit(main())
