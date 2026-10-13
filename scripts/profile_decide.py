"""Where does one /decide request spend its CPU?

    .venv/bin/python scripts/profile_decide.py            # stage timings + top functions
    .venv/bin/python scripts/profile_decide.py --n 20000

Runs the same steps as the /decide handler, in-process and without HTTP, over
the fixture cases the load test sends: validate the JSON (pydantic), run the
rules engine, build the explained response model, encode it to JSON. Compare the
total with the load test's CPU per request (server cores / rps): the
difference is what uvicorn, Starlette and FastAPI spend on HTTP, routing and
the thread pool.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.policy import decide  # noqa: E402
from app.schemas import ExplainedResponse, ServiceCase  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
BODIES = [json.dumps(c["case"]).encode() for name in ("handwritten_cases.json", "challenge_cases.json")
          for c in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


def one(raw: bytes) -> bytes:
    case = ServiceCase.model_validate_json(raw)
    result = decide(case)
    body = ExplainedResponse(**result.public(), trace=result.trace).model_dump(mode="json")
    return json.dumps(body).encode()


def stage_times(n: int) -> None:
    t = {"parse + validate": 0.0, "rules engine": 0.0, "response model": 0.0, "json encode": 0.0}
    clock = time.perf_counter
    for i in range(n):
        raw = BODIES[i % len(BODIES)]
        a = clock(); case = ServiceCase.model_validate_json(raw)
        b = clock(); result = decide(case)
        c = clock(); body = ExplainedResponse(**result.public(), trace=result.trace).model_dump(mode="json")
        d = clock(); json.dumps(body)
        e = clock()
        t["parse + validate"] += b - a
        t["rules engine"] += c - b
        t["response model"] += d - c
        t["json encode"] += e - d
    total = sum(t.values())
    print(f"{n} requests, {len(BODIES)} distinct cases, explain=true\n")
    print(f"{'stage':<18} {'us/request':>10} {'share':>7}")
    for k, v in t.items():
        print(f"{k:<18} {v / n * 1e6:>10.1f} {v / total:>7.0%}")
    print(f"{'total':<18} {total / n * 1e6:>10.1f}  -> max ~{n / total:,.0f} req/s on one core, before HTTP")


def top_functions(n: int, limit: int) -> None:
    prof = cProfile.Profile()
    prof.enable()
    for i in range(n):
        one(BODIES[i % len(BODIES)])
    prof.disable()
    print(f"\nTop {limit} functions by own time (cProfile adds overhead; compare shares, not absolutes):")
    pstats.Stats(prof).sort_stats("tottime").print_stats(limit)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    for raw in BODIES[:50]:  # warm up imports and caches
        one(raw)
    stage_times(args.n)
    top_functions(args.n, args.top)


if __name__ == "__main__":
    main()
