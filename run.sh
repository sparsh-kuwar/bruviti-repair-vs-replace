#!/usr/bin/env sh
# One command: create a local virtualenv, install pinned dependencies, start the
# service (API + UI) on port 8000. Safe to re-run; it reuses .venv if present.
set -eu
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$candidate"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "Python 3.9+ is required (set PYTHON=/path/to/python to override)." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
