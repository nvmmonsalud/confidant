#!/usr/bin/env python3
"""Write the synthetic demo vault to data/samples/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from confidant.samples import seed  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "samples"
    written = seed(target)
    print(f"seeded {len(written)} documents into {target}")
    for path in written:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
