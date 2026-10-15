"""Versioned consistency templates; factories return independent dictionaries."""
import copy
import json
from support.paths import ROOT

BIBLE = json.loads((ROOT / "templates/asset-bible.json").read_text("utf-8"))
STATE = json.loads((ROOT / "templates/scene-state.json").read_text("utf-8"))
PLAN = json.loads((ROOT / "templates/continuity-plan.json").read_text("utf-8"))
RECORD = json.loads((ROOT / "templates/generation-record.json").read_text("utf-8"))


def bible(**changes):
    value = copy.deepcopy(BIBLE)
    value.update(changes)
    return value


def state():
    return copy.deepcopy(STATE)


class RecordFixture:
    def record(self):
        return copy.deepcopy(RECORD)
