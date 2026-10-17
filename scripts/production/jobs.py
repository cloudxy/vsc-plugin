#!/usr/bin/env python3
"""Command entry for vsc.production.jobs."""
from pathlib import Path
import sys

_root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_root / "src"), str(_root)]
from vsc.production.jobs import main

if __name__ == "__main__":
    raise SystemExit(main())
