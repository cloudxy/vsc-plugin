#!/usr/bin/env python3
"""scripts/maintenance/vendor_sync.py 自测。运行：python3 -B tests/run.py --test maintenance.integration.test_vendor_sync"""
import importlib.util
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from support.paths import SCRIPTS
from support.fixtures.vendor import refresh_policy
SYNC_PATH = SCRIPTS / "maintenance/vendor_sync.py"
import tools.maintenance.vendor_sync as SYNC


def declared_source(**changes):
    source = {
        "id": "sample-skill", "type": "git", "url": "https://example.invalid/sample.git",
        "revision": "a" * 40, "license_spdx": "MIT", "license_evidence": "LICENSE",
        "purpose": "本地辅助技能评估", "owner": "维护者", "redistribution": "local_only",
        "usage": {"mode": "external_tool", "interface": "cli", "modified": False},
    }
    source.update(changes)
    return source




class TestExplicitInstall(unittest.TestCase):
    def test_pinned_existing_local_repository_installs_normally(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source repo'
            source.mkdir()
            def git(*args):
                return subprocess.run(['git', '-C', str(source), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-b', 'main')
            (source / 'SKILL.md').write_text('synthetic local installation fixture\n', encoding='utf-8')
            git('add', 'SKILL.md')
            git('-c', 'user.name=VSC fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-m', 'synthetic fixture')
            revision = git('rev-parse', 'HEAD')
            vendor = root / 'vendor'
            vendor.mkdir()
            entry = declared_source(url=str(source), revision=revision)
            with mock.patch.object(SYNC, 'VENDOR', vendor), contextlib.redirect_stdout(io.StringIO()):
                SYNC.sync(entry)
            installed = vendor / entry['id']
            self.assertEqual((installed / 'SKILL.md').read_text('utf-8'),
                             'synthetic local installation fixture\n')
            self.assertEqual(subprocess.run(['git', '-C', str(installed), 'rev-parse', 'HEAD'],
                             check=True, capture_output=True, text=True).stdout.strip(), revision)

    def test_explicit_source_requires_notice_and_is_skipped_by_default(self):
        explicit = declared_source(id="assets", install="explicit")
        self.assertIn("notice", SYNC.validate(explicit))
        explicit["notice"] = "商用前须向版权方取得授权"
        self.assertEqual(SYNC.validate(explicit), "")
        self.assertIn("install", SYNC.validate(declared_source(install="always")))
        sources = [declared_source(), explicit]
        self.assertEqual([source["id"] for source in SYNC.select_sources(sources, [])], ["sample-skill"])
        self.assertEqual([source["id"] for source in SYNC.select_sources(sources, ["assets"])], ["assets"])

    def test_ported_and_reference_sources_have_no_runtime_interface(self):
        ported = declared_source(usage={"mode": "ported", "interface": "none", "modified": False})
        self.assertEqual(SYNC.validate(ported), "")
        self.assertIn("interface=none", SYNC.validate(declared_source(usage={"mode": "ported", "interface": "cli", "modified": False})))

    def test_declaration_lists_explicit_sources_with_notice(self):
        data = {"sources": [declared_source(), declared_source(id="assets", install="explicit", notice="商用前须向版权方取得授权")]}
        text = SYNC.declaration_markdown(data)
        self.assertIn("`assets`（需显式安装）", text)
        self.assertIn("- `assets`：商用前须向版权方取得授权", text)


class TestValidation(unittest.TestCase):
    def test_git_url_transport_validation_preserves_known_forms_without_git_or_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'local repo';repo.mkdir();(repo/'.git').mkdir()
            bare=root/'bare.git';bare.mkdir();(bare/'HEAD').write_text('ref: refs/heads/main\n');(bare/'objects').mkdir()
            values=['https://example.invalid/repo.git','ssh://git@example.invalid/team/repo.git',
                    'git@example.invalid:team/repo.git','git@host:./repo.git','alias:repo.git',str(repo),str(bare),repo.as_uri()]
            before=sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            with mock.patch.object(SYNC.subprocess,'run',side_effect=AssertionError('no git')):
                for value in values:
                    with self.subTest(url=value):self.assertEqual(SYNC.validate(declared_source(url=value)),'')
            self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob('*')),before)

    def test_install_rejects_disguised_transports_before_git_or_filesystem_writes(self):
        values=['clawhub://owner/skill','unknown://host/skill','ext::sh -c malicious','other::https://example.invalid/repo',
                '--config=protocol.ext.allow=always','-uhelper','https://example.invalid/repo\n--upload-pack=bad',
                'ssh://git@-oProxyCommand/repo','git@host:-oProxyCommand=bad','https://example.invalid/repo\x00tail',
                'https://example.invalid/repo\x85tail']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);vendor=root/'vendor';vendor.mkdir();lock=vendor/'sources.lock.json'
            for value in values:
                source=declared_source(url=value)
                lock.write_text(json.dumps(dict(schema_version=4,policy={'upstream_refresh':refresh_policy()},
                    sources=[source])),encoding='utf-8')
                before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                dirs=sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_dir())
                for entry in ('cli','sync'):
                    with self.subTest(url=value,entry=entry),mock.patch.object(SYNC,'LOCK',lock),mock.patch.object(SYNC,'VENDOR',vendor), \
                         mock.patch.object(SYNC,'call',side_effect=AssertionError('no git')), \
                         mock.patch.object(SYNC.subprocess,'run',side_effect=AssertionError('no git')), \
                         mock.patch.object(sys,'argv',['vendor_sync.py','--install']),contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as invalid:
                            if entry=='cli':SYNC.main()
                            else:SYNC.sync(source)
                        self.assertEqual(invalid.exception.code,1)
                    self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()},before)
                    self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_dir()),dirs)

    def test_unregistered_distribution_formats_are_not_disguised_as_git(self):
        self.assertEqual(SYNC.validate(declared_source()),'')
        for kind in ('clawhub','https','unknown'):
            with self.subTest(kind=kind):
                self.assertIn('仅支持 type=git',SYNC.validate(declared_source(type=kind)))
        for revision in ('main','v1.0.0','latest'):
            with self.subTest(revision=revision):
                self.assertIn('40 位',SYNC.validate(declared_source(revision=revision)))

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
            lock.write_text(json.dumps({"schema_version": 4, "policy": {"upstream_refresh": refresh_policy()}, "sources": [declared_source()]}, ensure_ascii=False), "utf-8")
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

    def test_candidate_policy_requires_review_and_bounded_retention(self):
        self.assertEqual(SYNC.validate_refresh_policy({"policy": {"upstream_refresh": refresh_policy()}}), "")
        self.assertIn("automatic_adoption", SYNC.validate_refresh_policy({"policy": {"upstream_refresh": refresh_policy(automatic_adoption=True)}}))
        self.assertIn("scheduler", SYNC.validate_refresh_policy({"policy": {"upstream_refresh": refresh_policy(scheduler="zcode-plugin-updater")}}))
        self.assertIn("正整数", SYNC.validate_refresh_policy({"policy": {"upstream_refresh": refresh_policy(candidate_retention_days=0)}}))
        self.assertEqual(SYNC.validate(declared_source(
            license_spdx="AGPL-3.0-only", usage={"mode": "local_component", "interface": "cli", "modified": True}
        )), "")

    def test_sparse_paths_must_be_safe_relative_paths(self):
        self.assertEqual(SYNC.validate(declared_source(sparse_paths=[".agents/skills", "docs"])), "")
        self.assertIn("sparse_paths", SYNC.validate(declared_source(sparse_paths=[])))
        self.assertIn("sparse_paths", SYNC.validate(declared_source(sparse_paths=["../outside"])))

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

    def test_declaration_is_derived_from_the_machine_lock(self):
        data = {"sources": [declared_source(id="sample-source", purpose="测试用途")]}
        rendered = SYNC.declaration_markdown(data)
        self.assertIn("[sample-source](https://example.invalid/sample)", rendered)
        self.assertIn("`sample-source`", rendered)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "THIRD_PARTY.md"
            old_declaration = SYNC.DECLARATION
            try:
                SYNC.DECLARATION = target
                SYNC.write_declaration(data)
                self.assertEqual(target.read_text("utf-8"), rendered)
            finally:
                SYNC.DECLARATION = old_declaration


if __name__ == "__main__":
    unittest.main()
