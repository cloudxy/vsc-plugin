#!/usr/bin/env python3
"""Command entry for tools.maintenance.vsc_pre_commit."""
from pathlib import Path
import sys

_root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_root / "src"), str(_root)]
from tools.maintenance.vsc_pre_commit import main

if __name__ == "__main__":
    raise SystemExit(main())
