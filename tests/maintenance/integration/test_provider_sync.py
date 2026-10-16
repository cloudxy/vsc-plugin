"""Exercise actual bundle validation and Git tree switches with local test repos."""
from contextlib import ExitStack
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from tools.maintenance import provider_sync as sync
from support.fixtures.vendor import refresh_policy


class ProviderSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vendor = self.root / "vendor"
        self.vendor.mkdir()
        self.remote = self.root / "upstream"
        self.remote.mkdir()
        self.git("init", "-q", str(self.remote))
        self.git("-C", str(self.remote), "config", "user.email", "test@example.invalid")
        self.git("-C", str(self.remote), "config", "user.name", "Test")
        self.skill = self.remote / "skills" / "example" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: example\ndescription: Example.\n---\n\nOld instructions.\n")
        (self.remote / "LICENSE").write_text("Test license\n")
        self.git("-C", str(self.remote), "add", ".")
        self.git("-C", str(self.remote), "commit", "-qm", "first")
        self.old = self.git("-C", str(self.remote), "rev-parse", "HEAD")
        self.source = {"id": "test-tool", "type": "git", "url": "https://example.invalid/official.git", "revision": self.old,
            "license_spdx": "MIT", "license_evidence": "https://example.invalid/LICENSE", "purpose": "test", "owner": "test",
            "redistribution": "local_only", "usage": {"mode": "local_component", "interface": "file", "modified": False}}
        self.git("clone", "-q", str(self.remote), str(self.vendor / "test-tool"))
        self.lock = self.vendor / "sources.lock.json"
        self.lock.write_text(json.dumps({"schema_version": 4, "policy": {"upstream_refresh": refresh_policy()}, "sources": [self.source]}))
        self.before = self.lock.read_text()
        self.skill.write_text(self.skill.read_text().replace("Old instructions.", "New instructions."))
        self.git("-C", str(self.remote), "commit", "-qam", "second")
        self.new = self.git("-C", str(self.remote), "rev-parse", "HEAD")
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(sync, "_git", side_effect=self.fake_git))
        self.stack.enter_context(patch.object(sync.vendor_watch, "ensure_cache", side_effect=self.cache))
        self.stack.enter_context(patch.object(sync.vendor_watch, "fetch", side_effect=lambda path, rev: self.git("-C", str(path), "rev-parse", rev)))
        self.updater = sync.ProviderSync(self.root, active_jobs=lambda tool: False)

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], text=True, capture_output=True, check=True).stdout.strip()

    def fake_git(self, *args):
        if args[-3:] == ("remote", "get-url", "origin"):
            return self.source["url"]
        if args[0] == "ls-remote":
            return self.new + "\tHEAD"
        return self.git(*[str(self.remote) if arg == self.source["url"] else arg for arg in args])

    def cache(self, path, source):
        if not path.exists():
            self.git("clone", "-q", str(self.remote), str(path))

    def test_one_update_action_installs_verified_tree_and_records_identity(self):
        checked = self.updater.check("test-tool")["tools"][0]
        self.assertEqual("update_available", checked["status"])
        result = self.updater.update("test-tool", checked["latest_revision"], "human")
        self.assertEqual("updated", result["status"])
        self.assertEqual(self.new, self.git("-C", str(self.vendor / "test-tool"), "rev-parse", "HEAD"))
        self.assertIn("New instructions.", (self.vendor / "test-tool/skills/example/SKILL.md").read_text())
        self.assertEqual(self.new, json.loads(self.lock.read_text())["sources"][0]["revision"])
        report = json.loads(next((self.vendor / ".reviews").glob("*.json")).read_text())
        self.assertEqual("human", report["adoption"]["actor"])
        self.assertEqual("up_to_date", self.updater.check("test-tool")["tools"][0]["status"])

    def test_switch_failure_restores_old_tree_and_lock(self):
        original = sync.vendor_review.write_atomic
        def fail(path, data):
            if Path(path).resolve() == self.lock.resolve() and self.new in data:
                raise OSError("simulated failed lock write")
            return original(path, data)
        with patch.object(sync.vendor_review, "write_atomic", side_effect=fail):
            with self.assertRaises(sync.SyncError):
                self.updater.update("test-tool", self.new, "human")
        self.assertEqual(self.old, self.git("-C", str(self.vendor / "test-tool"), "rev-parse", "HEAD"))
        self.assertEqual(self.before, self.lock.read_text())

    def test_inflight_or_unknown_authority_prevents_download(self):
        for active in (None, lambda tool: True):
            with patch.object(sync.vendor_watch, "fetch", side_effect=AssertionError("must not download")):
                with self.assertRaises(sync.SyncError):
                    sync.ProviderSync(self.root, active_jobs=active).update("test-tool", self.new, "human")
        self.assertEqual(self.before, self.lock.read_text())

    def test_removed_routed_skill_keeps_old_version(self):
        with patch.object(sync.vendor_review, "routed_paths", return_value={"skills/example/SKILL.md": ["produce"]}):
            self.skill.unlink()
            self.git("-C", str(self.remote), "commit", "-qam", "remove")
            removed = self.git("-C", str(self.remote), "rev-parse", "HEAD")
            with self.assertRaises(sync.SyncError):
                self.updater.update("test-tool", removed, "human")
        self.assertEqual(self.before, self.lock.read_text())

    def test_concurrent_sync_and_tampered_candidate_do_not_switch(self):
        with self.updater._locked():
            with self.assertRaises(sync.SyncError):
                sync.ProviderSync(self.root, active_jobs=lambda tool: False).update("test-tool", self.new, "human")
        materialize = sync.vendor_watch.materialize
        def tamper(cache, revision, source, target):
            result = materialize(cache, revision, source, target)
            (target / "skills/example/SKILL.md").write_text("tampered")
            return result
        with patch.object(sync.vendor_watch, "materialize", side_effect=tamper):
            with self.assertRaises(sync.SyncError):
                self.updater.update("test-tool", self.new, "human")
        self.assertEqual(self.before, self.lock.read_text())

    def test_check_failure_is_not_latest_and_host_update_is_unsupported(self):
        with patch.object(sync, "_git", side_effect=sync.SyncError("network unavailable")):
            result = self.updater.check("test-tool")["tools"][0]
            self.assertEqual("check_failed", result["status"])
            self.assertFalse(result["can_update"])
        with self.assertRaises(sync.SyncError):
            self.updater.update(sync.HOST["id"], self.new, "human")
