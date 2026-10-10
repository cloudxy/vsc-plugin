#!/usr/bin/env python3
"""vsc_local_ci.py 自测。运行：python3 tests/test_vsc_local_ci.py"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _paths import SCRIPTS
SCRIPT = SCRIPTS / "vsc_local_ci.py"
SPEC = importlib.util.spec_from_file_location("vsc_local_ci", SCRIPT)
LOCAL_CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOCAL_CI)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class TestTracked(unittest.TestCase):
    def test_repository_sources_and_vendor_declarations_pass(self):
        paths = ["skills/vsc/SKILL.md", "scripts/vsc_state.py", "vendor/README.md", "vendor/sources.lock.json", "vendor/THIRD_PARTY.md"]
        self.assertEqual(LOCAL_CI.tracked_problems(paths), [])

    def test_project_data_vendor_source_and_local_files_are_rejected(self):
        problems = LOCAL_CI.tracked_problems([
            "projects/放下/vsc.json",
            "vendor/inkos/README.md",
            ".claude/settings.local.json",
            "docs/.DS_Store",
            "scripts/__pycache__/vsc_state.cpython-39.pyc",
        ])
        self.assertEqual(len(problems), 5)
        self.assertIn("作品数据", problems[0])
        self.assertIn("vendor 源码", problems[1])


class TestLinks(unittest.TestCase):
    def test_relative_links_must_resolve_and_symlinked_entries_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs/guide").mkdir(parents=True)
            (root / "docs/guide/cli.md").write_text("[ok](../README.md#x) [web](https://example.com) [bad](../missing.md)", "utf-8")
            (root / "docs/README.md").write_text("# 文档", "utf-8")
            (root / "agents").mkdir()
            (root / "agents/role.md").write_text("[卡](../docs/README.md)", "utf-8")
            (root / ".agents").mkdir()
            os.symlink("../agents/role.md", root / ".agents/role.md")
            checked, problems = LOCAL_CI.link_problems(["docs/guide/cli.md", "docs/README.md", "agents/role.md", ".agents/role.md", "vendor/x.md"], root)
            self.assertEqual(checked, 3)
            self.assertEqual(problems, ["docs/guide/cli.md 链接不存在：../missing.md"])


class TestVendor(unittest.TestCase):
    def test_installed_revision_must_match_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            vendor = Path(temp)
            source = vendor / "sample"
            source.mkdir()
            git(source, "init", "-q")
            (source / "README.md").write_text("sample\n", "utf-8")
            git(source, "add", "README.md")
            git(source, "-c", "user.name=VSC test", "-c", "user.email=vsc-test@example.invalid", "commit", "-q", "-m", "init")
            revision = git(source, "rev-parse", "HEAD")
            self.assertEqual(LOCAL_CI.installed_problems([{"id": "sample", "revision": revision}], vendor), [])
            stale = LOCAL_CI.installed_problems([{"id": "sample", "revision": "a" * 40}], vendor)
            self.assertIn("不一致", stale[0])
            missing = LOCAL_CI.installed_problems([{"id": "absent", "revision": revision}], vendor)
            self.assertIn("--install absent", missing[0])

    def test_routed_skill_missing_from_vendor_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            problems = LOCAL_CI.route_problems(Path(temp))
            self.assertTrue(problems)
            self.assertTrue(all("缺失" in problem for problem in problems))


class TestProjects(unittest.TestCase):
    def test_readable_project_passes_and_unreadable_project_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run([sys.executable, "-B", str(SCRIPTS / "vsc_state.py"), "init", str(root / "可读"), "--title", "可读"], check=True, capture_output=True)
            projects, problems = LOCAL_CI.project_problems(root)
            self.assertEqual((len(projects), problems), (1, []))
            broken = root / "旧版"
            broken.mkdir()
            (broken / "vsc.json").write_text(json.dumps({"schema_version": 99}), "utf-8")
            projects, problems = LOCAL_CI.project_problems(root)
            self.assertEqual(len(projects), 2)
            self.assertEqual(len(problems), 1)
            self.assertIn("旧版", problems[0])


if __name__ == "__main__":
    unittest.main()
