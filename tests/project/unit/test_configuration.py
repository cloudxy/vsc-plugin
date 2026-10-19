"""Configuration behavior through fresh application processes and real files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

from support.paths import ROOT
from vsc.bootstrap import workspace_python
from vsc.configuration import workspace_env_path


class WorkspaceConfigurationTests(unittest.TestCase):
    def run_settings(self, directory, content=None, environment=None, code=None):
        path = Path(directory) / 'config/.env'
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            path.write_text(content, encoding='utf-8')
        env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT/'src'),
               'VSC_ENV_FILE': str(path), **(environment or {})}
        return subprocess.run([sys.executable, '-c', code or (
            'from vsc.configuration import settings; import json; '
            'print(json.dumps([settings.DATABASE_URL, settings.TEST_DATABASE_URL, settings.MEDIA_ROOT]))')],
            cwd=directory, env=env, text=True, capture_output=True)

    def test_checks_choose_project_runtime_without_shell_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(workspace_python(root), sys.executable)
            candidate = root/'.venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            candidate.parent.mkdir(parents=True)
            candidate.write_text('#!/bin/sh\nexit 0\n')
            candidate.chmod(0o700)
            self.assertEqual(workspace_python(root), str(candidate))

    def test_quoted_urls_comments_unicode_and_shell_text_remain_data(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, "# 设置\nVSC_DATABASE_URL='postgresql://user:p#word@localhost/db'\n"
                'VSC_TEST_DATABASE_URL="$(touch marker)"\nVSC_MEDIA_ROOT="本机 媒体" # note\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['postgresql://user:p#word@localhost/db',
                             '$(touch marker)', '本机 媒体'])
            self.assertFalse((Path(directory)/'marker').exists())

    def test_local_file_overrides_old_shell_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, 'VSC_DATABASE_URL=file-app\nVSC_TEST_DATABASE_URL=file-test\n',
                {'VSC_DATABASE_URL': 'old-app', 'VSC_TEST_DATABASE_URL': 'old-test'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['file-app', 'file-test', '.vsc-resource-media'])

    def test_missing_file_uses_defaults_and_process_config(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, environment={
                'VSC_DATABASE_URL': 'process-app', 'VSC_TEST_DATABASE_URL': 'process-test'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['process-app', 'process-test', '.vsc-resource-media'])

    def test_explicit_isolation_disables_dotenv_even_when_it_exists(self):
        self.assertIsNone(workspace_env_path({'VSC_ENV_FILE': ''}))
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, 'VSC_DATABASE_URL=must-not-load\n',
                {'VSC_ENV_FILE': '', 'VSC_DATABASE_URL': 'isolated-app', 'VSC_TEST_DATABASE_URL': 'isolated-test'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[:2], ['isolated-app', 'isolated-test'])

    def test_errors_do_not_echo_config_values(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in ("BAD KEY=private-credential", "TOKEN='private-credential", "TOKEN=a\x00private-credential"):
                with self.subTest(content=content[:6]):
                    result = self.run_settings(directory, content)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('ConfigurationError', result.stderr)
                    self.assertNotIn('private-credential', result.stderr + result.stdout)

    def test_existing_custom_connection_key_and_file_key_have_same_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, 'OTHER_CONNECTION=custom-app\nVSC_DATABASE_URL=regular-app\n',
                code='from vsc.configuration import get_config; import json; '
                     'print(json.dumps([get_config("OTHER_CONNECTION"), get_config("VSC_DATABASE_URL")]))')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['custom-app', 'regular-app'])

    def test_workspace_root_loads_dotenv_from_other_cwd_without_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'workspace'
            root.mkdir()
            (root/'workflow').mkdir()
            (root/'workflow/kernel.json').write_text('{}')
            (root/'config').mkdir()
            (root/'config/.env').write_text('VSC_DATABASE_URL=config-app\nVSC_TEST_DATABASE_URL=config-test\n')
            (root/'.env').write_text('VSC_DATABASE_URL=obsolete-app\nVSC_TEST_DATABASE_URL=obsolete-test\n')
            env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT/'src'),
                   'VSC_WORKFLOW_ROOT': str(root)}
            result = subprocess.run([sys.executable, '-c',
                'from vsc.configuration import settings; import json; '
                'print(json.dumps([settings.DATABASE_URL, settings.TEST_DATABASE_URL]))'],
                cwd=directory, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['config-app', 'config-test'])

    def test_old_root_file_is_not_an_implicit_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'workflow').mkdir()
            (root/'workflow/kernel.json').write_text('{}')
            (root/'.env').write_text('VSC_DATABASE_URL=obsolete-app\n')
            env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT/'src'),
                   'VSC_WORKFLOW_ROOT': directory, 'VSC_DATABASE_URL': 'process-app',
                   'VSC_TEST_DATABASE_URL': 'process-test'}
            result = subprocess.run([sys.executable, '-c',
                'from vsc.configuration import settings; import json; '
                'print(json.dumps([settings.DATABASE_URL, settings.TEST_DATABASE_URL]))'],
                cwd=directory, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['process-app', 'process-test'])

    def test_default_location_has_one_owner(self):
        self.assertEqual(workspace_env_path({'VSC_WORKFLOW_ROOT': '/workspace'}), Path('/workspace/config/.env'))
        self.assertEqual(workspace_env_path({}), ROOT/'config/.env')

    def test_example_uses_two_databases_on_same_port(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_settings(directory, (ROOT/'config/.env.example').read_text())
            self.assertEqual(result.returncode, 0, result.stderr)
            application, test = [urlsplit(url) for url in json.loads(result.stdout)[:2]]
            self.assertEqual((application.hostname, application.port), (test.hostname, test.port))
            self.assertTrue(test.path.endswith('_test'))
            self.assertNotEqual(application.path, test.path)
