"""Run the stress test once per uvicorn worker count and summarise the results.

    .venv/bin/python scripts/stress.py                       # workers 1 2 4
    .venv/bin/python scripts/stress.py --workers 1 --locust-processes 4

For each worker count: start `uvicorn app.main:app --workers N` on a spare
port, wait for /health, run load/locustfile.py headless (it steps the user
count up until p95 > 1 s or errors > 1%), then stop the server. Every step is
appended to load/results/steps.csv; the last line printed per run is its
capacity: the highest throughput reached and the last step that stayed under
the limit.

Locust runs on the same machine, so the script reports Locust's own CPU next
to the server's. If Locust is near its process count in cores, it, not the
service, is the limit.
"""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
RESULTS = ROOT / "load" / "results"


def wait_healthy(port: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server on port {port} did not become healthy")


def run_one(workers: int, locust_procs: int, port: int, out: Path) -> None:
    label = f"workers={workers}"
    server = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--workers", str(workers), "--no-access-log", "--log-level", "warning"],
        cwd=ROOT, start_new_session=True,
    )
    try:
        wait_healthy(port)
        time.sleep(1 if workers == 1 else 3)  # let every worker finish importing
        env = dict(os.environ, SERVER_PID=str(server.pid), STEP_CSV=str(out), RUN_LABEL=label)
        print(f"\n=== {label}, locust processes={locust_procs} ===", flush=True)
        subprocess.run(
            [PY, "-m", "locust", "-f", str(ROOT / "load" / "locustfile.py"), "--headless",
             "--host", f"http://127.0.0.1:{port}", "--processes", str(locust_procs),
             "--only-summary", "--loglevel", "WARNING"],
            cwd=ROOT, env=env, check=False,
        )
    finally:
        os.killpg(server.pid, signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(server.pid, signal.SIGKILL)


def summarise(out: Path) -> None:
    rows = list(csv.DictReader(out.open()))
    print("\nrun          | peak rps | last OK step (users, rps, p95 ms) | broke at (users, p95 ms, errors)")
    for label in dict.fromkeys(r["run"] for r in rows):
        mine = [r for r in rows if r["run"] == label]
        ok = [r for r in mine if r["broke"] == "False"]
        bad = [r for r in mine if r["broke"] == "True"]
        peak = max(float(r["rps"]) for r in mine)
        last = f"{ok[-1]['users']}, {ok[-1]['rps']}, {ok[-1]['p95_ms']}" if ok else "-"
        broke = f"{bad[0]['users']}, {bad[0]['p95_ms']}, {bad[0]['error_rate']}" if bad else "did not break"
        print(f"{label:<12} | {peak:>8.0f} | {last:<33} | {broke}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--locust-processes", type=int, default=4)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", type=Path, default=RESULTS / "steps.csv")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    for w in args.workers:
        run_one(w, args.locust_processes, args.port, args.out)
    summarise(args.out)


if __name__ == "__main__":
    main()
