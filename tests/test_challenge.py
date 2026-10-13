"""The 14-case post-build challenge, sent over HTTP, as regression tests.

Expected decisions were written before the fixes and have not been changed.
Three originally failed: "sparkes", "current lag raha hai" and warranty "OOW".
"""

import json
from pathlib import Path

import pytest

ROWS = json.loads((Path(__file__).parent / "fixtures" / "challenge_cases.json").read_text())


@pytest.mark.parametrize("row", ROWS, ids=[r["note"] for r in ROWS])
def test_challenge_case(client, row):
    r = client.post("/decide", json=row["case"])
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == row["expected"]["decision"]
