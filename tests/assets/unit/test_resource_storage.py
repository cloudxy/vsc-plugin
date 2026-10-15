"""Storage verifies bytes and permits retry after a repository failure."""
import hashlib
from io import BytesIO
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
import wave

from support.paths import ROOT
from vsc.adapters.storage.local.store import LocalStorage
from vsc.adapters.storage.s3.store import S3Storage
from vsc.assets.resource_service import ResourceError


class StorageTests(unittest.TestCase):
    def test_staging_is_durable_content_addressed_and_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory)
            upload = storage.stage_upload(BytesIO("一句中文，正常换行。".encode()), "文案.md")
            first = storage.commit_upload(upload["staged_upload"])
            # A new process resumes the receipt after a database write fails.
            second = LocalStorage(directory).commit_upload(upload["staged_upload"])
            self.assertEqual(first, second)
            self.assertEqual(storage.read(first["object_key"], first["sha256"]), "一句中文，正常换行。".encode())
            storage.resolve(first["object_key"]).write_bytes(b"changed")
            with self.assertRaises(ResourceError):
                storage.verify(first["object_key"], first["sha256"])

    def test_invalid_upload_limit_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            storage = LocalStorage(directory, max_bytes=3)
            with self.assertRaises(ResourceError):
                storage.stage_upload(BytesIO(b"four"))
            self.assertEqual(list(storage.staging.glob("*.bytes")), [])
            for key in ("../outside", "/etc/passwd", "..\\outside"):
                with self.subTest(key=key), self.assertRaises(ResourceError):
                    storage.resolve(key)
            (Path(directory) / "escape").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ResourceError):
                storage.resolve("escape/secret")
            with self.assertRaises(ResourceError):
                storage.commit_upload("../fake")

    def test_s3_replica_verifies_actual_content(self):
        class Client:
            def put_object(self, **kw):
                self.content = kw["Body"]
            def get_object(self, **kw):
                return {"Body": BytesIO(self.content)}
        client = Client()
        storage = S3Storage("fixture", client=client)
        row = storage.put(b"original")
        self.assertEqual(storage.read(row["object_key"], row["sha256"]), b"original")
        client.content = b"different"
        with self.assertRaises(ResourceError):
            storage.verify(row["object_key"], row["sha256"])

    def test_filename_cannot_change_actual_media_modality(self):
        audio = BytesIO()
        with wave.open(audio, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(24000)
            writer.writeframes(b"\x00\x00" * 240)
        probe = Mock()
        probe.probe.return_value = {"streams": [{"codec_type": "audio", "codec_name": "pcm_s16le", "sample_rate": "24000"}], "duration_seconds": .01}
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory, probe=probe)
            upload = storage.stage_upload(BytesIO(audio.getvalue()), "pretend.png")
            metadata = storage.commit_upload(upload["staged_upload"])
            self.assertEqual((metadata["modality"], metadata["mime_type"]), ("audio", "audio/wav"))
