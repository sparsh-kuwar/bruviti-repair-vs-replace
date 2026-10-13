"""Run the engine over the synthetic corpus and the hand-labelled fixtures.

Labels in both come from the written policy, not from app/policy.py (see
DATA.md), so a mismatch means the engine and our reading of the brief disagree.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate import evaluate, macro_f1  # noqa: E402
from generate_cases import SCENARIOS, generate  # noqa: E402


def test_generator_is_deterministic():
    assert generate(seed=11, per_scenario=5) == generate(seed=11, per_scenario=5)
    assert generate(seed=11, per_scenario=5) != generate(seed=12, per_scenario=5)


def test_synthetic_corpus_is_balanced_across_decisions():
    counts = Counter(r["expected"]["decision"] for r in generate())
    assert set(counts) == {"repair", "replace", "escalate"}
    assert min(counts.values()) / max(counts.values()) > 0.7


@pytest.mark.parametrize("seed", [2026, 1, 99])
def test_engine_matches_every_synthetic_scenario(seed):
    report = evaluate(generate(seed=seed, per_scenario=30))
    assert report["misses"] == [], report["misses"][:3]
    assert report["macro_f1"] == 1.0 and report["cost_within_10pct"] == 1.0


def test_every_scenario_is_exercised():
    assert {r["scenario"] for r in generate(per_scenario=1)} == set(SCENARIOS)


def test_handwritten_fixtures():
    rows = json.loads((ROOT / "tests" / "fixtures" / "handwritten_cases.json").read_text(encoding="utf-8"))
    report = evaluate(rows)
    assert report["misses"] == [], report["misses"]


def test_macro_f1_implementation():
    # Sanity-check our own metric code on a known example.
    pairs = [("repair", "repair"), ("replace", "repair"), ("escalate", "escalate"), ("replace", "replace")]
    # repair: P=1/2 R=1 F=2/3; replace: P=1 R=1/2 F=2/3; escalate: F=1 -> mean 7/9
    assert macro_f1(pairs) == pytest.approx(7 / 9)
