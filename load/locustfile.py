"""Stress test for POST /decide: step the user count up until the service breaks.

Breaking point: the first step whose p95 latency is over 1 s (an agent is
waiting on the answer), or whose error rate is over 1%. Requests slower than
10 s count as errors.

Each simulated user is a support agent: send one case the way the UI does
(?explain=true), wait 0.5-1.5 s, repeat. Cases rotate through the hand-labelled
and challenge fixtures so the text scan sees short and long symptom text.

Run it through the driver, which also starts the server and samples CPU:

    .venv/bin/python scripts/stress.py --workers 1 2 4

Each step is held for its warm-up (WARMUP_S plus the time to spawn the new
users at SPAWN_RATE) and then MEASURE_S. Stats are reset after the warm-up,
so a step's numbers cover only its steady state. At the end of every step one
row is appended to the CSV named by $STEP_CSV, with CPU used by the server
($SERVER_PID and its worker children) and by Locust itself, in cores.
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import select
import time
from pathlib import Path
from typing import List, Optional

import psutil
from geventhttpclient.connectionpool import ConnectionPool
from locust import LoadTestShape, between, task
from locust.contrib.fasthttp import FastHttpUser

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

STEPS = [25, 50, 100, 200, 400, 600, 800, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000, 6000,
         7000, 8000, 9000, 10000, 12000, 14000]
WARMUP_S = 5  # plus the time to spawn the step's new users
SPAWN_RATE = 400  # users per second; Locust warns above ~100 per load process
MEASURE_S = 15
P95_LIMIT_MS = 1000
ERROR_LIMIT = 0.01

CASES = [c["case"] for name in ("handwritten_cases.json", "challenge_cases.json")
         for c in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


def _socket_alive(self, sock) -> bool:
    """geventhttpclient checks an idle pooled socket with select(), which raises
    for file descriptors above 1024. It then treats every such socket as dead
    and reconnects on each request; above ~1000 users per Locust process the
    closed sockets pile up in TIME_WAIT until the client runs out of local ports
    (OSError Errno 49), which looks like the service failing. poll() has no
    such limit. Same rule otherwise: readable while idle means FIN or junk."""
    if sock is None or sock.fileno() < 0:
        return False
    try:
        p = select.poll()
        p.register(sock.fileno(), select.POLLIN)
        return not p.poll(0)
    except (OSError, ValueError):
        return False


ConnectionPool._is_socket_alive = _socket_alive


class Agent(FastHttpUser):
    wait_time = between(0.5, 1.5)
    network_timeout = 10.0
    connection_timeout = 10.0

    def on_start(self) -> None:
        # each user starts at a different case so the mix is even from step 1
        self.cases = itertools.islice(itertools.cycle(CASES), id(self) % len(CASES), None)

    @task
    def decide(self) -> None:
        with self.client.post("/decide?explain=true", json=next(self.cases),
                              name="/decide", catch_response=True) as r:
            if r.status_code == 0:  # no HTTP response: the connection itself failed
                r.failure(f"connection: {type(r.error).__name__}: {r.error}")
            elif r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")


def _procs(root_pid: int) -> List[psutil.Process]:
    try:
        root = psutil.Process(root_pid)
        return [root] + root.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def _cpu_seconds(procs: List[psutil.Process]) -> float:
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except psutil.NoSuchProcess:
            pass
    return total


class StepRamp(LoadTestShape):
    def __init__(self) -> None:
        super().__init__()
        self.step = 0
        self.step_started: Optional[float] = None
        self.measuring = False
        self.broke = False
        self.server_pid = int(os.environ.get("SERVER_PID", "0"))
        self.out = os.environ.get("STEP_CSV")
        self.label = os.environ.get("RUN_LABEL", "")

    def _snapshot(self) -> None:
        self.server_procs = _procs(self.server_pid) if self.server_pid else []
        self.locust_procs = _procs(os.getpid())
        self.cpu_server0 = _cpu_seconds(self.server_procs)
        self.cpu_locust0 = _cpu_seconds(self.locust_procs)
        self.wall0 = time.monotonic()

    def _record(self) -> None:
        wall = time.monotonic() - self.wall0
        s = self.runner.stats.total
        n, fails = s.num_requests, s.num_failures
        row = {
            "run": self.label,
            "users": STEPS[self.step],
            "requests": n,
            "rps": round(n / wall, 1),
            "p50_ms": s.get_response_time_percentile(0.50) if n else 0,
            "p95_ms": s.get_response_time_percentile(0.95) if n else 0,
            "p99_ms": s.get_response_time_percentile(0.99) if n else 0,
            "max_ms": round(s.max_response_time or 0),
            "error_rate": round(fails / n, 4) if n else 0,
            "server_cpu_cores": round((_cpu_seconds(self.server_procs) - self.cpu_server0) / wall, 2),
            "locust_cpu_cores": round((_cpu_seconds(self.locust_procs) - self.cpu_locust0) / wall, 2),
        }
        self.broke = row["p95_ms"] > P95_LIMIT_MS or row["error_rate"] > ERROR_LIMIT
        row["broke"] = self.broke
        print(f"[step] {row}", flush=True)
        if self.out:
            new = not Path(self.out).exists()
            with open(self.out, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(row))
                if new:
                    w.writeheader()
                w.writerow(row)

    def tick(self):
        now = self.get_run_time()
        if self.step_started is None:
            self.step_started = now
        elapsed = now - self.step_started
        added = STEPS[self.step] - (STEPS[self.step - 1] if self.step else 0)
        warmup = WARMUP_S + -(-added // SPAWN_RATE)
        if not self.measuring and elapsed >= warmup:
            self.runner.stats.reset_all()
            self._snapshot()
            self.measuring = True
        elif self.measuring and elapsed >= warmup + MEASURE_S:
            self._record()
            if self.broke or self.step + 1 >= len(STEPS):
                return None  # stop the test
            self.step += 1
            self.step_started = now
            self.measuring = False
        return STEPS[self.step], SPAWN_RATE

