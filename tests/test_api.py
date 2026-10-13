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
        text = f.read_text()
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


@pytest.mark.parametrize("cid", ["C-9", "  spaced id  ", "ünïcode-✓", 12345])
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
])
def test_invalid_input_is_a_clean_422(client, payload):
    r = client.post("/decide", json=payload)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("raw", ['{"case_id": "x", "replacement_price": NaN}',
                                 '{"case_id": "x", "replacement_price": Infinity}',
                                 '{"case_id": "x", "labour_hours": -Infinity}'])
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
