"""Real PostgreSQL canvas directory, permissions, bounded paging and HTTP reads."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import secrets
import tempfile
import time
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, current_principal, set_principal, reset_principal
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class CanvasLibraryTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-canvas-library-')
        self.addCleanup(self.temp.cleanup)
        self.service.storage = LocalStorage(self.temp.name)
        self.owner = self.service.ensure_local_access('test-human')
        self.token = set_principal(Principal(**self.owner))
        self.addCleanup(reset_principal, self.token)
        self.bind(self.p)
        self.marker = 'library-' + uuid.uuid4().hex

    def bind(self, p):
        preview = self.service.access_migration_preview(p, self.owner['workspace_id'])
        self.service.access_command('assign-project', dict(project_id=p, workspace_id=self.owner['workspace_id'],
            preview_sha256=preview['sha256']), actor='test-human',
            expected_revision=self.service.access_snapshot()['access_revision'], idempotency_key=uuid.uuid4().hex)

    def project_for_test(self):
        p = self.service.create_project({'name': 'Canvas library fixture'}, actor='test-human')['id']
        self.bind(p)
        return p

    def member(self, role, projects=None):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        identifier = str(uuid.uuid4())
        actor = 'member:' + identifier
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_identities).values(id=identifier, subject_key='remote:' + identifier,
                actor=actor, display_name='Same visible name', preferences={}, active=True))
            for p in projects or [self.p]:
                conn.execute(insert(S.access_project_members).values(project_id=p, identity_id=identifier,
                    role=role, active=True))
        return dict(identity_id=identifier, actor=actor)

    @contextmanager
    def as_member(self, member):
        token = set_principal(Principal(**member))
        try:
            yield
        finally:
            reset_principal(token)

    def canvas(self, p=None, **payload):
        p = p or self.p
        row = self.service.create_creative_canvas(p, dict({'title':self.marker, 'document':{'nodes': [], 'edges': []}}, **payload),
            actor=current_principal().actor, expected_revision=self.service.get_project(p)['revision'], idempotency_key=uuid.uuid4().hex)
        if p == self.p:
            self.rev = row['revision']
        return row

    def test_creator_permissions_filters_and_complete_options(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        editor, viewer = self.member('editor'), self.member('viewer')
        owned = self.canvas()
        with self.as_member(editor):
            authored = self.canvas()
        hidden = self.project_for_test()
        secret = self.canvas(hidden)
        with self.engine.begin() as conn:
            conn.execute(update(S.access_identities).where(S.access_identities.c.id == self.owner['identity_id']).values(display_name='Same visible name'))
        with self.as_member(editor):
            mine = self.service.list_canvas_library(project_id=self.p)
            self.assertEqual([r['id'] for r in mine['items']], [authored['id']])
            self.assertEqual(mine['items'][0]['creator_id'], editor['actor'])
            self.assertEqual(mine['items'][0]['creator_name'], 'Same visible name')
            page = self.service.list_canvas_library(creator_filter='all', query=self.marker, limit=1)
            self.assertEqual(page['total'], 2)
            self.assertEqual(page['next_offset'], 1)
            self.assertEqual(page['capabilities']['collaboration'], True)
            first_row = page['items'][0]
            self.assertEqual(first_row['id'], authored['id'])
            self.assertEqual(first_row['permissions'], dict(can_read=True, can_edit=True, can_rename=True, can_copy=True,
                can_delete=False, can_manage_collaboration=True))
            following = self.service.list_canvas_library(creator_filter='all', query=self.marker, limit=1, offset=1)
            self.assertEqual({page['items'][0]['id'], following['items'][0]['id']}, {owned['id'], authored['id']})
            self.assertEqual(following['items'][0]['permissions'], dict(can_read=True, can_edit=False, can_rename=False, can_copy=True,
                can_delete=False, can_manage_collaboration=False))
            self.assertIsNone(following['next_offset'])
            self.assertEqual(self.service.list_canvas_library(creator_filter='member', creator_id='test-human', query=self.marker)['items'][0]['id'], owned['id'])
            self.assertEqual([r['id'] for r in self.service.list_canvas_library(creator_filter='all', permission='view', query=self.marker)['items']], [owned['id']])
            self.assertEqual([r['id'] for r in self.service.list_canvas_library(creator_filter='all', permission='edit', query=self.marker)['items']], [authored['id']])
            options = self.service.canvas_library_options()
            self.assertNotIn(hidden, [r['id'] for r in options['projects']])
            self.assertEqual({r['id'] for r in options['creators']}, {'test-human', editor['actor']})
            self.assertTrue(next(r for r in options['projects'] if r['id'] == self.p)['permissions']['can_edit'])
            with self.assertRaises(ResourceError):
                self.service.list_canvas_library(project_id=hidden, creator_filter='all')
        toggled = self.service.set_canvas_collaboration(self.p, dict(canvas_id=owned['id'], collaboration_enabled=True),
            actor='test-human', expected_revision=self.service.get_project(self.p)['revision'], idempotency_key=uuid.uuid4().hex)
        self.rev = toggled['revision']
        with self.as_member(editor):
            self.assertEqual(self.service.list_canvas_library(creator_filter='all', permission='view', query=self.marker)['total'], 0)
            self.assertEqual(self.service.list_canvas_library(creator_filter='all', permission='edit', query=self.marker)['total'], 2)
            self.assertEqual([r['id'] for r in self.service.list_canvas_library(creator_filter='all', collaboration_only=True, query=self.marker)['items']], [owned['id']])
        with self.as_member(viewer):
            self.assertEqual(self.service.list_canvas_library(query=self.marker)['total'], 0)
            rows = self.service.list_canvas_library(creator_filter='all', permission='view', query=self.marker)['items']
            self.assertEqual({r['id'] for r in rows}, {owned['id'], authored['id']})
            self.assertTrue(all(not r['permissions']['can_edit'] and not r['permissions']['can_delete'] for r in rows))
            self.assertEqual(self.service.list_canvas_library(creator_filter='all', permission='edit', query=self.marker)['total'], 0)
            self.assertFalse(next(r for r in self.service.canvas_library_options()['projects'] if r['id'] == self.p)['permissions']['can_edit'])
        row = next(r for r in self.service.list_canvas_library(project_id=self.p, creator_filter='all')['items'] if r['id'] == owned['id'])
        self.assertTrue(row['permissions']['can_delete'])
        self.assertIs(row['collaboration_enabled'], True)

    def test_ancestor_recycle_fixed_current_version_and_cover(self):
        import io
        from support.fixtures.resources import png_bytes
        hierarchy = self.hierarchy()
        image = self.write('register_media', dict(staged_upload=self.service.storage.stage_upload(io.BytesIO(png_bytes()), 'cover.png')['staged_upload'],
            rights='owned', source={'kind': 'test-owned', 'content': 'synthetic image'}))['id']
        video = self.media('not a cover', modality='video')
        canvas = self.canvas(episode_id=hierarchy['episode'], document={'nodes': [dict(id='video', type='video', media_id=video),
            dict(id='image', type='image', media_id=image)], 'edges': []})
        def rows():
            return self.service.list_canvas_library(project_id=self.p, episode_id=hierarchy['episode'], creator_filter='all')['items']
        original = rows()[0]
        self.assertEqual(original['cover_url'], '/api/v1/projects/' + self.p + '/media/' + image + '/content')
        self.assertEqual(original['version_id'], canvas['version_id'])
        self.assertEqual(original['episode_name'], self.service.get_project_tree(self.p)['nodes'][1]['title'])
        for typ, identifier in [('canvas', canvas['id']), ('object', hierarchy['episode']), ('object', hierarchy['work']), ('project', self.p)]:
            self.write('management_command', dict(operation='trash', target_type=typ, target_id=identifier, reason='directory lifecycle'))
            self.assertEqual(rows(), [])
            self.write('management_command', dict(operation='restore', target_type=typ, target_id=identifier, reason='restore directory lifecycle'))
            self.assertEqual(rows()[0]['id'], canvas['id'])
        protected = self.write('recycle_media', dict(media_ids=[image], action='trash', reason='cover source hidden'))
        self.assertEqual(protected['items'][0]['status'], 'protected')
        self.assertEqual(rows()[0]['cover_url'], original['cover_url'])
        # A media item retired before being referenced remains a fixed history
        # reference, but cannot become a newly advertised library cover.
        retired = self.media('retired cover')
        recycled = self.write('recycle_media', dict(media_ids=[retired], action='trash', reason='retire before reference'))
        self.assertEqual(recycled['items'][0]['status'], 'trashed')
        retired_canvas = self.canvas(episode_id=hierarchy['episode'], document={
            'nodes': [dict(id='retired', type='image', media_id=retired)], 'edges': []})
        self.assertIsNone(next(row for row in rows() if row['id'] == retired_canvas['id'])['cover_url'])
        self.write('save_creative_canvas', dict(canvas_id=canvas['id'], canvas_revision=1, title='new current title', document={'nodes': [], 'edges': []}))
        updated = rows()[0]
        self.assertEqual(updated['canvas_revision'], 2)
        self.assertEqual(updated['title'], 'new current title')
        self.assertNotEqual(updated['version_id'], original['version_id'])
        self.assertIsNone(updated['cover_url'])

    def test_stable_order_search_validation_and_episode_scope(self):
        first = self.canvas(title='match_%\\literal')
        second = self.canvas(title='not wildcard')
        self.write('save_creative_canvas', dict(canvas_id=first['id'], canvas_revision=1,
            title='match_%\\literal', document={'nodes': [], 'edges': []}))
        desc = self.service.list_canvas_library(project_id=self.p, creator_filter='all')['items']
        asc = self.service.list_canvas_library(project_id=self.p, creator_filter='all', order='updated_asc')['items']
        self.assertEqual([r['id'] for r in desc], [first['id'], second['id']])
        self.assertEqual([r['id'] for r in asc], [second['id'], first['id']])
        self.assertEqual(self.service.list_canvas_library(project_id=self.p, creator_filter='all', query='_%\\')['items'][0]['id'], first['id'])
        def simultaneous(conn, project):
            ids = []
            for _ in range(2):
                saved = self.store.create_creative_canvas(self.p, dict(title='tie-' + self.marker, document={'nodes': [], 'edges': []}),
                    actor='test-human', expected_revision=project['revision'], idempotency_key='inner-fixture', _transaction=(conn, project))
                ids.append(saved['id'])
            return {'ids': ids}
        tied = self.store._mutate(self.p, 'create_canvas_library_fixture', {}, actor='test-human',
            expected_revision=self.rev, idempotency_key=uuid.uuid4().hex, callback=simultaneous)
        self.rev = tied['revision']
        for order in ('updated_desc', 'updated_asc'):
            page = self.service.list_canvas_library(project_id=self.p, creator_filter='all', query='tie-' + self.marker, order=order)['items']
            self.assertEqual(page[0]['updated_at'], page[1]['updated_at'])
            self.assertEqual([r['id'] for r in page], sorted(tied['ids']))
        for change in [{'creator_filter':'unknown'}, {'creator_filter':'member'}, {'creator_filter':'all','creator_id':'someone'},
                       {'permission':'owner'}, {'order':'created_desc'}, {'offset':-1}, {'offset':True}, {'limit':101}, {'query':'x'*201},
                       {'episode_id':str(uuid.uuid4())}, {'project_id':'not-uuid'}, {'creator_filter':'member','creator_id':'\x00'}]:
            with self.subTest(change=change), self.assertRaises(ResourceError):
                self.service.list_canvas_library(**change)
        hierarchy = self.hierarchy()
        other = self.project_for_test()
        with self.assertRaises(ResourceError):
            self.service.list_canvas_library(project_id=other, episode_id=hierarchy['episode'], creator_filter='all')
        self.assertEqual(self.service.list_canvas_library(project_id=self.p, creator_filter='all', offset=999)['items'], [])

    def test_http_options_etag_and_real_image_cover(self):
        import io
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        from support.fixtures.resources import png_bytes
        raw = png_bytes()
        image = self.write('register_media', dict(staged_upload=self.service.storage.stage_upload(io.BytesIO(raw), 'http-cover.png')['staged_upload'],
            rights='owned', source={'kind':'test-owned','content':'synthetic HTTP cover'}))['id']
        canvas = self.canvas(document={'nodes':[dict(id='image',type='image',media_id=image)],'edges':[]})
        app = create_app(dict(allowed_hosts=['testserver'], allowed_origins=['http://testserver'], access_token='fixture-token',
            human_identity='test-human', background_enabled=False), catalog=ResourceCatalog(self.temp.name, self.service, media_root=self.temp.name), service=self.service)
        with TestClient(app) as client:
            anonymous = client.get('/api/v1/canvas-library/options')
            self.assertEqual(anonymous.status_code, 200)
            self.assertNotIn(self.p, [r['id'] for r in anonymous.json()['projects']])
            response = client.post('/api/v1/session', json={'token':'fixture-token'}, headers={'Origin':'http://testserver'})
            self.assertEqual(response.status_code, 200, response.text)
            path = '/api/v1/canvas-library?project_id=' + self.p
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['items'][0]['id'], canvas['id'])
            cover = client.get(response.json()['items'][0]['cover_url'])
            self.assertEqual(cover.status_code, 200, cover.text)
            self.assertEqual(cover.content, raw)
            self.assertEqual(client.get(path, headers={'If-None-Match':response.headers['etag']}).status_code, 304)
            self.assertEqual(client.get(path + '&limit=101').status_code, 422)
            options = client.get('/api/v1/canvas-library/options')
            self.assertEqual(options.status_code, 200, options.text)
            self.assertTrue(next(r for r in options.json()['projects'] if r['id'] == self.p)['permissions']['can_edit'])

    def test_share_and_api_key_never_expand_canvas_directory(self):
        canvas = self.canvas()
        secret = secrets.token_urlsafe(32)
        self.service.access_command('share', dict(project_id=self.p, canvas_version_id=canvas['version_id'], mode='view', secret=secret,
            expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()), actor='test-human',
            expected_revision=self.service.access_snapshot()['access_revision'], idempotency_key=uuid.uuid4().hex)
        shared = self.service.authenticate_access(secret)
        with self.as_member(shared):
            self.assertEqual(self.service.list_canvas_library(creator_filter='all')['items'], [])
            self.assertEqual(self.service.canvas_library_options(), dict(projects=[], creators=[]))
        api_secret = secrets.token_urlsafe(32)
        self.write('issue_service_api_key', dict(name='directory-denied', secret=api_secret, capabilities=['read'],
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        key = self.service.authenticate_service_api_key(api_secret)
        token = set_principal(key)
        try:
            for call in (lambda: self.service.list_canvas_library(creator_filter='all'), self.service.canvas_library_options):
                with self.assertRaises(ResourceError) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'access_denied')
        finally:
            reset_principal(token)

    def test_unrelated_project_growth_keeps_authorized_page_and_sql_bounded(self):
        from sqlalchemy import event
        viewer = self.member('viewer')
        expected = [self.canvas()['id'] for _ in range(3)]
        def grow(number):
            for _ in range(number):
                self.canvas(self.project_for_test())
        def measure():
            statements = []
            def capture(conn, cursor, statement, params, context, many):
                if statement.lstrip().upper().startswith(('SELECT','WITH')):
                    statements.append((statement, params, cursor.rowcount))
            with self.as_member(viewer):
                event.listen(self.engine, 'after_cursor_execute', capture)
                started = time.perf_counter()
                try:
                    page = self.service.list_canvas_library(creator_filter='all', query=self.marker, limit=2)
                finally:
                    elapsed = time.perf_counter()-started
                    event.remove(self.engine, 'after_cursor_execute', capture)
            self.assertEqual(page['total'], 3)
            self.assertEqual(len(page['items']), 2)
            self.assertTrue({r['id'] for r in page['items']} <= set(expected))
            page_sql = next((sql, params) for sql, params, _ in statements if ' AS canvas_revision' in sql and 'LIMIT' in sql)
            with self.engine.connect() as conn:
                plan = conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + page_sql[0], page_sql[1]).scalar_one()
            return dict(statement_count=len(statements), fetched_rows=sum(max(count,0) for _,_,count in statements),
                page_ids=[r['id'] for r in page['items']], total=page['total'], application_seconds=elapsed, plan=plan)
        grow(5)
        before = measure()
        grow(45)
        after = measure()
        self.assertEqual(before['statement_count'], after['statement_count'])
        self.assertEqual(before['fetched_rows'], after['fetched_rows'])
        self.assertEqual(before['page_ids'], after['page_ids'])
        Path('/private/tmp/vsc-canvas-library-scale.json').write_text(json.dumps(dict(
            conditions='Existing isolated PostgreSQL17.11, warm synthetic fixture, 3 authorized canvases, 5 to 50 unrelated projects, limit2. Query timing is not end-to-end latency.',
            before=before, after=after), ensure_ascii=False, indent=2, default=str))
