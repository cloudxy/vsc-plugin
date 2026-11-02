"""Original job/unit pins and incremental Canvas edits in isolated PostgreSQL."""
from copy import deepcopy
import os
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import func, insert, select

from support.fixtures.resource_store import HAS_DB_DEPS, ResourceStoreFixture
from vsc.adapters.persistence.postgres import schema as S
from vsc.adapters.persistence.postgres.editor_professional import professional_context
from vsc.adapters.persistence.postgres.editor_workspace import EditorWorkspaceRepository
from vsc.assets.resource_service import ResourceError
from vsc.post.edit_workspace import FORMAT
from vsc.production.quotes import fingerprint


@unittest.skipUnless(HAS_DB_DEPS and os.environ.get('VSC_TEST_DATABASE_URL'), 'requires isolated PostgreSQL')
class EditorSourceHandoffTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.objects = self.hierarchy()
        self.shot_b = self.write('create_object', dict(kind='shot', parent_id=self.objects['sequence'], display_code='SHOT-B', ordinal=1))['id']
        self.flow = self.write('create_intelligent_workflow', dict(episode_id=self.objects['episode'], script_text='隔离固定双镜头', route='creation'))['id']
        self.repo = EditorWorkspaceRepository(self.store)
        provider = self.service.register_provider(dict(id='editor-sources-'+uuid.uuid4().hex, base_url='https://example.invalid', auth_ref='OFFLINE_TEST_KEY'), actor='test-admin')
        self.model = self.service.register_model(dict(provider_id=provider['id'], model_key='source-video', model_version='1', modality='video', capabilities={}), actor='test-admin')

    def media(self, name='synthetic source', rights='owned', modality='video', duration=3000):
        media = self.write('register_media', dict(name=name, modality=modality, sha256=uuid.uuid4().hex*2,
            size_bytes=10, mime_type='video/mp4' if modality=='video' else 'audio/wav', duration_ms=duration,
            width=128 if modality=='video' else None, height=128 if modality=='video' else None,
            storage='local', object_key=uuid.uuid4().hex+'.bin', rights=rights,
            source={'kind':'synthetic-test', 'content':'isolated original source metadata; no provider invoked'}))['id']
        self.write('record_media_check', dict(media_id=media, checker='fixture', criteria_version='1', outcome='pass'))
        return media

    def workflow(self, a='native', b='native'):
        detail = self.service.get_intelligent_workflow(self.p, self.flow)
        state = detail['state']
        state['blocking_mode'] = 'skip';state['document']['skip_blocking_reason'] = '隔离测试明确跳过站位'
        state['units'] = [dict(unit_key=key, shot_id=shot, title=key, professional={'sound_route':route})
                          for key, shot, route in [('A', self.objects['shot'], a), ('B', self.shot_b, b)]]
        request = dict(workflow_id=self.flow, base_version_id=detail['version']['id'], state=state)
        impact = self.service.preview_intelligent_change(self.p, request)
        self.write('save_intelligent_workflow', dict(request, impact_sha256=impact['sha256']))
        detail = self.service.get_intelligent_workflow(self.p, self.flow)
        artifact = self.service.get_artifact_version(self.p, detail['version']['artifact_id'])
        return dict(version_id=detail['version']['id'], artifact_id=artifact['id'], artifact_sha256=artifact['sha256'],
                    state_sha256=fingerprint(detail['state']), unit_key='A')

    def output(self, shot, workflow, pins=None, media=None):
        media = media or self.media()
        current = next((draft for draft in self.store.list_classic_drafts(self.p, shot)['items']
                        if draft['document']['mode']=='text'), None)
        draft = self.write('save_classic_draft', dict(base_draft_id=current['id'] if current else None, document=dict(
            shot_id=shot, mode='text', prompt='isolated original job', references=[], source_workflow=workflow,
            professional_inputs=pins or [])))
        def fixed(conn, project):
            run = self.store._create_artifact(conn, project, dict(artifact_key='test-source-run:'+str(uuid.uuid4()),
                artifact_type='workbench-generation-run', document={'workbench_draft':{'id':draft['id'],'sha256':draft['sha256']}},
                object_ids=[shot], dependency_ids=[draft['id']]))
            job = str(uuid.uuid4())
            conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p, id=str(uuid.uuid4()),
                run_version_id=run['id'], shot_id=shot, output_kind='video', draft_version_id=draft['id'], draft_sha256=draft['sha256']))
            conn.execute(insert(S.generation_jobs).values(project_id=self.p, id=job, run_version_id=run['id'], shot_id=shot,
                purpose='video_clip', modality='video', candidate_no=0, provider_id=self.model['provider_id'],
                model_id=self.model['id'], model_version='1', request_payload={}, request_sha256='0'*64,
                context_sha256='0'*64, idempotency_key=uuid.uuid4().hex, status='succeeded', attempt=0))
            conn.execute(insert(S.job_outputs).values(project_id=self.p, id=str(uuid.uuid4()), job_id=job, media_id=media, asset_type='video'))
            return dict(id=job)
        result = self.store._mutate(self.p, 'test_original_editor_job', {}, expected_revision=self.rev,
            idempotency_key=uuid.uuid4().hex, actor='test-human', callback=fixed)
        self.rev = result['revision']
        candidate = self.write('propose_binding', dict(target_object_id=shot, media_id=media, role='video_take', slot_key='workbench'))
        current = next((s for s in self.service.list_working_selections(self.p, shot_id=shot)['items'] if s['output_kind']=='video'), None)
        selection = self.write('save_working_selection', dict(shot_id=shot, output_kind='video', candidate_id=candidate['candidate_id'],
            base_version_id=current['id'] if current else None, trim_in_ms=500, trim_out_ms=2500))
        return dict(job_id=result['id'], media_id=media, selection_id=selection['id'])

    def canvas(self, output, explicit=True):
        node = dict(id='output', type='video', media_id=output['media_id'])
        if explicit:node['job_id'] = output['job_id']
        return self.write('create_creative_canvas', dict(episode_id=self.objects['episode'], document={'nodes':[node], 'edges':[]}))

    def add(self, canvas, revision=0, **kw):
        return self.write('canvas_node_to_edit', dict(canvas_id=canvas['id'], canvas_revision=canvas['canvas_revision'],
            node_id='output', edit_revision=revision), **kw)

    def test_mixed_original_workflow_versions_save_readback_and_relational_pins(self):
        first = self.workflow()
        a = self.output(self.objects['shot'], first)
        later = self.workflow(a='separate', b='silent')
        b = self.output(self.shot_b, dict(later, unit_key='B'))
        seed = self.repo.seed(self.p, self.objects['episode'])
        self.assertEqual(seed['gaps'], [])
        clips = seed['document']['clips']
        self.assertEqual([clip['source_job_id'] for clip in clips], [a['job_id'], b['job_id']])
        self.assertEqual([clip['muted'] for clip in clips], [False, True])
        saved = self.write('save_edit_workspace', dict(episode_id=self.objects['episode'], edit_revision=0, document=seed['document']))
        reopened = self.service.get_edit_workspace(self.p, self.objects['episode'])['current']['document']
        self.assertEqual(reopened, seed['document'])
        with self.engine.connect() as conn:
            context = professional_context(self.store, conn, self.p, self.objects['episode'], reopened)
            members = list(conn.execute(select(S.edit_revision_media.c.source_job_id).where(
                S.edit_revision_media.c.project_id==self.p, S.edit_revision_media.c.edit_version_id==saved['edit_version_id'])
                .order_by(S.edit_revision_media.c.ordinal)).scalars())
        self.assertEqual(context['shot_conditions'][self.objects['shot']]['sound_route'], 'native')
        self.assertEqual(context['shot_conditions'][self.shot_b]['sound_route'], 'silent')
        self.assertEqual(members, [a['job_id'], b['job_id']])

    def test_canvas_matches_seed_professional_rules_and_preserves_all_manual_tracks(self):
        audio = self.media('fixed music', modality='audio', duration=1000)
        choice = self.candidate(self.shot_b, audio, role='music', track_key='music');self.select(choice)
        sound = self.write('create_artifact', dict(artifact_key='source-music', artifact_type='creative-relations',
            object_ids=[self.objects['episode']], document={'format':'vsc.creative-relations/v1', 'project_id':self.p,
                'cues':[dict(key='music', kind='music', scope_object_id=self.objects['episode'],
                    shots=[dict(shot_id=self.shot_b, start_ms=500, end_ms=1500)], slot_ids=[choice['slot_id']], parameters={'source_in_ms':0})]}))
        rules = self.write('create_artifact', dict(artifact_key='subtitle-rules', artifact_type='creative-brief',
            object_ids=[self.objects['episode']], document={'creative_rules':{'subtitle':{'max_cps':{'value':4,'level':'warning'}}}}))
        pins = [dict(id=sound['id'], sha256=sound['sha256'], kind='sound_plan'), dict(id=rules['id'], sha256=rules['sha256'], kind='creative_rules')]
        output = self.output(self.shot_b, dict(self.workflow(b='separate'), unit_key='B'), pins)
        seed = self.repo.seed(self.p, self.objects['episode'])['document']
        manual_clip = dict(id='manual', media_id=self.media('manual video'), shot_id=self.objects['shot'],
                           in_frame=3, out_frame=27, muted=False, volume=.4)
        manual_audio = dict(id='manual-audio', media_id=self.media('manual music', modality='audio'),
                            in_frame=4, out_frame=20, at_frame=1, volume=.3, purpose='music')
        caption = dict(start_frame=0, end_frame=12, text='人工保留字幕')
        document = dict(format=FORMAT, width=128, height=128, fps=24, clips=[manual_clip], audio=[manual_audio], captions=[caption])
        self.write('save_edit_workspace', dict(episode_id=self.objects['episode'], edit_revision=0, document=document))
        canvas = self.canvas(output)
        added = self.add(canvas, 1, idempotency_key='original-canvas-add')
        replay = self.service.canvas_node_to_edit(self.p, dict(canvas_id=canvas['id'], canvas_revision=canvas['canvas_revision'], node_id='output', edit_revision=1),
            actor='test-human', expected_revision=0, idempotency_key='original-canvas-add')
        self.assertEqual(replay, added)
        current = self.service.get_edit_workspace(self.p, self.objects['episode'])['current']['document']
        self.assertEqual(current['clips'][0], manual_clip);self.assertEqual(current['audio'][0], manual_audio)
        self.assertEqual(current['captions'], [caption]);self.assertEqual(current['professional_inputs'], seed['professional_inputs'])
        for key in ('source_job_id', 'working_selection_version_id', 'shot_id', 'in_frame', 'out_frame', 'muted'):
            self.assertEqual(current['clips'][1][key], seed['clips'][0][key])
        self.assertEqual(current['audio'][1]['media_id'], seed['audio'][0]['media_id'])
        self.assertEqual(current['audio'][1]['at_frame'], seed['audio'][0]['at_frame']+24)
        self.assertEqual(len(current['clips']), 2);self.assertEqual(len(current['audio']), 2)
        with self.engine.connect() as conn:
            context = professional_context(self.store, conn, self.p, self.objects['episode'], current)
        self.assertEqual(context['creative_rules']['subtitle']['max_cps']['value'], 4)

    def test_ambiguous_same_shot_jobs_reject_and_explicit_job_survives_fixed_readback(self):
        source = self.output(self.objects['shot'], self.workflow(a='silent'))
        self.output(self.objects['shot'], self.workflow(a='native'), media=source['media_id'])
        canvas = self.canvas(source, explicit=False)
        with self.assertRaises(ResourceError) as caught:self.add(canvas)
        self.assertEqual(caught.exception.code, 'canvas_edit_job_ambiguous')
        self.assertIsNone(self.service.get_edit_workspace(self.p, self.objects['episode'])['workspace'])
        explicit = self.canvas(source)
        self.add(explicit)
        document = self.service.get_edit_workspace(self.p, self.objects['episode'])['current']['document']
        self.assertEqual(document['clips'][0]['source_job_id'], source['job_id']);self.assertTrue(document['clips'][0]['muted'])
        stripped = deepcopy(document);stripped['professional_inputs'] = []
        with self.assertRaises(ResourceError) as caught:self.write('save_edit_workspace', dict(
            episode_id=self.objects['episode'], edit_revision=1, document=stripped))
        self.assertEqual(caught.exception.code, 'edit_professional_source_missing')
        self.assertEqual(self.service.get_edit_workspace(self.p, self.objects['episode'])['current']['document'], document)

    def test_canvas_failure_after_editor_save_rolls_back_both_versions(self):
        source = self.output(self.objects['shot'], self.workflow(a='silent'))
        canvas = self.canvas(source)
        revision = self.service.get_project(self.p)['revision']
        with patch.object(self.store, '_insert_canvas_version', side_effect=ResourceError('synthetic canvas save failure', 'test_canvas_save_failure')):
            with self.assertRaises(ResourceError):self.add(canvas)
        self.assertEqual(self.service.get_project(self.p)['revision'], revision)
        self.assertIsNone(self.service.get_edit_workspace(self.p, self.objects['episode'])['workspace'])
        self.assertEqual(self.service.get_creative_canvas(self.p, canvas['id'])['version_id'], canvas['version_id'])
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.edit_revisions).where(S.edit_revisions.c.project_id==self.p)), 0)
        self.add(canvas)

