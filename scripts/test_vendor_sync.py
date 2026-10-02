#!/usr/bin/env python3
"""vendor_sync.py 自测。运行：python3 scripts/test_vendor_sync.py"""
import importlib.util
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


def approved_source(**changes):
    source = {
        "id": "sample-skill", "type": "git", "url": "https://example.invalid/sample.git",
        "revision": "a" * 40, "license_spdx": "MIT", "license_evidence": "LICENSE",
        "purpose": "本地辅助技能评估", "owner": "维护者", "redistribution": "local_only",
        "usage": {"mode": "external_tool", "interface": "cli", "modified": False},
        "review": {"status": "approved", "by": "责任人", "at": "2026-10-01"},
    }
    source.update(changes)
    return source


class TestValidation(unittest.TestCase):
    def test_approved_pinned_source_is_valid(self):
        self.assertEqual(SYNC.validate(approved_source()), "")

    def test_branch_and_unapproved_source_are_rejected(self):
        self.assertIn("40 位", SYNC.validate(approved_source(revision="main")))
        self.assertIn("approved", SYNC.validate(approved_source(review={"status": "pending"})))

    def test_check_mode_never_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vendor = root / "vendor"
            vendor.mkdir()
            lock = vendor / "sources.lock.json"
            lock.write_text(json.dumps({"schema_version": 2, "sources": [approved_source()]}, ensure_ascii=False), "utf-8")
            old_lock, old_vendor = SYNC.LOCK, SYNC.VENDOR
            try:
                SYNC.LOCK, SYNC.VENDOR = lock, vendor
                self.assertEqual(SYNC.load_lock()["sources"][0]["id"], "sample-skill")
                self.assertFalse((vendor / "sample-skill").exists())
            finally:
                SYNC.LOCK, SYNC.VENDOR = old_lock, old_vendor

    def test_usage_mode_and_agpl_network_review_are_enforced(self):
        self.assertIn("usage.mode", SYNC.validate(approved_source(usage={"mode": "embedded", "interface": "cli", "modified": False})))
        agpl = approved_source(license_spdx="AGPL-3.0-only", usage={"mode": "external_service", "interface": "http", "modified": True})
        self.assertIn("network_source_offer", SYNC.validate(agpl))
        agpl["usage"]["network_source_offer"] = "https://example.invalid/source-offer"
        self.assertEqual(SYNC.validate(agpl), "")

    def test_repository_lock_passes_without_network(self):
        result = subprocess.run([sys.executable, "-B", str(SYNC_PATH), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("未联网、未下载", result.stdout)


if __name__ == "__main__":
    unittest.main()
