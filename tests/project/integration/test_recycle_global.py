"""Bounded direct recycle listing and existing project access authority."""
import os
import tempfile
import unittest
import uuid

from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and HAS_DB_DEPS, 'requires isolated PostgreSQL')
class GlobalRecycleTests(ResourceStoreFixture, unittest.TestCase):
    def test_authorized_pagination_parent_blocking_and_original_receipts(self):
        from sqlalchemy import event, insert, select, update
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.access_control import Principal, set_principal, reset_principal
        from vsc.assets.resource_service import ResourceError

        objects = self.hierarchy()
        asset = self.write('create_object', {'kind': 'asset', 'asset_kind': 'character', 'display_code': 'A'})['id']
        video = self.media('video membership',modality='video')
        self.write('recycle_media',{'media_ids':[video],'action':'trash','reason':'synthetic'})
        for target in (objects['episode'], asset, objects['work']):
            self.write('management_command', {'operation': 'trash', 'target_type': 'object', 'target_id': target, 'reason': 'synthetic'})
        key = uuid.uuid4().hex
        self.write('management_command', {'operation': 'trash', 'target_type': 'project', 'target_id': self.p, 'reason': 'synthetic'}, idempotency_key=key)
        secret_project = self.service.create_project({'name': 'private synthetic'}, actor='test-human')['id']
        original_project, original_revision=self.p,self.rev
        self.p,self.rev=secret_project,0
        secret_video=self.media('secret video',modality='video')
        self.write('recycle_media',{'media_ids':[secret_video],'action':'trash','reason':'synthetic'})
        secret_revision=self.rev
        self.p,self.rev=original_project,original_revision
        self.service.management_command(secret_project, {'operation': 'trash', 'target_type': 'project', 'target_id': secret_project, 'reason': 'synthetic'}, actor='test-human', expected_revision=secret_revision, idempotency_key=uuid.uuid4().hex)
        identity, other, parent, child = [str(uuid.uuid4()) for _ in range(4)]
        with self.engine.begin() as conn:
            for identifier in (identity, other):
                conn.execute(insert(S.access_identities).values(id=identifier, subject_key='remote:'+identifier,
                    actor='actor:'+identifier, display_name='synthetic', preferences={}, active=True))
            conn.execute(insert(S.access_workspaces).values(id=parent, name='parent', kind='studio', created_by=other))
            conn.execute(insert(S.access_workspaces).values(id=child, name='child', kind='substudio', parent_id=parent, created_by=other))
            for p in (self.p, secret_project):
                conn.execute(insert(S.access_projects).values(project_id=p, workspace_id=child, assigned_by=other, review_lanes=[]))
            conn.execute(insert(S.access_project_members).values(project_id=self.p, identity_id=identity, role='viewer', active=True))
        token = set_principal(Principal(identity_id=identity, actor='actor:'+identity))
        try:
            statements = []
            def capture(conn, cursor, statement, parameters, context, many):
                statements.append(statement)
            event.listen(self.engine, 'before_cursor_execute', capture)
            try:
                seen, cursor = [], None
                while True:
                    page = self.service.management_recycle_items(limit=1, cursor=cursor)
                    seen.extend(page['items'])
                    cursor = page['next_cursor']
                    if cursor is None:
                        break
            finally:
                event.remove(self.engine, 'before_cursor_execute', capture)
            self.assertEqual({(r['kind'], r['target_id']) for r in seen}, {('project', self.p), ('episode', objects['episode']), ('asset', asset), ('video',video)})
            self.assertTrue(all(r['project_id'] == self.p and not r['can_restore'] for r in seen))
            episode = next(r for r in seen if r['kind'] == 'episode')
            self.assertTrue(episode['blocked_by_project'])
            self.assertTrue(episode['blocked_by_ancestor'])
            self.assertTrue(any('LIMIT' in sql and 'recycle_items' in sql for sql in statements))
            self.assertFalse(any(sql.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ')) for sql in statements))
            for kind in ('project', 'episode', 'asset', 'video'):
                self.assertEqual([r['kind'] for r in self.service.management_recycle_items(kind=kind)['items']], [kind])
            for kw in ({'kind': 'unknown'}, {'limit': 101}, {'cursor': 'bad'}):
                with self.assertRaises(ResourceError):
                    self.service.management_recycle_items(**kw)
            # Verify the reusable SQL authorization set against the authoritative per-project check.
            for membership in ('viewer', 'editor', 'owner', 'inactive', 'ancestor_viewer', 'ancestor_owner'):
                with self.engine.begin() as conn:
                    conn.execute(update(S.access_project_members).where(S.access_project_members.c.project_id == self.p,
                        S.access_project_members.c.identity_id == identity).values(active=membership in {'viewer','editor','owner'},
                            role=membership if membership in {'viewer','editor','owner'} else 'viewer'))
                    conn.execute(S.access_workspace_members.delete().where(S.access_workspace_members.c.workspace_id == parent,
                        S.access_workspace_members.c.identity_id == identity))
                    if membership.startswith('ancestor_'):
                        conn.execute(insert(S.access_workspace_members).values(workspace_id=parent, identity_id=identity,
                            role=membership.removeprefix('ancestor_'), active=True))
                with self.engine.connect() as conn:
                    sql_allowed = set(conn.execute(self.store._recycle_readable_projects(conn)).scalars())
                    checked = set()
                    for p in (self.p, secret_project):
                        try:
                            self.store._access_require(conn, p, 'read')
                            checked.add(p)
                        except ResourceError as exc:
                            self.assertEqual(exc.code, 'access_denied')
                    self.assertEqual(sql_allowed & {self.p, secret_project}, checked, membership)
                self.assertEqual({r['project_id'] for r in self.service.management_recycle_items()['items']}, checked, membership)
            # Parent owner can restore the project, but the old object state remains.
            result = self.service.management_command(self.p, {'operation':'restore', 'target_type':'project', 'target_id':self.p, 'reason':'synthetic restore'},
                actor='actor:'+identity, expected_revision=self.rev, idempotency_key=uuid.uuid4().hex)
            self.assertGreater(result['revision'], self.rev)
            rows = [r for r in self.service.management_recycle_items()['items'] if r['project_id'] == self.p]
            self.assertEqual({r['kind'] for r in rows}, {'episode', 'asset', 'video'})
            self.assertTrue(next(r for r in rows if r['kind'] == 'episode')['blocked_by_ancestor'])
            self.assertTrue(next(r for r in rows if r['kind'] == 'asset')['can_restore'])
            self.assertTrue(next(r for r in rows if r['kind'] == 'video')['can_restore'])
        finally:
            reset_principal(token)
        receipt = self.service.get_operation_receipt(self.p, key, actor='test-human')['response']
        self.assertEqual(receipt['state'], 'trashed')

    def test_recycled_video_uses_latest_record_and_original_restore(self):
        video=self.media('video',modality='video');image=self.media('image',modality='image')
        for mid in (video,image):
            self.write('recycle_media',{'media_ids':[mid],'action':'trash','reason':'synthetic'})
        listed=[row for row in self.service.management_recycle_items(kind='video')['items'] if row['project_id']==self.p]
        self.assertEqual([(item['target_type'],item['target_id']) for item in listed],[('media',video)])
        self.assertTrue(listed[0]['can_restore']);self.assertEqual(listed[0]['reason'],'synthetic')
        self.assertIn(video,[row['target_id'] for row in self.service.management_recycle_items()['items']])
        self.write('recycle_media',{'media_ids':[video],'action':'restore','reason':'synthetic restore'})
        self.assertFalse([row for row in self.service.management_recycle_items(kind='video')['items'] if row['project_id']==self.p])

    def test_http_requires_session_and_routes_filter(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        with tempfile.TemporaryDirectory() as root:
            app = create_app({'allowed_hosts':['testserver'], 'allowed_origins':['http://testserver'],
                'access_token':'test-token', 'human_identity':'browser-test'}, catalog=ResourceCatalog(root, self.service), service=self.service)
            with TestClient(app) as client:
                url = '/api/v1/project-management/recycle-items'
                self.assertEqual(client.get(url).status_code, 403)
                login = client.post('/api/v1/session', json={'token':'test-token'}, headers={'Origin':'http://testserver'})
                headers = {'X-CSRF-Token':login.json()['csrf_token'], 'Origin':'http://testserver'}
                response = client.get(url, headers=headers, params={'kind':'asset', 'limit':1})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['items'], [])

    def test_http_video_restore_uses_the_original_media_route(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        video=self.media('http video',modality='video')
        self.write('recycle_media',{'media_ids':[video],'action':'trash','reason':'synthetic'})
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],
                'access_token':'test-token','human_identity':'test-human'},catalog=ResourceCatalog(root,self.service),service=self.service)
            with TestClient(app) as client:
                login=client.post('/api/v1/session',json={'token':'test-token'},headers={'Origin':'http://testserver'})
                headers={'X-CSRF-Token':login.json()['csrf_token'],'Origin':'http://testserver'}
                before=client.get('/api/v1/project-management/recycle-items',headers=headers,params={'kind':'video'})
                self.assertEqual(before.status_code,200,before.text)
                self.assertIn(video,[row['target_id'] for row in before.json()['items']])
                body={'payload':{'media_ids':[video],'action':'restore','reason':'synthetic'},'confirmed':True,'expected_revision':self.rev,'idempotency_key':uuid.uuid4().hex}
                path='/api/v1/projects/'+self.p+'/recycle-actions'
                result=client.post(path,json=body,headers=headers);self.assertEqual(result.status_code,200,result.text)
                replay=client.post(path,json=body,headers=headers);self.assertEqual(replay.status_code,200,replay.text)
                self.assertEqual(replay.json(),result.json())
                after=client.get('/api/v1/project-management/recycle-items',headers=headers,params={'kind':'video'})
                self.assertNotIn(video,[row['target_id'] for row in after.json()['items']])
