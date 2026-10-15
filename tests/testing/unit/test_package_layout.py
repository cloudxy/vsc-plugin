"""The packaged domain API and compatible CLI entries share module state."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from support.paths import ROOT
from vsc.bootstrap import repository_root, script_path, service_from_environment


class TestPackageCompatibility(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("sqlalchemy") and importlib.util.find_spec("psycopg"), "requires postgres optional dependencies")
    def test_invalid_database_configuration_does_not_echo_connection_values(self):
        from vsc.assets.resource_service import ResourceError
        secret = "private-value-must-not-appear"
        url = "postgresql+psycopg://user@localhost:" + secret + "/database"
        with patch.dict(os.environ, {"VSC_TEST_INVALID_DATABASE": url}), self.assertRaises(ResourceError) as caught:
            service_from_environment("VSC_TEST_INVALID_DATABASE")
        self.assertEqual(caught.exception.code, "invalid_database_config")
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(url, str(caught.exception))

    def test_all_legacy_imports_resolve_to_the_canonical_module(self):
        mapping = json.loads((ROOT / "src/vsc/module-map.json").read_text())
        for legacy, canonical in mapping.items():
            with self.subTest(module=legacy):
                self.assertIs(importlib.import_module(legacy), importlib.import_module(canonical))
        state = importlib.import_module("vsc.project.state")
        legacy_state = importlib.import_module("vsc_state")
        sentinel = object()
        with patch.object(legacy_state, "ROLE_CARDS", sentinel):
            self.assertIs(state.ROLE_CARDS, sentinel)
        series = importlib.import_module("vsc_series")
        context = importlib.import_module("vsc.production.context")
        original_validator = context.validate_artifact
        with patch.object(series, "validate_artifact", return_value=[]) as validator:
            self.assertIs(context.validate_artifact, validator)
        self.assertIs(context.validate_artifact, original_validator)
        self.assertEqual(repository_root(), ROOT)
        self.assertEqual(script_path("vsc_state.py"), ROOT / "scripts/vsc_state.py")
        with self.assertRaises(ValueError):
            script_path("../secrets.py")

    def test_compatible_cli_keeps_exit_status_and_works_outside_workspace(self):
        result = subprocess.run([sys.executable, "-B", str(script_path("vsc_kernel.py")), "doctor"],
                                cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WORKFLOW DOCTOR: PASS", result.stdout)
        bad = subprocess.run([sys.executable, "-B", str(script_path("vsc_state.py")), "unknown-command"],
                             cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("invalid choice", bad.stderr)

    def test_domain_modules_import_without_the_legacy_scripts_path(self):
        source = "\n".join([
            "import sys",
            "sys.path[:0] = " + repr([str(ROOT / "src"), str(ROOT)]),
            "from vsc.project.state import profile_catalog",
            "from vsc.production.providers import ImageProvider, VideoProvider, AudioProvider",
            "from vsc.production.context import build_shot_context",
            "from vsc.assets.registry import import_media",
            "from tools.maintenance.vendor_sync import validate",
            "assert 'vsc.series-db' in profile_catalog()",
            "assert not any(name in sys.modules for name in ('vsc_state', 'vsc_series_db', 'consistency'))",
        ])
        result = subprocess.run([sys.executable, "-B", "-c", source], cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
