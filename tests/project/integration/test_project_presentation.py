"""Real PG read projections for project cards and original recent objects."""
import tempfile
import unittest
import uuid
from urllib.parse import parse_qs, urlsplit
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, set_principal, reset_principal


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class ProjectPresentationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**self.owner)); self.addCleanup(reset_principal, token)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def canvas(self, episode, media=None, title='原画布'):
        return self.write('create_creative_canvas', dict(episode_id=episode, title=title,
            document={'nodes': [{'id': 'image', 'type': 'image', 'media_id': media}] if media else [], 'edges': []}))

    def draft(self, shot, mode='single', media=None, base=None, prompt='固定草稿'):
        document = dict(shot_id=shot, mode=mode, prompt=prompt,
            references=[dict(role='reference_image' if mode=='image' else 'first_frame', media_id=media)] if media else [])
        return self.write('save_classic_draft', dict(document=document, base_draft_id=base))

    def episode(self, work, ordinal):
        parent = work; result = {}
        for kind in ('episode', 'scene', 'sequence', 'shot'):
            row = self.write('create_object', dict(kind=kind, parent_id=parent,
                display_code=kind.upper()+'-'+str(ordinal), title='第'+str(ordinal+1)+'集 '+kind,
                ordinal=ordinal if kind=='episode' else 0))
            result[kind] = parent = row['id']
        return result

    def recent(self, limit=24):
        from vsc.adapters.persistence.postgres.discovery import discover
        return [r for r in discover(self.store, limit=limit)['recent'] if r['project_id']==self.p]

    def app(self, actor='test-human'):
        from vsc.interfaces.web.app import create_app
        return create_app(dict(projects_root=self.temp.name, allowed_hosts=['testserver'],
            allowed_origins=['http://testserver'], access_token='local-secret', human_identity=actor,
            background_enabled=False), service=self.service)

    def login(self, client):
        response = client.post('/api/v1/session', json={'token':'local-secret'}, headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({'Origin':'http://testserver', 'X-CSRF-Token':response.json()['csrf_token']})

    def test_project_cards_use_original_counts_and_media_and_keep_unknown_type_empty(self):
        from vsc.project.resource_catalog import ResourceCatalog
        from vsc.adapters.persistence.postgres.project_presentation import project_cards
        objects = self.hierarchy(); media = self.media('真实项目预览'); self.canvas(objects['episode'], media)
        catalog = ResourceCatalog(self.temp.name, self.service)
        row = next(r for r in catalog.list_projects()['items'] if r['id'] == self.p)
        self.assertEqual(row['counts'], {'episodes': 1, 'images': 1, 'videos': 0, 'canvases': 1})
        self.assertEqual(row['cover']['media_id'], media); self.assertIsNone(row['project_type'])
        self.write('management_command', dict(operation='rename', title='已改名作品'))
        self.assertEqual(next(r for r in catalog.list_projects()['items'] if r['id']==self.p)['name'], '已改名作品')
        empty = self.service.create_project({'name': '空作品', 'profile_snapshot': {'profile_id':'vsc.light-short','version':'1','stages':[]}}, actor='test-human')
        row = next(r for r in catalog.list_projects()['items'] if r['id'] == empty['id'])
        self.assertIsNone(row['cover']); self.assertEqual(row['counts']['episodes'], 0); self.assertEqual(row['project_type'], '短视频')
        legacy = {'id': 'legacy', 'storage_policy':'legacy-json', 'name':'旧作品'}
        self.assertEqual(project_cards(self.store, [legacy]), [legacy])

    def test_recent_canvas_and_edit_have_own_cover_episode_and_restore_links(self):
        from vsc.adapters.persistence.postgres.discovery import discover
        objects = self.hierarchy(); cover = self.media('本对象封面')
        canvas = self.canvas(objects['episode'], cover, '应恢复原身份')
        unrelated = self.media('更新但无关封面')
        edit = {'format':'vsc.edit-workspace/v1','width':128,'height':128,'fps':24,
            'clips':[{'id':'still','shot_id':objects['shot'],'media_id':cover,'in_frame':0,'out_frame':24}], 'audio':[], 'captions':[]}
        self.write('save_edit_workspace', dict(episode_id=objects['episode'], edit_revision=0, document=edit))
        recent = [r for r in discover(self.store)['recent'] if r['project_id']==self.p]
        self.assertEqual({r['kind'] for r in recent}, {'canvas', 'editing'})
        for row in recent:
            self.assertEqual(row['episode_id'], objects['episode']); self.assertIsNotNone(row['episode_name'])
            self.assertEqual(row['cover']['media_id'], cover); self.assertNotEqual(row['cover']['media_id'], unrelated)
            self.assertIn('episode='+objects['episode'], row['href']); self.assertTrue(row['kind_label'])
        self.assertIn('task_target='+canvas['id'], next(r for r in recent if r['kind']=='canvas')['href'])
        self.assertEqual(len(discover(self.store, limit=1)['recent']), 1)
        other = self.service.create_project({'name':'另一作品'}, actor='test-human')
        self.assertFalse(any(r['project_id']==other['id'] for r in recent))

    def test_classic_recent_uses_latest_modality_head_and_only_its_fixed_cover(self):
        objects = self.hierarchy(); first = self.media('旧草稿封面')
        old = self.draft(objects['shot'], media=first)
        original = self.service.get_artifact_version(self.p, old['id'])
        other_mode = self.draft(objects['shot'], mode='text')
        self.assertEqual(len(self.recent()), 1)
        self.assertEqual(self.recent()[0]['version_id'], other_mode['id'])
        self.assertIsNone(self.recent()[0]['cover'])
        cover = self.media('当前视频草稿封面')
        latest = self.draft(objects['shot'], media=cover, base=old['id'], prompt='已修改视频')
        image = self.draft(objects['shot'], mode='image', media=first)
        audio = self.draft(objects['shot'], mode='audio')
        unrelated = self.media('更新但未被草稿引用')
        revision = self.service.get_project(self.p)['revision']
        rows = self.recent()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['production_kind'] for r in rows}, {'image','video'})
        for row in rows:
            kind = row['production_kind']; expected = latest if kind=='video' else image
            self.assertEqual(row['kind'], 'classic'); self.assertEqual(row['version_id'], expected['id'])
            self.assertEqual(row['version'], expected['version']); self.assertEqual(row['sha256'], expected['sha256'])
            self.assertEqual(row['cover']['media_id'], cover if kind=='video' else first)
            self.assertNotEqual(row['cover']['media_id'], unrelated)
            params = parse_qs(urlsplit(row['href']).query)
            self.assertEqual(params, dict(page=['classic-production'], project=[self.p],
                scope=[objects['shot']], episode=[objects['episode']], kind=[kind],
                mode=['single' if kind=='video' else 'image']))
        self.assertEqual(self.service.get_project(self.p)['revision'], revision)
        preserved = self.service.get_artifact_version(self.p, old['id'])
        for key in ('id', 'artifact_key', 'version', 'sha256', 'document', 'supersedes_id'):
            self.assertEqual(preserved[key], original[key])
        options = self.service.classic_production_options(self.p, objects['shot'])
        self.assertEqual({r['id'] for r in options['drafts']}, {latest['id'], other_mode['id'], image['id'], audio['id']})
        self.assertEqual(next(r for r in options['drafts'] if r['id']==latest['id'])['document']['prompt'], '已修改视频')

    def test_classic_recent_groups_shots_by_episode_before_limiting_and_honors_hidden_scopes(self):
        objects = self.hierarchy(); second = self.episode(objects['work'], 1)
        first = self.draft(objects['shot'])
        for index in range(3):
            first = self.draft(objects['shot'], base=first['id'], prompt='版本'+str(index))
        later_shot = self.write('create_object', dict(kind='shot', parent_id=objects['sequence'],
            display_code='SHOT-2', title='同集后一个镜头', ordinal=1))['id']
        newest = self.draft(later_shot, mode='text')
        next_episode = self.draft(second['shot'])
        rows = self.recent(limit=2)
        self.assertEqual([r['version_id'] for r in rows], [next_episode['id'], newest['id']])
        self.assertEqual({r['episode_id'] for r in rows}, {objects['episode'], second['episode']})
        self.write('management_command', dict(operation='trash', target_type='object', target_id=later_shot, reason='隐藏单镜'))
        self.assertEqual({r['version_id'] for r in self.recent(limit=2)}, {first['id'], next_episode['id']})
        self.write('management_command', dict(operation='trash', target_type='object', target_id=second['episode'], reason='隐藏整集'))
        self.assertEqual([r['version_id'] for r in self.recent(limit=1)], [first['id']])
        self.write('management_command', dict(operation='trash', target_type='project', target_id=self.p, reason='隐藏项目'))
        self.assertEqual(self.recent(), [])
        self.write('management_command', dict(operation='restore', target_type='project', target_id=self.p, reason='恢复项目'))
        self.assertEqual([r['version_id'] for r in self.recent()], [first['id']])

    def test_classic_recent_http_consumer_restores_same_episode_mode_and_respects_acl(self):
        from fastapi.testclient import TestClient
        objects = self.hierarchy(); media = self.media('固定引用封面')
        draft = self.draft(objects['shot'], mode='first_last', media=media)
        image = self.draft(objects['shot'], mode='image', media=media)
        preview = self.service.access_migration_preview(self.p, self.owner['workspace_id'])
        self.service.access_command('assign-project', dict(project_id=self.p, workspace_id=self.owner['workspace_id'],
            preview_sha256=preview['sha256']), expected_revision=self.service.access_snapshot()['access_revision'],
            idempotency_key=uuid.uuid4().hex, actor='test-human')
        with TestClient(self.app()) as client:
            self.login(client)
            response = client.get('/api/v1/discovery')
            self.assertEqual(response.status_code, 200, response.text)
            rows = [r for r in response.json()['recent'] if r['project_id']==self.p]
            self.assertEqual(len(rows), 2)
            for row in rows:
                kind = row['production_kind']; expected = draft if kind=='video' else image
                self.assertEqual(row['version_id'], expected['id']); self.assertEqual(row['cover']['media_id'], media)
                params = parse_qs(urlsplit(row['href']).query)
                self.assertEqual(client.get(row['href']).status_code, 200)
                listing = client.get('/api/v1/projects/'+self.p+'/workbench',
                    params={'section':'shots', 'object_id':params['scope'][0], 'limit':100})
                self.assertEqual(listing.status_code, 200, listing.text)
                self.assertEqual(listing.json()['scope']['id'], objects['shot'])
                self.assertIn(objects['episode'], [r['id'] for r in listing.json()['ancestors']])
                options = client.get('/api/v1/projects/'+self.p+'/classic-production', params={'shot_id':params['scope'][0]})
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual(params['episode'], [objects['episode']]); self.assertEqual(params['kind'], [kind])
                self.assertEqual(params['mode'], ['first_last' if kind=='video' else 'image'])
                self.assertEqual(next(r for r in options.json()['drafts'] if r['document']['mode']==params['mode'][0])['id'], expected['id'])
        with TestClient(self.app('other-human')) as client:
            self.login(client)
            response = client.get('/api/v1/discovery')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(self.p, [r['project_id'] for r in response.json()['recent']])
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/classic-production', params={'shot_id':objects['shot']}).status_code, 403)
            self.assertEqual(client.get(row['cover']['content_url']).status_code, 403)
