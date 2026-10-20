"""Vercel entry point.

Vercel's Python runtime looks for an ASGI object named `app` in this file and
serves it for every routed request. Three things have to be true before the
package is imported, which is why they are set here and not in config:

1. ``src/`` must be on ``sys.path`` — the deployed tree has no editable install.
2. The ledger must move to ``/tmp`` — everything outside it is read-only.
3. Static assets and sample documents must resolve to the deployed root, since
   the package no longer sits two directories below it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Cloud tiers are real; the device tier is a labelled stand-in. A shared server
# has no laptop to be private on, and pretending otherwise would be the exact
# dishonesty this project exists to argue against.
os.environ.setdefault("CONFIDANT_MODE", "hybrid")
os.environ.setdefault("CONFIDANT_WEB", str(ROOT / "web"))
os.environ.setdefault("CONFIDANT_DATA", str(ROOT / "data"))
os.environ.setdefault("CONFIDANT_LEDGER", "/tmp/confidant-ledger.jsonl")

from confidant.api import app  # noqa: E402,F401  (Vercel discovers this name)
