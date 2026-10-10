#!/usr/bin/env python3
"""vsc_views.py 自测。运行：python3 tests/test_vsc_views.py"""
import json
import tempfile
import unittest
from pathlib import Path

from _paths import ROOT
import vsc_views as VIEWS


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in ("workflow/kernel.json", "workflow/hosts.json", ".zcode-plugin/plugin.json"):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        stage = {"id": "adapt", "command": "vsc-adapt", "skill": "vsc-adapt", "roles": ["story-analyst"],
                 "entry": {"mode": "adapt", "summary": "改编", "description": "d", "argument_hint": "h"}}
        (self.root / "workflow/kernel.json").write_text(json.dumps({"stages": [stage]}, ensure_ascii=False), "utf-8")
        (self.root / "workflow/hosts.json").write_text(json.dumps({"format": "vsc.hosts/v1", "entries": [], "hosts": []}), "utf-8")
        (self.root / ".zcode-plugin/plugin.json").write_text(json.dumps({"name": "vsc-workflow", "version": "1.2.3", "description": "简介。更多说明。", "keywords": ["short-drama"]}, ensure_ascii=False), "utf-8")
        (self.root / "docs/guide").mkdir(parents=True)
        (self.root / "docs/guide/workspace-setup.md").write_text("# 接入\n\n<!-- vsc:view hosts -->\n<!-- /vsc:view -->\n", "utf-8")
        (self.root / "AGENTS.md").write_text("# 规则\n\n<!-- vsc:view routes -->\n旧表\n<!-- /vsc:view -->\n\n结尾\n", "utf-8")
        (self.root / "README.md").write_text("<!-- vsc:view version -->\n<!-- /vsc:view -->\n", "utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_sync_renders_declarations_and_check_detects_drift(self):
        self.assertEqual(len(VIEWS.view_problems(self.root)), 4)
        VIEWS.sync(self.root)
        self.assertEqual(VIEWS.view_problems(self.root), [])
        agents = (self.root / "AGENTS.md").read_text("utf-8")
        self.assertIn("| 改编 | `vsc-adapt` | adapt | story-analyst |", agents)
        self.assertTrue(agents.endswith("<!-- /vsc:view -->\n\n结尾\n"))
        self.assertIn("v1.2.3", (self.root / "README.md").read_text("utf-8"))
        market = json.loads((self.root / "marketplace.json").read_text("utf-8"))["plugins"][0]
        self.assertEqual((market["version"], market["description"], market["tags"]), ("1.2.3", "简介。", ["short-drama"]))
        kernel = json.loads((self.root / "workflow/kernel.json").read_text("utf-8"))
        kernel["stages"][0]["entry"]["summary"] = "改编与分集"
        (self.root / "workflow/kernel.json").write_text(json.dumps(kernel, ensure_ascii=False), "utf-8")
        self.assertEqual(VIEWS.view_problems(self.root), ["文档视图已过期：AGENTS.md（运行 python3 -B scripts/vsc_views.py sync）"])

    def test_missing_block_is_reported(self):
        (self.root / "README.md").write_text("没有标记块\n", "utf-8")
        self.assertIn("vsc:view version", VIEWS.view_problems(self.root)[0])

    def test_repository_views_are_current(self):
        self.assertEqual(VIEWS.view_problems(ROOT), [])


if __name__ == "__main__":
    unittest.main()
