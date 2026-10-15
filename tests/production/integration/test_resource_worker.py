"""Offline provider orchestration against real PostgreSQL and real media bytes."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from io import BytesIO
import wave

from support.paths import ROOT
from support.fixtures.postgres import isolated_postgres
from support.fixtures.resources import ResourceFixture, png_bytes
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic"))


class FakeProvider:
    def __init__(self, modality="image", content=None, asynchronous=False, unknown=False):
        self.modality, self.content = modality, content or png_bytes()
        self.asynchronous, self.unknown, self.submits = asynchronous, unknown, 0

    def submit(self, request):
        self.submits += 1
        if self.unknown:
            raise TimeoutError("模拟 POST 后连接丢失")
        return JobHandle("fixture", "fixture", "fake-task" if self.asynchronous else None, {"fixture": "response"})

    def poll(self, handle):
        return JobStatus("succeeded", raw={"fixture": "response"})

    def parse_result(self, raw):
        return [GeneratedAsset(self.modality, inline_bytes=self.content)]


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires explicit test PostgreSQL URL and dependencies")
class ResourceWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(TEST_URL)
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from vsc.adapters.persistence.postgres.store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        self.temp = tempfile.TemporaryDirectory()
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), LocalStorage(self.temp.name))
        self.fixture = ResourceFixture(self.service)
        self.service.register_provider({"id": "fixture", "base_url": "https://example.invalid", "auth_ref": "FIXTURE_API_KEY"}, actor="fixture-human")

    def tearDown(self):
        self.temp.cleanup()

    def model(self, modality, purposes):
        return self.service.register_model({"provider_id": "fixture", "model_key": modality + "-" + "-".join(purposes), "model_version": "1", "modality": modality,
            "capabilities": {"purposes": purposes, "first_frame": True, "reference_media": True}}, actor="fixture-human")["id"]

    def test_sync_output_is_stored_without_automatic_selection_and_resume_is_safe(self):
        from vsc.production.resource_worker import ResourceWorker
        job = self.fixture.job("image", "keyframe", self.model("image", ["keyframe"]))
        adapter = FakeProvider()
        worker = ResourceWorker(self.service, lambda job, storage: adapter)
        worker.run_once(self.fixture.p)
        result = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(result["outputs"]), 1)
        media_id = result["outputs"][0]["media_id"]
        media = self.service.get_media(self.fixture.p, media_id)
        self.assertEqual(media["rights"]["outcome"], "unknown")
        self.assertEqual(self.service.get_media_usage(self.fixture.p, media_id)["current_bindings"], [])
        worker.finalize(self.fixture.p, job["id"])
        self.assertEqual(adapter.submits, 1)
        self.assertEqual(self.service.get_media_usage(self.fixture.p, media_id)["job_outputs"][0]["job_id"], job["id"])

    def test_first_identity_reference_can_start_without_existing_self_reference(self):
        from vsc.production.resource_worker import ResourceWorker
        asset = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "NEW-CHAR"})["id"]
        spec = self.fixture.artifact("first-character-spec", "asset-bible", {"asset_specs": [{"asset_id": asset, "variant_key": "master"}],
            "description": "合成测试的人物身份规格"})
        context = self.service.compile_asset_context(self.fixture.p, asset)
        self.assertTrue(context["ready"], context["gaps"])
        self.assertEqual(context["media"], [])
        request = {"shot_id": None, "asset_id": asset, "purpose": "asset_ref", "modality": "image",
            "prompt": "合成测试的人物参考", "params": {}, "reference_media_ids": []}
        pins = [{"id": a["id"], "sha256": a["sha256"]} for a in context["artifacts"]]
        run = self.fixture.artifact("asset-run", "production-run", {"approved_inputs": pins,
            "series_batch": {"jobs": [{"candidate_no": 0, "request": request}]}}, [p["id"] for p in pins])
        context = self.service.compile_asset_context(self.fixture.p, asset)
        job = self.fixture.write("create_generation_job", {"asset_id": asset, "purpose": "asset_ref", "modality": "image",
            "run_version_id": run, "model_id": self.model("image", ["asset_ref"]), "candidate_no": 0,
            "context_sha256": context["sha256"], "request_payload": request})
        adapter = FakeProvider()
        ResourceWorker(self.service, lambda job, storage: adapter).run_once(self.fixture.p)
        result = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual((result["asset_id"], result["shot_id"], result["status"]), (asset, None, "succeeded"))
        self.assertIn(spec, {version["artifact_id"] for version in result["input_versions"]})
        self.assertEqual(adapter.submits, 1)

    def test_unknown_submit_is_never_automatically_posted_again(self):
        from vsc.production.resource_worker import ResourceWorker
        job = self.fixture.job("image", "keyframe", self.model("image", ["keyframe"]))
        adapter = FakeProvider(unknown=True)
        worker = ResourceWorker(self.service, lambda job, storage: adapter)
        with self.assertRaises(TimeoutError):
            worker.run_once(self.fixture.p)
        self.assertEqual(self.service.get_generation_job(self.fixture.p, job["id"])["status"], "submission_unknown")
        self.assertIsNone(worker.run_once(self.fixture.p))
        self.assertEqual(adapter.submits, 1)

    def test_audio_uses_fixed_line_and_logical_character_voice(self):
        from vsc.production.resource_worker import ResourceWorker
        character = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "character", "display_code": "C001"})["id"]
        voice = self.fixture.write("create_object", {"kind": "asset", "asset_kind": "voice", "display_code": "V001"})["id"]
        audio = BytesIO()
        with wave.open(audio, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(24000)
            writer.writeframes(b"\x00\x00" * 24000)
        for target, role, content, name in ((character, "identity_face", png_bytes(), "face.png"),
                                           (voice, "voice_sample", audio.getvalue(), "voice.wav")):
            staged = self.service.storage.stage_upload(BytesIO(content), name)
            media = self.fixture.write("register_media", {"staged_upload": staged["staged_upload"], "name": name,
                "source": {"kind": "fixture", "content": "合成测试素材"}, "rights": "unknown"})
            self.fixture.select_media(media["id"], role, target)
        line_id, voice_spec_id = str(uuid.uuid4()), str(uuid.uuid4())
        script = self.fixture.artifact("script", "screenplay", {"script_lines": [{"id": line_id,
            "scene_id": self.fixture.objects["scene"], "speaker_id": character, "line_key": "L001", "text": "合成对白。"}]})
        self.fixture.artifact("coverage", "coverage-plan", {"line_coverage": [{"shot_id": self.fixture.objects["shot"],
            "line_id": line_id, "start_char": 0, "end_char": len("合成对白。")}]}, [script])
        self.fixture.artifact("voice", "voice-spec", {"voice_specs": [{"id": voice_spec_id, "voice_id": voice}],
            "voice_bindings": [{"character_id": character, "voice_spec_id": voice_spec_id}]})
        self.fixture.artifact("scene-state", "scene-state", {"state_versions": [{"scene_id": self.fixture.objects["scene"],
            "shot_id": self.fixture.objects["shot"], "entities": [{"asset_id": character, "relation": "offscreen_voice"}]}]})
        model = self.service.register_model({"provider_id": "fixture", "model_key": "audio", "model_version": "voice-1", "modality": "audio",
            "capabilities": {"purposes": ["dialogue_dry"]}, "default_params": {"voice_map": {voice: {"engine": "fixture", "voice": "fixture-voice"}}}}, actor="fixture-human")["id"]
        job = self.fixture.job("audio", "dialogue_dry", model, {"prompt": "合成对白。", "script_line_ids": ["L001"]})
        adapter = FakeProvider("audio", audio.getvalue())
        ResourceWorker(self.service, lambda job, storage: adapter).run_once(self.fixture.p)
        result = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["request_payload"]["voice_binding"]["logical_voice_id"], voice)
        output = self.service.get_media(self.fixture.p, result["outputs"][0]["media_id"])
        self.assertEqual(output["sample_rate"], 24000)
        self.assertEqual(output["duration_ms"], 1000)

    def test_image_selection_drives_async_video_and_fixed_timeline(self):
        from vsc.production.resource_worker import ResourceWorker
        image_job = self.fixture.job("image", "keyframe", self.model("image", ["keyframe"]))
        ResourceWorker(self.service, lambda job, storage: FakeProvider()).run_once(self.fixture.p)
        image = self.service.get_generation_job(self.fixture.p, image_job["id"])["outputs"][0]["media_id"]
        self.fixture.select_media(image, "first_frame")
        path = Path(self.temp.name) / "fake-video.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=16x32:r=24:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
        video_job = self.fixture.job("video", "video_clip", self.model("video", ["video_clip"]), {"first_frame_media_id": image, "duration_ms": 1000})
        adapter = FakeProvider("video", path.read_bytes(), asynchronous=True)
        worker = ResourceWorker(self.service, lambda job, storage: adapter)
        self.assertEqual(worker.run_once(self.fixture.p)["status"], "submitted")
        worker.run_once(self.fixture.p, poll=True)
        video = self.service.get_generation_job(self.fixture.p, video_job["id"])["outputs"][0]["media_id"]
        selected = self.fixture.select_media(video, "video_take")
        items = [{"shot_id": self.fixture.objects["shot"], "track_key": "video", "offset_frame": 0, "duration_frames": 24,
            "media": [{"media_id": video, "role": "video_take", "binding_decision_id": selected["decision_id"], "source_in_frame": 0, "source_out_frame": 24}]}]
        composition = {"id": "Synthetic", "width": 16, "height": 32, "fps": 24, "duration_in_frames": 24}
        artifact = self.fixture.artifact("timeline", "timeline", {"items": items, "composition": composition, "project_id": self.fixture.p})
        timeline = self.fixture.write("freeze_timeline", {"artifact_id": artifact, "episode_id": self.fixture.objects["episode"], "fps_num": 24, "fps_den": 1, "items": items})
        self.assertTrue(timeline["id"])
        self.assertEqual(len(self.service.get_media_usage(self.fixture.p, video)["timeline_items"]), 1)
        self.assertEqual(adapter.submits, 1)
        from vsc.post.resource_export import export_render_package, scaffold_render_package
        import json
        exported = export_render_package(self.service, self.fixture.p, timeline["id"], Path(self.temp.name) / "export")
        plan_path = Path(exported["directory"]) / "render-plan.json"
        plan = json.loads(plan_path.read_text("utf-8"))
        self.assertEqual(plan["composition"], composition)
        scaffold_render_package(exported["directory"], Path(self.temp.name) / "remotion")
        self.assertTrue((Path(self.temp.name) / "remotion/src/Root.tsx").is_file())
        self.assertTrue((Path(self.temp.name) / "remotion/public" / plan["segments"][0]["source"]).is_file())
        self.assertEqual(exported["source_artifact"]["id"], artifact)
