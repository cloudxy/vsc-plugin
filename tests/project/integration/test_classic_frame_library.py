"""Classic first and last frames consume a fixed image from another project."""
import hashlib
import struct
import tempfile
import unittest
import uuid
import zlib

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.resource_service import Conflict, ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class ClassicFrameLibraryTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        old = self.service.storage
        self.addCleanup(setattr, self.service, 'storage', old)
        self.service.storage = LocalStorage(self.directory.name)
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        self.bytes = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                      + chunk(b'IDAT', zlib.compress(b'\x00\x30\x60\x90')) + chunk(b'IEND', b''))
        key = 'synthetic/source.png'
        path = self.service.storage.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.bytes)
        self.media_id = self.write('register_media', dict(name='固定站位图', modality='image', sha256=hashlib.sha256(self.bytes).hexdigest(),
            size_bytes=len(self.bytes), mime_type='image/png', storage='local', object_key=key, rights='owned',
            source={'kind': 'test-owned', 'content': 'synthetic fixture'}))['id']
        self.write('record_media_check', dict(media_id=self.media_id, checker='fixture', criteria_version='1', outcome='pass'))
        self.asset = self.write('save_asset_card', dict(name='固定角色', asset_kind='character', base_revision=0,
            forms=[dict(form_key='master', name='默认', base_version_id=None, description='', media_id=self.media_id, voice_spec_id=None)]))
        self.target = self.service.create_project({'name': '目标经典视频'}, actor='test-human')['id']
        parent = None
        revision = 0
        objects = {}
        for kind in ('work', 'episode', 'scene', 'sequence', 'shot'):
            row = self.service.create_object(self.target, {'kind': kind, 'display_code': kind.upper(), 'parent_id': parent, 'ordinal': 0},
                expected_revision=revision, idempotency_key=uuid.uuid4().hex, actor='test-human')
            objects[kind] = row['id']
            revision = row['revision']
            parent = row['id']
        self.shot = objects['shot']
        self.target_rev = revision

    def form_source(self, media_id=None, form_id=None, asset_id=None):
        return dict(kind='asset_form', asset_id=asset_id or self.asset['id'],
                    form_version_id=form_id or self.asset['forms'][0]['version_id'], media_id=media_id or self.media_id)

    def command(self, source=None, role='first_frame', key=None, expected=None, shot=None):
        payload = dict(shot_id=shot or self.shot, role=role, source_project_id=self.p, source=source or self.form_source())
        result = self.service.import_classic_frame_media(self.target, payload, actor='test-human',
            expected_revision=self.target_rev if expected is None else expected, idempotency_key=key or uuid.uuid4().hex)
        self.target_rev = result['revision']
        return result

    def blocking_source(self):
        objects = self.hierarchy()
        candidate = self.write('propose_binding', dict(target_object_id=objects['shot'], media_id=self.media_id, role='first_frame', slot_key='station'))
        selection = self.write('save_working_selection', dict(shot_id=objects['shot'], output_kind='image', candidate_id=candidate['candidate_id'], base_version_id=None))
        flow = self.write('create_intelligent_workflow', dict(episode_id=objects['episode'], route='storyboard', script_text='固定剧本'))['id']
        current = self.service.get_intelligent_workflow(self.p, flow)
        state = current['state']
        state['units'] = [dict(unit_key='station', kind='blocking', title='站位', description='', duration_ms=5000,
            segments=[dict(start_ms=0, end_ms=5000, text='等待')], skip_reason='', lineart_purpose='none', shot_id=objects['shot'], spatial_version_id=None)]
        state['media'] = [dict(unit_key='station', purpose='blocking', media_id=self.media_id, decision_id=None,
            working_selection_version_id=selection['selection_version_id'], spatial_export_id=None)]
        change = dict(workflow_id=flow, base_version_id=current['version']['id'], state=state)
        saved = self.write('save_intelligent_workflow', dict(change, impact_sha256=self.service.preview_intelligent_change(self.p, change)['sha256']))
        return dict(kind='blocking', workflow_id=flow, version_id=saved['version_id'], episode_id=objects['episode'],
                    unit_key='station', media_id=self.media_id, spatial_export_id=None)

    def test_http_blocking_import_replay_content_and_rights(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.interfaces.web.app import create_app
        source = self.blocking_source()
        app = create_app({'projects_root': self.directory.name + '/projects', 'media_root': self.directory.name, 'allowed_hosts': ['testserver'],
            'allowed_origins': ['http://testserver'], 'human_identity': 'test-human', 'access_token': 'test-token', 'background_enabled': False}, service=self.service)
        with TestClient(app) as client:
            session = client.post('/api/v1/session', headers={'Origin': 'http://testserver'}, json={'token': 'test-token'}).json()
            headers = {'Origin': 'http://testserver', 'X-CSRF-Token': session['csrf_token']}
            path = '/api/v1/projects/' + self.target + '/classic-production/frame-media'
            request = {'payload': {'shot_id': self.shot, 'role': 'first_frame', 'source_project_id': self.p, 'source': source},
                       'expected_revision': self.target_rev, 'idempotency_key': 'same-request'}
            saved = client.post(path, headers=headers, json=request)
            self.assertEqual(saved.status_code, 200, saved.text)
            replay = client.post(path, headers=headers, json=request)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(saved.json(), replay.json())
            result = saved.json()
            self.assertEqual(result['role'], 'first_frame')
            self.assertEqual(result['modality'], 'image')
            self.assertEqual(result['source_media_id'], self.media_id)
            self.assertEqual(result['byte_check']['status'], 'verified')
            content = client.get('/api/v1/projects/' + self.target + '/media/' + result['media_id'] + '/content')
            self.assertEqual(content.status_code, 200, content.text)
            self.assertEqual(content.content, self.bytes)
        self.assertEqual(self.service.list_asset_cards(self.target)['total'], 0)
        with self.engine.connect() as conn:
            links = conn.execute(select(S.classic_frame_media_links).where(S.classic_frame_media_links.c.project_id == self.target)).mappings().all()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]['source_media_id'], self.media_id)
            self.assertEqual(links[0]['source_unit_key'], 'station')
            self.assertEqual(links[0]['role'], 'first_frame')
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id == self.target)), 1)
            _, gaps = self.store._usable(conn, self.target, result['media_id'], 'first_frame')
            self.assertNotIn('technical_check_missing', gaps)
        self.write('decide_rights', dict(media_id=self.media_id, outcome='revoked', reason='撤销测试来源'))
        with self.engine.connect() as conn:
            _, gaps = self.store._usable(conn, self.target, result['media_id'], 'first_frame')
            self.assertIn('copy_source_rights_restricted', gaps)

    def test_licensed_purpose_follows_the_frame_copy(self):
        origin = self.service.get_media(self.p, self.media_id)['sources'][0]['source_id']
        self.write('decide_rights', dict(media_id=self.media_id, outcome='licensed', source_id=origin,
            scope={'purposes': ['first_frame']}, reason='限定首帧测试'))
        result = self.command(key='licensed-frame')
        with self.engine.connect() as conn:
            _, allowed = self.store._usable(conn, self.target, result['media_id'], 'first_frame')
            _, other = self.store._usable(conn, self.target, result['media_id'], 'reference_image')
        self.assertNotIn('rights_scope_mismatch', allowed)
        self.assertIn('rights_scope_mismatch', other)

    def test_same_project_changed_source_and_missing_station_are_rejected(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        with self.assertRaises(ResourceError) as failure:
            self.service.import_classic_frame_media(self.p, dict(shot_id=self.shot, role='first_frame', source_project_id=self.p, source=self.form_source()),
                actor='test-human', expected_revision=self.rev, idempotency_key='same-project')
        self.assertEqual(failure.exception.code, 'invalid_classic_frame_reference')
        old = self.asset['forms'][0]['version_id']
        self.write('save_asset_card', dict(asset_id=self.asset['id'], name='新名称', asset_kind='character', base_revision=self.asset['asset_revision'],
            forms=[dict(form_key='master', name='默认', base_version_id=old, description='新版本', media_id=self.media_id, voice_spec_id=None)]))
        with self.assertRaises(Conflict) as changed:
            self.command(self.form_source(form_id=old), key='old-form')
        self.assertEqual(changed.exception.code, 'classic_frame_source_changed')
        missing = dict(kind='blocking', workflow_id=str(uuid.uuid4()), version_id=str(uuid.uuid4()), episode_id=str(uuid.uuid4()),
                       unit_key='missing', media_id=self.media_id, spatial_export_id=None)
        with self.assertRaises(Conflict) as station:
            self.command(missing, key='missing-station')
        self.assertEqual(station.exception.code, 'classic_frame_source_changed')
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.classic_frame_media_links).where(S.classic_frame_media_links.c.project_id == self.target)), 0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id == self.target)), 0)

    def test_invalid_bytes_roll_back_and_unavailable_storage_keeps_the_gap(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        path = self.service.storage.resolve('synthetic/source.png')
        for name, change in [('missing', lambda: path.unlink()), ('changed', lambda: path.write_bytes(b'changed'))]:
            with self.subTest(case=name):
                path.write_bytes(self.bytes)
                change()
                with self.assertRaises(ResourceError) as failure:
                    self.command(key='invalid-' + name)
                self.assertEqual(failure.exception.code, 'classic_frame_source_bytes_invalid')
                with self.engine.connect() as conn:
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id == self.target)), 0)
                    self.assertEqual(conn.scalar(select(func.count()).select_from(S.classic_frame_media_links).where(S.classic_frame_media_links.c.project_id == self.target)), 0)
        path.write_bytes(self.bytes)
        self.service.storage = None
        result = self.command(key='without-storage')
        self.assertEqual(result['byte_check'], {'checked': False, 'status': 'unavailable', 'reason': 'local_storage_unavailable'})
        with self.engine.connect() as conn:
            _, gaps = self.store._usable(conn, self.target, result['media_id'], 'first_frame')
        self.assertIn('technical_check_missing', gaps)

    def test_last_frame_import_can_be_saved_on_the_classic_draft(self):
        first = self.command(role='first_frame', key='first')
        last = self.command(role='last_frame', key='last')
        self.assertNotEqual(first['media_id'], last['media_id'])
        self.assertEqual(first['sha256'], last['sha256'])
        document = dict(shot_id=self.shot, mode='first_last', model_id='', purpose='', prompt='固定镜头',
                        duration_ms=5000, width=1080, height=1920, count=1, params={},
                        references=[{'role': 'first_frame', 'media_id': first['media_id'], 'sha256': first['sha256']},
                                    {'role': 'last_frame', 'media_id': last['media_id'], 'sha256': last['sha256']}])
        saved = self.service.save_classic_draft(self.target, {'document': document, 'base_draft_id': None},
            expected_revision=self.target_rev, idempotency_key='draft', actor='test-human')
        import json
        stored = json.loads(self.service.get_artifact_version(self.target, saved['id'])['document'])
        self.assertEqual([(row['role'], row['media_id']) for row in stored['references']],
                         [('first_frame', first['media_id']), ('last_frame', last['media_id'])])
        self.assertEqual(self.service.list_asset_cards(self.target)['total'], 0)

    def test_import_rejects_rights_that_cannot_fill_the_frame(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        origin = self.service.get_media(self.p, self.media_id)['sources'][0]['source_id']
        self.write('decide_rights', dict(media_id=self.media_id, outcome='licensed', source_id=origin,
            scope={'purposes': ['reference_image']}, reason='只允许参考图'))
        with self.assertRaises(ResourceError) as limited:
            self.command(key='reference-only')
        self.assertEqual(limited.exception.code, 'classic_frame_source_unavailable')
        self.assertIn('rights_scope_mismatch', str(limited.exception))
        unknown_key = 'synthetic/unknown.png'
        path = self.service.storage.resolve(unknown_key)
        path.write_bytes(self.bytes)
        unknown = self.write('register_media', dict(name='权利未定', modality='image', sha256=hashlib.sha256(b'unknown-frame').hexdigest(),
            size_bytes=len(self.bytes), mime_type='image/png', storage='local', object_key=unknown_key, rights='unknown',
            source={'kind': 'test-owned', 'content': 'unknown rights fixture'}))['id']
        card = self.write('save_asset_card', dict(name='未定素材', asset_kind='character', base_revision=0,
            forms=[dict(form_key='master', name='默认', base_version_id=None, description='', media_id=unknown, voice_spec_id=None)]))
        with self.assertRaises(ResourceError) as unsettled:
            self.command(self.form_source(unknown, card['forms'][0]['version_id'], card['id']), key='unknown-rights')
        self.assertEqual(unsettled.exception.code, 'classic_frame_source_unavailable')
        self.assertIn('rights_unknown', str(unsettled.exception))
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id == self.target)), 0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.classic_frame_media_links).where(S.classic_frame_media_links.c.project_id == self.target)), 0)

    def test_downgrade_refuses_while_a_frame_link_exists(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import func, select, text
        from sqlalchemy.exc import DBAPIError
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres import schema as S
        self.command(key='keep-link')
        config = Config(str(ROOT / 'migrations/postgres/alembic.ini'))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:
                config.attributes['connection'] = conn
                command.downgrade(config, '0049_canvas_project_media')
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')), S.SCHEMA_REVISION)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.classic_frame_media_links).where(
                S.classic_frame_media_links.c.project_id == self.target)), 1)
