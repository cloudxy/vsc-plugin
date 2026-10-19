"""Tests import source packages and tools from the repository root."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Load the same Dynaconf settings before database fixtures select their target.
from vsc.configuration import get_settings
get_settings().get("TEST_DATABASE_URL")
