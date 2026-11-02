"""Exact original job/unit projection and append-only Canvas enrichment rules."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import Column, JSON, MetaData, Table, create_engine, delete, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB

from vsc.adapters.persistence.postgres import editor_professional as E, schema as S
from vsc.assets.resource_service import ResourceError
from vsc.post.edit_workspace import FORMAT, validate_edit
from vsc.production.quotes import fingerprint


def identifier():
    return str(uuid.uuid4())


class EditorSourceProjectionTests(unittest.TestCase):
    def setUp(self):
        # Execute the adapter's selectors against isolated in-memory rows. This
        # checks rule/query projection, not PostgreSQL constraints or real media.
        self.engine = create_engine('sqlite://')
        metadata = MetaData()
        for table in (S.generation_jobs, S.job_outputs, S.workbench_run_inputs,
                      S.intelligent_versions, S.script_lines, S.sound_cues, S.cue_shots):
            Table(table.name, metadata, *(Column(c.name, JSON() if isinstance(c.type, JSONB) else c.type)
                                         for c in table.c))
        metadata.create_all(self.engine)
        self.conn = self.engine.connect()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.conn.close)
        self.p, self.episode, self.shot_a, self.shot_b = [identifier() for _ in range(4)]
        self.rows, self.states = {}, {}
        self.store = SimpleNamespace(
            _one=lambda conn, table, p, key: self.rows[(table.name, key)],
            _descendant_ids=lambda conn, p, episode: [self.shot_a, self.shot_b],
            _artifact_scopes=lambda conn, p, key: [self.episode],
            _intelligent_state=lambda conn, p, version: self.states[version['id']])

    def artifact(self, body, kind):
        key = identifier()
        raw = json.dumps(body, ensure_ascii=False).encode()
        row = dict(id=key, project_id=self.p, document=raw, artifact_type=kind,
                   sha256=hashlib.sha256(raw).hexdigest(), project_wide=False)
        self.rows[('artifact_versions', key)] = row
        return row

    def workflow(self, a='native', b='native'):
        body = dict(unit_conditions={'A': {'sound_route': a}, 'B': {'sound_route': b}})
        artifact = self.artifact(body, 'intelligent-workflow-state')
        workflow, version = identifier(), identifier()
        self.rows[('intelligent_workflows', workflow)] = dict(id=workflow, episode_id=self.episode)
        self.rows[('intelligent_versions', version)] = dict(id=version, workflow_id=workflow, artifact_id=artifact['id'])
        self.conn.execute(insert(S.intelligent_versions).values(project_id=self.p, **self.rows[('intelligent_versions', version)]))
        self.states[version] = dict(document=body, units=[
            dict(unit_key='A', shot_id=self.shot_a, professional=body['unit_conditions']['A']),
            dict(unit_key='B', shot_id=self.shot_b, professional=body['unit_conditions']['B'])])
        return dict(version_id=version, artifact_id=artifact['id'], artifact_sha256=artifact['sha256'],
                    state_sha256=fingerprint(self.states[version]), unit_key='A')

    def clip(self, shot, workflow=None, pins=None, media=None):
        media, job, run = media or identifier(), identifier(), identifier()
        body = dict(shot_id=shot, professional_inputs=pins or [])
        if workflow:body['source_workflow'] = workflow
        draft = self.artifact(body, 'classic-production-draft')
        self.conn.execute(insert(S.generation_jobs).values(project_id=self.p, id=job, shot_id=shot,
            run_version_id=run, status='succeeded', modality='video', purpose='video_clip'))
        self.conn.execute(insert(S.job_outputs).values(project_id=self.p, id=identifier(), job_id=job, media_id=media))
        self.conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p, id=identifier(),
            run_version_id=run, shot_id=shot, output_kind='video', draft_version_id=draft['id'], draft_sha256=draft['sha256']))
        return dict(id='clip-'+job, shot_id=shot, media_id=media, in_frame=0, out_frame=24,
                    muted=False, volume=1), job, draft

    def document(self, *clips):
        return dict(format=FORMAT, width=128, height=128, fps=24, clips=list(clips), audio=[], captions=[])

    def test_mixed_workflow_versions_project_only_each_actual_generated_unit(self):
        first = self.workflow()
        later = self.workflow(a='separate', b='silent')
        later['unit_key'] = 'B'
        a, a_job, _ = self.clip(self.shot_a, first)
        b, b_job, _ = self.clip(self.shot_b, later)
        document = self.document(a, b)
        self.assertEqual(E.seed_professional(self.store, self.conn, self.p, self.episode, document), [])
        self.assertEqual((a['source_job_id'], b['source_job_id']), (a_job, b_job))
        context = E.professional_context(self.store, self.conn, self.p, self.episode, document)
        self.assertEqual(context['shot_conditions'], {self.shot_a: {'sound_route': 'native'}, self.shot_b: {'sound_route': 'silent'}})
        self.assertFalse(a['muted']);self.assertTrue(b['muted'])
        self.assertEqual([p['id'] for p in document['professional_inputs']], [first['artifact_id'], later['artifact_id']])
        validate_edit(document)

    def test_job_ambiguity_requires_explicit_origin_while_unknown_source_stays_editable(self):
        a, job, _ = self.clip(self.shot_a, self.workflow())
        self.clip(self.shot_a, self.workflow(a='silent'), media=a['media_id'])
        with self.assertRaises(ResourceError) as caught:E.clip_sources(self.store, self.conn, self.p, self.episode, a)
        self.assertEqual(caught.exception.code, 'edit_professional_job_ambiguous')
        a['source_job_id'] = job
        self.assertEqual(E.clip_sources(self.store, self.conn, self.p, self.episode, a)['job_id'], job)
        wrong = dict(a, source_job_id=identifier())
        with self.assertRaises(ResourceError) as caught:E.clip_sources(self.store, self.conn, self.p, self.episode, wrong)
        self.assertEqual(caught.exception.code, 'edit_professional_job_mismatch')
        legacy = self.document(dict(id='legacy', media_id=identifier(), in_frame=0, out_frame=24))
        self.assertEqual(E.seed_professional(self.store, self.conn, self.p, self.episode, legacy), [])
        context = E.professional_context(self.store, self.conn, self.p, self.episode, legacy)
        self.assertTrue(all(gap['severity']=='warning' for gap in context['gaps']))
        validate_edit(legacy)

    def test_original_sha_state_scope_and_required_pins_remain_fixed(self):
        workflow = self.workflow()
        clip, _, draft = self.clip(self.shot_a, workflow)
        doc = self.document(clip)
        E.seed_professional(self.store, self.conn, self.p, self.episode, doc)
        cases = [
            ('draft', lambda: self.rows[('artifact_versions', draft['id'])].update(sha256='f'*64), 'edit_professional_changed'),
            ('state', lambda: self.states[workflow['version_id']]['units'][0]['professional'].update(sound_route='silent'), 'edit_professional_changed'),
            ('scope', lambda: self.rows[('intelligent_workflows', self.rows[('intelligent_versions', workflow['version_id'])]['workflow_id'])].update(episode_id=identifier()), 'edit_professional_scope'),
            ('pins', lambda: doc.update(professional_inputs=[]), 'edit_professional_source_missing')]
        for name, change, code in cases:
            with self.subTest(name=name):
                rows, states, original = deepcopy(self.rows), deepcopy(self.states), deepcopy(doc)
                change()
                with self.assertRaises(ResourceError) as caught:E.professional_context(self.store, self.conn, self.p, self.episode, doc)
                self.assertEqual(caught.exception.code, code)
                self.rows, self.states = rows, states
                doc.clear();doc.update(original)

    def test_incremental_enrichment_preserves_manual_tracks_and_seeds_only_new_clip_sources(self):
        rules = self.artifact({'creative_rules': {'subtitle': {'max_cps': {'value': 4, 'level': 'warning'}}}}, 'creative-brief')
        sound = self.artifact({}, 'creative-relations')
        pins = [dict(id=rules['id'], sha256=rules['sha256'], kind='creative_rules'),
                dict(id=sound['id'], sha256=sound['sha256'], kind='sound_plan')]
        old = dict(id='manual', shot_id=self.shot_a, media_id=identifier(), in_frame=5, out_frame=29, volume=.5, muted=False)
        new, _, _ = self.clip(self.shot_b, dict(self.workflow(b='separate'), unit_key='B'), pins)
        cue = identifier()
        self.conn.execute(insert(S.sound_cues).values(project_id=self.p, id=cue, artifact_id=sound['id'],
            scope_object_id=self.episode, cue_kind='dialogue', label='fixed dialogue', parameters={}))
        self.conn.execute(insert(S.cue_shots).values(project_id=self.p, id=identifier(), cue_id=cue,
            shot_id=self.shot_b, start_ms=0, end_ms=1000))
        document = self.document(old, new)
        manual_audio = dict(id='human-audio', media_id=identifier(), in_frame=2, out_frame=24, at_frame=0, purpose='music')
        caption = dict(start_frame=0, end_frame=10, text='人工字幕')
        document['audio'].append(manual_audio);document['captions'].append(caption)
        before = deepcopy((old, manual_audio, caption))
        captured = []
        def seed(store, conn, p, doc, row):
            captured.append(row)
            return dict(id='cue-'+cue, media_id=identifier(), cue_id=cue, binding_decision_id=identifier(),
                        in_frame=0, out_frame=24, at_frame=24, purpose='dialogue_dry')
        with patch.object(E, 'seed_cue', side_effect=seed), patch.object(E, 'seed_caption', side_effect=ResourceError('missing measured caption', 'edit_caption_timing_missing')):
            gaps = E.merge_professional(self.store, self.conn, self.p, self.episode, document, [new])
        self.assertEqual((old, manual_audio, caption), before)
        self.assertEqual(len(document['clips']), 2);self.assertEqual(len(document['audio']), 2)
        self.assertEqual(document['captions'], [caption]);self.assertTrue(new['muted'])
        self.assertEqual(captured[0]['intervals'][0]['start_ms'], 1000)
        caption_gap = next(gap for gap in gaps if gap.get('code')=='edit_caption_timing_missing')
        self.assertEqual(caption_gap['severity'], 'warning')
        self.assertEqual(E.professional_context(self.store, self.conn, self.p, self.episode,
            dict(document, audio=[manual_audio]))['creative_rules']['subtitle']['max_cps']['value'], 4)
        # Existing Cue audio, including deliberate human edits, is never reseeded.
        with patch.object(E, 'seed_cue') as reseed:
            # Skip professional_context's separate audio binding check in this
            # rule-only case; the actual PostgreSQL API test owns that seam.
            context = dict(gaps=[], shot_conditions={self.shot_b: {'sound_route': 'separate'}}, _cues={cue: captured[0]})
            with patch.object(E, 'professional_context', return_value=context):
                E.merge_professional(self.store, self.conn, self.p, self.episode, document, [new])
            reseed.assert_not_called()

    def test_explicit_separate_route_without_usable_sound_blocks_but_unknown_warns(self):
        clip, _, _ = self.clip(self.shot_a, self.workflow(a='separate'))
        doc = self.document(clip)
        gaps = E.seed_professional(self.store, self.conn, self.p, self.episode, doc)
        self.assertEqual(gaps[0]['severity'], 'blocking')
        self.assertTrue(clip['muted'])

    def test_undeclared_cue_timing_warns_until_separate_sound_is_explicit(self):
        sound = self.artifact({}, 'creative-relations')
        pin = dict(id=sound['id'], sha256=sound['sha256'], kind='sound_plan')
        self.conn.execute(insert(S.sound_cues).values(project_id=self.p, id=identifier(), artifact_id=sound['id'],
            scope_object_id=self.episode, cue_kind='music', label='timing unknown', parameters={}))
        for route, severity in [('unknown', 'warning'), ('separate', 'blocking')]:
            with self.subTest(route=route):
                clip, _, _ = self.clip(self.shot_a, self.workflow(a=route), [pin])
                gaps = E.seed_professional(self.store, self.conn, self.p, self.episode, self.document(clip))
                gap = next(gap for gap in gaps if gap.get('code')=='edit_cue_timing_missing')
                self.assertEqual(gap['severity'], severity)

    def test_actual_conflicting_conditions_for_same_shot_remain_an_explicit_error(self):
        first, _, _ = self.clip(self.shot_a, self.workflow(a='native'))
        second, _, _ = self.clip(self.shot_a, self.workflow(a='silent'))
        with self.assertRaises(ResourceError) as caught:
            E.seed_professional(self.store, self.conn, self.p, self.episode, self.document(first, second))
        self.assertEqual(caught.exception.code, 'edit_professional_workflow_conflict')

    def test_known_workbench_input_gaps_cannot_silently_downgrade_to_legacy(self):
        clip, job, _ = self.clip(self.shot_a, self.workflow())
        self.conn.execute(update(S.workbench_run_inputs).values(output_kind='image'))
        with self.assertRaises(ResourceError) as caught:E.clip_sources(self.store, self.conn, self.p, self.episode, clip)
        self.assertEqual(caught.exception.code, 'edit_professional_job_mismatch')
        self.conn.execute(delete(S.workbench_run_inputs))
        run = self.conn.scalar(select(S.generation_jobs.c.run_version_id).where(S.generation_jobs.c.id==job))
        self.rows[('artifact_versions', run)] = dict(id=run, artifact_type='workbench-generation-run')
        with self.assertRaises(ResourceError) as caught:E.clip_sources(self.store, self.conn, self.p, self.episode, clip)
        self.assertEqual(caught.exception.code, 'edit_professional_source_missing')
        self.rows[('artifact_versions', run)]['artifact_type'] = 'production-run'
        source = E.clip_sources(self.store, self.conn, self.p, self.episode, clip)
        self.assertEqual(source['job_id'], job);self.assertEqual(source['pins'], [])
