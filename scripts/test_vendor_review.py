#!/usr/bin/env python3
"""vendor_review.py 自测。运行：python3 scripts/test_vendor_review.py"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("vendor_review", HERE / "vendor_review.py")
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


class TestVendorReview(unittest.TestCase):
    def test_changed_deleted_and_new_skills_are_classified_without_auto_adoption(self):
        with tempfile.TemporaryDirectory() as temp:
            current, candidate = Path(temp) / "current", Path(temp) / "candidate"
            referenced = "packages/core/skills/inkos-script-writing/SKILL.md"
            deleted = "packages/core/skills/inkos-story-review/SKILL.md"
            write(current, referenced, "old")
            write(current, deleted, "old review")
            write(candidate, referenced, "new")
            write(candidate, "skills/new/SKILL.md", "new skill")
            report = REVIEW.analyze("inkos", current, candidate, "oldrev", "newrev")
            actions = {change["path"]: change for change in report["changes"]}
            self.assertEqual(actions[referenced]["kind"], "changed_referenced_skill")
            self.assertEqual(actions[deleted]["required_action"], "retain_last_approved_snapshot_or_replace_route")
            self.assertEqual(actions["skills/new/SKILL.md"]["kind"], "new_skill")
            self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")

    def test_report_writes_machine_and_human_views(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, candidate = root / "current", root / "candidate"
            write(current, "SKILL.md", "before")
            write(candidate, "SKILL.md", "after")
            report = REVIEW.analyze("unknown", current, candidate, candidate_revision="abcdef123456")
            json_path, markdown_path = REVIEW.write_report(report, root / "reports")
            self.assertEqual(json.loads(json_path.read_text("utf-8"))["format"], REVIEW.FORMAT)
            self.assertIn("待填写", markdown_path.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
