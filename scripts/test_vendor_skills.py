#!/usr/bin/env python3
"""vendor_skills.py 自测。运行：python3 scripts/test_vendor_skills.py"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "vendor_skills.py"
SPEC = importlib.util.spec_from_file_location("vendor_skills", SCRIPT)
VENDOR_SKILLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VENDOR_SKILLS)


class TestVendorSkills(unittest.TestCase):
    def write_skill(self, root, source, relative, text):
        path = root / source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        return path

    def test_discover_reads_skill_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write_skill(root, "inkos", "skills/sample/SKILL.md", "---\nname: sample\ndescription: example\n---\n# Skill\n")
            records = VENDOR_SKILLS.discover(root)
            self.assertEqual(records, [{"source_id": "inkos", "name": "sample", "description": "example", "relative_path": "inkos/skills/sample/SKILL.md"}])

    def test_resolve_marks_installed_guide_as_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write_skill(root, "inkos", "packages/core/skills/inkos-script-writing/SKILL.md", "---\nname: inkos-script-writing\n---\n")
            self.write_skill(root, "inkos", "packages/core/skills/inkos-story-review/SKILL.md", "---\nname: inkos-story-review\n---\n")
            records = VENDOR_SKILLS.resolve("adapt", root)
            self.assertEqual(records[0]["readiness"], "guide")
            self.assertEqual(records[2]["readiness"], "missing: install source")

    def test_safe_skill_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                VENDOR_SKILLS.safe_skill_path("inkos", "../../outside/SKILL.md", Path(temp))


if __name__ == "__main__":
    unittest.main()
