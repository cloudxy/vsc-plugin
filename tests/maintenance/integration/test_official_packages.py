"""Offline official-format npm fixtures: byte integrity, archive safety, atomic adoption."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from tools.maintenance import official_packages as packages, provider_sync


class OfficialPackagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "vendor").mkdir()
        (self.root / "vendor/sources.lock.json").write_text('{"sources": []}')
        self.work = self.root / "vendor/.provider-sync"
        self.binary = b"synthetic-not-executable"
        self.files = {}
        self.release("1.0.39")
        self.updater = provider_sync.ProviderSync(self.root, active_jobs=lambda tool: False)
        # Exercise the production entry point; only the credential-free network seam is replaced.
        self.addCleanup(patch.stopall)
        patch.object(packages.platform, "system", return_value="Darwin").start()
        patch.object(packages.platform, "machine", return_value="arm64").start()
        patch.object(packages, "check", side_effect=lambda work: self.check(work)).start()
        real_adopt = packages.adopt
        patch.object(packages, "adopt", side_effect=lambda *args: real_adopt(*args, download=self.download)).start()

    def check(self, work):
        item = packages.tool(work)
        latest = packages.metadata(download=self.download)
        return dict(item, latest_revision=latest["revision"], can_update=item["current_revision"] != latest["revision"], status="update_available")

    def release(self, version, member=None):
        url = packages.CDN + version + "/arkcli-" + version + "-darwin-arm64"
        manifest = {"version": version, "platforms": {"darwin-arm64": {"url": url, "sha256": hashlib.sha256(self.binary).hexdigest()}}}
        blob = io.BytesIO()
        with tarfile.open(fileobj=blob, mode="w:gz") as tar:
            for name, value in {"package/package.json": {"name": packages.PACKAGE, "version": version, "license": "Apache-2.0", "scripts": {"postinstall": "SHOULD NEVER RUN"}},
                                "package/manifest.json": manifest}.items():
                raw = json.dumps(value).encode()
                item = tarfile.TarInfo(name); item.size = len(raw)
                tar.addfile(item, io.BytesIO(raw))
            raw = b"Apache License\nVersion 2.0, January 2004\nSynthetic fixture only"
            item = tarfile.TarInfo("package/LICENSE"); item.size = len(raw)
            tar.addfile(item, io.BytesIO(raw))
            if member:
                tar.addfile(member)
        content = blob.getvalue()
        tarball = "https://registry.npmjs.org/@volcengine/ark-cli/-/ark-cli-" + version + ".tgz"
        metadata = json.dumps({"name": packages.PACKAGE, "version": version, "dist": {"tarball": tarball,
            "integrity": "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode()}}).encode()
        self.files.update({packages.REGISTRY + version: metadata, packages.REGISTRY + "latest": metadata, tarball: content, url: self.binary})
        return packages.metadata(version, self.download)["revision"]

    def download(self, url, limit=None):
        return self.files[url]

    def update(self, revision=None):
        revision = revision or self.updater.check(packages.TOOL_ID)["tools"][0]["latest_revision"]
        return self.updater.update(packages.TOOL_ID, revision, "human")

    def test_official_package_single_action_keeps_old_versions_and_never_executes_scripts(self):
        with patch("subprocess.run", side_effect=AssertionError("must not execute package")):
            first = self.update()
            old = packages.current(self.work)
            self.assertEqual("updated", first["status"])
            self.assertEqual("method_reference", first["execution_status"])
            self.assertFalse(old["scripts_executed"])
            revision = self.release("1.0.40")
            self.update(revision)
        self.assertTrue((self.work / "official-packages" / packages.TOOL_ID / old["revision"] / "arkcli").is_file())
        self.assertEqual(revision, packages.current(self.work)["revision"])

    def test_corrupt_package_and_binary_leave_old_active(self):
        self.update()
        old = packages.current(self.work)
        for suffix in ("package", "binary"):
            revision = self.release("1.0.40")
            release = packages.metadata("1.0.40", self.download)
            url = release["tarball"] if suffix == "package" else packages.CDN + "1.0.40/arkcli-1.0.40-darwin-arm64"
            self.files[url] += b"corrupt"
            with self.assertRaises(provider_sync.SyncError):
                self.update(revision)
            self.assertEqual(old, packages.current(self.work))

    def test_archive_links_traversal_and_unsupported_platform_fail_closed(self):
        for name, kind in (("package/../../outside", tarfile.REGTYPE), ("package/link", tarfile.SYMTYPE)):
            member = tarfile.TarInfo(name); member.type = kind; member.linkname = "/tmp"
            revision = self.release("1.0.40", member)
            with self.assertRaises(provider_sync.SyncError):
                self.update(revision)
        revision = self.release("1.0.40")
        with patch.object(packages.platform, "machine", return_value="unsupported"):
            with self.assertRaises(provider_sync.SyncError):
                self.update(revision)
        self.assertIsNone(packages.current(self.work))

    def test_active_tasks_pointer_failure_and_changed_bytes_keep_old(self):
        self.update()
        old = packages.current(self.work)
        revision = self.release("1.0.40")
        with patch.object(self.updater, "active_jobs", return_value=True):
            with self.assertRaises(provider_sync.SyncError):
                self.update(revision)
        with patch("tools.maintenance.vendor_review.write_atomic", side_effect=OSError("synthetic failure")):
            with self.assertRaises(provider_sync.SyncError):
                self.update(revision)
        self.assertEqual(old, packages.current(self.work))
        (self.work / "official-packages" / packages.TOOL_ID / old["revision"] / "arkcli").write_bytes(b"changed")
        self.assertEqual("check_failed", self.updater.check(packages.TOOL_ID)["tools"][0]["status"])
        with self.assertRaises(provider_sync.SyncError):
            self.update(revision)
