"""Fresh-start smoke test: what a grader does, in one process.

    python scripts/smoke_start.py                    # run.sh (or run.ps1 on Windows), port 8000
    python scripts/smoke_start.py --timeout 60
    python scripts/smoke_start.py --command "python -m uvicorn app.main:app --port 8123" --port 8123

1. Start the documented one-command launcher as a child process, logging its
   output to server.log.
2. Poll http://127.0.0.1:<port>/health (2 s per request) until it returns
   HTTP 200 with exactly {"status": "ok"}, or the deadline passes.
3. Check that / serves the page and that the brief's three examples match.
4. Stop the whole process tree.

It fails fast if the launcher exits, and on timeout it reports whether the
process is alive, whether anything listens on the port, the last health error
and the tail of the log.

Why one process: on GitHub's Windows runners every process a CI step starts is
killed when that step ends, so "start in one step, poll in the next" can never
work there. Keeping launcher and checks in one process works on every OS.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple, Union

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ("C-2001", "C-2002", "C-2003")
REQUEST_TIMEOUT = 2.0
POLL_INTERVAL = 0.5


def default_command() -> List[str]:
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "run.ps1")]
    return [str(ROOT / "run.sh")]


def health_ok(status: int, body: bytes) -> bool:
    """The exact readiness contract: HTTP 200 and {"status": "ok"}."""
    if status != 200:
        return False
    try:
        return json.loads(body) == {"status": "ok"}
    except ValueError:
        return False


def probe(url: str) -> Tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as r:
            body = r.read()
            return health_ok(r.status, body), f"HTTP {r.status} {body[:200]!r}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def port_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def log_tail(path: Path, lines: int = 40) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "(no log file)"
    tail = text.splitlines()[-lines:]
    return "\n".join(tail) if tail else "(log is empty)"


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait(timeout=10)


def check_examples(base: str) -> List[str]:
    problems = []
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        if 'id="case-form"' not in r.read().decode("utf-8", "replace"):
            problems.append("/ does not serve the case form")
    for cid in EXAMPLES:
        body = (ROOT / "examples" / f"{cid}.request.json").read_bytes()
        expected = json.loads((ROOT / "examples" / f"{cid}.expected.json").read_text(encoding="utf-8"))
        req = urllib.request.Request(base + "/decide", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            got = json.load(r)
        for key in ("case_id", "decision", "estimated_repair_cost", "confidence"):
            if got.get(key) != expected[key]:
                problems.append(f"{cid}: {key} = {got.get(key)!r}, expected {expected[key]!r}")
        print(f"  {cid}: {got['decision']} {got['estimated_repair_cost']} {got['confidence']}")
    return problems


def run(command: Union[str, List[str]], port: int, timeout: float, log: Path) -> int:
    env = dict(os.environ, PORT=str(port))
    started = time.monotonic()
    shown = command if isinstance(command, str) else " ".join(command)
    print(f"starting: {shown}  (port {port}, deadline {timeout:.0f}s, log {log})", flush=True)
    with open(log, "wb") as out:
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, **kwargs)
    url = f"http://127.0.0.1:{port}/health"
    last = "no attempt yet"
    try:
        while True:
            elapsed = time.monotonic() - started
            code = proc.poll()
            if code is not None:
                print(f"FAIL: the launcher exited early with code {code} after {elapsed:.1f}s.\n"
                      f"--- last lines of {log.name}:\n{log_tail(log)}")
                return 1
            ok, last = probe(url)
            if ok:
                print(f"healthy after {elapsed:.1f}s ({url} -> {last})", flush=True)
                break
            if elapsed >= timeout:
                print(f"FAIL: not healthy after {timeout:.0f}s.\n"
                      f"  process still running: {proc.poll() is None} (pid {proc.pid})\n"
                      f"  anything listening on 127.0.0.1:{port}: {port_listening(port)}\n"
                      f"  last /health result: {last}\n"
                      f"--- last lines of {log.name}:\n{log_tail(log)}")
                return 1
            time.sleep(POLL_INTERVAL)
        problems = check_examples(f"http://127.0.0.1:{port}")
        if problems:
            print("FAIL:\n  " + "\n  ".join(problems))
            return 1
        print("PASS: started with the documented command, /health ok, / served, brief examples match.")
        return 0
    finally:
        stop(proc)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--command", help="launcher to run (default: run.sh, or run.ps1 on Windows)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for /health (default 60)")
    ap.add_argument("--log", type=Path, default=ROOT / "server.log")
    args = ap.parse_args(argv)
    if not args.command:
        command: Union[str, List[str]] = default_command()
    elif os.name == "nt":
        command = args.command  # Windows parses its own command line; shlex would keep the quotes
    else:
        command = shlex.split(args.command)
    return run(command, args.port, args.timeout, args.log)


if __name__ == "__main__":
    sys.exit(main())
