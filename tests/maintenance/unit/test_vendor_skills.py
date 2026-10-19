#!/usr/bin/env python3
"""scripts/maintenance/vendor_skills.py 自测。运行：python3 -B tests/run.py --test maintenance.unit.test_vendor_skills"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from support.paths import SCRIPTS
SCRIPT = SCRIPTS / "maintenance/vendor_skills.py"
import tools.maintenance.vendor_skills as VENDOR_SKILLS


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

    def test_product_guides_resolve_original_pinned_files_without_wrapper(self):
        import json
        from support.paths import ROOT
        sources = {s["id"]: s for s in json.loads((ROOT / "vendor/sources.lock.json").read_text())["sources"]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source, relative, _, _ in VENDOR_SKILLS.ROUTES["architecture"]:
                if source not in {"anthropic-frontend-design", "vercel-web-interface-guidelines", "agency-product-design"}:
                    continue
                self.assertEqual(len(sources[source]["revision"]), 40)
                self.assertTrue(any(relative == path or relative.startswith(path + "/") for path in sources[source]["sparse_paths"]))
                self.write_skill(root, source, relative, "---\ndescription: original upstream fixture\n---\n")
            guides = [r for r in VENDOR_SKILLS.resolve("architecture", root) if r["source_id"] != "mattpocock-skills"]
            self.assertEqual(len(guides), 5)
            self.assertTrue(all(r["readiness"] == "guide" for r in guides))
            canonical = next(r for r in guides if r["source_id"] == "vercel-web-interface-guidelines")
            self.assertEqual(canonical["relative_path"], "vercel-web-interface-guidelines/command.md")
            self.assertFalse(any("agent-skills" in r["source_id"] for r in guides))


if __name__ == "__main__":
    unittest.main()
