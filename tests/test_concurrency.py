"""Concurrent requests get exactly the answers sequential requests get.

FastAPI runs the sync /decide handler in a thread pool, so requests overlap.
The engine keeps no state between requests; this checks that nothing leaks
between threads (a shared mutable default, a module-level buffer). Thread
switches are made very frequent so an overlap is likely on every request.

Throughput and the breaking point under load are measured separately with
Locust (load/locustfile.py, scripts/stress.py); see TESTING.md §6.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
CASES = [c["case"] for name in ("handwritten_cases.json", "challenge_cases.json")
         for c in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


@pytest.fixture
def fast_switching():
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    yield
    sys.setswitchinterval(old)


@pytest.mark.parametrize("explain", [False, True])
def test_parallel_requests_get_the_same_answers_as_sequential(fast_switching, explain):
    url = "/decide?explain=true" if explain else "/decide"
    with TestClient(app) as seq:
        expected = [seq.post(url, json=c).json() for c in CASES]

    clients = threading.local()  # one client per thread, reused across its requests

    def send(i):
        if not hasattr(clients, "c"):
            clients.c = TestClient(app)
        return i % len(CASES), clients.c.post(url, json=CASES[i % len(CASES)]).json()

    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(send, range(5 * len(CASES))))
    assert all(body == expected[i] for i, body in results)
