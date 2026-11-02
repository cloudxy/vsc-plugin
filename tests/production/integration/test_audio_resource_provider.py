"""Offline MediaKit transport through the real PG worker and decoded MP3 bytes."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import ResourceSettings, PRESETS, validate_configuration
from vsc.adapters.providers.speech import audio


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL and shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires isolated PostgreSQL and FFmpeg")
class AudioResourceProviderTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-audio-worker-")
        self.addCleanup(self.temp.cleanup)
        self.storage = self.service.storage = LocalStorage(Path(self.temp.name) / "storage")
        self.addCleanup(setattr, self.service, "storage", None)
        self.objects = self.hierarchy()
        self.artifact(objects=[self.objects["shot"]])
        self.artifact("state", "scene-state", [self.objects["scene"]], {"state_versions": [{"scene_id": self.objects["scene"]}]})
        preset = next(row for row in PRESETS if row["id"] == "volcengine-seed-audio")
        self.config = dict({k:v for k,v in preset.items() if k not in {"id", "label"}}, enabled=True)
        self.model = ResourceSettings(self.store).save(self.config, "test-human")

    def create_job(self, purpose="music"):
        now = datetime.now(timezone.utc)
        saved = self.write("save_creative_tool_draft", dict(base_draft_id=None, document=dict(tool={"music":"music_description","sfx":"sfx","ambience":"ambience"}[purpose],
            episode_id=self.objects["episode"], shot_id=self.objects["shot"], model_id=self.model["id"], prompt="合成测试声音候选", style="明确风格")))
        request = dict(draft_version_id=saved["id"], execution_policy=dict(version="bounded-v1",
            first_draft_due_at=(now+timedelta(minutes=45)).isoformat(), stop_submitting_at=(now+timedelta(minutes=60)).isoformat(),
            max_attempts_per_purpose=2, max_repair_rounds=1,
            authorization=dict(mode="new_batch", reason="Explicit offline audio worker verification")))
        missing = self.service.preview_creative_tool_run(self.p, request)
        self.assertFalse(missing["ready"])
        self.assertEqual(missing["gaps"][0]["code"], "tool_work_input_required")
        fixed = self.write("prepare_creative_tool_work", {"draft_version_id": saved["id"]})
        self.assertEqual(fixed["tool_draft_id"], saved["id"])
        preview = self.service.preview_creative_tool_run(self.p, request)
        self.assertTrue(preview["ready"], preview.get("gaps"))
        self.assertEqual(preview["generation_quote"]["native_units"]["audio_jobs"], 1)
        self.assertEqual(preview["work_request"]["draft_version_id"], fixed["draft_version_id"])
        result = self.write("generate_creative_tool_work", dict(request=request, preview_sha256=preview["preview_sha256"]))
        self.assertEqual(len(result["jobs"]), 1, result)
        self.rev = self.service.get_project(self.p)["revision"]
        return result["jobs"][0]["id"]

    def response(self):
        path = Path(self.temp.name) / "fixture.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "0.4", "-c:a", "libmp3lame", str(path)], check=True, capture_output=True)
        return dict(success=True, task_id="audio-test-1", status="completed",
            result=dict(api="doubao.audio_generation", maas_result=dict(audio=base64.b64encode(path.read_bytes()).decode())))

    def test_original_worker_keeps_terminal_response_and_recovers_storage_without_get(self):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.adapters.providers.worker_factory import worker_adapter_factory
        job_id, completed, calls = self.create_job(), self.response(), []
        def transport(path, key, payload=None):
            self.assertEqual(key, "offline-test-key")
            calls.append((path, payload))
            if payload is not None:
                self.assertEqual(payload["maas_params"]["model"], "seed-audio-1.0")
                self.assertEqual(payload["maas_params"]["text_prompt"], "合成测试声音候选\n明确风格")
                return {"success": True, "task_id": "audio-test-1"}
            return completed
        with patch.object(audio, "call", transport), patch.object(audio, "api_key", return_value="offline-test-key"):
            worker = ResourceWorker(self.service, worker_adapter_factory, worker_id="audio-worker")
            self.assertEqual(worker.run_once(self.p)["status"], "submitted")
            with patch.object(self.storage, "stage_upload", side_effect=ResourceError("synthetic storage interruption", "test_storage")):
                with self.assertRaises(ResourceError):
                    worker.run_once(self.p, poll=True)
            waiting = self.service.get_generation_job(self.p, job_id)
            self.assertEqual(waiting["raw_response"]["status"], "completed")
            recovered = ResourceWorker(self.service, worker_adapter_factory, worker_id="audio-restarted").run_once(self.p, poll=True)
            self.assertEqual(recovered["status"], "succeeded")
            self.assertEqual(len(calls), 2)
            self.assertIsNone(worker.run_once(self.p))
        job = self.service.get_generation_job(self.p, job_id)
        self.assertEqual(job["external_task_id"], "audio-test-1")
        self.assertNotIn("offline-test-key", json.dumps(job))
        self.assertEqual(len(job["outputs"]), 1)
        media = self.service.get_media(self.p, job["outputs"][0]["media_id"])
        self.assertEqual(media["mime_type"], "audio/mpeg")
        self.assertEqual(media["sample_rate"], 48000)
        self.assertEqual(media["probe"]["decode"]["status"], "passed")
        self.assertEqual(media["rights"]["outcome"], "unknown")

    def test_unknown_submission_cannot_repeat_paid_post(self):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.adapters.providers.worker_factory import worker_adapter_factory
        job_id = self.create_job("sfx")
        with patch.object(audio, "api_key", return_value="offline-test-key"), patch.object(audio, "call", side_effect=audio.AudioError("simulated submit timeout")) as transport:
            worker = ResourceWorker(self.service, worker_adapter_factory)
            with self.assertRaises(audio.AudioError):
                worker.run_once(self.p)
            self.assertEqual(self.service.get_generation_job(self.p, job_id)["status"], "submission_unknown")
            self.assertIsNone(worker.run_once(self.p))
            self.assertIsNone(worker.run_once(self.p, poll=True))
            self.assertEqual(transport.call_count, 1)

    def test_settings_and_audio_authorization_reject_route_and_dialogue_misuse(self):
        from vsc.production.run_authorization import normalize_request, validate_capabilities
        self.assertTrue(self.model["adapter_available"])
        for fields in (dict(base_url="https://example.invalid"), dict(auth_ref="XAI_API_KEY"),
                       dict(capabilities={"purposes": ["dialogue_dry"]}), dict(default_params={"max_prompt_chars": True})):
            with self.subTest(fields=fields), self.assertRaises(ResourceError):
                validate_configuration(dict(self.config, **fields))
        logical = normalize_request(dict(prompt="ambient rain"), self.objects["shot"], "ambience", "audio")
        self.assertIsNone(validate_capabilities(self.model, logical, {"media": []}))
        logical["script_line_ids"] = ["unapproved-line"]
        with self.assertRaises(ResourceError):
            validate_capabilities(self.model, logical, {"media": []})
