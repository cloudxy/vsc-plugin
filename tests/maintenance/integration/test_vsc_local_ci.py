#!/usr/bin/env python3
"""scripts/maintenance/local_ci.py 自测。运行：python3 -B tests/run.py --test maintenance.integration.test_vsc_local_ci"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from support.paths import SCRIPTS
SCRIPT = SCRIPTS / "maintenance/local_ci.py"
import tools.maintenance.vsc_local_ci as LOCAL_CI


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class TestTracked(unittest.TestCase):
    def test_real_initialization_files_are_rejected_but_example_is_allowed(self):
        problems = LOCAL_CI.tracked_problems(['.env', '.env.local', 'config/.env.prod', '.env.example'])
        self.assertEqual(len(problems), 3)
        self.assertTrue(all('本机初始化配置' in value for value in problems))
    def test_repository_sources_and_vendor_declarations_pass(self):
        paths = ["skills/vsc/SKILL.md", "scripts/project/state.py", "vendor/README.md", "vendor/sources.lock.json", "vendor/THIRD_PARTY.md"]
        self.assertEqual(LOCAL_CI.tracked_problems(paths), [])

    def test_project_data_vendor_source_and_local_files_are_rejected(self):
        problems = LOCAL_CI.tracked_problems([
            "projects/示例作品/vsc.json",
            "library/character/示例/item.json",
            "vendor/inkos/README.md",
            ".claude/settings.local.json",
            "docs/.DS_Store",
            "docs/plans/local-plan.md",
            "scripts/__pycache__/vsc_state.cpython-39.pyc",
        ])
        self.assertEqual(len(problems), 7)
        self.assertIn("作品数据", problems[0])
        self.assertIn("素材库内容", problems[1])
        self.assertIn("vendor 源码", problems[2])


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
            checked, problems = LOCAL_CI.link_problems(["docs/guide/cli.md", "docs/README.md", "agents/role.md", ".agents/role.md"], root)
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
            optional = LOCAL_CI.installed_problems([{"id": "absent", "revision": revision, "install": "explicit"}], vendor)
            self.assertEqual(optional, [])
            ported = LOCAL_CI.installed_problems([{"id": "absent", "revision": revision, "usage": {"mode": "ported"}}], vendor)
            self.assertEqual(ported, [])

    def test_routed_skill_missing_from_vendor_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            problems = LOCAL_CI.route_problems(Path(temp))
            self.assertTrue(problems)
            self.assertTrue(all("缺失" in problem for problem in problems))


class TestProjects(unittest.TestCase):
    def test_readable_project_passes_and_unreadable_project_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run([sys.executable, "-B", str(SCRIPTS / "project/state.py"), "init", str(root / "可读"), "--title", "可读"], check=True, capture_output=True)
            projects, problems = LOCAL_CI.project_problems(root)
            self.assertEqual((len(projects), problems), (1, []))
            broken = root / "旧版"
            broken.mkdir()
            (broken / "vsc.json").write_text(json.dumps({"schema_version": 99}), "utf-8")
            projects, problems = LOCAL_CI.project_problems(root)
            self.assertEqual(len(projects), 2)
            self.assertEqual(len(problems), 1)
            self.assertIn("旧版", problems[0])


class TestFullTestGate(unittest.TestCase):
    def test_final_gate_runs_configured_full_suite_and_propagates_failures(self):
        for code in (0, 1, 2):
            with self.subTest(exit_code=code):
                completed = subprocess.CompletedProcess([], code,
                    stdout="TEST RESULT: methods=3 subtests=2\nDURATION 0.1s sample.test\n",
                    stderr="Ran 3 tests in 0.1s\n" + ("OK" if code == 0 else "FAILED"))
                with mock.patch.object(LOCAL_CI, "run", return_value=completed) as invoke:
                    detail, problems = LOCAL_CI.check_tests()
                args = invoke.call_args.args
                self.assertEqual(args[0], LOCAL_CI.PYTHON)
                self.assertEqual(Path(args[2]), SCRIPTS.parent / "tests/run.py")
                self.assertIn("--all", args)
                self.assertEqual(bool(problems), code != 0)
                self.assertIn("Ran 3 tests", detail)
                if code == 0:
                    self.assertIn("DURATION", detail)


class TestScopedGate(unittest.TestCase):
    def test_document_push_does_not_run_code_tests(self):
        mode, checks = LOCAL_CI.scoped_checks(["docs/plans/plan.html", "docs/README.md"])
        self.assertEqual(mode, "docs")
        self.assertEqual([name for name, _ in checks], ["tracked", "links"])

    def test_code_and_unknown_baseline_keep_full_default(self):
        for paths in (["src/vsc/example.py"], ["skills/vsc/SKILL.md"], None):
            with self.subTest(paths=paths):
                mode, checks = LOCAL_CI.scoped_checks(paths)
                self.assertEqual(mode, "full")
                self.assertEqual(checks, LOCAL_CI.CHECKS)
        self.assertEqual(LOCAL_CI.scoped_checks(["docs/README.md"], "full")[0], "full")

    def test_small_fix_uses_selected_tests_and_preserves_failure(self):
        mode, checks = LOCAL_CI.scoped_checks(["src/vsc/example.py"], "targeted", ["post.unit.test_subtitles"])
        self.assertEqual(mode, "targeted")
        for code in (0, 1, 2):
            with self.subTest(code=code):
                completed = subprocess.CompletedProcess([], code, "", "OK" if code == 0 else "FAILED")
                with mock.patch.object(LOCAL_CI, "run", return_value=completed) as invoke:
                    _, problems = dict(checks)["tests"]()
                self.assertIn("--test", invoke.call_args.args)
                self.assertIn("post.unit.test_subtitles", invoke.call_args.args)
                self.assertNotIn("--all", invoke.call_args.args)
                self.assertEqual(bool(problems), code != 0)

    def test_targeted_without_explicit_tests_uses_changed_paths(self):
        _, checks = LOCAL_CI.scoped_checks(["src/vsc/example.py"], "targeted")
        with mock.patch.object(LOCAL_CI, "check_tests", return_value=("", [])) as invoke:
            dict(checks)["tests"]()
        invoke.assert_called_once_with(("--files", "src/vsc/example.py"))
        for scope, paths in (("skip", []), ("targeted", None)):
            with self.assertRaises(ValueError):
                LOCAL_CI.scoped_checks(paths, scope)

    def test_actual_push_diff_includes_deletions_and_multiple_refs(self):
        result = subprocess.CompletedProcess([], 0, "docs/removed.md\0src/changed.py\0", "")
        with mock.patch.object(LOCAL_CI, "run", return_value=result) as invoke:
            paths = LOCAL_CI.push_paths(["refs/heads/main abc refs/heads/main def\n",
                                         "refs/heads/other ghi refs/heads/other jkl\n"])
        self.assertEqual(paths, ["docs/removed.md", "src/changed.py"])
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("--no-renames", invoke.call_args.args)
        self.assertEqual(invoke.call_args.args[-2:], ("jkl", "ghi"))
        self.assertIsNone(LOCAL_CI.push_paths(["ref abc ref " + "0" * 40]))
        self.assertEqual(LOCAL_CI.push_paths(["ref " + "0" * 40 + " ref abc"]), [])
        with self.assertRaises(ValueError):
            LOCAL_CI.push_paths(["invalid"])
        with mock.patch.object(LOCAL_CI, "run", return_value=subprocess.CompletedProcess([], 1, "", "bad ref")):
            with self.assertRaises(ValueError):
                LOCAL_CI.push_paths(["ref abc ref def"])


if __name__ == "__main__":
    unittest.main()
