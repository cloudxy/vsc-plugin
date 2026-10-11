#!/usr/bin/env python3
"""consistency.py 自测。运行：python3 tests/test_consistency.py"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT, SCRIPTS
import consistency as C

BIBLE = json.loads((ROOT / "templates/asset-bible.json").read_text("utf-8"))
STATE = json.loads((ROOT / "templates/scene-state.json").read_text("utf-8"))
PLAN = json.loads((ROOT / "templates/continuity-plan.json").read_text("utf-8"))


def bible(**changes):
    value = copy.deepcopy(BIBLE)
    value.update(changes)
    return value


def state():
    return copy.deepcopy(STATE)


class BibleTest(unittest.TestCase):
    def test_template_is_valid(self):
        self.assertEqual(C.bible_errors(BIBLE), [])

    def test_identity_variants_and_bindings_are_required(self):
        value = bible()
        value["entities"][0]["identity"] = []
        value["entities"][1]["variants"] = {"夜": "冷光"}
        value["entities"][2]["voice"] = {"engine": "edge-tts", "voice": "x", "rights": "temp_only"}
        value["entities"][0]["references"][0]["sha256"] = "abc"
        errors = C.bible_errors(value)
        self.assertTrue(any("identity 不能为空" in error for error in errors))
        self.assertTrue(any("包含 default" in error for error in errors))
        self.assertTrue(any("voice 只用于人物" in error for error in errors))
        self.assertTrue(any("sha256" in error for error in errors))

    def test_duplicate_ids_and_bad_style_are_rejected(self):
        value = bible(subtitle_style={"position": "left", "color": "white"})
        value["entities"][1]["id"] = "主角"
        errors = C.bible_errors(value)
        self.assertTrue(any("id 必须唯一" in error for error in errors))
        self.assertTrue(any("position" in error for error in errors))
        self.assertTrue(any("#RRGGBB" in error for error in errors))

    def test_media_files_must_match_their_sha256(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            media = root / "06-素材/参考/主角-正面.png"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"front")
            value = bible()
            value["entities"] = [value["entities"][0]]
            value["entities"][0]["references"][0]["sha256"] = hashlib.sha256(b"front").hexdigest()
            self.assertEqual(C.media_problems(value, root), [])
            media.write_bytes(b"changed")
            self.assertIn("SHA-256 不一致", C.media_problems(value, root)[0])


class StateTest(unittest.TestCase):
    def test_template_is_valid_and_derives_entry_and_exit(self):
        self.assertEqual(C.state_errors(STATE, BIBLE), [])
        derived = C.derive(STATE)
        self.assertEqual(derived["SH-002"]["entry"]["entities"]["信封"]["variant"], "default")
        self.assertEqual(derived["SH-002"]["exit"]["entities"]["信封"]["variant"], "信封-已拆")
        self.assertEqual(derived["SH-001"]["entry"]["environment"]["weather"], "雨")

    def test_changes_accumulate_across_non_adjacent_shots(self):
        value = state()
        value["scenes"][0]["shots"] = [
            {"id": "A", "changes": {"entities": {"主角": {"position": "门口"}}}},
            {"id": "B", "changes": {}},
            {"id": "C", "changes": {"entities": {"信封": {"exit": True}, "主角": {"holding": []}}}},
            {"id": "D", "changes": {}},
        ]
        derived = C.derive(value)
        self.assertEqual(derived["B"]["entry"]["entities"]["主角"]["position"], "门口")
        self.assertNotIn("信封", derived["D"]["entry"]["entities"])
        self.assertEqual(C.state_errors(value, BIBLE), [])

    def test_held_items_must_be_present_and_held_once(self):
        value = state()
        value["scenes"][0]["shots"][1]["changes"] = {"entities": {"信封": {"exit": True}}}
        self.assertTrue(any("不在场" in error for error in C.state_errors(value, BIBLE)))
        value = state()
        value["scenes"][0]["baseline"]["entities"]["配角"] = {"holding": ["信封"]}
        errors = C.state_errors(value)
        self.assertTrue(any("同时被" in error for error in errors))

    def test_bible_checks_entities_variants_and_location(self):
        value = state()
        value["scenes"][0]["location_id"] = "主角"
        value["scenes"][0]["shots"][1]["changes"] = {"entities": {"信封": {"variant": "烧毁"}, "路人": {"position": "窗外"}}}
        errors = C.state_errors(value, BIBLE)
        self.assertTrue(any("不是资产库中的地点" in error for error in errors))
        self.assertTrue(any("没有变体 烧毁" in error for error in errors))
        self.assertTrue(any("路人 不在资产库中" in error for error in errors))

    def test_shot_ids_are_unique_across_scenes(self):
        value = state()
        second = copy.deepcopy(value["scenes"][0])
        second["id"] = "EP-001-SC-002"
        value["scenes"].append(second)
        self.assertTrue(any("全片唯一" in error for error in C.state_errors(value)))


class ContinuityCrossCheckTest(unittest.TestCase):
    def test_template_plan_agrees_with_timeline(self):
        problems, warnings = C.continuity_problems(PLAN, C.derive(STATE), BIBLE)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_costume_location_and_presence_mismatches_are_reported(self):
        plan = copy.deepcopy(PLAN)
        plan["shots"][0]["entry_state"]["characters"]["主角"]["costume_id"] = "default"
        plan["shots"][0]["exit_state"]["location_id"] = "别处"
        plan["shots"][1]["entry_state"]["characters"]["配角"] = {"costume_id": "x"}
        problems, warnings = C.continuity_problems(plan, C.derive(STATE), BIBLE)
        self.assertTrue(any("costume_id=default" in problem for problem in problems))
        self.assertTrue(any("location_id=别处" in problem for problem in problems))
        self.assertTrue(any("配角" in warning for warning in warnings))


class KernelTest(unittest.TestCase):
    def test_contracts_dispatch_through_the_kernel(self):
        for fmt, template in (("vsc.asset-bible/v1", "asset-bible.json"), ("vsc.scene-state/v1", "scene-state.json")):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_kernel.py"), "contract", "validate", fmt, str(ROOT / "templates" / template)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
