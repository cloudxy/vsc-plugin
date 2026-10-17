#!/usr/bin/env python3
"""Command entry for vsc.adapters.providers.xai_grok.api."""
from pathlib import Path
import sys

_root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_root / "src"), str(_root)]
from vsc.adapters.providers.xai_grok.api import main

if __name__ == "__main__":
    raise SystemExit(main())
