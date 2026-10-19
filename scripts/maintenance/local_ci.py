#!/usr/bin/env python3
"""Command entry for tools.maintenance.vsc_local_ci."""
from pathlib import Path
import os
import sys

_root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_root / "src"), str(_root)]
from vsc.bootstrap import workspace_python
_python = workspace_python(_root)
if Path(sys.executable).absolute() != Path(_python).absolute():
    os.execv(_python, [_python, "-B", *sys.argv])
from tools.maintenance.vsc_local_ci import main

if __name__ == "__main__":
    raise SystemExit(main())
