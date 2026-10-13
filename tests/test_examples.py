"""The three worked examples from the brief, through the real HTTP endpoint."""

import json
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("cid", ["C-2001", "C-2002", "C-2003"])
def test_brief_example_matches_expected(client, cid):
    request = json.loads((EXAMPLES / f"{cid}.request.json").read_text())
    expected = json.loads((EXAMPLES / f"{cid}.expected.json").read_text())
    got = client.post("/decide", json=request).json()
    assert got["case_id"] == expected["case_id"]
    assert got["decision"] == expected["decision"]
    assert got["estimated_repair_cost"] == expected["estimated_repair_cost"]
    assert got["confidence"] == pytest.approx(expected["confidence"])


def test_c2001_reason_names_d2(client):
    request = json.loads((EXAMPLES / "C-2001.request.json").read_text())
    reason = client.post("/decide", json=request).json()["reason"]
    assert reason == "Out of warranty, repair cost 23% of replacement, age within 70% of expected life: rule D2."


def test_c2002_reason_names_d1b(client):
    request = json.loads((EXAMPLES / "C-2002.request.json").read_text())
    reason = client.post("/decide", json=request).json()["reason"]
    assert "D1b" in reason and "28 days" in reason


def test_c2003_reason_names_both_triggers(client):
    request = json.loads((EXAMPLES / "C-2003.request.json").read_text())
    reason = client.post("/decide", json=request).json()["reason"]
    assert "D5" in reason and "negative sentiment" in reason and "part price missing" in reason
