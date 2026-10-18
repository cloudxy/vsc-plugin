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
import json
from unittest import mock

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
        # One fixed professional artifact may describe the same line in two
        # shots; the task inspector must show only its actual shot and voice.
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.workbench import query_workbench
        other=self.fixture.write('create_object',{'kind':'shot','parent_id':self.fixture.objects['sequence'],'display_code':'OTHER','ordinal':1})['id']
        artifact=self.fixture.artifact('fixed-performance','generic',{'fixture':'two voice executions'})
        fixed=self.service.get_artifact_version(self.fixture.p,artifact)
        own_id=str(uuid.uuid4())
        with self.service.store.engine.begin() as conn:
            conn.execute(insert(S.job_input_versions).values(project_id=self.fixture.p,id=str(uuid.uuid4()),job_id=job['id'],artifact_id=artifact,sha256=fixed['sha256'],role='creative-relations'))
            for identifier,shot,label in ((own_id,self.fixture.objects['shot'],'own'),(str(uuid.uuid4()),other,'other')):
                conn.execute(insert(S.execution_instances).values(project_id=self.fixture.p,id=identifier,artifact_id=artifact,
                    execution_key=label,label=label,domain='voice',line_id=line_id,voice_spec_id=voice_spec_id,
                    parameters={'controls':[{'field':'delivery','model_default':'context_texts','expected':[label]}]}))
                conn.execute(insert(S.execution_shots).values(project_id=self.fixture.p,id=str(uuid.uuid4()),execution_id=identifier,shot_id=shot))
        row=query_workbench(self.service.store,self.fixture.p,section='job_attempts',entity_id=job['id'])['sections']['job_attempts']['items'][0]
        self.assertEqual([item['execution_id'] for item in row['performance_coverage']],[own_id])
        self.assertEqual(row['performance_coverage'][0]['controls'][0]['expected'],['own'])

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


    def subtitle_fixture(self, defect=None):
        """Real PCM windows measured by RMS, not allocated from text length.

        These audible synthetic tones test fixed timing provenance. They are
        not human speech or evidence of semantic speech synchronization.
        """
        import array
        import hashlib
        import math
        rate, length, window = 24000, 3, 240
        intervals = [(200, 1300), (1800, 2500)]
        samples = array.array("h", [0] * (rate * length))
        for begin, end in intervals:
            for index in range(begin * rate // 1000, end * rate // 1000):
                samples[index] = int(10000 * math.sin(index * 2 * math.pi * 440 / rate))
        audio = BytesIO()
        with wave.open(audio, "wb") as writer:
            writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            writer.writeframes(samples.tobytes())
        # Scan actual stored PCM windows; interval boundaries follow detected
        # energy and retain the unequal 1100ms/700ms durations.
        active = []
        for offset in range(0, len(samples), window):
            block = samples[offset:offset + window]
            active.append(sum(value * value for value in block) / len(block) > 500 ** 2)
        measured, start = [], None
        for index, present in enumerate(active + [False]):
            if present and start is None:
                start = index * window * 1000 // rate
            elif not present and start is not None:
                measured.append((start, index * window * 1000 // rate))
                start = None
        self.assertEqual(measured, intervals)
        blob = audio.getvalue()
        sha = hashlib.sha256(blob).hexdigest()
        uploaded = bytearray(blob)
        if defect == "replacement_audio":
            uploaded[-2] ^= 1  # valid replacement PCM, distinct byte identity
        staged = self.service.storage.stage_upload(BytesIO(bytes(uploaded)), "measured.wav")
        media = self.fixture.write("register_media", {"staged_upload": staged["staged_upload"], "name": "measured.wav",
            "source": {"kind": "fixture", "content": "audible synthetic PCM with measured activity windows"}, "rights": "unknown"})
        line_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        lines = [{"id": identifier, "scene_id": self.fixture.objects["scene"], "line_key": "L" + str(index), "text": "好，2:30见！"}
                 for index, identifier in enumerate(line_ids)]
        script = self.fixture.artifact("subtitle-script", "screenplay", {"script_lines": lines})
        script_sha = self.service.get_artifact_version(self.fixture.p, script)["sha256"]
        second_shot = self.fixture.write("create_object", {"kind": "shot", "parent_id": self.fixture.objects["sequence"], "display_code": "CUT", "ordinal": 1})["id"]
        covers = [{"shot_id": shot, "line_id": identifier, "start_char": 0, "end_char": len(lines[0]["text"])}
                  for identifier, shots in [(line_ids[0], [self.fixture.objects["shot"], second_shot]), (line_ids[1], [second_shot])]
                  for shot in shots]
        coverage = self.fixture.artifact("subtitle-coverage", "coverage-plan", {"line_coverage": covers}, [script])
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.fixture.write("decide_rights", {"media_id": media["id"], "source_id": self.service.get_media(self.fixture.p, media["id"])["sources"][0]["source_id"],
            "outcome": "owned", "scope": {"purposes": ["*"]}, "reason": "本地合成音频夹具"})
        self.fixture.write("record_media_check", {"media_id": media["id"], "checker": "fixture-rms", "criteria_version": "1", "outcome": "pass"})
        selected = []
        for line, shot in zip(line_ids, [self.fixture.objects["shot"], second_shot]):
            with self.engine.connect() as conn:
                coverage_id = conn.execute(select(S.shot_line_coverage.c.id).where(S.shot_line_coverage.c.project_id == self.fixture.p,
                    S.shot_line_coverage.c.line_id == line, S.shot_line_coverage.c.shot_id == shot)).scalar_one()
            candidate = self.fixture.write("propose_binding", {"target_object_id": shot, "media_id": media["id"], "role": "dialogue_dry", "line_coverage_id": coverage_id})
            self.fixture.write("record_review", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reviewer_type": "human", "reason": "明确标注的合成夹具人审模拟"})
            selected.append(self.fixture.write("select_candidate", {"candidate_id": candidate["candidate_id"], "reason": "合成测试模拟采用决定"}))
        video = Path(self.temp.name) / "subtitle-video.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=30)
        staged_video = self.service.storage.stage_upload(BytesIO(video.read_bytes()), "video.mp4")
        visual = self.fixture.write("register_media", {"staged_upload": staged_video["staged_upload"], "name": "video.mp4", "source": {"kind": "fixture", "content": "generated local color video"}, "rights": "unknown"})
        v1 = self.fixture.select_media(visual["id"], "video_take")
        v2 = self.fixture.select_media(visual["id"], "video_take", second_shot)
        items = [{"shot_id": shot, "track_key": "video", "offset_frame": start, "duration_frames": duration,
            "media": [{"media_id": visual["id"], "role": "video_take", "binding_decision_id": decision["decision_id"], "source_in_frame": start, "source_out_frame": start + duration}]}
            for shot, start, duration, decision in [(self.fixture.objects["shot"], 0, 30, v1), (second_shot, 30, 60, v2)]]
        items.extend({"shot_id": shot, "track_key": "dialogue-" + str(index), "offset_frame": begin * 30 // 1000, "duration_frames": (end - begin) * 30 // 1000,
            "media": [{"media_id": media["id"], "role": "dialogue_dry", "binding_decision_id": decision["id"], "source_in_frame": begin * 30 // 1000, "source_out_frame": end * 30 // 1000}]}
            for index, (shot, (begin, end), decision) in enumerate(zip([self.fixture.objects["shot"], second_shot], measured, selected)))
        if defect == "replay":
            replay = json.loads(json.dumps(items[2]))
            replay["track_key"] = "dialogue-replay"
            items.append(replay)
        composition = {"id": "SubtitleFixture", "width": 640, "height": 360, "fps": 30, "duration_in_frames": 90}
        timeline_artifact = self.fixture.artifact("subtitle-timeline", "timeline", {"project_id": self.fixture.p, "items": items, "composition": composition}, [script, coverage])
        timeline = self.fixture.write("freeze_timeline", {"artifact_id": timeline_artifact, "episode_id": self.fixture.objects["episode"], "fps_num": 30, "fps_den": 1, "items": items})
        frozen = self.service.get_timeline(self.fixture.p, timeline["id"])
        audio_items = {item["track_key"]: item for item in frozen["items"] if item["track_key"].startswith("dialogue-")}
        cues = []
        for index, (line, (begin, end)) in enumerate(zip(lines, measured)):
            measurement = {"method": "pcm_activity_scan", "version": "fixture-rms/v1", "line_key": line["line_key"],
                "audio_media_sha256": sha, "start_ms": begin, "end_ms": end,
                "evidence": {"algorithm": "contiguous RMS windows above threshold", "sample_rate": rate,
                    "sample_count": len(samples), "window_samples": window, "threshold": 500, "activity_intervals": measured}}
            alignment = {"script_version_sha256": script_sha, "audio_media_sha256": sha, "start_ms": begin, "end_ms": end, "measurement": measurement}
            if defect == "wrong_sha" and index == 0:
                alignment["audio_media_sha256"] = "f" * 64
            if defect == "wrong_script" and index == 0:
                alignment["script_version_sha256"] = "f" * 64
            if defect == "wrong_range" and index == 0:
                alignment["end_ms"] = measurement["end_ms"] = 4000
            if defect == "uniform" and index == 0:
                measurement["method"] = "equal_duration_from_text"
            cue = {"key": "subtitle-" + str(index), "kind": "dialogue", "scope_object_id": self.fixture.objects["episode"],
                "line_id": line["id"], "shots": [{"shot_id": row["shot_id"]} for row in covers if row["line_id"] == line["id"]],
                "timeline_item_ids": [audio_items["dialogue-" + str(index)]["id"]], "parameters": {"subtitle_alignment": alignment}}
            cues.append(cue)
        if defect == "missing":
            cues.pop()
        if defect == "duplicate":
            clone = json.loads(json.dumps(cues[0]))
            clone["key"] = "duplicate-line"
            cues.append(clone)
        if defect == "no_measurement":
            cues[0]["parameters"] = {}
        if defect == "wrong_scope":
            cues[0]["scope_object_id"] = second_shot
        cue_artifact = self.fixture.artifact("subtitle-cues", "creative-relations", {
            "format": "vsc.creative-relations/v1", "project_id": self.fixture.p, "cues": cues}, [script, coverage, timeline_artifact])
        return {"timeline": timeline["id"], "cue_artifact": cue_artifact, "video": video, "audio": blob, "line_ids": line_ids}

    def test_pg_subtitle_package_measured_repeated_lines_reach_three_consumers(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.post.resource_export import export_render_package, scaffold_render_package
        from vsc.post import subtitles as sub, subtitle_burn as burn
        from vsc.adapters.editors import jianying_export as jy
        from vsc.post import remotion_plan as remotion
        data = self.subtitle_fixture()
        root = Path(self.temp.name)
        exported = export_render_package(self.service, self.fixture.p, data["timeline"], root / "subtitle-export")
        package_root = Path(exported["directory"])
        package = json.loads((package_root / "subtitles.json").read_text())
        plan = json.loads((package_root / "render-plan.json").read_text())
        self.assertEqual([cue["line_id"] for cue in package["cues"]], data["line_ids"])
        self.assertEqual([(cue["start_ms"], cue["end_ms"]) for cue in package["cues"]], [(200, 1300), (1800, 2500)])
        self.assertEqual(len(package["audio_sources"]), 2)  # each source interval plays once; first spans both shots
        style = dict(burn.DEFAULT_STYLE, font=str(burn.DEFAULT_FONT), font_size=32)
        payload, captions, _ = jy.draft_payload(plan, package_root, style, formal_subtitles=True)
        manifest = scaffold_render_package(package_root, root / "subtitle-remotion")
        generated = json.loads((root / "subtitle-remotion/src/plan.ts").read_text().split(" = ", 1)[1].strip().removesuffix(";"))
        self.assertEqual([(row["subtitle_start_ms"], row["subtitle_end_ms"], row["text"]) for row in generated["segments"] if row["kind"] == "caption"],
            [(200, 1300, "好2:30见"), (1800, 2500, "好2:30见")])
        from contextlib import redirect_stdout
        from io import StringIO
        from vsc.interfaces.cli import resources
        with mock.patch.object(resources, "service_from_environment", return_value=self.service), mock.patch.object(self.service.store, "close"), redirect_stdout(StringIO()) as stdout:
            resources.main(["render-export", self.fixture.p, data["timeline"], "--out", str(root / "formal-cli")])
        cli_receipt = json.loads(stdout.getvalue())
        self.assertEqual(cli_receipt["subtitle_package_sha256"], package["package_sha256"])
        self.assertEqual(cli_receipt["subtitle_status"], "verified")
        captured = []
        def local_renderer(command, **kwargs):
            if "render" in command:
                burn.render(command[-1])
                captured.extend(json.loads(Path(command[-1]).read_text())["cues"])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return subprocess.run(command, **kwargs)
        with mock.patch.object(burn.shutil, "which", return_value="offline-renderer"):
            result = burn.burn(data["video"], None, root / "burned.mp4", style, run=local_renderer,
                subtitle_package=package, subtitle_root=package_root, formal_subtitles=True)
        expected = [(0.2, 1.3, "好2:30见"), (1.8, 2.5, "好2:30见")]
        self.assertEqual(captions, expected)
        self.assertEqual([(cue["start"], cue["end"], cue["text"]) for cue in captured], expected)
        self.assertTrue((root / "burned.mp4").is_file())
        for checks in [payload["subtitle_checks"], manifest["subtitle_checks"], result["subtitle_checks"]]:
            self.assertEqual(checks["line_binding"], "verified")
            self.assertEqual(checks["audio_alignment"], "measured_timecodes_verified")
            self.assertEqual(checks["human_review"], "not_run")
            self.assertEqual(checks["package_sha256"], package["package_sha256"])
        for defect in ["missing_line", "missing_line_and_cue", "changed_line", "wrong_script_sha", "wrong_scope"]:
            broken = json.loads(json.dumps(package))
            if defect == "missing_line":
                broken["lines"].pop()
            elif defect == "missing_line_and_cue":
                missing = broken["lines"].pop()["id"]
                broken["cues"] = [cue for cue in broken["cues"] if cue["line_id"] != missing]
            elif defect == "changed_line":
                broken["lines"][0]["text"] = broken["cues"][0]["source_text"] = "changed approved text"
            elif defect == "wrong_script_sha":
                broken["cues"][0]["script_version_sha256"] = "f" * 64
            else:
                broken["scope_episode_id"] = str(uuid.uuid4())
            broken = sub.seal_package(broken)
            changed_plan = json.loads(json.dumps(plan))
            changed_plan["subtitle_package"] = broken
            changed_path = package_root / (defect + ".json")
            changed_path.write_text(json.dumps(changed_plan))
            for consumer, consume in [
                ("burn", lambda: burn.burn(data["video"], None, root / (defect + ".mp4"), style, subtitle_package=broken, subtitle_root=package_root, formal_subtitles=True)),
                ("remotion", lambda: remotion.scaffold(changed_plan, root / (defect + "-remotion"), plan_path=changed_path, formal_subtitles=True)),
                ("jianying", lambda: jy.draft_payload(changed_plan, package_root, style, formal_subtitles=True))]:
                with self.subTest(defect=defect, consumer=consumer), self.assertRaises((ValueError, RuntimeError)):
                    consume()
        # The adopted waveform can be transcoded, but old measured bindings
        # cannot silently attach to the replacement byte version.
        changed = root / "transcoded.wav"
        audio_path = package_root / package["audio_sources"][0]["path"]
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-ar", "48000", str(changed)], check=True, timeout=30)
        audio_path.write_bytes(changed.read_bytes())
        for consume in [lambda: sub.package_cues(package, package_root), lambda: jy.draft_payload(plan, package_root, style, formal_subtitles=True),
                        lambda: scaffold_render_package(package_root, root / "changed-remotion"),
                        lambda: burn.burn(data["video"], None, root / "changed.mp4", style, subtitle_package=package, subtitle_root=package_root, formal_subtitles=True)]:
            with self.assertRaises((ValueError, RuntimeError, ResourceError)):
                consume()

    def test_pg_subtitle_missing_or_wrong_fixed_evidence_blocks_formal_export(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.post.resource_export import export_render_package
        for defect in ["missing", "duplicate", "wrong_sha", "wrong_script", "wrong_range", "no_measurement", "replacement_audio", "uniform", "unapproved", "replay"]:
            # Each case has an independent project and simulated fixture decisions.
            self.fixture = ResourceFixture(self.service)
            data = self.subtitle_fixture(defect)
            if defect == "unapproved":
                self.fixture.write("decide_artifact", {"artifact_id": data["cue_artifact"], "outcome": "revoke", "reason": "合成夹具的明确撤销模拟"})
            with self.subTest(defect=defect), self.assertRaisesRegex(ResourceError, "字幕"):
                export_render_package(self.service, self.fixture.p, data["timeline"], Path(self.temp.name) / defect)

    def test_pg_subtitle_current_cue_version_excludes_historical_duplicate(self):
        from vsc.post.resource_export import export_render_package
        data = self.subtitle_fixture()
        previous = self.service.get_artifact_version(self.fixture.p, data["cue_artifact"])
        current = self.fixture.artifact("subtitle-cues", "creative-relations", json.loads(previous["document"]), previous["dependency_ids"])
        exported = export_render_package(self.service, self.fixture.p, data["timeline"], Path(self.temp.name) / "current-cues")
        package = json.loads((Path(exported["directory"]) / "subtitles.json").read_text())
        self.assertEqual({cue["cue_artifact_id"] for cue in package["cues"]}, {current})
        self.assertTrue(self.service.get_artifact_version(self.fixture.p, data["cue_artifact"])["approved"])

    def test_pg_subtitle_scope_mismatch_cannot_be_registered_as_formal_relation(self):
        from vsc.assets.resource_service import ResourceError
        with self.assertRaisesRegex(ResourceError, "范围"):
            self.subtitle_fixture("wrong_scope")

    def test_pg_subtitle_draft_lists_gap_and_cli_uses_same_export(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from vsc.interfaces.cli import resources
        data = self.subtitle_fixture("no_measurement")
        root = Path(self.temp.name)
        # Exercise the actual CLI parser/dispatch with the real isolated service;
        # the factory override only prevents discovering any configured live DB.
        with mock.patch.object(resources, "service_from_environment", return_value=self.service), mock.patch.object(self.service.store, "close"), redirect_stdout(StringIO()) as stdout:
            resources.main(["render-export", self.fixture.p, data["timeline"], "--out", str(root / "draft"), "--draft-subtitles"])
        receipt = json.loads(stdout.getvalue())
        self.assertEqual(receipt["subtitle_status"], "not_verified")
        package = json.loads((root / "draft/subtitles.json").read_text())
        self.assertTrue(package["gaps"])
        self.assertEqual(package["status"], "not_verified")
        with mock.patch.object(resources, "service_from_environment", return_value=self.service), mock.patch.object(self.service.store, "close"), self.assertRaises(SystemExit):
            resources.main(["render-export", self.fixture.p, data["timeline"], "--out", str(root / "formal")])

    def grok_worker(self, transport, download=None):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.adapters.providers.xai_grok.provider import GrokVideoProvider
        from vsc.adapters.providers.xai_grok.resource_factory import ConfiguredGrokProvider
        from vsc.adapters.providers.xai_grok import credentials
        self.login = Path(self.temp.name) / "synthetic-auth.json"
        self.login.write_text(json.dumps({"synthetic": {"user_id": "account-A", "key": "synthetic-A"}}))
        patch = mock.patch.object(credentials, "LOGIN_FILE", self.login)
        patch.start()
        self.addCleanup(patch.stop)
        key = "grok-imagine-video-1.5"
        staged = self.service.storage.stage_upload(BytesIO(png_bytes()), "grok-frame.png")
        frame = self.fixture.write("register_media", {"staged_upload":staged["staged_upload"],"name":"grok-frame.png",
            "source":{"kind":"fixture","content":"synthetic first frame"},"rights":"unknown"})['id']
        self.fixture.select_media(frame,"first_frame")
        model = self.service.register_model({"provider_id": "fixture", "model_key": key,
            "model_version": "grok-offline", "modality": "video", "capabilities": {"purposes": ["video_clip"],"first_frame":True}}, actor="fixture-human")["id"]
        job = self.fixture.job("video", "video_clip", model, {"duration_ms": 6000,"first_frame_media_id":frame})
        import base64
        adapter = ConfiguredGrokProvider(GrokVideoProvider(key, lambda value: 'data:image/png;base64,'+base64.b64encode(png_bytes()).decode(), "480p", transport=transport), "fixture")
        return ResourceWorker(self.service, lambda job, storage: adapter, download=download), job

    def test_grok_success_response_is_durable_before_transfer_and_same_account_refresh_resumes(self):
        from support.fixtures.media import production_media
        calls, downloads = [], []
        def transport(path, payload=None):
            calls.append((path, payload))
            return {"request_id": "grok-pg-1"} if payload is not None else {"status": "done", "video": {"url": "https://example.invalid/out.mp4"}}
        def download(url, target):
            downloads.append(url)
            if len(downloads) == 1:
                raise OSError("synthetic transfer interruption")
            target.write_bytes(production_media()["mp4"])
        worker, job = self.grok_worker(transport, download)
        worker.run_once(self.fixture.p)
        with self.assertRaises(OSError):
            worker.run_once(self.fixture.p, poll=True)
        saved = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual(saved["status"], "running")
        self.assertEqual(saved["raw_response"]["status"], "done")
        self.assertTrue(any((e["evidence"] or {}).get("source") == "provider_success_awaiting_storage" for e in saved["events"]))
        self.login.write_text(json.dumps({"synthetic": {"user_id": "account-B", "key": "synthetic-B"}}))
        before = (len(calls), len(downloads))
        with self.assertRaisesRegex(ValueError, "账号"):
            worker.finalize(self.fixture.p, job["id"])
        self.assertEqual((len(calls), len(downloads)), before)
        self.login.write_text(json.dumps({"synthetic": {"user_id": "account-A", "key": "new-token-A"}}))
        result = worker.run_once(self.fixture.p, poll=True)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(calls), 2)  # one POST and one GET, transfer recovery uses saved done
        saved = self.service.get_generation_job(self.fixture.p, job["id"])
        media = self.service.get_media(self.fixture.p, saved["outputs"][0]["media_id"])
        self.assertGreater(media["duration_ms"], 0)

    def test_grok_local_endpoint_error_precedes_submission_intent_and_budget(self):
        calls = []
        worker, job = self.grok_worker(lambda *args: calls.append(args))
        with mock.patch.dict(os.environ, {"GROK_BASE_URL": "https://invalid.example/v1"}):
            with self.assertRaisesRegex(RuntimeError, "GROK_BASE_URL"):
                worker.run_once(self.fixture.p)
        saved = self.service.get_generation_job(self.fixture.p, job["id"])
        self.assertEqual(saved["status"], "created")
        self.assertEqual(saved["attempt"], 0)
        self.assertIsNone(saved["raw_response"])
        self.assertFalse(any(e["event_type"] == "submission_unknown" for e in saved["events"]))
        self.assertEqual(calls, [])
