"""Canonical professional sources through real PostgreSQL working consumers.

Only metadata reference media and the existing configured model fixture are
used. Preview never submits a provider request or approves a working source.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture
from vsc.assets.resource_service import ResourceError


ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(HAS_DB_DEPS and os.environ.get('VSC_TEST_DATABASE_URL'), 'requires isolated PostgreSQL')
class ProfessionalInputConsumerTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.production.resource_settings import PRESETS, ResourceSettings
        self.objects = self.hierarchy()
        self.target = self.write('create_object', dict(kind='shot', display_code='SHOT-TARGET',
            parent_id=self.objects['sequence'], ordinal=1))['id']
        for code, kind in (('主角', 'character'), ('信封', 'prop'), ('场景-客厅-v1', 'location')):
            self.write('create_object', dict(kind='asset', display_code=code, asset_kind=kind))
        episode = self.write('create_object', dict(kind='episode', display_code='EP-OTHER',
            parent_id=self.objects['work'], ordinal=1))['id']
        scene = self.write('create_object', dict(kind='scene', display_code='SCENE-OTHER',
            parent_id=episode, ordinal=0))['id']
        sequence = self.write('create_object', dict(kind='sequence', display_code='SEQUENCE-OTHER',
            parent_id=scene, ordinal=0))['id']
        shot = self.write('create_object', dict(kind='shot', display_code='SHOT-OTHER',
            parent_id=sequence, ordinal=0))['id']
        self.other = dict(episode=episode, scene=scene, sequence=sequence, shot=shot)
        preset = next(row for row in PRESETS if row['id'] == 'xai-grok-imagine-video')
        self.model = ResourceSettings(self.store).save({**{key: value for key, value in preset.items()
            if key not in {'id', 'label'}}, 'enabled': True,
            'model_version': 'isolated-canonical-professional-consumer'}, 'test-human')['id']
        media = self.media('canonical 专业正文消费者元数据首帧')
        self.document = dict(shot_id=self.target, mode='single', model_id=self.model,
            purpose='image_to_video', prompt='固定原始用户提示', duration_ms=5000,
            references=[dict(role='first_frame', media_id=media)])
        now = datetime.now(timezone.utc)
        self.policy = dict(version='bounded-v1', first_draft_due_at=(now + timedelta(minutes=10)).isoformat(),
            stop_submitting_at=(now + timedelta(minutes=30)).isoformat(), max_attempts_per_purpose=2,
            max_repair_rounds=1, authorization=dict(mode='new_batch', reason='隔离消费者预览，不调用供应商'))

    def template(self, name):
        return json.loads((ROOT / 'templates' / name).read_text())

    def register_state(self, key, *, other=False, missing_target=False):
        document = self.template('scene-state.json')
        document['project_id'] = self.p
        scene = document['scenes'][0]
        scene['id'] = 'SCENE-OTHER' if other else 'SCENE'
        scene['baseline']['lighting'] = '固定雨夜暖台灯基线'
        scene['shots'][0]['id'] = 'SHOT-OTHER' if other else 'SHOT'
        scene['shots'][0]['changes']['entities']['主角']['pose'] = '前镜抬头后目光停在门口'
        scene['shots'][1]['id'] = 'SHOT-TARGET'
        if other or missing_target:
            scene['shots'] = scene['shots'][:1]
        artifact = self.write('create_artifact', dict(artifact_key=key, artifact_type='vsc.scene_state',
            document=document, object_ids=[self.other['episode'] if other else self.objects['episode']]))
        return artifact

    def register_sources(self):
        state = self.register_state('canonical-state')
        other = self.register_state('canonical-other-state', other=True)
        links = self.template('sequence-links.json')
        links['project_id'] = self.p
        links['units'][0].update(id='EPISODE', entry_shot='SHOT', exit_shot='SHOT-TARGET',
            state_path='sources/current-scene-state.json', state_sha256=state['sha256'])
        links['units'][1].update(id='EP-OTHER', entry_shot='SHOT-OTHER', exit_shot='SHOT-OTHER',
            state_path='sources/next-scene-state.json', state_sha256=other['sha256'])
        links['links'][0].update({'from': 'EPISODE', 'to': 'EP-OTHER', 'purpose': '保留门响把本集悬念交到下一集'})
        links['links'][0]['narrative'].update(carry='门响后角色尚未开门', receive='下一集接住同一次敲门')
        links['links'][0]['audio'].update(strategy='L cut', description='门外三次敲击声跨集延续')
        bridge = self.write('create_artifact', dict(artifact_key='canonical-links', artifact_type='vsc.sequence_links',
            document=links, object_ids=[self.objects['work']], dependency_ids=[state['id'], other['id']]))
        return state, bridge, other

    def pin(self, artifact, kind):
        return dict(id=artifact['id'], sha256=artifact['sha256'], kind=kind)

    def save(self, pins, base=None):
        return self.write('save_classic_draft', dict(base_draft_id=base,
            document=dict(self.document, professional_inputs=pins)))

    def preview(self, draft):
        return self.service.preview_workbench_generation(self.p,
            dict(draft_version_id=draft['id'], execution_policy=self.policy))

    def logical_request(self, preview):
        self.assertTrue(preview['ready'], preview)
        return preview['artifact']['document']['series_batch']['jobs'][0]['request']

    def test_canonical_state_and_cross_episode_bridge_reach_real_preview_prompt_and_hash(self):
        from sqlalchemy import func, select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.workbench_generation import working_context
        state, bridge, _ = self.register_sources()
        original = self.save([])
        before = self.logical_request(self.preview(original))
        pins = [self.pin(state, 'scene_state'), self.pin(bridge, 'sequence_links')]
        fixed = self.save(pins, base=original['id'])
        preview = self.preview(fixed)
        request = self.logical_request(preview)
        for text in ('固定原始用户提示', '固定雨夜暖台灯基线', '前镜抬头后目光停在门口',
                     '门外三次敲击声跨集延续', '下一集接住同一次敲门'):
            self.assertIn(text, request['prompt'])
        self.assertEqual(before['prompt'], self.document['prompt'])
        self.assertNotEqual(request['context_sha256'], before['context_sha256'])
        self.assertEqual(preview['artifact']['document']['approved_inputs'], [])
        self.assertFalse(preview['needs_approval'])
        self.assertTrue(preview['needs_confirmation'])
        with self.engine.connect() as conn:
            context = working_context(self.store, conn, self.store._project(conn, self.p), fixed['id'])
            self.assertEqual(context['sha256'], request['context_sha256'])
            self.assertEqual(context['professional_inputs'], pins)
            self.assertEqual({row['path'] for row in context['semantic_inputs']}, {'scenes[0].shots[1]', 'links[0]'})
            for semantic in context['semantic_inputs']:
                self.assertIn(semantic['text'], request['prompt'])
            dependencies = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == self.p,
                S.artifact_dependencies.c.artifact_id == fixed['id'])).scalars())
            self.assertTrue({state['id'], bridge['id']} <= dependencies)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.artifact_decisions).where(
                S.artifact_decisions.c.project_id == self.p)), 0)
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.generation_jobs).where(
                S.generation_jobs.c.project_id == self.p)), 0)

    def test_scope_and_missing_shot_reject_save_and_preserve_the_last_previewable_draft(self):
        state, bridge, other = self.register_sources()
        saved = self.save([self.pin(state, 'scene_state'), self.pin(bridge, 'sequence_links')])
        original_prompt = self.logical_request(self.preview(saved))['prompt']
        missing = self.register_state('canonical-no-target', missing_target=True)
        for source, code in ((other, 'professional_input_scope'), (missing, 'professional_input_incomplete')):
            with self.subTest(code=code), self.assertRaises(ResourceError) as error:
                self.save([self.pin(source, 'scene_state')], base=saved['id'])
            self.assertEqual(error.exception.code, code)
            latest = self.store.list_classic_drafts(self.p, self.target)['items']
            self.assertEqual([row['id'] for row in latest], [saved['id']])
            self.assertEqual(self.logical_request(self.preview(saved))['prompt'], original_prompt)


if __name__ == '__main__':
    unittest.main()
