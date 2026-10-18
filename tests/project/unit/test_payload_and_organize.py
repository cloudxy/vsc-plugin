"""B4-02 payload 对照、B3-03 任务尝试对照与 B3-06 整理预览（离线纯函数）。"""
import json
import tempfile
import unittest
from pathlib import Path

import support.paths  # noqa: F401
from vsc.production.performance import performance_payload_coverage
from vsc.project.organize import organize_preview


class PayloadCoverageTest(unittest.TestCase):
    MODEL = {"capabilities": {"performance_controls": {"rate": "speech_rate", "delivery": "context_texts"}},
             "default_params": {"speech_rate": 1.0}}

    def test_consumed_unconsumed_and_unsupported_fields_listed(self):
        result = performance_payload_coverage({"delivery": "speech", "emotion": "温柔",
            "controls": [{"field": "rate", "model_default": "speech_rate", "expected": 1.0},
                         {"field": "pace", "model_default": "pace_key", "expected": "x"}]}, self.MODEL)
        self.assertEqual([row["consumed"] for row in result["controls"]], [True, False])
        self.assertEqual(result["fields_without_model_control"], ["emotion"])
        self.assertIn("speech_rate", result["payload_note"])

    def test_empty_controls_yield_empty_rows(self):
        self.assertEqual(performance_payload_coverage({"delivery": "speech"}, self.MODEL)["controls"], [])


class OrganizePreviewTest(unittest.TestCase):
    def test_five_categories_and_readonly(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "04-视听设计").mkdir()
            (project / "04-视听设计/bible.json").write_text("{}", "utf-8")
            (project / "06-素材").mkdir()
            (project / "06-素材/视频.mp4").write_bytes(b"x")
            (project / "09-台账").mkdir(parents=True)
            (project / "09-台账/旧-备份.zip").write_bytes(b"x")
            (project / "random.txt").write_text("?", "utf-8")
            result = organize_preview(project)
            self.assertEqual(result["counts"], {"current": 1, "history": 0, "backup": 1, "renewable": 1, "unknown": 1})
            self.assertTrue(result["read_only"])
            self.assertIn("不计为清理完成", result["meaning"])
            self.assertIn("未知归属", result["actions"]["unknown"])

    def test_inventory_input_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            result = organize_preview(project, inventory={"files": [{"path": "06-素材/a.png"}, {"path": "x.md"}]})
            self.assertEqual(result["counts"]["renewable"], 1)
            self.assertEqual(result["counts"]["unknown"], 1)


if __name__ == "__main__":
    unittest.main()
