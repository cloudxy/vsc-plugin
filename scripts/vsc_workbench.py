#!/usr/bin/env python3
"""Compatibility entry for the shared read-only creative workspace."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from vsc.compat import expose
expose(__name__, 'vsc.interfaces.cli.workbench', globals())
