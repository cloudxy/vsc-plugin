"""Canvas preference whitelist and preferences/import frontend tests."""
from pathlib import Path
import shutil
import subprocess
import unittest

import support.paths
from support.paths import ROOT
from vsc.adapters.persistence.postgres.access_control import AccessControlRepository
from vsc.assets.resource_service import ResourceError


class CanvasPreferencesImportTests(unittest.TestCase):
    def test_font_and_watermark_preferences_round_trip_in_memory(self):
        merged = AccessControlRepository._validate_preferences(
            {"ui": {"font_size": 18}, "ai_watermark": {"visible": False}},
            base={
                "language": "zh-cn",
                "platform_admin": True,
                "collaboration": {"enabled_on_new_canvas": True},
                "ui": {"font_size": 14},
            },
        )
        self.assertEqual(merged["ui"]["font_size"], 18)
        self.assertIs(merged["ai_watermark"]["visible"], False)
        self.assertEqual(merged["language"], "zh-cn")
        self.assertIs(merged["platform_admin"], True)
        self.assertIs(merged["collaboration"]["enabled_on_new_canvas"], True)
        kept = AccessControlRepository._validate_preferences(
            {"collaboration": {"enabled_on_new_canvas": False}},
            base=merged,
        )
        self.assertEqual(kept["ui"]["font_size"], 18)
        self.assertIs(kept["ai_watermark"]["visible"], False)
        self.assertIs(kept["collaboration"]["enabled_on_new_canvas"], False)
        presented = AccessControlRepository._present_preferences({"collaboration": {}, "platform_admin": True})
        self.assertEqual(presented["ui"]["font_size"], 14)
        self.assertIs(presented["ai_watermark"]["visible"], True)
        self.assertIs(presented["collaboration"]["enabled_on_new_canvas"], False)
        self.assertIs(presented["platform_admin"], True)
        with self.assertRaises(ResourceError):
            AccessControlRepository._validate_preferences({"ui": {"font_size": 9}})
        with self.assertRaises(ResourceError):
            AccessControlRepository._validate_preferences({"ui": {"font_size": True}})
        with self.assertRaises(ResourceError):
            AccessControlRepository._validate_preferences({"theme": "dark"})

    @unittest.skipUnless(shutil.which("node"), "requires Node.js")
    def test_canvas_preferences_import_frontend(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("canvas_preferences_import.test.mjs"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
