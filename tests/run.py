#!/usr/bin/env python3
"""Configured VSC tests. Use --changed while editing; --all at final verification."""
from pathlib import Path
import os
import sys

_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root / "src"))
from vsc.bootstrap import workspace_python
_python = workspace_python(_root)
if Path(sys.executable).absolute() != Path(_python).absolute():
    os.execv(_python, [_python, "-B", *sys.argv])
from support.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
