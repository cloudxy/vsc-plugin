"""Real PG read projections for project cards and original recent objects."""
import tempfile
import unittest
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, set_principal, reset_principal


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class ProjectPresentationTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**owner)); self.addCleanup(reset_principal, token)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def canvas(self, episode, media=None, title='原画布'):
        return self.write('create_creative_canvas', dict(episode_id=episode, title=title,
            document={'nodes': [{'id': 'image', 'type': 'image', 'media_id': media}] if media else [], 'edges': []}))

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
