"""Real PostgreSQL HTTP workflow in a random disposable schema; no provider calls."""
import importlib.util
import os
import struct
import tempfile
import unittest
import uuid
import zlib
from datetime import datetime, timedelta, timezone

from support.paths import ROOT
from support.fixtures.postgres import isolated_postgres

TEST_URL = os.environ.get("VSC_TEST_DATABASE_URL")
HAS_DEPS = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "psycopg", "alembic", "fastapi", "httpx"))


def fixture_png():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x30\x70\x60" * 2 + b"\x00" + b"\x30\x70\x60" * 2)) + chunk(b"IEND", b"")


@unittest.skipUnless(TEST_URL and HAS_DEPS, "requires explicit PostgreSQL test URL and web/postgres dependencies")
class PostgresPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = isolated_postgres(TEST_URL)
        cls.engine = cls.database.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.database.__exit__(None, None, None)

    def setUp(self):
        from fastapi.testclient import TestClient
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.assets.resource_service import ResourceService
        from vsc.interfaces.web.app import create_app
        self.temp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.temp.name)
        self.service = ResourceService(PostgresResourceStore(engine=self.engine), storage=self.storage)
        self.project = self.service.create_project({"name": "合成测试项目"}, actor="fixture-human")
        self.p, self.revision = self.project["id"], 0
        self.client = TestClient(create_app({"projects_root": self.temp.name + "/empty-projects", "media_root": self.temp.name,
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"], "human_identity": "fixture-human", "access_token": "fixture-token"}, service=self.service))
        self.client.__enter__()
        session = self.client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "fixture-token"}).json()
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
        self.base = "/api/v1/projects/" + self.p

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def write(self, endpoint, payload, status=200, revision=None, key=None):
        response = self.client.post(self.base + "/" + endpoint, headers=self.headers,
            json={"payload": payload, "expected_revision": self.revision if revision is None else revision,
                  "idempotency_key": key or uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(response.status_code, status, response.text)
        result = response.json()
        if status == 200:
            self.revision = result["revision"]
        return result

    def hierarchy(self):
        objects, parent = {}, None
        for kind in ("work", "episode", "scene", "sequence", "shot"):
            row = self.write("objects", {"kind": kind, "display_code": kind.upper(), "parent_id": parent})
            objects[kind] = parent = row["id"]
        return objects

    def upload(self, data=None, name='fixture.png'):
        uploaded = self.client.post(self.base + "/uploads", content=fixture_png() if data is None else data, headers={**self.headers, "X-Filename": name})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        return self.write("media", {"staged_upload": uploaded.json()["staged_upload"], "name": name, "rights": "owned",
            "rights_scope": {"purposes": ["first_frame"]}, "source": {"kind": "synthetic_test", "content": "test fixture source"}})["id"]

    def test_rejected_first_draft_revision_can_be_approved_from_panel(self):
        first = self.write("artifacts", {"artifact_key": "brief-revision", "artifact_type": "plain-spec", "document": "Initial draft"})
        self.write("artifact-decisions", {"artifact_id": first["id"], "outcome": "reject", "reason": "Please revise"})
        revised = self.write("artifacts", {"artifact_key": "brief-revision", "artifact_type": "plain-spec",
            "document": "Revised fixed content", "supersedes_id": first["id"]})
        self.write("artifact-decisions", {"artifact_id": revised["id"], "reason": "Approve the revision"})
        restored = self.client.get(self.base + "/artifacts/" + revised["id"]).json()
        self.assertTrue(restored["approved"])
        self.assertEqual(restored["supersedes_id"], first["id"])

    def test_upload_review_select_and_fixed_shot_context(self):
        objects = self.hierarchy()
        state = [{"scene_id": objects["scene"], "shot_id": objects["shot"], "entities": []}]
        artifact = self.write("artifacts", {"artifact_key": "shot-plan", "artifact_type": "shot-plan",
            "object_ids": [objects["shot"]], "document": {"state_versions": state}, "state_versions": state})
        self.write("artifact-decisions", {"artifact_id": artifact["id"], "reason": "synthetic fixture decision"})
        media = self.upload()
        candidate = self.write("binding-candidates", {"target_object_id": objects["shot"], "media_id": media, "role": "first_frame"})
        self.write("binding-decisions", {"candidate_id": candidate["candidate_id"], "reason": "incomplete"}, status=422)
        detail = self.client.get(self.base + "/media/" + media).json()
        self.assertEqual(detail["integrity"], "verified")
        self.write("media-checks", {"media_id": media, "checker": "fixture-ffprobe", "criteria_version": "1", "outcome": "pass", "report": detail["probe"]})
        self.write("reviews", {"candidate_id": candidate["candidate_id"], "outcome": "pass", "reviewer_type": "human", "reason": "synthetic fixture review"})
        decision = self.write("binding-decisions", {"candidate_id": candidate["candidate_id"], "reason": "synthetic fixture choice"})
        context = self.client.get(self.base + "/shots/" + objects["shot"] + "/context")
        self.assertEqual(context.status_code, 200, context.text)
        self.assertTrue(context.json()["ready"], context.text)
        self.assertEqual(context.json()["media"][0]["binding_decision_id"], decision["decision_id"])
        content = self.client.get(self.base + "/media/" + media + "/content", headers={"Range": "bytes=0-7"})
        self.assertEqual(content.status_code, 206)
        self.assertEqual(content.content, b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.client.get(self.base + "/media?object_id=" + objects["work"]).json()["total"], 1)

    def test_http_revision_conflict_and_project_media_isolation(self):
        objects = self.hierarchy()
        media = self.upload()
        self.write("binding-candidates", {"target_object_id": objects["shot"], "media_id": media, "role": "first_frame"}, status=409, revision=0)
        self.write("media-lifecycle-decisions", {"media_id": media, "reason": "synthetic fixture retirement"})
        self.assertEqual(self.client.get(self.base + "/media?status=deprecated").json()["total"], 1)
        self.assertEqual(self.client.get(self.base + "/media?status=active").json()["total"], 0)
        self.assertEqual(self.client.get(self.base + "/media/" + media + "/content").content, fixture_png())
        other = self.service.create_project({"name": "另一合成项目"}, actor="fixture-human")
        response = self.client.get("/api/v1/projects/" + other["id"] + "/media/" + media + "/content")
        self.assertEqual(response.status_code, 404)

    def test_durable_preview_worker_publishes_only_rendition_and_http_preview(self):
        from vsc.post.previews import PreviewWorker, RECIPE_VERSION
        media = self.upload()
        job = self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        result = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual((result["id"], result["status"]), (job["id"], "succeeded"))
        detail = self.client.get(self.base + "/media/" + media).json()
        self.assertEqual(len(detail["renditions"]), 1)
        self.assertEqual(detail["renditions"][0]["source_sha256"], detail["sha256"])
        self.assertEqual(detail["renditions"][0]["source_blob_id"], detail["blob_id"])
        self.assertEqual(detail["renditions"][0]["recipe_version"], RECIPE_VERSION)
        self.assertIn("ffmpeg version", detail["renditions"][0]["tool_version"])
        self.assertEqual(detail["decisions"], [])
        self.assertEqual(self.client.get(self.base + "/media").json()["total"], 1)
        response = self.client.get(self.base + "/media/" + media + "/preview?purpose=thumbnail")
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else "")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        jobs = self.client.get(self.base + "/preview-jobs?media_id=" + media).json()["items"]
        self.assertEqual(jobs[0]["status"], "succeeded")

    def test_expired_preview_lease_is_resumed_and_old_attempt_is_fenced(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import Conflict
        from vsc.post.previews import PreviewWorker, RECIPE_VERSION
        media = self.upload()
        self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        old = self.service.store.claim_preview_job(project_id=self.p)
        with self.engine.begin() as connection:
            connection.execute(update(S.preview_jobs).where(S.preview_jobs.c.project_id == self.p,
                S.preview_jobs.c.id == old["id"]).values(claim_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        resumed = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(resumed["status"], "succeeded")
        self.assertEqual(resumed["attempt"], old["attempt"] + 1)
        with self.assertRaises(Conflict) as conflict:
            self.service.store.finish_preview_job(self.p, old["id"], old["attempt"], {})
        self.assertEqual(conflict.exception.code, "preview_attempt_conflict")
        self.assertEqual(self.service.list_preview_jobs(self.p)["items"][0]["status"], "succeeded")

    def test_failed_preview_requires_explicit_retry_and_keeps_source(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.post.previews import PreviewConverter, PreviewWorker, RECIPE_VERSION
        class MissingConverter(PreviewConverter):
            def convert(self, *args, **kw):
                raise ResourceError("fixture conversion unavailable", "preview_tool_unavailable")
        media = self.upload()
        job = self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        failed = PreviewWorker(self.service.store, self.storage, converter=MissingConverter()).run_once(project_id=self.p)
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p))
        self.revision = failed["revision"]
        self.write("preview-retries", {"job_id": job["id"]})
        retried = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(retried["status"], "succeeded")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(self.client.get(self.base + "/media/" + media + "/content").content, fixture_png())

    def test_preview_provenance_survives_identical_byte_deduplication(self):
        import hashlib
        from pathlib import Path
        from vsc.post.previews import PreviewConverter, PreviewWorker, RECIPE_VERSION
        root = Path(self.temp.name)
        source = root / "source.png"
        raw = fixture_png()
        source.write_bytes(raw)
        canonical, _ = PreviewConverter().convert(source, {"modality": "image", "sha256": hashlib.sha256(raw).hexdigest()}, "thumbnail", root)
        media = self.upload(canonical.read_bytes())
        self.write("preview-jobs", {"media_id": media, "purpose": "thumbnail", "recipe_version": RECIPE_VERSION})
        result = PreviewWorker(self.service.store, self.storage).run_once(project_id=self.p)
        self.assertEqual(result["status"], "succeeded")
        detail = self.client.get(self.base + "/media/" + media).json()
        rendition = detail["renditions"][0]
        self.assertEqual(rendition["sha256"], detail["sha256"])
        self.assertEqual(rendition["blob_id"], rendition["source_blob_id"])
        self.assertIn("ffmpeg version", rendition["tool_version"])
        self.assertNotIn("preview", detail["probe"])

    def test_registration_retry_keeps_same_media_and_revision_after_staging_move(self):
        uploaded = self.client.post(self.base + "/uploads", content=fixture_png(), headers={**self.headers, "X-Filename": "fixture.png"}).json()
        payload = {"staged_upload": uploaded["staged_upload"], "rights": "unknown", "source": {"kind": "synthetic_test", "content": "test-only upload source"}}
        first = self.write("media", payload, key="same-upload-once")
        repeated = self.write("media", payload, revision=0, key="same-upload-once")
        self.assertEqual(first, repeated)
        self.assertEqual(self.client.get(self.base + "/media").json()["total"], 1)

    def test_project_media_catalog_pages_original_cross_episode_references_and_filters(self):
        from sqlalchemy import event
        objects = self.hierarchy()
        second = self.write('objects', dict(kind='episode', display_code='EP2', parent_id=objects['work'], ordinal=1))['id']
        first_media, second_media = self.upload(), self.upload()
        self.write('binding-candidates', dict(target_object_id=objects['shot'], media_id=first_media, role='first_frame'))
        self.write('episode-assets', dict(episode_id=second, base_revision=0, asset_key='cross-episode', name='跨集固定引用',
            asset_kind='character', forms=[dict(form_key='master', name='日常', base_version_id=None,
                source_asset_id=None, spec_id=None, media_id=first_media)]))
        canvas = self.write('creative-canvases', dict(title='分集画布来源', episode_id=second,
            document=dict(nodes=[dict(id='media', type='image', title='画布原图', media_id=second_media, x=0, y=0)], edges=[])))
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(self.engine, 'before_cursor_execute', capture)
        try:
            first_page = self.client.get('/api/v1/project-media', params=dict(project_id=self.p, limit=1, order='created_desc'))
        finally:
            event.remove(self.engine, 'before_cursor_execute', capture)
        self.assertEqual(first_page.status_code, 200, first_page.text)
        first_page = first_page.json()
        self.assertEqual((first_page['total'], len(first_page['items']), first_page['next_offset']), (2, 1, 1))
        next_page = self.client.get('/api/v1/project-media', params=dict(project_id=self.p, limit=1, offset=1)).json()
        self.assertIsNone(next_page['next_offset'])
        self.assertNotEqual(first_page['items'][0]['id'], next_page['items'][0]['id'])
        self.assertTrue(any('LIMIT' in sql and 'OFFSET' in sql for sql in statements))
        self.assertFalse(any(sql.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for sql in statements))
        rows = self.client.get('/api/v1/project-media', params=dict(project_id=self.p, order='updated_desc')).json()['items']
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id[first_media]['episode_count'], 2)
        self.assertIsNone(by_id[first_media]['episode_id'])
        self.assertEqual(by_id[second_media]['episode_id'], second)
        self.assertIn(canvas['id'], by_id[second_media]['source_href'])
        self.assertIsNone(by_id[first_media]['reuse_href'])
        self.assertIsNone(by_id[first_media]['source_job_id'])
        self.assertEqual(self.client.get(by_id[first_media]['content_url']).content, fixture_png())
        scoped = self.client.get('/api/v1/project-media', params=dict(project_id=self.p, episode_id=objects['episode'])).json()
        self.assertEqual([row['id'] for row in scoped['items']], [first_media])
        self.assertEqual(scoped['items'][0]['episode_id'], objects['episode'])
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p, episode_id=second)).json()['total'], 2)
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p, modality='video')).json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p, query='%')).json()['total'], 0)
        now = datetime.now(timezone.utc)
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p,
            created_after=(now-timedelta(hours=1)).isoformat(), created_before=(now+timedelta(hours=1)).isoformat())).json()['total'], 2)
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p,
            created_after=(now+timedelta(days=1)).isoformat())).json()['total'], 0)
        free_media = self.upload()
        self.write('recycle-actions', dict(action='trash', media_ids=[free_media], reason='隔离目录回收测试'))
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).json()['total'], 2)
        self.write('recycle-actions', dict(action='restore', media_ids=[free_media], reason='恢复原登记'))
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).json()['total'], 3)
        for filters in (dict(limit=101), dict(offset=-1), dict(order='name'), dict(modality='unknown'),
                        dict(created_after='2026-01-01T00:00:00'), dict(created_after='bad'),
                        dict(created_after='2026-03-02', created_before='2026-03-01')):
            with self.subTest(filters=filters):
                response = self.client.get('/api/v1/project-media', params=filters)
                self.assertEqual(response.status_code, 422, response.text)

    def test_project_media_catalog_enforces_full_project_read_and_active_state(self):
        import io
        from sqlalchemy import insert, update
        from vsc.adapters.persistence.postgres import schema as S
        marker = 'catalog-acl-'+uuid.uuid4().hex
        media = self.upload(name=marker)
        identity = self.service.ensure_local_access('fixture-human')['identity_id']
        owner, studio, child = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_identities).values(id=owner, subject_key='remote:'+owner, actor='private-'+owner,
                display_name='未授权成员', preferences={}, active=True))
            conn.execute(insert(S.access_workspaces).values(id=studio, name='私有父工作室', kind='studio', created_by=owner))
            conn.execute(insert(S.access_workspaces).values(id=child, name='私有子工作室', kind='substudio', parent_id=studio, created_by=owner))
            conn.execute(insert(S.access_projects).values(project_id=self.p, workspace_id=child, assigned_by=owner, review_lanes=[]))
        self.assertNotIn(media, {row['id'] for row in self.client.get('/api/v1/project-media').json()['items']})
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).status_code, 403)
        other = self.service.create_project({'name':'目录另一个可读项目'},actor='fixture-human')['id']
        staged = self.storage.stage_upload(io.BytesIO(fixture_png()),'other.png')
        other_media = self.service.register_media(other,dict(staged_upload=staged['staged_upload'],name=marker,
            rights='owned',source={'kind':'synthetic_test','content':'global page fixture'}),actor='fixture-human',
            expected_revision=0,idempotency_key=uuid.uuid4().hex)['id']
        only_other = self.client.get('/api/v1/project-media',params=dict(query=marker)).json()
        self.assertEqual([row['id'] for row in only_other['items']],[other_media])
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_project_members).values(project_id=self.p, identity_id=identity, role='viewer', active=True))
        visible = self.client.get('/api/v1/project-media', params=dict(project_id=self.p))
        self.assertEqual(visible.status_code, 200, visible.text)
        self.assertEqual([row['id'] for row in visible.json()['items']], [media])
        global_first = self.client.get('/api/v1/project-media',params=dict(query=marker,limit=1)).json()
        global_next = self.client.get('/api/v1/project-media',params=dict(query=marker,limit=1,offset=1)).json()
        self.assertEqual((global_first['total'],global_first['next_offset'],global_next['next_offset']),(2,1,None))
        self.assertEqual({global_first['items'][0]['id'],global_next['items'][0]['id']},{media,other_media})
        with self.engine.begin() as conn:
            conn.execute(update(S.access_project_members).where(S.access_project_members.c.project_id==self.p).values(active=False))
            conn.execute(insert(S.access_workspace_members).values(workspace_id=studio, identity_id=identity, role='viewer', active=True))
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).status_code, 403)
        with self.engine.begin() as conn:
            conn.execute(update(S.access_workspace_members).where(S.access_workspace_members.c.workspace_id==studio,
                S.access_workspace_members.c.identity_id==identity).values(role='owner'))
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).json()['total'], 1)
        trashed = self.client.post(self.base+'/management',headers=self.headers,json=dict(
            payload=dict(operation='trash',target_type='project',target_id=self.p,reason='目录活动项目测试'),
            expected_revision=self.revision,idempotency_key=uuid.uuid4().hex))
        self.assertEqual(trashed.status_code,200,trashed.text)
        self.assertEqual(self.client.get('/api/v1/project-media', params=dict(project_id=self.p)).json()['total'], 0)
        self.client.cookies.clear()
        anonymous = self.client.get('/api/v1/project-media',params=dict(query=marker))
        self.assertEqual(anonymous.status_code,200,anonymous.text)
        self.assertEqual(anonymous.json()['total'],0)

    def test_project_media_catalog_reuse_requires_original_fixed_job_configuration(self):
        import json
        from sqlalchemy import insert, func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import digest
        objects = self.hierarchy()
        original, legacy, uploaded = self.upload(), self.upload(), self.upload()
        provider, model = 'catalog-offline-'+uuid.uuid4().hex, str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name='无线上供应商', modality='image', base_url='https://example.invalid',
                auth_ref='none', enabled=False, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key='offline', modality='image',
                model_version='1', capabilities={}, default_params={}, cost_rule={}, enabled=False))
        document = dict(shot_id=objects['shot'], mode='image', purpose='image', model_id=model,
            prompt='固定原稿的完整提示词', duration_ms=5000, width=1024, height=1024, count=1, params={}, references=[])
        draft = self.write('classic-production/drafts', dict(document=document, base_draft_id=None))
        fixed = self.service.get_artifact_version(self.p, draft['id'])
        runs = [self.write('artifacts', dict(artifact_key='catalog-run-'+str(index), artifact_type='plain-spec',
            document={'workbench_draft':dict(id=draft['id'],sha256=fixed['sha256'])} if index==0 else {}))['id'] for index in range(2)]
        jobs = []
        with self.engine.begin() as conn:
            for index, medium in enumerate((original, legacy)):
                job = str(uuid.uuid4());jobs.append(job)
                request = {'prompt':'仅原生部分字段'}
                conn.execute(insert(S.generation_jobs).values(project_id=self.p,id=job,run_version_id=runs[index],shot_id=objects['shot'],
                    purpose='image',modality='image',candidate_no=0,provider_id=provider,model_id=model,model_version='1',
                    request_payload=request,request_sha256=digest(request),context_sha256='0'*64,idempotency_key='catalog-'+job,
                    status='succeeded',attempt=1))
                conn.execute(insert(S.job_outputs).values(project_id=self.p,id=str(uuid.uuid4()),job_id=job,media_id=medium,asset_type='image'))
        before = self.service.get_project(self.p)['revision']
        response = self.client.get('/api/v1/project-media', params=dict(project_id=self.p))
        self.assertEqual(response.status_code, 200, response.text)
        by_id = {row['id']:row for row in response.json()['items']}
        self.assertEqual(by_id[original]['source_job_id'], jobs[0])
        self.assertIn('reuse_media='+original, by_id[original]['reuse_href'])
        self.assertIn('kind=image', by_id[original]['reuse_href'])
        self.assertEqual(by_id[legacy]['source_job_id'], jobs[1])
        self.assertIsNone(by_id[legacy]['reuse_href'])
        self.assertIsNone(by_id[uploaded]['source_href'])
        self.assertIsNone(by_id[uploaded]['source_job_id'])
        config = self.client.get(self.base+'/classic-production/candidate-configuration',params=dict(shot_id=objects['shot'],media_id=original)).json()
        self.assertEqual(config['document']['prompt'], document['prompt'])
        self.assertEqual(config['configuration_source'], 'fixed_workbench_draft')
        self.assertEqual(self.service.get_project(self.p)['revision'], before)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).scalar_one(),2)
