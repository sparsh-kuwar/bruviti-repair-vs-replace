"""HTTP contract: /decide, /health, /, validation, tolerance, performance."""

import json
import math
import re
import time
from pathlib import Path

import pytest

from .conftest import case

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
RESPONSE_KEYS = {"case_id", "decision", "estimated_repair_cost", "confidence", "reason"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_index_serves_the_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'id="case-form"' in r.text
    for asset in ("/static/app.js", "/static/app.css"):
        assert client.get(asset).status_code == 200


def test_ui_has_no_remote_assets():
    for f in STATIC.iterdir():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)\s*=\s*["']https?://""", text), f.name
        assert "@import url(" not in text, f.name
        assert not re.search(r"""fetch\(\s*["']https?://""", text), f.name


def test_response_has_exactly_the_contract_fields(client):
    body = client.post("/decide", json=case()).json()
    assert set(body) == RESPONSE_KEYS
    assert body["decision"] in {"repair", "replace", "escalate"}
    assert isinstance(body["confidence"], float) and 0 <= body["confidence"] <= 1
    assert isinstance(body["reason"], str) and body["reason"].endswith(".")


def test_explain_adds_trace_only_on_request(client):
    body = client.post("/decide?explain=true", json=case()).json()
    assert set(body) == RESPONSE_KEYS | {"trace"} and body["trace"]["rule"] == "D2"


@pytest.mark.parametrize("cid", ["C-9", "  spaced id  ", "ünïcode-✓", 12345],
                         ids=["plain", "spaces", "unicode", "integer"])
def test_case_id_echoed_unchanged(client, cid):
    assert client.post("/decide", json=case(case_id=cid)).json()["case_id"] == cid


# ------------------------------------------------------------------ 422s


@pytest.mark.parametrize("payload", [
    case(product_category="toaster"),
    case(fault_category="exploded"),
    case(warranty_status="lifetime"),
    case(customer_sentiment="furious-ish"),
    case(replacement_price=-1),
    case(labour_hours=-0.5),
    case(technician_travel_minutes=-10),
    case(parts=[{"sku": "x", "price": -5, "lead_time_days": 1}]),
    case(labour_rate_per_hour="lots"),
    case(parts="motor"),
    case(replacement_price=True),
    {k: v for k, v in case().items() if k != "case_id"},
    case(case_id=None),
    case(case_id=""),
], ids=["unknown-product", "unknown-fault", "unknown-warranty", "unknown-sentiment",
        "negative-replacement-price", "negative-labour-hours", "negative-travel",
        "negative-part-price", "non-numeric-rate", "parts-not-a-list", "boolean-price",
        "missing-case-id", "null-case-id", "empty-case-id"])
def test_invalid_input_is_a_clean_422(client, payload):
    r = client.post("/decide", json=payload)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("raw", ['{"case_id": "x", "replacement_price": NaN}',
                                 '{"case_id": "x", "replacement_price": Infinity}',
                                 '{"case_id": "x", "labour_hours": -Infinity}'],
                         ids=["nan", "infinity", "negative-infinity"])
def test_nan_and_infinity_rejected(client, raw):
    r = client.post("/decide", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_malformed_json_is_422(client):
    r = client.post("/decide", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_array_body_is_422(client):
    assert client.post("/decide", json=[case()]).status_code == 422


# ------------------------------------------------------------------ tolerance of format


def test_enum_spelling_and_synonyms_are_normalised(client):
    body = client.post("/decide", json=case(
        product_category="Washing Machine", warranty_status="Out-of-Warranty",
        fault_category="MOTOR_OR_DRIVE", customer_sentiment=" Neutral ")).json()
    assert body["decision"] == "repair"
    assert client.post("/decide", json=case(product_category="fridge", fault_category="other")).status_code == 200


def test_numbers_as_strings_are_accepted(client):
    data = case(replacement_price="36,000", labour_rate_per_hour="Rs 900",
                parts=[{"sku": "P1", "price": "6200", "lead_time_days": "4"}])
    body = client.post("/decide", json=data).json()
    assert body["estimated_repair_cost"] == 8150.0 and body["decision"] == "repair"


def test_us_spelling_of_labour(client):
    data = case()
    data["labor_hours"] = data.pop("labour_hours")
    data["labor_rate_per_hour"] = data.pop("labour_rate_per_hour")
    assert client.post("/decide", json=data).json()["estimated_repair_cost"] == 8150.0


def test_extra_fields_are_ignored(client):
    assert client.post("/decide", json=case(customer_name="X", channel="phone")).status_code == 200


def test_minimal_payload_does_not_crash(client):
    r = client.post("/decide", json={"case_id": "MIN"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "escalate" and body["estimated_repair_cost"] is None


@pytest.mark.parametrize("field", ["product_age_months", "purchase_price", "replacement_price",
                                   "fault_category", "labour_hours", "technician_travel_minutes",
                                   "prior_repairs_12m", "customer_sentiment", "symptom_text",
                                   "parts", "product_category", "warranty_status"])
def test_each_field_missing_or_null_gives_a_valid_response(client, field):
    for data in (case(**{field: None}), {k: v for k, v in case().items() if k != field}):
        r = client.post("/decide", json=data)
        assert r.status_code == 200, (field, r.text)
        body = r.json()
        assert set(body) == RESPONSE_KEYS
        assert math.isfinite(body["confidence"])


def test_purchase_price_is_not_used_by_any_rule(client):
    a = client.post("/decide", json=case(purchase_price=1)).json()
    b = client.post("/decide", json=case(purchase_price=None)).json()
    assert a == b


# ------------------------------------------------------------------ reliability


def test_deterministic_over_http(client):
    bodies = {json.dumps(client.post("/decide", json=case()).json(), sort_keys=True) for _ in range(20)}
    assert len(bodies) == 1


def test_latency_well_under_one_second(client):
    long_text = "No sparks or smoke but the drum does not turn and the motor hums loudly. " * 200
    payload = case(symptom_text=long_text,
                   parts=[{"sku": f"P{i}", "price": 10, "lead_time_days": 3} for i in range(200)])
    start = time.perf_counter()
    for _ in range(20):
        assert client.post("/decide", json=payload).status_code == 200
    per_request = (time.perf_counter() - start) / 20
    assert per_request < 0.25, per_request   # generous bound; the brief's limit is 1 s


# ------------------------------------------------------------------ warranty abbreviations (regression)


@pytest.mark.parametrize("raw,canonical", [
    ("OOW", "out_of_warranty"), (" oow ", "out_of_warranty"), ("Oow", "out_of_warranty"),
    ("IW", "in_warranty"), ("iw", "in_warranty"),
    ("EW", "extended"), (" Ew", "extended"),
])
def test_warranty_abbreviations(raw, canonical):
    from app.schemas import ServiceCase
    assert ServiceCase.model_validate(case(warranty_status=raw)).warranty_status.value == canonical


def test_oow_abbreviation_gives_same_decision_as_full_value(client):
    full = client.post("/decide", json=case(warranty_status="out_of_warranty")).json()
    abbr = client.post("/decide", json=case(warranty_status="OOW")).json()
    assert abbr == full


@pytest.mark.parametrize("raw", ["OOWX", "O O W", "W", "oo", "XW"])
def test_unknown_abbreviations_stay_invalid(client, raw):
    assert client.post("/decide", json=case(warranty_status=raw)).status_code == 422


# ------------------------------------------------------------------ UI trace fields


@pytest.mark.parametrize("data,stopped_rule,skipped", [
    (case(), "D2", 0),                                                     # plain D2 repair
    (case(symptom_text="smoke from the back"), "D5", 3),                   # escalation stops first
    (case(warranty_status="in_warranty", technician_travel_minutes=200,
          parts=[{"sku": "P", "price": 20000, "lead_time_days": 2}]), "D3", 2),
])
def test_trace_stages_show_where_precedence_stopped(client, data, stopped_rule, skipped):
    trace = client.post("/decide?explain=true", json=data).json()["trace"]
    stages = trace["stages"]
    assert [s["status"] for s in stages].count("stopped") == 1
    assert next(s for s in stages if s["status"] == "stopped")["rule"] == stopped_rule
    assert [s["status"] for s in stages].count("skipped") == skipped


def test_trace_lists_every_escalation_check(client):
    trace = client.post("/decide?explain=true", json=case(prior_repairs_12m=2, customer_sentiment="negative")).json()["trace"]
    checks = {c["check"]: c["triggered"] for c in trace["escalation_checks"]}
    assert len(checks) == 4
    assert checks["Repeat repairs with negative sentiment"] is True
    assert checks["Safety hazard in symptom text"] is False


def test_confidence_basis_always_adds_up_to_confidence(client):
    # Display-only explanation must never disagree with the real number.
    variants = [case(), case(warranty_status="unknown"), case(technician_travel_minutes=None),
                case(warranty_status="in_warranty", parts=[{"sku": "P", "price": 19000, "lead_time_days": 2}]),
                case(symptom_text="smoke"), case(replacement_price=None), case(product_age_months=None),
                case(warranty_status="unknown", technician_travel_minutes=None, prior_repairs_12m=None,
                     customer_sentiment="negative")]
    for data in variants:
        body = client.post("/decide?explain=true", json=data).json()
        basis = body["trace"]["confidence_basis"]
        assert round(sum(line["delta"] for line in basis), 2) == body["confidence"], basis


def test_cost_formula_exposes_every_component(client):
    f = client.post("/decide?explain=true", json=case()).json()["trace"]["cost_formula"]
    assert (f["parts_total"], f["labour"], f["travel"], f["total"]) == (6200.0, 1350.0, 600.0, 8150.0)
    assert f["labour_hours"] == 1.5 and f["labour_rate_per_hour"] == 900 and f["technician_travel_minutes"] == 40


# ------------------------------------------------------------------ the network guard itself


def test_network_guard_blocks_external_hosts_but_allows_loopback():
    import socket as _socket
    from tests.conftest import NetworkBlocked
    with pytest.raises(NetworkBlocked):
        _socket.getaddrinfo("example.com", 80)
    with pytest.raises(NetworkBlocked):
        _socket.create_connection(("93.184.216.34", 80), timeout=1)
    # Loopback is allowed (Windows event loops need it): the call reaches the OS
    # and returns an errno for the closed port instead of raising NetworkBlocked.
    s = _socket.socket()
    try:
        s.settimeout(1)
        assert isinstance(s.connect_ex(("127.0.0.1", 9)), int)
    finally:
        s.close()
    a, b = _socket.socketpair()  # what asyncio's Windows event loop does at start-up
    a.close(), b.close()
