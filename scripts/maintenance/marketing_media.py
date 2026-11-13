#!/usr/bin/env python3
"""Command entry for tools.maintenance.marketing_media."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'src'), str(root)]
from vsc.bootstrap import workspace_python
python = workspace_python(root)
if Path(sys.executable).absolute() != Path(python).absolute():
    os.execv(python, [python, '-B', *sys.argv])
from tools.maintenance.marketing_media import main

if __name__ == '__main__':
    raise SystemExit(main())
