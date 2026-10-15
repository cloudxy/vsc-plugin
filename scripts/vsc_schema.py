#!/usr/bin/env python3
"""Compatible command entry for relational schema review."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vsc.compat import expose
expose(__name__, "vsc.project.schema_review", globals())
