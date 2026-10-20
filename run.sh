#!/usr/bin/env bash
# One command from a clean clone to a running Confidant.
set -euo pipefail
cd "$(dirname "$0")"

# A stray PYTHONPATH (Hermes exports one pointing at its own venv) makes a
# missing dependency look installed, and then the app dies on first import.
unset PYTHONPATH

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
./.venv/bin/python -m pip install -q --upgrade pip
./.venv/bin/python -m pip install -q -r requirements-dev.txt

# Fail loudly here rather than mysteriously at request time.
./.venv/bin/python - <<'PYCHECK'
import importlib, sys

def _has(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except ModuleNotFoundError:
        return False

missing = [m for m in ("fastapi", "uvicorn", "httpx", "pydantic") if not _has(m)]
if missing:
    sys.exit("missing from the venv (is PYTHONPATH polluting it?): " + ", ".join(missing))
PYCHECK

export PYTHONPATH="$PWD/src"
export CONFIDANT_MODE="${CONFIDANT_MODE:-mock}"

# Seed the synthetic vault if it is not already on disk.
./.venv/bin/python scripts/seed.py

echo
echo "  Confidant  ·  mode=${CONFIDANT_MODE}"
echo "  http://127.0.0.1:${PORT:-8765}"
echo "  (mock mode needs no credentials; live mode needs NEBIUS_API_KEY + TAVILY_API_KEY)"
echo
exec ./.venv/bin/python -m uvicorn confidant.api:app --host 127.0.0.1 --port "${PORT:-8765}"
