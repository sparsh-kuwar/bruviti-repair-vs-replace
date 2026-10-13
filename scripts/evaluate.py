"""Score the engine on a labelled corpus with the brief's two metrics.

    python scripts/evaluate.py                     # synthetic corpus (regenerated in memory)
    python scripts/evaluate.py --file tests/fixtures/handwritten_cases.json

Reports macro-F1 over {repair, replace, escalate}, the share of cost estimates
within 10% of the expected cost, a confusion matrix, and every miss. These are
self-checks against our own reading of the policy -- NOT evidence of real-world
accuracy (see DATA.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.policy import decide  # noqa: E402
from app.schemas import ServiceCase  # noqa: E402

LABELS = ("repair", "replace", "escalate")


def macro_f1(pairs: List[tuple]) -> float:
    scores = []
    for label in LABELS:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        fp = sum(1 for e, p in pairs if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        if tp + fp + fn == 0:
            continue  # label absent from both truth and predictions
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def cost_within_10pct(expected: Any, got: Any) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if expected == 0:
        return got == 0
    return abs(got - expected) / abs(expected) <= 0.10


def evaluate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pairs, cost_hits, misses = [], 0, []
    for row in rows:
        result = decide(ServiceCase.model_validate(row["case"]))
        exp = row["expected"]
        pairs.append((exp["decision"], result.decision))
        hit = cost_within_10pct(exp.get("estimated_repair_cost"), result.estimated_repair_cost)
        cost_hits += hit
        if exp["decision"] != result.decision or not hit:
            misses.append({"case_id": row["case"]["case_id"], "scenario": row.get("scenario"),
                           "expected": exp, "got": result.public()})
    confusion = Counter(pairs)
    return {
        "n": len(rows),
        "macro_f1": round(macro_f1(pairs), 4),
        "cost_within_10pct": round(cost_hits / len(rows), 4) if rows else 0.0,
        "confusion": {f"{e}->{p}": n for (e, p), n in sorted(confusion.items())},
        "misses": misses,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="JSON list or JSONL of {case, expected}")
    args = ap.parse_args()
    if args.file:
        text = Path(args.file).read_text()
        rows = json.loads(text) if text.lstrip().startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
    else:
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_cases import generate
        rows = generate()
    report = evaluate(rows)
    misses = report.pop("misses")
    print(json.dumps(report, indent=2))
    for m in misses:
        print("MISS", json.dumps(m))


if __name__ == "__main__":
    main()
