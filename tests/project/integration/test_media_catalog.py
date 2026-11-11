"""Real PostgreSQL media directory categories, producer provenance, detail projection and HTTP reads."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.access_control import Principal, current_principal, reset_principal, set_principal
from vsc.assets.resource_service import NotFound, ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ProjectMediaCatalogTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-media-catalog-')
        self.addCleanup(self.temp.cleanup)
        self.service.storage = LocalStorage(self.temp.name)
        self.owner = self.service.ensure_local_access('test-human')
        self.token = set_principal(Principal(**self.owner))
        self.addCleanup(reset_principal, self.token)
        self.bind(self.p)

    def bind(self, project_id):
        preview = self.service.access_migration_preview(project_id, self.owner['workspace_id'])
        self.service.access_command('assign-project', dict(
            project_id=project_id, workspace_id=self.owner['workspace_id'], preview_sha256=preview['sha256']
        ), actor='test-human', expected_revision=self.service.access_snapshot()['access_revision'],
            idempotency_key=uuid.uuid4().hex)

    def member(self, role):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        identifier = str(uuid.uuid4())
        actor = 'member:' + identifier
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_identities).values(
                id=identifier, subject_key='remote:' + identifier, actor=actor,
                display_name='Synthetic Member', preferences={}, active=True))
            conn.execute(insert(S.access_project_members).values(
                project_id=self.p, identity_id=identifier, role=role, active=True))
        return dict(identity_id=identifier, actor=actor)

    @contextmanager
    def as_member(self, member):
        token = set_principal(Principal(**member))
        try:
            yield
        finally:
            reset_principal(token)

    def register_local_media(self, name, modality='image', width=None, height=None, duration_ms=None, body=None):
        raw = body if body is not None else f'owned-{name}-{modality}-{uuid.uuid4().hex}'.encode()
        sha = hashlib.sha256(raw).hexdigest()
        key = f'{sha}.bin'
        (Path(self.temp.name) / key).write_bytes(raw)
        mime = {'image': 'image/png', 'video': 'video/mp4', 'audio': 'audio/wav', 'text': 'text/plain'}[modality]
        payload = {
            'name': name, 'modality': modality, 'sha256': sha, 'size_bytes': len(raw),
            'mime_type': mime, 'storage': 'local', 'object_key': key, 'rights': 'owned',
            'source': {'kind': 'test-owned', 'content': 'owned test evidence ' + name},
        }
        if width is not None:
            payload['width'] = width
        if height is not None:
            payload['height'] = height
        if duration_ms is not None:
            payload['duration_ms'] = duration_ms
        row = self.write('register_media', payload, actor=current_principal().actor)
        self.write('record_media_check', {
            'media_id': row['id'], 'checker': 'test-probe', 'criteria_version': '1', 'outcome': 'pass'
        }, actor=current_principal().actor)
        return row['id'], raw, Path(self.temp.name) / key

    def ensure_provider_model(self, modality, purposes, model_key=None, enabled=True, extra_caps=None):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        provider_id = 'fake_' + uuid.uuid4().hex
        model_id = str(uuid.uuid4())
        caps = {'purposes': list(purposes), **(extra_caps or {})}
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(
                id=provider_id, name='offline fake', modality=modality,
                base_url='https://example.invalid', auth_ref='secret_env_ref', enabled=enabled, rate_limit={}))
            conn.execute(insert(S.provider_models).values(
                id=model_id, provider_id=provider_id, model_key=model_key or ('fake-' + modality),
                modality=modality, model_version='2.1', capabilities=caps,
                default_params={}, cost_rule={}, enabled=enabled))
        return provider_id, model_id

    def succeed_job(self, *, run_id, model_id, modality, purpose, output_media_id, request, shot_id=None, asset_id=None, context_sha=''):
        payload = {
            'run_version_id': run_id, 'purpose': purpose, 'modality': modality,
            'model_id': model_id, 'context_sha256': context_sha, 'request_payload': request,
        }
        if shot_id:
            payload['shot_id'] = shot_id
        if asset_id:
            payload['asset_id'] = asset_id
        job = self.write('create_generation_job', payload)
        self.write('update_generation_job', {'job_id': job['id'], 'status': 'submitted', 'external_task_id': 'ext-' + job['id'][:8]})
        self.write('update_generation_job', {'job_id': job['id'], 'status': 'succeeded', 'outputs': [{'media_id': output_media_id}]})
        return job['id']

    def succeed_working_job(self, *, shot_id, mode, purpose, modality, model_id, prompt, resolution=None, output_media_id, request_prompt=None, first_frame_media_id=None, reference_media_id=None, canvas_version_id=None, node_key=None):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.workbench_generation import working_context

        refs = []
        if first_frame_media_id:
            refs.append({'role': 'first_frame', 'media_id': first_frame_media_id})
        if reference_media_id:
            refs.append({'role': 'reference_image', 'media_id': reference_media_id})
        draft_doc = {
            'shot_id': shot_id, 'mode': mode, 'model_id': model_id, 'purpose': purpose,
            'prompt': prompt, 'duration_ms': 5000, 'width': 1920, 'height': 1080,
            'count': 1, 'params': {'resolution': resolution} if resolution else {}, 'references': refs,
        }
        draft_art = self.write('save_classic_draft', {'document': draft_doc, 'base_draft_id': None})
        with self.engine.begin() as conn:
            proj = self.store._project(conn, self.p, lock=True)
            working_sha = working_context(self.store, conn, proj, draft_art['id'])['sha256']
            req = {
                'prompt': request_prompt or prompt, 'params': {'resolution': resolution} if resolution else {},
                'shot_id': shot_id, 'purpose': purpose, 'modality': modality, 'context_sha256': working_sha,
            }
            if first_frame_media_id:
                req['first_frame_media_id'] = first_frame_media_id
            if reference_media_id:
                req['reference_media_ids'] = [reference_media_id]
            run = self.store._create_artifact(conn, proj, {
                'artifact_key': 'run-' + uuid.uuid4().hex[:8], 'artifact_type': 'workbench-generation-run',
                'document': {
                    'workbench_draft': {'id': draft_art['id'], 'sha256': draft_art['sha256']},
                    'series_batch': {
                        'jobs': [{'candidate_no': 0, 'model_id': model_id, 'request': req}],
                        'operations': {f'series:{shot_id}:{purpose}:0': 1},
                    },
                    'approved_inputs': [], 'jobs': [{'candidate_no': 0, 'request': req}],
                    'operations': {f'series:{shot_id}:{purpose}:0': 1},
                },
                'object_ids': [shot_id], 'dependency_ids': [],
            })
            conn.execute(insert(S.workbench_run_inputs).values(
                project_id=self.p, id=str(uuid.uuid4()), run_version_id=run['id'],
                shot_id=shot_id, draft_version_id=draft_art['id'],
                draft_sha256=draft_art['sha256'], output_kind=modality))
            if canvas_version_id and node_key:
                conn.execute(insert(S.creative_canvas_runs).values(
                    project_id=self.p, id=str(uuid.uuid4()), version_id=canvas_version_id,
                    node_key=node_key, artifact_id=run['id'], preview_sha256='a' * 64))
        self.rev = self.service.get_project(self.p)['revision']
        self.write('decide_artifact', {'artifact_id': run['id'], 'reason': '批准固定工作运行'})
        return self.succeed_job(
            run_id=run['id'], model_id=model_id, modality=modality, purpose=purpose,
            output_media_id=output_media_id, request=req, shot_id=shot_id, context_sha=working_sha)

    def test_six_categories_producer_precedence_and_non_misclassification(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S

        objects = self.hierarchy()
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']], {'state_versions': [{'scene_id': objects['scene']}]})

        # 1. asset_image via asset_card_form_versions, also referenced on a canvas (must remain asset_image).
        asset_media, _, _ = self.register_local_media('角色立绘', 'image', width=1024, height=1024)
        asset_card = self.write('save_asset_card', {
            'name': '主角', 'asset_kind': 'character', 'base_revision': 0,
            'forms': [{'form_key': 'default', 'name': '默认形态', 'base_version_id': None, 'media_id': asset_media}],
        })

        # 2. shot_image via classic fixed workbench draft + generation_job, also bound to another asset form
        #    (priority 0 shot_generation must win over priority 1 asset_form, and reuse must be available).
        _, image_model = self.ensure_provider_model('image', ['first_frame', 'image_edit'], model_key='seedream-v3', extra_caps={'reference_media': True})
        shot_image, _, _ = self.register_local_media('镜头首帧', 'image', width=1920, height=1080)
        shot_img_job = self.succeed_working_job(
            shot_id=objects['shot'], mode='image', purpose='first_frame', modality='image',
            model_id=image_model, prompt='固定分镜提示词', resolution='2K',
            output_media_id=shot_image, request_prompt='被覆盖的底层请求提示词')
        # Bind shot_image to an episode asset too: priority 0 generation must win over priority 1 episode_asset_form.
        self.write('save_episode_asset', {
            'episode_id': objects['episode'], 'base_revision': 0, 'asset_key': 'ep-prop',
            'name': '道具引用', 'asset_kind': 'prop',
            'forms': [{'form_key': 'main', 'name': '主形态', 'base_version_id': None, 'media_id': shot_image}],
        })

        # 3. composite_video via shot generation_job.
        _, video_model = self.ensure_provider_model('video', ['video_clip', 'text_to_video'], model_key='seedance-pro', extra_caps={'first_frame': True})
        composite_video, _, _ = self.register_local_media('合成镜头视频', 'video', width=1920, height=1080, duration_ms=5000)
        self.succeed_working_job(
            shot_id=objects['shot'], mode='single', purpose='video_clip', modality='video',
            model_id=video_model, prompt='镜头合成视频', resolution='1080p',
            first_frame_media_id=shot_image, output_media_id=composite_video)

        # 4–6. canvas_image, canvas_audio, canvas_video via creative_canvas_runs,
        #      plus an uploaded raw image attached to canvas & job_input_media (must NOT become canvas_image).
        uploaded_input, _, _ = self.register_local_media('上传参考原图', 'image')
        canvas = self.write('create_creative_canvas', {
            'title': '测试画布', 'episode_id': objects['episode'],
            'document': {
                'nodes': [
                    {'id': 'ref1', 'type': 'image', 'media_id': uploaded_input},
                    {'id': 'asset_ref', 'type': 'image', 'media_id': asset_media},
                    {'id': 'gen_img', 'type': 'image', 'text': '当前画布上被改过的文字'},
                    {'id': 'gen_aud', 'type': 'audio', 'text': '画布配音'},
                    {'id': 'gen_vid', 'type': 'video', 'text': '画布视频'},
                ],
                'edges': [],
            },
        })
        _, audio_model = self.ensure_provider_model('audio', ['music'], model_key='doubao-audio')
        canvas_image, _, _ = self.register_local_media('画布生成图', 'image', width=1280, height=720)
        canvas_audio, _, _ = self.register_local_media('画布生成音频', 'audio', duration_ms=3200)
        canvas_video, _, _ = self.register_local_media('画布生成视频', 'video', width=1280, height=720, duration_ms=4000)

        for index, (key, mode, mod, model, purpose, res, out_media, prompt_text) in enumerate((
            ('gen_img', 'image', 'image', image_model, 'image_edit', '1080p', canvas_image, '固定画布生图提示词'),
            ('gen_aud', 'audio', 'audio', audio_model, 'music', None, canvas_audio, '固定画布音频提示词'),
            ('gen_vid', 'text', 'video', video_model, 'text_to_video', '1080p', canvas_video, '固定画布视频提示词'),
        ), start=1):
            c_shot = self.write('create_object', {
                'kind': 'shot', 'display_code': f'CSHOT-{index}', 'parent_id': objects['sequence'], 'ordinal': index
            })['id']
            self.succeed_working_job(
                shot_id=c_shot, mode=mode, purpose=purpose, modality=mod, model_id=model,
                prompt=prompt_text, resolution=res, output_media_id=out_media,
                reference_media_id=uploaded_input if mod == 'image' else None,
                canvas_version_id=canvas['version_id'], node_key=key)

        # 7. Ambiguous priority-1 producer: uploaded image bound to both asset_card_form and shot binding_candidate.
        ambiguous_media, _, _ = self.register_local_media('双重归属图片', 'image', width=800, height=600)
        self.write('save_asset_card', {
            'name': '场景卡', 'asset_kind': 'location', 'base_revision': 0,
            'forms': [{'form_key': 'main', 'name': '主景', 'base_version_id': None, 'media_id': ambiguous_media}],
        })
        self.candidate(objects['shot'], ambiguous_media, role='composition', slot_key='comp')

        listing = self.service.list_project_media(project_id=self.p, limit=20)
        by_id = {row['id']: row for row in listing['items']}
        self.assertEqual(listing['total'], 8)

        expected_categories = {
            'asset_image': {asset_media},
            'shot_image': {shot_image},
            'composite_video': {composite_video},
            'canvas_image': {canvas_image},
            'canvas_audio': {canvas_audio},
            'canvas_video': {canvas_video},
        }
        for cat, expected_ids in expected_categories.items():
            filtered = self.service.list_project_media(project_id=self.p, category=cat, limit=1)
            self.assertEqual(filtered['total'], len(expected_ids), cat)
            self.assertEqual({r['id'] for r in filtered['items']}, expected_ids, cat)
            self.assertIsNone(filtered['next_offset'], cat)

        # Uploaded canvas input is NOT canvas_image; it has unknown_source + canvas usage navigation.
        raw_item = by_id[uploaded_input]
        self.assertIsNone(raw_item['category'])
        self.assertEqual(raw_item['category_reason'], 'unknown_source')
        self.assertIsNone(raw_item['producer'])
        self.assertIsNone(raw_item['width'])
        self.assertIsNone(raw_item['duration_ms'])
        self.assertTrue(raw_item['actions']['source']['available'])
        self.assertIn(canvas['id'], raw_item['actions']['source']['href'])
        self.assertFalse(raw_item['actions']['reuse']['available'])

        # Ambiguous priority-1 media has no category, no producer, and withdraws source navigation.
        amb_item = by_id[ambiguous_media]
        self.assertIsNone(amb_item['category'])
        self.assertEqual(amb_item['category_reason'], 'ambiguous_source')
        self.assertIsNone(amb_item['producer'])
        self.assertIsNone(amb_item['source_href'])
        self.assertEqual(amb_item['actions']['source'], {'available': False, 'reason_code': 'ambiguous_source'})

        # Asset image placed on canvas keeps asset_image producer & asset source link, reuse unavailable.
        asset_item = by_id[asset_media]
        self.assertEqual(asset_item['category'], 'asset_image')
        self.assertEqual(asset_item['producer']['kind'], 'asset_form')
        self.assertIn('page=assets', asset_item['actions']['source']['href'])
        self.assertEqual(asset_item['actions']['reuse'], {'available': False, 'reason_code': 'configuration_unavailable'})

        # Shot image with fixed workbench draft exposes classic_fixed_draft reuse and pinned draft metadata.
        shot_item = by_id[shot_image]
        self.assertEqual(shot_item['category'], 'shot_image')
        self.assertEqual(shot_item['producer']['source_job_id'], shot_img_job)
        self.assertTrue(shot_item['actions']['reuse']['available'])
        self.assertEqual(shot_item['actions']['reuse']['kind'], 'classic_fixed_draft')
        self.assertIn(f'reuse_media={shot_image}', shot_item['actions']['reuse']['href'])

        detail = self.service.get_project_media_detail(self.p, shot_image)
        self.assertEqual(detail['prompt'], '固定分镜提示词')
        self.assertEqual(detail['resolution_label'], '2K')
        self.assertEqual(detail['aspect_ratio'], '16:9')
        self.assertEqual(detail['model'], {'id': image_model, 'name': 'seedream-v3', 'version': '2.1', 'available': True})
        for forbidden in ('raw_response', 'original_uri', 'auth_ref', 'request_payload'):
            self.assertNotIn(forbidden, detail)

        # Canvas image detail reads fixed job prompt, never current canvas node text.
        canvas_detail = self.service.get_project_media_detail(self.p, canvas_image)
        self.assertEqual(canvas_detail['prompt'], '固定画布生图提示词')
        self.assertEqual(canvas_detail['aspect_ratio'], '16:9')
        self.assertFalse(canvas_detail['actions']['reuse']['available'])

        asset_detail = self.service.get_project_media_detail(self.p, asset_media)
        self.assertEqual(asset_detail['asset_kind'], 'character')
        self.assertEqual(asset_detail['aspect_ratio'], '1:1')

        # Viewer can read list & detail, but cannot reuse classic draft configuration.
        viewer = self.member('viewer')
        with self.as_member(viewer):
            viewer_detail = self.service.get_project_media_detail(self.p, shot_image)
            self.assertEqual(viewer_detail['id'], shot_image)
            self.assertFalse(viewer_detail['actions']['reuse']['available'])

        # Trashing the canvas keeps canvas-generated and canvas-referenced media in catalog,
        # while withdrawing active source navigation on both until restored.
        self.write('management_command', {
            'operation': 'trash', 'target_type': 'canvas', 'target_id': canvas['id'], 'reason': '回收画布验证来源撤回'
        })
        trashed_by_id = {row['id']: row for row in self.service.list_project_media(project_id=self.p, limit=20)['items']}
        self.assertEqual(trashed_by_id[canvas_image]['actions']['source'], {'available': False, 'reason_code': 'source_inactive'})
        self.assertEqual(trashed_by_id[uploaded_input]['actions']['source'], {'available': False, 'reason_code': 'source_unknown'})
        self.write('management_command', {
            'operation': 'restore', 'target_type': 'canvas', 'target_id': canvas['id'], 'reason': '恢复画布验证来源恢复'
        })
        restored_by_id = {row['id']: row for row in self.service.list_project_media(project_id=self.p, limit=20)['items']}
        self.assertTrue(restored_by_id[canvas_image]['actions']['source']['available'])
        self.assertTrue(restored_by_id[uploaded_input]['actions']['source']['available'])

    def test_date_boundaries_pagination_recycle_and_http_read_only_contract(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import func, insert, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog

        objects = self.hierarchy()

        def insert_dated_media(name, created_at, width=None, height=None):
            raw = f'dated-{name}-{uuid.uuid4().hex}'.encode()
            sha = hashlib.sha256(raw).hexdigest()
            key = f'{sha}.bin'
            path = Path(self.temp.name) / key
            path.write_bytes(raw)
            blob_id, media_id, loc_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            with self.engine.begin() as conn:
                conn.execute(insert(S.media_blobs).values(
                    id=blob_id, sha256=sha, size_bytes=len(raw), mime_type='image/png',
                    width=width, height=height, probe={}, created_at=created_at))
                conn.execute(insert(S.blob_locations).values(
                    id=loc_id, blob_id=blob_id, storage='local', object_key=key, available=True, created_at=created_at))
                conn.execute(insert(S.media_items).values(
                    project_id=self.p, id=media_id, blob_id=blob_id, name=name, modality='image',
                    registered_by='test-human', created_at=created_at))
            self.write('record_media_check', {
                'media_id': media_id, 'checker': 'test-probe', 'criteria_version': '1', 'outcome': 'pass'
            })
            return media_id, raw, path

        t1 = datetime(2026, 11, 1, 23, 59, 59, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
        m1, raw1, path1 = insert_dated_media('day-one', t1, width=1920, height=1080)
        m2, _, path2 = insert_dated_media('day-two', t2)
        m3, _, _ = self.register_local_media('recycled-item', 'image')
        self.candidate(objects['shot'], m1, role='first_frame', slot_key='s1')
        self.candidate(objects['shot'], m2, role='last_frame', slot_key='s2')

        # Half-open UTC date and ISO8601 boundaries.
        nov1 = self.service.list_project_media(project_id=self.p, created_after='2026-11-01', created_before='2026-11-01')
        self.assertEqual([r['id'] for r in nov1['items']], [m1])
        half_open = self.service.list_project_media(
            project_id=self.p, created_after='2026-11-01T23:59:59Z', created_before='2026-11-02T00:00:00Z')
        self.assertEqual([r['id'] for r in half_open['items']], [m1])

        # Recycle m3 -> excluded from list and 404 in detail.
        self.write('recycle_media', {'media_ids': [m3], 'action': 'trash', 'reason': '清理测试素材'})
        self.assertNotIn(m3, {r['id'] for r in self.service.list_project_media(project_id=self.p)['items']})
        with self.assertRaises(NotFound):
            self.service.get_project_media_detail(self.p, m3)

        # Validation errors.
        for bad in (
            {'category': 'unknown'},
            {'episode_id': objects['episode']},
            {'created_after': '2026-11-05', 'created_before': '2026-11-04'},
            {'created_after': '2026-11-01T10:00:00'},
            {'limit': 0},
            {'limit': 101},
        ):
            with self.assertRaises(ResourceError):
                self.service.list_project_media(**bad)

        # Snapshot counts before HTTP GET calls to prove zero side-effect writes.
        def state_counts():
            with self.engine.connect() as conn:
                rev = conn.scalar(select(S.projects.c.revision).where(S.projects.c.id == self.p))
                jobs = conn.scalar(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id == self.p))
                shares = conn.scalar(select(func.count()).select_from(S.access_shares).where(S.access_shares.c.project_id == self.p))
                renditions = conn.scalar(select(func.count()).select_from(S.media_renditions).where(S.media_renditions.c.project_id == self.p))
            return rev, jobs, shares, renditions

        before_counts = state_counts()
        catalog = ResourceCatalog(self.temp.name, self.service, media_root=self.temp.name)
        app = create_app(
            config={
                'allowed_hosts': ['testserver'], 'allowed_origins': ['http://testserver'],
                'access_token': 'fixture-token', 'human_identity': 'test-human', 'background_enabled': False,
            },
            catalog=catalog, service=self.service)
        with TestClient(app) as client:
            session_resp = client.post('/api/v1/session', json={'token': 'fixture-token'}, headers={'Origin': 'http://testserver'})
            self.assertEqual(session_resp.status_code, 200, session_resp.text)

            page1 = client.get(f'/api/v1/project-media?project_id={self.p}&category=shot_image&limit=1')
            self.assertEqual(page1.status_code, 200, page1.text)
            body1 = page1.json()
            self.assertEqual(body1['total'], 2)
            self.assertEqual(body1['next_offset'], 1)
            self.assertEqual(client.get(
                f'/api/v1/project-media?project_id={self.p}&category=shot_image&limit=1',
                headers={'If-None-Match': page1.headers['etag']},
            ).status_code, 304)

            detail_url = f'/api/v1/projects/{self.p}/media/{m1}/catalog-detail'
            detail_resp = client.get(detail_url)
            self.assertEqual(detail_resp.status_code, 200, detail_resp.text)
            self.assertEqual(detail_resp.json()['integrity'], 'verified')
            self.assertTrue(detail_resp.json()['actions']['download']['available'])
            self.assertEqual(client.get(detail_url, headers={'If-None-Match': detail_resp.headers['etag']}).status_code, 304)

            content_resp = client.get(detail_resp.json()['actions']['download']['href'])
            self.assertEqual(content_resp.status_code, 200)
            self.assertEqual(content_resp.content, raw1)

            # Tampered or missing bytes disable download action in catalog-detail.
            path2.unlink()
            missing_resp = client.get(f'/api/v1/projects/{self.p}/media/{m2}/catalog-detail')
            self.assertEqual(missing_resp.status_code, 200)
            self.assertEqual(missing_resp.json()['availability'], 'missing')
            self.assertEqual(missing_resp.json()['actions']['download'], {'available': False, 'reason_code': 'media_unavailable'})

            self.assertEqual(client.get(f'/api/v1/projects/{self.p}/media/{m3}/catalog-detail').status_code, 404)
            self.assertEqual(client.get('/api/v1/project-media?category=invalid').status_code, 422)
            self.assertEqual(client.get(f'/api/v1/project-media?episode_id={objects["episode"]}').status_code, 422)

        self.assertEqual(state_counts(), before_counts)
