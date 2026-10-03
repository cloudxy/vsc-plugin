#!/usr/bin/env python3
"""Deployment tests only touch a temporary updater, never actual scheduler/configuration."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import install_vendor_scheduler as INSTALL

HERE = Path(__file__).resolve().parent


class TestVendorSchedulerInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "plugin-updater"
        self.plugin = Path(self.temp.name).resolve() / "plugin"
        (self.root / "scripts/lib").mkdir(parents=True)
        (self.plugin / "scripts").mkdir(parents=True)
        for name in INSTALL.NAMES:
            (self.root / "scripts" / name).write_text("old " + name)
        (self.root / "scripts/lib/paths.sh").write_text(f'BASE="{self.root}"\nLOGS="$BASE/logs"\nmkdir -p "$LOGS" "$BASE/state"\n')
        (self.root / "scripts/lib/log.sh").write_text('init_log() { LOG="$1"; }\nlog() { echo "$*" >> "$LOG"; }\n')
        (self.root / "scripts/lib/lock.sh").write_text('ensure_lock() { return 0; }\n')
        (self.plugin / "scripts/vendor_watch.py").write_text("import sys\nprint('worker args:', sys.argv[1:])\nraise SystemExit(7)\n")
        (self.plugin / "scripts/vsc-vendor-maintenance.sh").write_bytes((HERE / "vsc-vendor-maintenance.sh").read_bytes())

    def test_read_only_plan_then_apply_backup_and_idempotent_check(self):
        plan = INSTALL.deploy(self.root, self.plugin)
        self.assertEqual(plan["status"], "needs_deployment")
        self.assertFalse((self.root / "backups").exists())
        result = INSTALL.deploy(self.root, self.plugin, apply=True)
        self.assertEqual(result["status"], "deployed")
        backup = Path(result["backup"])
        for name in INSTALL.NAMES:
            self.assertEqual((backup / name).read_text(), "old " + name)
        self.assertEqual(set(json.loads((backup / "manifest.json").read_text())["targets"]), set(INSTALL.NAMES))
        self.assertEqual(INSTALL.deploy(self.root, self.plugin)["status"], "current")
        self.assertEqual(INSTALL.deploy(self.root, self.plugin, apply=True)["status"], "current")

    def test_central_thin_shell_logs_and_returns_failure(self):
        INSTALL.deploy(self.root, self.plugin, apply=True)
        result = subprocess.run(["/bin/bash", str(self.root / "scripts/vsc-vendor-maintenance.sh"), "--source", "fixture"],
                                capture_output=True, text=True, errors="replace")
        self.assertEqual(result.returncode, 7, result.stderr)
        log = next((self.root / "logs").glob("*.log")).read_text()
        self.assertIn("fixture", log)
        self.assertIn("失败 exit=7", log)
        self.assertNotIn("结束：成功", log)

    def test_central_python_compatibility_passes_existing_arguments(self):
        INSTALL.deploy(self.root, self.plugin, apply=True)
        result = subprocess.run(["python3", "-B", str(self.root / "scripts/vsc-vendor-watch.py"),
                                 "--plugin", str(self.plugin), "--updater-root", str(self.root), "--source", "fixture"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn("fixture", result.stdout)

    def test_rejects_broad_directory_and_symlink_target(self):
        with self.assertRaises(ValueError):
            INSTALL.deploy(self.root.parent, self.plugin, apply=True)
        target = self.root / "scripts/vsc-vendor-watch.py"
        target.unlink()
        target.symlink_to(self.plugin / "scripts/vendor_watch.py")
        with self.assertRaises(ValueError):
            INSTALL.deploy(self.root, self.plugin, apply=True)


if __name__ == "__main__":
    unittest.main()
