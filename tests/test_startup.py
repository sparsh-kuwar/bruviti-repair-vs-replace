"""Start-up behaviour (scripts/smoke_start.py and the launchers).

Regression for the Windows CI hang: the server was started in one CI step and
polled from the next, but Windows runners kill a step's processes when it ends,
and the poll had no per-request bound. These tests run real child processes
over loopback only (the network guard still blocks anything external).
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import smoke_start  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke(args, timeout=120):
    started = time.monotonic()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_start.py"), *args],
                       cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - started


def test_server_stays_up_and_passes_the_grader_check(tmp_path):
    port = free_port()
    code, out, _ = smoke(["--command", f'"{sys.executable}" -m uvicorn app.main:app --host 127.0.0.1 --port {port}',
                          "--port", str(port), "--timeout", "30", "--log", str(tmp_path / "s.log")])
    assert code == 0, out
    assert "healthy after" in out and "PASS" in out
    for line in ("C-2001: repair 8150.0 0.9", "C-2002: replace 16675.0 0.85", "C-2003: escalate None 0.7"):
        assert line in out


def test_launcher_that_exits_fails_fast_with_its_output(tmp_path):
    port = free_port()
    code, out, took = smoke(["--command", f'"{sys.executable}" -c "print(\'boom\'); raise SystemExit(3)"',
                             "--port", str(port), "--timeout", "60", "--log", str(tmp_path / "s.log")])
    assert code == 1
    assert "exited early with code 3" in out and "boom" in out
    assert took < 20, took  # does not wait for the 60 s deadline


def test_launcher_that_never_listens_fails_at_the_deadline_with_diagnostics(tmp_path):
    port = free_port()
    code, out, took = smoke(["--command", f'"{sys.executable}" -c "import time; time.sleep(60)"',
                             "--port", str(port), "--timeout", "3", "--log", str(tmp_path / "s.log")])
    assert code == 1
    assert "not healthy after 3s" in out
    assert "process still running: True" in out
    assert f"anything listening on 127.0.0.1:{port}: False" in out
    assert took < 20, took  # bounded: deadline + per-request timeouts, then the child is killed


@pytest.mark.parametrize("status,body,ok", [
    (200, b'{"status":"ok"}', True),
    (200, b'{"status": "ok"}', True),
    (200, b'{"status":"starting"}', False),
    (200, b'{"status":"ok","extra":1}', False),
    (503, b'{"status":"ok"}', False),
    (200, b"ok", False),
])
def test_health_contract_is_exact(status, body, ok):
    assert smoke_start.health_ok(status, body) is ok


def test_windows_launcher_prefers_the_python_on_path():
    # Root cause of the Windows failure: `py` picked the newest installed Python
    # (3.14), not the one set up. PATH python must be tried first.
    line = next(l for l in (ROOT / "run.ps1").read_text(encoding="utf-8").splitlines() if "foreach ($candidate" in l)
    order = [c.strip(' "') for c in line.split("@(")[1].split(")")[0].split(",")]
    assert order.index("python") < order.index("py"), order


def test_requirements_have_wheels_for_supported_pythons():
    # pydantic 2.10 / pydantic-core 2.27 had no Python 3.14 wheel, so pip tried to
    # compile Rust and the service could not install. Guard the pin floor.
    pins = dict(line.split("==") for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                if "==" in line and not line.startswith("#"))
    major, minor, *_ = (int(x) for x in pins["pydantic"].split("."))
    assert (major, minor) >= (2, 12), "pydantic < 2.12 has no Python 3.14 wheels"
