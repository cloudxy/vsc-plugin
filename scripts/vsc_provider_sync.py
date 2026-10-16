#!/usr/bin/env python3
"""Compatibility entry for the shared provider tool updater."""
from pathlib import Path
import sys
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))
sys.path.insert(0, str(_root))
from vsc.compat import expose
expose(__name__, "tools.maintenance.provider_sync", globals())
