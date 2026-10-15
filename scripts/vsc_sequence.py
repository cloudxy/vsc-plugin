#!/usr/bin/env python3
"""Compatibility entry for vsc_sequence; implementation lives in vsc.story.sequence."""
from pathlib import Path as _Path
import sys as _sys
_root = _Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_root / "src"))
_sys.path.insert(0, str(_root))
from vsc.compat import expose as _expose
_expose(__name__, 'vsc.story.sequence', globals())
