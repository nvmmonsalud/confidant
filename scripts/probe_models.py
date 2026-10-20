#!/usr/bin/env python3
"""List the live Token Factory catalogue.

Model ids move. This prints what your key can actually call, so you never ship
a name you read in a blog post.

    PYTHONPATH=src ./.venv/bin/python scripts/probe_models.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidant.config import settings  # noqa: E402
from confidant.providers import probe_token_factory  # noqa: E402


async def main() -> int:
    result = await probe_token_factory(settings)
    if not result.get("ok"):
        print(f"probe failed: {result.get('error')}")
        print("Set NEBIUS_API_KEY in .env (or ~/.hermes/.env) and try again.")
        return 1

    print(f"base_url : {settings.nebius_base_url}")
    print(f"models   : {result['count']} available\n")

    nemotron = result["nemotron"]
    if nemotron:
        print("Nemotron ids you can call:")
        for mid in nemotron:
            print(f"  {mid}")
    else:
        print("No Nemotron ids in this catalogue — check the key's project scope.")

    print("\nconfigured ->")
    print(f"  light : {settings.model_light}")
    print(f"  deep  : {settings.model_deep}")

    configured = {settings.model_light, settings.model_deep}
    missing = configured - set(result["all"])
    if missing:
        print("\nWARNING: these configured ids are not in the catalogue:")
        for mid in sorted(missing):
            print(f"  {mid}")
        print("Pick the closest id above and set CONFIDANT_MODEL_LIGHT / CONFIDANT_MODEL_DEEP.")
        return 2

    print("\nBoth configured ids are live. Good to run with CONFIDANT_MODE=live.")
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
