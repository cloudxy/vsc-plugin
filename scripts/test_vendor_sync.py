#!/usr/bin/env python3
"""vendor_sync.py 自测。运行：python3 scripts/test_vendor_sync.py"""
import importlib.util
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNC_PATH = HERE / "vendor_sync.py"
SPEC = importlib.util.spec_from_file_location("vendor_sync", SYNC_PATH)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def declared_source(**changes):
    source = {
        "id": "sample-skill", "type": "git", "url": "https://example.invalid/sample.git",
        "revision": "a" * 40, "license_spdx": "MIT", "license_evidence": "LICENSE",
        "purpose": "本地辅助技能评估", "owner": "维护者", "redistribution": "local_only",
        "usage": {"mode": "external_tool", "interface": "cli", "modified": False},
    }
    source.update(changes)
    return source


class TestValidation(unittest.TestCase):
    def test_declared_pinned_source_is_valid_without_approval_field(self):
        self.assertEqual(SYNC.validate(declared_source()), "")

    def test_branch_and_missing_local_only_boundary_are_rejected(self):
        self.assertIn("40 位", SYNC.validate(declared_source(revision="main")))
        self.assertIn("local_only", SYNC.validate(declared_source(redistribution="bundled")))

    def test_check_mode_never_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vendor = root / "vendor"
            vendor.mkdir()
            lock = vendor / "sources.lock.json"
            lock.write_text(json.dumps({"schema_version": 3, "sources": [declared_source()]}, ensure_ascii=False), "utf-8")
            old_lock, old_vendor = SYNC.LOCK, SYNC.VENDOR
            try:
                SYNC.LOCK, SYNC.VENDOR = lock, vendor
                self.assertEqual(SYNC.load_lock()["sources"][0]["id"], "sample-skill")
                self.assertFalse((vendor / "sample-skill").exists())
            finally:
                SYNC.LOCK, SYNC.VENDOR = old_lock, old_vendor

    def test_local_components_accept_apache_and_agpl(self):
        self.assertIn("usage.mode", SYNC.validate(declared_source(usage={"mode": "embedded", "interface": "cli", "modified": False})))
        self.assertEqual(SYNC.validate(declared_source(
            license_spdx="Apache-2.0", usage={"mode": "local_component", "interface": "cli", "modified": False}
        )), "")
        self.assertEqual(SYNC.validate(declared_source(
            license_spdx="AGPL-3.0-only", usage={"mode": "local_component", "interface": "cli", "modified": True}
        )), "")

    def test_select_sources_only_uses_user_named_entries(self):
        first, second = declared_source(id="first"), declared_source(id="second")
        self.assertEqual(SYNC.select_sources([first, second], ["second"]), [second])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                SYNC.select_sources([first], ["absent"])

    def test_repository_lock_passes_without_network(self):
        result = subprocess.run([sys.executable, "-B", str(SYNC_PATH), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("未联网、未下载", result.stdout)


if __name__ == "__main__":
    unittest.main()
