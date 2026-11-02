"""A workbench generation click fixes inputs without approving a screenplay."""
import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS, "requires isolated PostgreSQL")
class WorkbenchGenerationTests(ResourceStoreFixture, unittest.TestCase):
    def test_multimodal_modes_create_fixed_jobs_without_formal_adoption(self):
        from vsc.production.resource_settings import ResourceSettings, PRESETS
        objects, image, document, _, request = self.prepare()
        audio = self.media('固定驱动声音', modality='audio')
        video = self.media('固定动作参考', modality='video')
        preset = next(row for row in PRESETS if row['id'] == 'volcengine-agent-plan')
        model = ResourceSettings(self.store).save({**{k: v for k, v in preset.items() if k not in {'id', 'label'}},
            'enabled': True, 'modality': 'video', 'model_key': 'doubao-seedance-isolated',
            'model_version': 'isolated-mixed-contract', 'capabilities': {
                'purposes': ['reference_to_video', 'digital_human', 'motion_transfer'],
                'reference_media': True, 'reference_audio': True, 'reference_video': True},
            'default_params': {'resolution': '720p', 'ratio': '9:16', 'generate_audio': True}}, 'test-human')
        for mode, purpose, refs in [
            ('omni', 'reference_to_video', [('reference_image', image), ('reference_video', video), ('reference_audio', audio)]),
            ('digital_human', 'digital_human', [('portrait', image), ('speech', audio)]),
            ('motion', 'motion_transfer', [('character', image), ('motion_video', video)])]:
            with self.subTest(mode=mode):
                saved = self.write('save_classic_draft', {'document': dict(document, mode=mode,
                    purpose=purpose, model_id=model['id'], references=[{'role': role, 'media_id': identifier} for role, identifier in refs]),
                    'base_draft_id': None})
                fixed = dict(request, draft_version_id=saved['id'])
                preview = self.service.preview_workbench_generation(self.p, fixed)
                if mode == 'digital_human':
                    # Generic image+audio generation is not speaking-subject
                    # control. The native mask pipeline has its own PG test.
                    self.assertFalse(preview['ready'])
                    self.assertIn('subject_selection_required', [gap['code'] for gap in preview['gaps']])
                    continue
                self.assertTrue(preview['ready'], preview.get('gaps'))
                result = self.write('generate_workbench', {'request': fixed, 'preview_sha256': preview['preview_sha256']})
                job = self.service.get_generation_job(self.p, result['jobs'][0]['id'])
                self.assertEqual({item['media_id'] for item in job['input_media']}, {identifier for _, identifier in refs})
                self.assertEqual(job['request_payload']['reference_video_media_ids'], [video] if mode != 'digital_human' else [])
                self.assertIsNone(job['request_payload']['first_frame_media_id'])

    def test_output_selection_trim_clear_and_edit_share_fixed_media(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        objects, _, _, _, request = self.prepare()
        preview = self.service.preview_workbench_generation(self.p, request)
        generated = self.write('generate_workbench', {'request': request, 'preview_sha256': preview['preview_sha256']})
        job_id = generated['jobs'][0]['id']
        self.write('configure_budget', {'limits': {'remote_jobs': 2, 'video_seconds': 10}, 'reason': '隔离任务额度'})
        self.write('update_generation_job', {'job_id': job_id, 'status': 'submitted', 'external_task_id': 'isolated-provider-task'})
        output = self.write('register_media', {'name': '隔离任务视频', 'modality': 'video',
            'sha256': uuid.uuid4().hex * 2, 'size_bytes': 10, 'mime_type': 'video/mp4',
            'duration_ms': 5000, 'width': 720, 'height': 1280, 'storage': 'local',
            'object_key': uuid.uuid4().hex + '.mp4', 'rights': 'unknown',
            'source': {'kind': 'test-generation', 'content': 'isolated output metadata'}})
        self.write('update_generation_job', {'job_id': job_id, 'status': 'succeeded',
            'outputs': [{'media_id': output['id']}]})
        page = self.service.list_working_candidates(self.p, objects['shot'], 'video')
        self.assertEqual(page['total'], 1)
        selected = page['items'][0]
        self.assertTrue(selected['selected'])
        self.assertEqual(selected['job_id'], job_id)
        trimmed = self.write('save_working_selection', {'shot_id': objects['shot'], 'output_kind': 'video',
            'candidate_id': selected['candidate_id'], 'base_version_id': selected['selection_version_id'],
            'event_kind': 'trim', 'trim_in_ms': 500, 'trim_out_ms': 4500})
        seed = self.service.seed_edit_workspace(self.p, objects['episode'])
        clip = seed['document']['clips'][0]
        self.assertEqual((clip['in_frame'], clip['out_frame'], seed['dynamic_frames']), (12, 108, 96))
        saved = self.write('save_edit_workspace', {'episode_id': objects['episode'], 'edit_revision': 0,
            'document': seed['document']})
        with self.engine.connect() as conn:
            fixed = conn.execute(select(S.edit_revision_working_selections).where(
                S.edit_revision_working_selections.c.edit_version_id == saved['edit_version_id'])).mappings().one()
            self.assertEqual(fixed['selection_version_id'], trimmed['selection_version_id'])
            self.assertEqual(self.service._editor()._inputs(conn, self.p, saved['edit_version_id'], usable=True)[0]['media_id'], output['id'])
        self.write('save_working_selection', {'shot_id': objects['shot'], 'output_kind': 'video',
            'candidate_id': None, 'base_version_id': trimmed['selection_version_id']})
        self.assertEqual(self.service.seed_edit_workspace(self.p, objects['episode'])['document']['clips'], [])
        self.assertEqual(self.service.get_edit_workspace(self.p, objects['episode'])['current']['document']['clips'][0], clip)
        self.assertFalse(self.service.list_working_candidates(self.p, objects['shot'], 'video')['items'][0]['selected'])
        replacement = self.media('不能替换选片来源', modality='video')
        bad = json.loads(json.dumps(seed['document']))
        bad['clips'][0]['media_id'] = replacement
        with self.assertRaises(ResourceError):
            self.write('save_edit_workspace', {'episode_id': objects['episode'], 'edit_revision': 1, 'document': bad})

    def prepare(self, mode="single", reference=None):
        from vsc.production.resource_settings import ResourceSettings, PRESETS
        objects = self.hierarchy()
        media = reference or self.media("本次上传参考")
        preset = next(row for row in PRESETS if row["id"] == "xai-grok-imagine-video")
        model = ResourceSettings(self.store).save({**{k: v for k, v in preset.items() if k not in {"id", "label"}},
            "enabled": True, "model_version": "isolated-workbench-test"}, "test-human")
        document = {"shot_id": objects["shot"], "mode": mode, "model_id": model["id"],
                    "purpose": "image_to_video", "prompt": "固定的本次动作", "count": 1,
                    "duration_ms": 5000, "references": [{"role": "first_frame", "media_id": media}]}
        saved = self.write("save_classic_draft", {"document": document, "base_draft_id": None})
        now = datetime.now(timezone.utc)
        policy = {"version": "bounded-v1", "first_draft_due_at": (now + timedelta(minutes=10)).isoformat(),
                  "stop_submitting_at": (now + timedelta(minutes=30)).isoformat(),
                  "max_attempts_per_purpose": 2, "max_repair_rounds": 1,
                  "authorization": {"mode": "new_batch", "reason": "在制作页明确生成此候选"}}
        request = {"draft_version_id": saved["id"], "execution_policy": policy}
        return objects, media, document, saved, request

    def test_original_worker_consumes_working_context_and_registers_decoded_output(self):
        import tempfile
        from io import BytesIO
        from support.fixtures.media import production_media
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_worker import ResourceWorker
        from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus
        with tempfile.TemporaryDirectory(prefix='vsc-working-worker-') as directory:
            self.service.storage = LocalStorage(directory)
            self.addCleanup(setattr, self.service, 'storage', None)
            samples = production_media()
            staged = self.service.storage.stage_upload(BytesIO(samples['png']), 'input.png')
            media = self.write('register_media', {'staged_upload': staged['staged_upload'], 'name': '实际上传图',
                'rights': 'unknown', 'source': {'kind': 'test-owned', 'content': 'synthetic pixels'}})
            objects, _, _, _, request = self.prepare(reference=media['id'])
            preview = self.service.preview_workbench_generation(self.p, request)
            generated = self.write('generate_workbench', {'request': request, 'preview_sha256': preview['preview_sha256']})
            self.write('configure_budget', {'limits': {'remote_jobs': 1, 'video_seconds': 5}, 'reason': '测试额度'})
            requests = []
            class Adapter:
                def submit(self, value):
                    requests.append(value)
                    return JobHandle('isolated', 'isolated', None, {'synthetic': True})
                def poll(self, handle):
                    return JobStatus('succeeded', raw=handle.raw)
                def parse_result(self, raw):
                    return [GeneratedAsset('video', inline_bytes=samples['mp4'])]
            worker = ResourceWorker(self.service, lambda *_: Adapter())
            finished = worker.run_once(self.p)
            self.assertEqual(finished['status'], 'succeeded')
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].first_frame_media_id, media['id'])
            self.assertIsNone(worker.run_once(self.p))
            candidate = self.service.list_working_candidates(self.p, objects['shot'], 'video')['items'][0]
            self.assertTrue(candidate['selected'])
            self.assertEqual(candidate['job_id'], generated['jobs'][0]['id'])
            self.assertGreater(candidate['duration_ms'], 0)

    def test_generation_is_one_receipted_action_without_formal_adoption(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        objects, media, document, saved, request = self.prepare()
        self.assertFalse(self.service.compile_shot_context(self.p, objects["shot"], "image_to_video")["ready"])
        preview = self.service.preview_workbench_generation(self.p, request)
        self.assertTrue(preview["ready"], preview.get("gaps"))
        payload = {"request": request, "preview_sha256": preview["preview_sha256"]}
        key = uuid.uuid4().hex
        generated = self.write("generate_workbench", payload, idempotency_key=key)
        replay = self.service.generate_workbench(self.p, payload, expected_revision=0,
            idempotency_key=key, actor="test-human")
        self.assertEqual(replay, generated)
        self.assertEqual(len(generated["jobs"]), 1)
        run = self.service.get_artifact_version(self.p, generated["run_version_id"])
        self.assertEqual(run["artifact_type"], "workbench-generation-run")
        self.assertTrue(run["approved"])
        self.assertFalse(self.service.get_artifact_version(self.p, saved["id"])["approved"])
        job = self.service.get_generation_job(self.p, generated["jobs"][0]["id"])
        self.assertEqual(job["input_media"][0]["media_id"], media)
        self.assertEqual(job["input_versions"][0]["artifact_id"], saved["id"])
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.current_bindings).where(S.current_bindings.c.project_id == self.p)), 0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.workbench_run_inputs).where(S.workbench_run_inputs.c.project_id == self.p)), 1)
        self.write("save_classic_draft", {"document": dict(document, prompt="下一次的新动作"), "base_draft_id": saved["id"]})
        self.write("configure_budget", {"limits": {"remote_jobs": 2, "video_seconds": 10}, "reason": "隔离任务额度"})
        claimed = self.service.claim_generation_job("test-working-worker", project_id=self.p)
        self.rev = self.service.get_project(self.p)["revision"]
        self.assertEqual(claimed["id"], job["id"])
        self.write("mark_submission_started", {"job_id": job["id"], "worker_id": "test-working-worker"})
        fixed = self.service.get_generation_job(self.p, job["id"])
        self.assertEqual(fixed["status"], "submission_unknown")
        self.assertEqual(fixed["request_payload"]["prompt"], "固定的本次动作")

    def test_first_last_accepts_only_first_but_quote_drift_and_foreign_input_reject(self):
        from vsc.assets.resource_service import Conflict, ResourceError
        _, _, _, _, request = self.prepare("first_last")
        preview = self.service.preview_workbench_generation(self.p, request)
        self.assertTrue(preview["ready"], preview.get("gaps"))
        with self.assertRaises(Conflict):
            self.write("generate_workbench", {"request": request, "preview_sha256": "0" * 64})
        other = self.service.create_project({"name": "其他项目"}, actor="test-human")["id"]
        with self.assertRaises(ResourceError):
            self.service.preview_workbench_generation(other, request)
        self.assertEqual(self.service.list_generation_jobs(self.p)["total"], 0)

    def test_http_requires_current_user_confirmation_and_restores_receipt(self):
        import tempfile
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        _, _, _, _, request = self.prepare()
        with tempfile.TemporaryDirectory() as root:
            app = create_app({"allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
                "access_token": "test", "human_identity": "test-human", "background_enabled": False},
                catalog=ResourceCatalog(root, service=self.service))
            with TestClient(app) as client:
                path = "/api/v1/projects/" + self.p + "/classic-production"
                login = client.post("/api/v1/session", json={"token": "test"}, headers={"origin": "http://testserver"}).json()
                headers = {"origin": "http://testserver", "x-csrf-token": login["csrf_token"]}
                quote = client.post(path + "/quote", json={"payload": request}, headers=headers)
                self.assertEqual(quote.status_code, 200, quote.text)
                body = {"payload": {"request": request, "preview_sha256": quote.json()["preview_sha256"]},
                        "expected_revision": self.rev, "idempotency_key": uuid.uuid4().hex}
                self.assertEqual(client.post(path + "/generate", json=body, headers=headers).status_code, 422)
                body["confirmed"] = True
                result = client.post(path + "/generate", json=body, headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(client.post(path + "/generate", json=body, headers=headers).json(), result.json())
                job_id = result.json()['jobs'][0]['id']
                detail = client.get(f'/api/v1/projects/{self.p}/production-platform/jobs/{job_id}')
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(detail.json()['usage']['quote']['native_units']['video_seconds'], 5)
                self.assertIsNone(detail.json()['usage']['reconciliation']['actual_amount'])
