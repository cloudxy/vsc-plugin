#!/usr/bin/env python3
"""Candidate maintenance interface tests with local Git repositories; no network or real Vendor writes."""
import datetime
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from _paths import SCRIPTS
import vendor_watch as WATCH
from test_vendor_sync import refresh_policy



def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


class TestVendorWatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        git(self.upstream, "init", "-q")
        git(self.upstream, "config", "user.name", "VSC test")
        git(self.upstream, "config", "user.email", "vsc-test@example.invalid")
        write(self.upstream, "skills/a/SKILL.md", "Read [rule](rules.md).")
        write(self.upstream, "skills/a/rules.md", "old")
        write(self.upstream, "skills/a/run.py", "raise RuntimeError('must not execute')")
        (self.upstream / "skills/a/run.py").chmod(0o755)
        write(self.upstream, "LICENSE", "MIT")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "baseline")
        self.base_revision = git(self.upstream, "rev-parse", "HEAD")
        write(self.upstream, "skills/a/rules.md", "new")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "rule update")
        self.new_revision = git(self.upstream, "rev-parse", "HEAD")
        self.source = {"id": "local-test", "type": "git", "url": str(self.upstream),
                       "revision": self.base_revision, "license_spdx": "MIT", "license_evidence": "fixture",
                       "purpose": "test", "owner": "test", "redistribution": "local_only",
                       "usage": {"mode": "local_component", "interface": "file", "modified": False}}
        self.plugin = self.root / "plugin"
        self.updater = self.root / "updater"
        write(self.plugin, "vendor/local-test/keep.txt", "active untouched")
        self.snapshots = self.updater / "backups/vsc-vendor-candidates/local-test"

    def process(self, **kwargs):
        return WATCH.process(self.plugin, self.updater, self.source, 90, 3, **kwargs)

    def test_complete_restorable_bundles_analysis_and_active_unchanged(self):
        self.assertEqual(self.process(), "reviewed")
        snapshots = list(self.snapshots.glob("*"))
        self.assertEqual(len(snapshots), 2)
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", self.new_revision)
        self.assertEqual((candidate / "skills/a/rules.md").read_text(), "new")
        self.assertEqual((candidate / "LICENSE").read_text(), "MIT")
        self.assertTrue((candidate / "skills/a/run.py").stat().st_mode & 0o111)
        state = WATCH.load_json(candidate / ".analysis.json")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(WATCH.load_json(Path(state["json_report"]))["summary"]["change_count"], 1)
        self.assertEqual((self.plugin / "vendor/local-test/keep.txt").read_text(), "active untouched")
        self.assertEqual(self.process(), "unchanged")

    def test_analysis_failure_is_retried_without_redownloading_snapshot(self):
        def fail(*_args):
            raise RuntimeError("injected review failure")
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.process(review_fn=fail)
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", self.new_revision)
        self.assertEqual(WATCH.load_json(candidate / ".analysis.json")["status"], "failed")
        self.assertEqual(self.process(), "reviewed")
        self.assertEqual(len(list(self.snapshots.glob("*"))), 2)
        self.assertEqual(WATCH.load_json(candidate / ".analysis.json")["status"], "completed")

    def test_deleted_report_triggers_reanalysis(self):
        self.process()
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", self.new_revision)
        state = WATCH.load_json(candidate / ".analysis.json")
        Path(state["json_report"]).unlink()
        self.assertEqual(self.process(), "reviewed")
        self.assertTrue(Path(state["json_report"]).is_file())

    def test_corrupt_analysis_checkpoint_and_report_are_rebuilt(self):
        self.process()
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", self.new_revision)
        write(candidate, ".analysis.json", "not JSON")
        self.assertEqual(self.process(), "reviewed")
        state = WATCH.load_json(candidate / ".analysis.json")
        Path(state["json_report"]).write_text("[]", "utf-8")
        self.assertEqual(self.process(), "reviewed")

    def test_tampered_snapshot_fails_integrity(self):
        self.process()
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", self.new_revision)
        write(candidate, "skills/a/rules.md", "tampered")
        with self.assertRaisesRegex(WATCH.WatchError, "完整性"):
            self.process()

    def test_retention_applies_age_and_count_including_baseline(self):
        self.snapshots.mkdir(parents=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        for index, age in enumerate((100, 5, 4, 3, 2)):
            folder = self.snapshots / str(index)
            write(folder, ".vsc-candidate.json", json.dumps({"format": WATCH.CANDIDATE_FORMAT,
                  "created_at": (now - datetime.timedelta(days=age)).isoformat()}))
        WATCH.prune_candidates(self.snapshots, 90, 3)
        self.assertEqual({path.name for path in self.snapshots.iterdir()}, {"2", "3", "4"})

    def test_git_symlink_is_not_materialized_or_followed(self):
        (self.upstream / "skills/a/escape").symlink_to("/etc/passwd")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "unsafe symlink")
        self.assertEqual(self.process(), "reviewed")
        revision = git(self.upstream, "rev-parse", "HEAD")
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", revision)
        self.assertFalse((candidate / "skills/a/escape").exists())
        metadata = WATCH.load_json(candidate / ".vsc-candidate.json")
        self.assertFalse(metadata["skills"]["skills/a/SKILL.md"]["usable"])
        state = WATCH.load_json(candidate / ".analysis.json")
        self.assertEqual(WATCH.load_json(Path(state["json_report"]))["summary"]["adoption"], "blocked_pending_review")
        self.assertEqual(self.process(), "unchanged")
        self.assertEqual((self.plugin / "vendor/local-test/keep.txt").read_text(), "active untouched")

    def test_missing_real_resource_produces_blocked_candidate_report(self):
        write(self.upstream, "skills/broken/SKILL.md", "[required](missing.md)")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "missing resource")
        revision = git(self.upstream, "rev-parse", "HEAD")
        self.assertEqual(self.process(), "reviewed")
        candidate = WATCH.existing_candidate(self.snapshots, "local-test", revision)
        state = WATCH.load_json(candidate / ".analysis.json")
        report = WATCH.load_json(Path(state["json_report"]))
        self.assertEqual(report["summary"]["candidate_unusable_skill_count"], 1)
        self.assertEqual(report["summary"]["adoption"], "blocked_pending_review")
        self.assertEqual(self.process(), "unchanged")

    def test_oversize_resource_is_diagnosed_and_not_materialized(self):
        write(self.upstream, "skills/a/large.bin", "x" * 100)
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "large fixture")
        # Limit only the binary fixture; Markdown and script remain below this threshold.
        from unittest import mock
        with mock.patch.object(WATCH.vendor_bundle, "MAX_FILE_BYTES", 80):
            self.assertEqual(self.process(), "reviewed")
            revision = git(self.upstream, "rev-parse", "HEAD")
            candidate = WATCH.existing_candidate(self.snapshots, "local-test", revision)
            self.assertFalse((candidate / "skills/a/large.bin").exists())
            self.assertFalse(WATCH.load_json(candidate / ".vsc-candidate.json")["skills"]["skills/a/SKILL.md"]["usable"])
            self.assertEqual(self.process(), "unchanged")

    def test_wrapper_preserves_worker_nonzero_status(self):
        stub = self.root / "python-stub"
        stub.write_text("#!/bin/sh\nexit 7\n")
        stub.chmod(0o755)
        result = subprocess.run(["/bin/bash", str(SCRIPTS / "vsc-vendor-maintenance.sh"),
                                 "--plugin", str(self.plugin), "--updater-root", str(self.updater)],
                                env={**os.environ, "VSC_VENDOR_PYTHON": str(stub)}, text=True, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn("exit=7", result.stderr)

    def test_safe_child_rejects_symlink(self):
        folder = self.root / "safe"
        folder.mkdir()
        (folder / "link").symlink_to(self.root / "outside")
        with self.assertRaises(WATCH.WatchError):
            WATCH.safe_child(folder, "link", "file")

    def write_lock(self):
        write(self.plugin, "vendor/sources.lock.json", json.dumps({
            "schema_version": 4, "policy": {"upstream_refresh": refresh_policy()},
            "sources": [self.source],
        }))

    def cli(self, *args, env=None):
        return subprocess.run(["/bin/bash", str(SCRIPTS / "vsc-vendor-maintenance.sh"),
                               "--plugin", str(self.plugin), *args], cwd=self.root,
                              env=env, text=True, capture_output=True)

    def test_manual_plan_never_invokes_git_or_creates_maintenance_data(self):
        self.write_lock()
        stub = self.root / "bin/git"
        write(self.root, "bin/git", f'#!/bin/sh\ntouch "{self.root}/git-called"\nexit 74\n')
        stub.chmod(0o755)
        before = (self.plugin / "vendor/sources.lock.json").read_bytes()
        result = self.cli("--plan", "--source", "local-test",
                          env={**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"mode": "manual"', result.stdout)
        self.assertIn('"local-test"', result.stdout)
        self.assertFalse((self.root / "git-called").exists())
        self.assertFalse((self.plugin / "vendor/.maintenance").exists())
        self.assertFalse((self.plugin / "vendor/.reviews").exists())
        self.assertEqual(before, (self.plugin / "vendor/sources.lock.json").read_bytes())

    def test_manual_cli_runs_once_without_central_updater(self):
        self.write_lock()
        before = (self.plugin / "vendor/sources.lock.json").read_bytes()
        first = self.cli("--source", "local-test")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("CANDIDATE local-test", first.stdout)
        snapshots = self.plugin / "vendor/.maintenance/backups/vsc-vendor-candidates/local-test"
        self.assertEqual(len(list(snapshots.iterdir())), 2)
        self.assertTrue(list((self.plugin / "vendor/.reviews").glob("*.json")))
        second = self.cli("--source", "local-test")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("UNCHANGED-CANDIDATE", second.stdout)
        self.assertEqual(before, (self.plugin / "vendor/sources.lock.json").read_bytes())
        self.assertEqual((self.plugin / "vendor/local-test/keep.txt").read_text(), "active untouched")
        self.assertFalse(self.updater.exists())

    def test_manual_root_supports_legacy_updater_root_alias(self):
        self.write_lock()
        result = self.cli("--plan", "--maintenance-root", str(self.updater))
        legacy = self.cli("--plan", "--updater-root", str(self.updater))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(result.stdout, legacy.stdout)
        self.assertIn(str(self.updater.resolve()), result.stdout)
        self.assertFalse(self.updater.exists())

    def test_manual_unknown_source_fails_before_writes(self):
        self.write_lock()
        result = self.cli("--source", "not-declared")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未声明来源", result.stderr)
        self.assertFalse((self.plugin / "vendor/.maintenance").exists())


if __name__ == "__main__":
    unittest.main()
