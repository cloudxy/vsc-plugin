"""Local initialization works without shell setup and never executes .env text."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support.paths import ROOT
from vsc.configuration import ConfigurationError, load_workspace_env, read_env_file, workspace_env_path
from vsc.bootstrap import workspace_python


class WorkspaceConfigurationTests(unittest.TestCase):
    def test_checks_choose_project_runtime_without_shell_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(workspace_python(root), sys.executable)
            candidate = root/'.venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            candidate.parent.mkdir(parents=True)
            candidate.write_text('#!/bin/sh\nexit 0\n')
            candidate.chmod(0o700)
            self.assertEqual(workspace_python(root), str(candidate))

    def test_quoted_urls_comments_unicode_and_literals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text("# 设置\nVSC_DATABASE_URL='postgresql://user:p#word@localhost/db'\n"
                'VSC_MEDIA_ROOT="本机 媒体" # note\nexport LITERAL=$(touch marker)\nEMPTY=\n', encoding='utf-8-sig')
            values = read_env_file(path)
            self.assertEqual(values['VSC_MEDIA_ROOT'], '本机 媒体')
            self.assertIn('p#word', values['VSC_DATABASE_URL'])
            self.assertEqual(values['LITERAL'], '$(touch marker)')
            self.assertEqual(values['EMPTY'], '')
            self.assertFalse((Path(directory) / 'marker').exists())

    def test_local_file_is_authoritative_without_changing_another_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('VSC_DATABASE_URL=local-value\n', encoding='utf-8')
            environment = {'VSC_DATABASE_URL': 'old-shell-value', 'KEEP': 'unchanged'}
            self.assertEqual(load_workspace_env(path, environ=environment), ('VSC_DATABASE_URL',))
            self.assertEqual(environment, {'VSC_DATABASE_URL': 'local-value', 'KEEP': 'unchanged'})

    def test_missing_file_is_optional_and_explicit_isolation_can_disable_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_workspace_env(Path(directory)/'absent', environ={}), ())
        self.assertIsNone(workspace_env_path({'VSC_ENV_FILE': ''}))
        self.assertEqual(load_workspace_env(environ={'VSC_ENV_FILE': ''}), ())

    def test_errors_do_not_echo_config_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            for content in ("BAD KEY=private-credential", "TOKEN='private-credential", "TOKEN=a\x00private-credential"):
                path.write_text(content)
                with self.assertRaises(ConfigurationError) as raised:
                    read_env_file(path)
                self.assertNotIn('private-credential', str(raised.exception))

    def test_fresh_python_host_import_uses_env_file_without_shell_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.env'
            path.write_text('VSC_DATABASE_URL=synthetic-application\nVSC_TEST_DATABASE_URL=synthetic-test\n')
            environment = {'PATH': os.environ.get('PATH',''), 'PYTHONPATH': str(ROOT/'src'),
                           'VSC_ENV_FILE': str(path)}
            result = subprocess.run([sys.executable, '-c',
                'import vsc, os, json; print(json.dumps([os.environ.get("VSC_DATABASE_URL"), os.environ.get("VSC_TEST_DATABASE_URL")]))'],
                cwd=directory, env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['synthetic-application', 'synthetic-test'])

    def test_example_uses_two_databases_on_same_port(self):
        from urllib.parse import urlsplit
        example = read_env_file(ROOT/'.env.example')
        application, test = [urlsplit(example[key]) for key in ('VSC_DATABASE_URL','VSC_TEST_DATABASE_URL')]
        self.assertEqual((application.hostname, application.port), (test.hostname, test.port))
        self.assertTrue(test.path.endswith('_test'))
        self.assertNotEqual(application.path, test.path)
