"""Tests share one repository root and scripts import bootstrap."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for path in (ROOT / "src", ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
