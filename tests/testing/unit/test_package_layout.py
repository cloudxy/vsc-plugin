"""Commands have explicit owners and source packages are imported directly."""
import ast
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from support.paths import ROOT
from vsc.bootstrap import repository_root, script_path, service_from_environment


class TestPackageLayout(unittest.TestCase):
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

    def test_commands_have_owned_direct_entry_points_without_flat_aliases(self):
        owners = {
            "kernel": ("vsc.kernel.",), "project": ("vsc.project.",),
            "story": ("vsc.story.",), "assets": ("vsc.assets.", "vsc.interfaces.cli."),
            "production": ("vsc.production.", "vsc.interfaces.cli."),
            "providers": ("vsc.adapters.providers.",), "media": ("vsc.adapters.media.",),
            "post": ("vsc.post.", "vsc.adapters.editors."), "knowledge": ("vsc.knowledge.",),
            "maintenance": ("tools.maintenance.",),
        }
        self.assertEqual({path.name for path in (ROOT / "scripts").iterdir() if path.is_file()}, {"README.md"})
        scripts = list((ROOT / "scripts").rglob("*.py"))
        self.assertTrue(scripts)
        for path in scripts:
            with self.subTest(command=str(path.relative_to(ROOT))):
                tree = ast.parse(path.read_text())
                imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                           and any(alias.name == "main" for alias in node.names)]
                self.assertEqual(len(imports), 1)
                owner = path.relative_to(ROOT / "scripts").parts[0]
                self.assertTrue(imports[0].module.startswith(owners[owner]))
                self.assertTrue(callable(importlib.import_module(imports[0].module).main))
                self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.ClassDef)) for node in tree.body))
        for name in ("vsc_state", "volc_ark", "vsc.compat", "vsc.production.series"):
            with self.subTest(obsolete_module=name):
                self.assertIsNone(importlib.util.find_spec(name))

    def test_script_location_requires_a_group_and_rejects_escape(self):
        self.assertEqual(repository_root(), ROOT)
        self.assertEqual(script_path("project/state.py"), ROOT / "scripts/project/state.py")
        self.assertEqual(script_path("providers/volcengine/ark.py"), ROOT / "scripts/providers/volcengine/ark.py")
        for name in ("vsc_state.py", "../secrets.py", "project/../secrets.py", "/tmp/command.py", "project\\state.py", "project/state.sh"):
            with self.subTest(path=name), self.assertRaises(ValueError):
                script_path(name)

    def test_grouped_cli_works_outside_workspace_and_preserves_exit_status(self):
        result = subprocess.run([sys.executable, "-B", str(script_path("kernel/catalog.py")), "doctor"],
                                cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WORKFLOW DOCTOR: PASS", result.stdout)
        bad = subprocess.run([sys.executable, "-B", str(script_path("project/state.py")), "unknown-command"],
                             cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("invalid choice", bad.stderr)
        provider = subprocess.run([sys.executable, "-B", str(script_path("providers/volcengine/ark.py")), "--help"],
                                  cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(provider.returncode, 0, provider.stdout + provider.stderr)

    def test_domain_modules_import_without_any_scripts_on_python_path(self):
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
            "assert not any(path.endswith('/scripts') for path in sys.path)",
        ])
        result = subprocess.run([sys.executable, "-B", "-c", source], cwd="/private/tmp", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
