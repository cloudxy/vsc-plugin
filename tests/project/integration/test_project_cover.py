"""Real PostgreSQL cover history, controlled bytes and original HTTP upload consumers."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

import support.paths
from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, set_principal, reset_principal
from vsc.assets.resource_service import Conflict, ResourceError


def image_bytes():
    from PIL import Image
    data = BytesIO(); Image.new('RGB', (48, 32), (20, 80, 140)).save(data, 'PNG')
    return data.getvalue()


def migrate(conn, target, direction='upgrade'):
    from alembic import command
    from alembic.config import Config
    config = Config(str(ROOT/'migrations/postgres/alembic.ini')); config.attributes['connection'] = conn
    getattr(command, direction)(config, target)


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class ProjectCoverTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-project-cover-'); self.addCleanup(self.temp.cleanup)
        self.storage = self.service.storage = LocalStorage(Path(self.temp.name)/'media')
        self.owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**self.owner)); self.addCleanup(reset_principal, token)

    def image(self, title='封面.png'):
        data = image_bytes()
        staged = self.storage.stage_upload(BytesIO(data), title)
        return self.write('register_media', dict(staged_upload=staged['staged_upload'], name=title,
            rights='unknown', source=dict(kind='test-owned', content='isolated display-cover fixture')))['id']

    def raw_media(self, data, modality='image', declared_size=None):
        """Explicit legacy/fault fixture; consumption must verify bytes, not metadata alone."""
        digest = sha256(data).hexdigest(); key = 'fixture/'+digest
        path = self.storage.resolve(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        return self.write('register_media', dict(name='原登记', modality=modality, sha256=digest,
            size_bytes=len(data) if declared_size is None else declared_size,
            mime_type='image/png' if modality=='image' else 'video/mp4', storage='local', object_key=key,
            rights='unknown', source=dict(kind='test-fault-fixture', content='isolated legacy-byte validation')))['id']

    def cover(self, media_id, **kw):
        return self.write('set_project_cover', {'media_id':media_id}, **kw)

    def history(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(S.project_cover_versions).where(
                S.project_cover_versions.c.project_id==self.p).order_by(S.project_cover_versions.c.version)).mappings()]

    def app(self, actor='test-human'):
        from vsc.interfaces.web.app import create_app
        return create_app(dict(projects_root=self.temp.name, media_root=str(self.storage.root),
            allowed_hosts=['testserver'], allowed_origins=['http://testserver'], access_token='test-token',
            human_identity=actor, background_enabled=False), service=self.service)

    def login(self, client):
        result = client.post('/api/v1/session', json={'token':'test-token'}, headers={'Origin':'http://testserver'})
        self.assertEqual(result.status_code, 200, result.text)
        client.headers.update({'Origin':'http://testserver', 'X-CSRF-Token':result.json()['csrf_token']})

    def bind_project(self):
        preview = self.service.access_migration_preview(self.p, self.owner['workspace_id'])
        self.service.access_command('assign-project', dict(project_id=self.p, workspace_id=self.owner['workspace_id'],
            preview_sha256=preview['sha256']), expected_revision=self.service.access_snapshot()['access_revision'],
            idempotency_key=uuid.uuid4().hex, actor='test-human')

    def test_explicit_cover_survives_new_media_clear_restores_inference_and_history_is_fixed(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.project.resource_catalog import ResourceCatalog
        first = self.image(); initial = self.service.get_project_cover(self.p)
        self.assertIsNone(initial['selection']); self.assertEqual(initial['cover']['media_id'], first)
        profile = self.service.get_project(self.p)['profile_snapshot']
        chosen = self.cover(first)
        self.assertEqual(chosen['selection']['version'], 1)
        self.assertEqual(chosen['selection']['media_id'], first)
        second = self.image('更新但无关的素材.png')
        self.assertEqual(self.service.get_project_cover(self.p)['cover']['media_id'], first)
        catalog = ResourceCatalog(self.temp.name, self.service)
        card = next(r for r in catalog.list_projects()['items'] if r['id']==self.p)
        self.assertEqual(card['cover']['media_id'], first)
        cleared = self.cover(None)
        self.assertEqual(cleared['selection']['version'], 2)
        self.assertIsNone(cleared['selection']['media_id']); self.assertIsNone(cleared['selection']['blob_id'])
        self.assertIsNone(cleared['selection']['sha256']); self.assertEqual(cleared['cover']['media_id'], second)
        again = self.cover(first)
        self.assertEqual(again['selection']['version'], 3)
        rows = self.history()
        self.assertEqual(rows[0]['id'], chosen['selection']['id']); self.assertEqual(rows[0]['sha256'], chosen['selection']['sha256'])
        self.assertEqual(rows[0]['media_id'], first); self.assertIsNone(rows[1]['media_id'])
        self.assertEqual(self.service.get_project(self.p)['profile_snapshot'], profile)
        with self.engine.connect() as conn:
            rights = list(conn.execute(select(S.rights_decisions.c.outcome).where(S.rights_decisions.c.project_id==self.p)).scalars())
            self.assertEqual(rights, ['unknown', 'unknown'])
            for table in (S.binding_candidates, S.binding_decisions, S.current_bindings):
                self.assertEqual(conn.execute(select(func.count()).select_from(table).where(table.c.project_id==self.p)).scalar_one(), 0)
        self.service.storage = None
        self.assertIsNotNone(self.cover(None)['selection'])

    def test_replay_stale_revision_and_conflicting_key_do_not_append_or_decode_again(self):
        media = self.image(); before = self.rev; key = uuid.uuid4().hex
        chosen = self.cover(media, idempotency_key=key)
        self.service.storage = None
        replay = self.service.set_project_cover(self.p, {'media_id':media}, expected_revision=before, idempotency_key=key, actor='test-human')
        self.assertEqual(replay, chosen); self.assertEqual(len(self.history()), 1)
        with self.assertRaises(Conflict):
            self.service.set_project_cover(self.p, {'media_id':None}, expected_revision=before, idempotency_key=key, actor='test-human')
        with self.assertRaises(Conflict):
            self.service.set_project_cover(self.p, {'media_id':None}, expected_revision=before, idempotency_key=uuid.uuid4().hex, actor='test-human')
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.service.get_project(self.p)['revision'], chosen['revision'])

    def test_explicit_image_cover_is_not_hidden_by_automatic_depth_filter(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.project.resource_catalog import ResourceCatalog
        objects = self.hierarchy()
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']],
            {'state_versions':[{'scene_id':objects['scene']}]})
        automatic = self.image('默认项目图.png')
        depth = self.raw_media(image_bytes()+b'depth-output')
        provider = 'cover-depth-'+uuid.uuid4().hex; model = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider, name='isolated depth fixture', modality='image',
                base_url='https://example.invalid', auth_ref='none', enabled=True, rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model, provider_id=provider, model_key='depth',
                modality='image', model_version='1', capabilities={'purposes':['depth']},
                default_params={}, cost_rule={}, enabled=True))
        request = {'prompt':'isolated depth-image fixture', 'params':{}}
        run = self.production_run(objects['shot'], request, purpose='depth', modality='image')
        context = self.service.compile_shot_context(self.p, objects['shot'], purpose='depth')
        job = self.write('create_generation_job', dict(run_version_id=run, shot_id=objects['shot'], purpose='depth',
            modality='image', model_id=model, context_sha256=context['sha256'], request_payload=request))
        self.write('update_generation_job', dict(job_id=job['id'], status='submitted', external_task_id='fixture-depth'))
        self.write('update_generation_job', dict(job_id=job['id'], status='succeeded', outputs=[{'media_id':depth}]))
        self.assertEqual(self.service.get_project_cover(self.p)['cover']['media_id'], automatic)
        self.assertEqual(self.cover(depth)['cover']['media_id'], depth)
        self.assertEqual(self.service.get_project_cover(self.p)['cover']['media_id'], depth)
        card = next(r for r in ResourceCatalog(self.temp.name, self.service).list_projects()['items'] if r['id']==self.p)
        self.assertEqual(card['cover']['media_id'], depth)
        self.assertEqual(self.cover(None)['cover']['media_id'], automatic)

    def test_real_image_size_boundary_corrupt_missing_bytes_and_recycled_media_are_rejected(self):
        from vsc.assets.project_cover import MAX_COVER_BYTES
        base = image_bytes(); exact = self.raw_media(base+b'\0'*(MAX_COVER_BYTES-len(base)))
        self.assertEqual(self.cover(exact)['cover']['media_id'], exact)
        too_large = self.raw_media(base+b'\0'*(MAX_COVER_BYTES+1-len(base)))
        with self.assertRaises(ResourceError) as raised: self.cover(too_large)
        self.assertEqual(raised.exception.code, 'project_cover_too_large')
        corrupted = self.raw_media(b'\x89PNG\r\n\x1a\ntruncated')
        with self.assertRaises(ResourceError) as raised: self.cover(corrupted)
        self.assertEqual(raised.exception.code, 'project_cover_invalid_image')
        video = self.raw_media(b'video-registration', modality='video')
        with self.assertRaises(ResourceError) as raised: self.cover(video)
        self.assertEqual(raised.exception.code, 'project_cover_image_required')
        missing = self.image('字节消失.png')
        self.storage.resolve(self.service.get_media(self.p, missing)['locations'][0]['object_key']).unlink()
        with self.assertRaises(ResourceError) as raised: self.cover(missing)
        self.assertEqual(raised.exception.code, 'project_cover_media_unavailable')
        recycled = self.raw_media(image_bytes()+b'old-file')
        result = self.write('recycle_media', dict(media_ids=[recycled], action='trash', reason='封面设置前回收'))
        self.assertEqual(result['items'][0]['status'], 'trashed')
        with self.assertRaises(ResourceError) as raised: self.cover(recycled)
        self.assertEqual(raised.exception.code, 'project_cover_media_unavailable')
        self.assertEqual(len(self.history()), 1)

    def test_typed_scope_seals_receipts_and_fixed_cover_prevents_recycle_and_purge(self):
        from sqlalchemy import insert, update, delete
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        media = self.image(); chosen = self.cover(media); table = S.project_cover_versions
        for statement in (update(table).where(table.c.project_id==self.p).values(created_by='forged'),
                          delete(table).where(table.c.project_id==self.p)):
            with self.assertRaises(IntegrityError), self.engine.begin() as conn: conn.execute(statement)
        row = dict(self.history()[0]); row.update(id=str(uuid.uuid4()), version=2, command_key='unrelated-command')
        self.write('create_object', dict(kind='work', display_code='UNRELATED'), idempotency_key='unrelated-command')
        with self.assertRaises(IntegrityError), self.engine.begin() as conn: conn.execute(insert(table).values(**row))
        other = self.service.create_project({'name':'其他项目'}, actor='test-human')['id']
        with self.assertRaises(ResourceError) as raised:
            self.service.set_project_cover(other, {'media_id':media}, expected_revision=0,
                idempotency_key='wrong-project-cover', actor='test-human')
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIsNone(self.service.get_project_cover(other)['selection'])
        for changed in (dict(row, project_id=other, version=1), dict(row, blob_id=str(uuid.uuid4())),
                        dict(row, sha256='0'*64), dict(row, version=4), dict(row, media_id=None)):
            with self.subTest(changed=tuple(changed[k] for k in ('project_id','version','media_id','blob_id','sha256'))):
                with self.assertRaises(IntegrityError), self.engine.begin() as conn: conn.execute(insert(table).values(**changed))
        preview = self.service.preview_media_recycle(self.p, [media])
        self.assertTrue(preview['items'][0]['protected'])
        self.assertIn('project_cover_versions', [r['code'] for r in preview['items'][0]['reasons']])
        result = self.write('recycle_media', dict(media_ids=[media], action='trash', reason='仍有固定封面'))
        self.assertEqual(result['items'][0]['status'], 'protected')
        self.cover(None)
        self.assertTrue(self.service.preview_media_recycle(self.p, [media])['items'][0]['protected'])
        self.write('management_command', dict(operation='trash', target_type='project', target_id=self.p, reason='准备永久停用'))
        protected = self.write('management_command', dict(operation='purge', target_type='project', target_id=self.p,
            confirm_name=self.project['name'], reason='固定封面历史仍存在'))
        self.assertEqual(protected['status'], 'protected'); self.assertEqual(protected['state'], 'trashed')
        self.assertEqual(self.history()[0]['id'], chosen['selection']['id'])

    def test_two_real_transactions_same_revision_choose_once_and_preserve_losing_input(self):
        from sqlalchemy import event, text
        media = self.image(); before = self.rev; entered = threading.Event(); release = threading.Event()
        second_started = threading.Event(); thread_state = threading.local(); second_pid = []
        def track_connection(conn, cursor, statement, parameters, context, many):
            if getattr(thread_state, 'key', None)=='parallel-second' and not second_pid:
                second_pid.append(conn.connection.driver_connection.info.backend_pid); second_started.set()
        event.listen(self.engine, 'before_cursor_execute', track_connection)
        self.addCleanup(event.remove, self.engine, 'before_cursor_execute', track_connection)
        original_check = self.service._check_project_cover_media
        def held_check(row):
            entered.set(); self.assertTrue(release.wait(10)); original_check(row)
        self.service._check_project_cover_media = held_check
        self.addCleanup(delattr, self.service, '_check_project_cover_media')
        def choose(key, value):
            thread_state.key = key
            token = set_principal(Principal(**self.owner))
            try:
                return self.service.set_project_cover(self.p, {'media_id':value}, expected_revision=before,
                    idempotency_key=key, actor='test-human')
            finally: reset_principal(token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(choose, 'parallel-first', media)
            self.assertTrue(entered.wait(10))
            loser = pool.submit(choose, 'parallel-second', None)
            try:
                self.assertTrue(second_started.wait(10)); blocked = False; deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    with self.engine.connect() as conn:
                        blocked = conn.execute(text('SELECT cardinality(pg_blocking_pids(:pid))>0'), {'pid':second_pid[0]}).scalar_one()
                    if blocked: break
                    time.sleep(0.01)
                self.assertTrue(blocked, 'second real transaction must wait on the original project lock')
            finally: release.set()
            first = winner.result(timeout=15)
            with self.assertRaises(Conflict): loser.result(timeout=15)
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(self.service.get_project_cover(self.p)['selection']['id'], first['selection']['id'])
        self.rev = first['revision']

    def test_http_original_upload_set_replay_reload_clear_and_nonmember_scope(self):
        from fastapi.testclient import TestClient
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        self.bind_project(); data = image_bytes(); base = '/api/v1/projects/'+self.p
        with TestClient(self.app()) as client:
            self.login(client)
            def post(path, payload, revision, key):
                result = client.post(base+path, json=dict(payload=payload, expected_revision=revision, idempotency_key=key))
                self.assertEqual(result.status_code, 200, result.text); return result.json()
            created = post('/media-imports', dict(title='项目封面', rights='unknown',
                files=[dict(filename='封面.png', size_bytes=len(data), sha256=sha256(data).hexdigest())]), self.rev, 'cover-import')
            batch_id = created['id']; detail = client.get(base+'/media-imports/'+batch_id).json()
            item = detail['items'][0]; upload = base+'/media-imports/'+batch_id+'/items/'+item['id']+'/upload?offset=0'
            first = client.put(upload, content=data); self.assertEqual(first.status_code, 200, first.text)
            repeated = client.put(upload, content=data); self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json()['uploaded_bytes'], len(data))
            detail = client.get(base+'/media-imports/'+batch_id).json()
            self.assertEqual(detail['items'][0]['uploaded_bytes'], len(data)); self.assertEqual(detail['items'][0]['status'], 'uploaded')
            process = dict(batch_id=batch_id, item_id=item['id'])
            registered = post('/media-imports/process', process, detail['revision'], 'cover-process')
            replay = post('/media-imports/process', process, detail['revision'], 'cover-process')
            self.assertEqual(replay, registered)
            chosen = post('/cover', {'media_id':registered['media_id']}, registered['revision'], 'cover-setting')
            self.assertEqual(post('/cover', {'media_id':registered['media_id']}, registered['revision'], 'cover-setting'), chosen)
            self.assertEqual(client.get(base+'/cover').json(), chosen)
            card = next(r for r in client.get('/api/v1/projects').json()['items'] if r['id']==self.p)
            self.assertEqual(card['cover']['media_id'], registered['media_id'])
            self.assertEqual(client.get(chosen['cover']['content_url']).content, data)
            fresh = ResourceService(PostgresResourceStore(engine=self.engine), storage=self.storage)
            self.assertEqual(fresh.get_project_cover(self.p), chosen)
            bad = client.post(base+'/cover', json=dict(payload={'media_id':None}, expected_revision=chosen['revision'],
                idempotency_key='forged-actor', actor='forged'))
            self.assertEqual(bad.status_code, 422)
            cleared = post('/cover', {'media_id':None}, chosen['revision'], 'cover-clear')
            self.assertIsNone(cleared['selection']['media_id']); self.assertEqual(cleared['cover']['media_id'], registered['media_id'])
        self.rev = cleared['revision']
        with TestClient(self.app('other-human')) as client:
            self.login(client)
            self.assertEqual(client.get(base+'/cover').status_code, 403)
            self.assertEqual(client.get(chosen['cover']['content_url']).status_code, 403)
            self.assertEqual(client.post(base+'/cover', json=dict(payload={'media_id':None},
                expected_revision=self.rev, idempotency_key='unauthorized')).status_code, 403)
        self.assertEqual(len(self.history()), 2)

    def test_populated_history_refuses_destructive_downgrade(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        media = self.image(); chosen = self.cover(media)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            migrate(conn, '0050_classic_frame_media', 'downgrade')
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(), S.SCHEMA_REVISION)
        self.assertEqual(self.service.get_project_cover(self.p)['selection']['id'], chosen['selection']['id'])


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class ProjectCoverMigrationTests(unittest.TestCase):
    def test_0050_to_0051_and_empty_downgrade_preserve_original_project_media_and_match_metadata(self):
        from sqlalchemy import inspect, text
        import json
        import subprocess
        import sys
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.adapters.persistence.postgres import schema as S
        with isolated_postgres(TEST_URL) as engine:
            service = ResourceService(PostgresResourceStore(engine=engine))
            project = service.create_project({'name':'0050保留项目'}, actor='test-human')
            data = image_bytes()
            service.register_media(project['id'], dict(name='0050原媒体', modality='image', sha256=sha256(data).hexdigest(),
                size_bytes=len(data), mime_type='image/png', storage='local', object_key='old/retained.png',
                rights='unknown', source=dict(kind='migration-fixture', content='pre-existing isolated media row')),
                expected_revision=0, idempotency_key='old-media', actor='test-human')
            # Populate common facts while the current writer's guard tables
            # exist, then exercise the actual populated 0050 -> head migration.
            with engine.begin() as conn: migrate(conn, '0050_classic_frame_media', 'downgrade')
            with engine.connect() as conn:
                self.assertFalse(inspect(conn).has_table('project_cover_versions'))
                before = conn.execute(text('SELECT id,name,profile_snapshot,revision FROM projects')).all()
                old_media = conn.execute(text('SELECT m.project_id,m.id,m.blob_id,m.name,b.sha256,b.size_bytes FROM media_items m JOIN media_blobs b ON b.id=m.blob_id')).all()
            with engine.begin() as conn: migrate(conn, 'head')
            with engine.connect() as conn:
                self.assertEqual(conn.execute(text('SELECT id,name,profile_snapshot,revision FROM projects')).all(), before)
                self.assertEqual(conn.execute(text('SELECT m.project_id,m.id,m.blob_id,m.name,b.sha256,b.size_bytes FROM media_items m JOIN media_blobs b ON b.id=m.blob_id')).all(), old_media)
                schema_name = conn.execute(text('SELECT current_schema()')).scalar_one()
                self.assertEqual(conn.execute(text('SELECT count(*) FROM project_cover_versions')).scalar_one(), 0)
                triggers = set(conn.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid='project_cover_versions'::regclass AND NOT tgisinternal")).scalars())
                self.assertEqual(triggers, {'immutable_record','project_cover_guard','project_cover_receipt_guard'})
            checked = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/project/schema.py'), 'check',
                '--database-env', 'VSC_TEST_DATABASE_URL', '--schema', schema_name], capture_output=True, text=True, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stdout+checked.stderr)
            self.assertTrue(json.loads(checked.stdout)['passed'])
            projection = service.get_project_cover(project['id'])
            self.assertIsNone(projection['selection']); self.assertEqual(projection['cover']['media_id'], str(old_media[0].id))
