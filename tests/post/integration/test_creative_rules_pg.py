"""Opt-in rules consume actual PG Profile, scope, dependencies and decisions."""
import copy
import importlib.util
import os
import unittest
from support.fixtures.resource_store import ResourceStoreFixture
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(os.environ.get('VSC_TEST_DATABASE_URL') and importlib.util.find_spec('psycopg'), 'requires isolated PostgreSQL')
class CreativeRulesPG(ResourceStoreFixture, unittest.TestCase):
    def project_rules(self, rules, stages=None):
        profile = {'profile_id': 'vsc.synthetic', 'version': '1', 'stages': stages or [], 'creative_rules': rules}
        if stages:
            profile['scope_required_from'] = stages[0]['id']
        project = self.service.create_project({'name': 'Declared rules fixture', 'profile_snapshot': profile}, actor='test-human')
        self.p, self.rev = project['id'], 0
        return self.hierarchy()

    def brief(self, objects, rules, approve=False):
        body = {'format': 'vsc.creative-brief/v1', 'audience': 'fixture audience', 'desired_experience': 'clear causal action',
            'objectives': [{'id': 'expression', 'goal': 'clear', 'success_evidence': 'explicit fixture review'}],
            'nonnegotiables': [], 'conflict_policy': 'owner decides', 'decision_owner': 'fixture-only', 'creative_rules': rules}
        row = self.write('create_artifact', {'artifact_key': 'brief-' + objects['episode'], 'artifact_type': 'vsc.creative_brief',
            'document': body, 'object_ids': [objects['episode']]})
        if approve:
            self.write('decide_artifact', {'artifact_id': row['id'], 'reason': 'Fixed synthetic decision'})
        return row

    def script(self, objects, duration, text='你12', dependencies=()):
        speakers = getattr(self, 'speakers', {})
        if self.p not in speakers:
            speakers[self.p] = self.write('create_object', {'kind': 'asset', 'display_code': 'FIXTURE-SPEAKER', 'asset_kind': 'character'})['id']
            self.speakers = speakers
        return self.write('create_artifact', {'artifact_key': 'screenplay', 'artifact_type': 'screenplay',
            'document': {'format': 'vsc.screenplay/v1', 'project_id': self.p, 'scope': objects['episode'], 'body': 'fixture',
                'scenes': [{'id': objects['scene'], 'estimated_duration_ms': duration, 'actions': [],
                    'dialogue': [{'id': 'L', 'text': text, 'speaker': speakers[self.p], 'narrative_refs': []}], 'silence': []}]},
            'object_ids': [objects['episode']], 'dependency_ids': [row['id'] for row in dependencies]})

    def approve(self, row):
        return self.write('decide_artifact', {'artifact_id': row['id'], 'reason': 'Fixed synthetic decision'})

    def other_episode(self, work_id, number):
        objects, parent = {'work': work_id}, work_id
        for kind in ('episode', 'scene', 'sequence', 'shot'):
            row = self.write('create_object', {'kind': kind, 'display_code': kind.upper() + str(number),
                'parent_id': parent, 'ordinal': number})
            objects[kind] = parent = row['id']
        return objects

    def scoped_brief(self, scope_ids, rules):
        body = {'format': 'vsc.creative-brief/v1', 'audience': 'fixture audience', 'desired_experience': 'clear causal action',
            'objectives': [{'id': 'expression', 'goal': 'clear', 'success_evidence': 'explicit fixture review'}],
            'nonnegotiables': [], 'conflict_policy': 'owner decides', 'decision_owner': 'fixture-only', 'creative_rules': rules}
        row = self.write('create_artifact', {'artifact_key': 'brief-' + '-'.join(scope_ids), 'artifact_type': 'vsc.creative_brief',
            'document': body, 'object_ids': scope_ids})
        self.approve(row)
        return row

    def test_profile_defaults_ignore_draft_brief_then_require_real_approved_fixed_scope(self):
        objects = self.project_rules({'duration': {'target_ms': 1000, 'tolerance_ms': 0},
            'line_length': {'max_characters': 3, 'level': 'error'}})
        brief = self.brief(objects, {'duration': {'target_ms': 2000}})
        valid = self.script(objects, 1000)
        self.approve(valid)
        invalid = self.script(objects, 1500)
        with self.assertRaises(ResourceError) as rejected:
            self.approve(invalid)
        self.assertEqual(rejected.exception.code, 'creative_rules_failed')
        self.assertFalse(self.service.get_artifact_version(self.p, invalid['id'])['approved'])
        self.approve(brief)
        unpinned = self.script(objects, 2000)
        with self.assertRaises(ResourceError):
            self.approve(unpinned)
        pinned = self.script(objects, 2000, dependencies=[brief])
        self.approve(pinned)
        too_long = self.script(objects, 2000, text='你好123', dependencies=[brief])
        with self.assertRaises(ResourceError):
            self.approve(too_long)

    def test_declared_warning_is_visible_in_original_approval_and_gate_response(self):
        from vsc.project.pg_workflow import check_gate
        objects = self.project_rules({'line_length': {'max_characters': 1, 'level': 'warning'}},
            [{'id': 'script', 'required': ['screenplay']}])
        artifact = self.script(objects, 1000, text='字数警告')
        self.assertTrue(self.approve(artifact)['creative_rule_warnings'])
        gate = check_gate(self.service, self.p, 'script', objects['episode'])
        self.assertTrue(gate['passed'], gate)
        self.assertTrue(gate['warnings'])

    def test_no_declaration_retains_old_behavior_and_other_episode_brief_does_not_leak(self):
        objects = self.hierarchy()
        other = dict(objects)
        parent = objects['work']
        for kind in ('episode', 'scene', 'sequence', 'shot'):
            row = self.write('create_object', {'kind': kind, 'display_code': kind.upper() + '2', 'parent_id': parent, 'ordinal': 1})
            other[kind] = parent = row['id']
        self.brief(other, {'duration': {'target_ms': 1000}, 'line_length': {'max_characters': 1, 'level': 'error'}}, approve=True)
        row = self.script(objects, 9000, text='Old unconfigured project keeps its existing long text ' * 3)
        self.approve(row)
        self.assertTrue(self.service.get_artifact_version(self.p, row['id'])['approved'])

    def test_multi_scope_brief_keeps_union_and_does_not_enable_rules_in_other_episode(self):
        import json
        first = self.hierarchy()
        second = self.other_episode(first['work'], 2)
        third = self.other_episode(first['work'], 3)
        brief = self.scoped_brief([first['episode'], second['episode']], {'duration': {'scope_targets': {
            first['episode']: {'target_ms': 1000}, second['episode']: {'target_ms': 2000}}}})
        # Both members of the union require the fixed brief. An unrelated
        # episode keeps its original unconfigured behavior.
        for objects in (first, second):
            with self.subTest(episode=objects['episode']):
                with self.assertRaises(ResourceError) as rejected:
                    self.approve(self.script(objects, 1000))
                self.assertEqual(rejected.exception.code, 'creative_rules_failed')
        self.approve(self.script(third, 9000))
        one = self.script(first, 1000, dependencies=[brief])
        two = self.script(second, 2000, dependencies=[brief])
        self.approve(one); self.approve(two)
        # A fixed screenplay can itself cover the same union. Validate each
        # episode's scenes against its target instead of summing both twice.
        documents = [json.loads(self.service.get_artifact_version(self.p, row['id'])['document']) for row in (one, two)]
        document = dict(documents[0], scope='project', scenes=[scene for data in documents for scene in data['scenes']])
        for scene in document['scenes']:
            for line in scene['dialogue']:
                line['id'] = scene['id'] + '-L'
        union = self.write('create_artifact', {'artifact_key': 'union-script', 'artifact_type': 'screenplay', 'document': document,
            'object_ids': [first['episode'], second['episode']], 'dependency_ids': [brief['id']]})
        self.approve(union)
        self.assertEqual(set(self.service.get_artifact_version(self.p, union['id'])['object_ids']), {first['episode'], second['episode']})
        quality = {'format': 'vsc.quality-plan/v1', 'project_id': self.p, 'requirements': [], 'inputs': [], 'attempts': [],
            'risks': [{'id': 'R' + str(index), 'hypothesis': 'bounded fixture', 'stop_condition': 'one attempt',
                'scope': objects['episode'], 'shot_ids': [objects['shot']]} for index, objects in enumerate((first, second))] +
                [{'id': 'UNION', 'hypothesis': 'shared bounded fixture', 'stop_condition': 'one attempt', 'shot_ids': [first['shot'], second['shot']]}]}
        fixed_quality = self.write('create_artifact', {'artifact_key': 'union-quality', 'artifact_type': 'quality-plan', 'document': quality,
            'object_ids': [first['episode'], second['episode']]})
        self.approve(fixed_quality)
        invalid = copy.deepcopy(quality)
        invalid['risks'][0]['scope'] = third['episode']
        outside = self.write('create_artifact', {'artifact_key': 'union-quality', 'artifact_type': 'quality-plan', 'document': invalid,
            'object_ids': [first['episode'], second['episode']]})
        with self.assertRaises(ResourceError) as rejected:
            self.approve(outside)
        self.assertEqual(rejected.exception.code, 'creative_rules_failed')

    def test_sequence_rules_recheck_identically_at_approval_context_gate_and_refreeze(self):
        from vsc.project.pg_workflow import check_gate
        objects = self.project_rules({}, [{'id': 'design', 'required': ['shot-plan']}])
        self.approve(self.script(objects, 1000))
        def shots(dependencies=()):
            return self.write('create_artifact', {'artifact_key': 'shots', 'artifact_type': 'shot-plan', 'stage': 'design',
                'document': {'format': 'vsc.continuity-plan/v1', 'project_id': self.p, 'sequence_id': objects['sequence'],
                    'shots': [{'id': objects['shot'], 'duration_ms': 1000}]}, 'object_ids': [objects['sequence']],
                'dependency_ids': [row['id'] for row in dependencies]})
        original = shots(); self.approve(original)
        self.artifact('state', 'scene-state', [objects['scene']], {'state_versions': [{'scene_id': objects['scene']}]})
        self.select(self.candidate(objects['shot'], self.media()))
        video = self.media('fixed timeline candidate', modality='video')
        decision = self.select(self.candidate(objects['shot'], video, role='video_take'))
        media = self.service.get_media(self.p, video)
        selected = self.write('create_artifact', {'artifact_key': 'selected', 'artifact_type': 'selected-takes',
            'document': {'items': [{'id': 'SEL', 'shot_id': objects['shot'], 'purpose': 'visual', 'usage_rights': 'owned',
                'media': {'path': 'fixture.mp4', 'sha256': media['sha256']}}]}, 'object_ids': [objects['sequence']]})
        self.approve(selected)
        def timeline(dependencies=()):
            body = {'format': 'vsc.timeline/v1', 'project_id': self.p, 'scope': objects['sequence'],
                'selected_takes': {'id': selected['id'], 'sha256': selected['sha256']},
                'render_plan': {'format': 'vsc.remotion-render-plan/v1', 'project_id': self.p,
                    'composition': {'id': 'Scope', 'width': 320, 'height': 240, 'fps': 24, 'duration_in_frames': 24},
                    'segments': [{'id': 'V', 'kind': 'video', 'source': 'fixture.mp4', 'source_shot_id': objects['shot'],
                        'from_frame': 0, 'duration_in_frames': 24}]},
                'bindings': [{'segment_id': 'V', 'selected_item_id': 'SEL', 'sha256': media['sha256'],
                    'purpose': 'visual', 'usage_rights': 'owned'}]}
            row = self.write('create_artifact', {'artifact_key': 'edit', 'artifact_type': 'edit-timeline', 'document': body,
                'object_ids': [objects['sequence']], 'dependency_ids': [selected['id']] + [item['id'] for item in dependencies]})
            self.approve(row)
            return row
        def freeze(row):
            return self.write('freeze_timeline', {'artifact_id': row['id'], 'episode_id': objects['episode'],
                'selected_media': {'SEL': {'media_id': video, 'binding_decision_id': decision['decision_id']}}})
        old_timeline = timeline(); freeze(old_timeline)
        self.assertTrue(self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')['ready'])
        self.assertTrue(check_gate(self.service, self.p, 'design', objects['episode'])['passed'])
        brief = self.scoped_brief([objects['sequence']], {'duration': {'target_ms': 1000}})
        with self.assertRaises(ResourceError) as approval:
            self.approve(original)
        self.assertEqual(approval.exception.code, 'creative_rules_failed')
        context = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertFalse(context['ready'])
        self.assertIn('creative_rules_failed', str(context['gaps']))
        self.assertFalse(check_gate(self.service, self.p, 'design', objects['episode'])['passed'])
        with self.assertRaises(ResourceError) as frozen:
            freeze(old_timeline)
        self.assertEqual(frozen.exception.code, 'creative_rules_failed')
        fixed = shots([brief]); self.approve(fixed)
        recovered = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertTrue(recovered['ready'], recovered['gaps'])
        self.assertTrue(check_gate(self.service, self.p, 'design', objects['episode'])['passed'])
        freeze(timeline([brief]))
        # Repeated membership in overlapping scopes still denotes one brief,
        # with its most specific applicable scope rather than two conflicts.
        self.write('decide_artifact', {'artifact_id': brief['id'], 'outcome': 'revoke', 'reason': 'Replace synthetic rule source'})
        overlapping = self.scoped_brief([objects['episode'], objects['sequence']], {'duration': {'target_ms': 1000}})
        self.approve(self.script(objects, 1000, dependencies=[overlapping]))
        final = shots([overlapping]); self.approve(final)
        self.assertTrue(self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')['ready'])

    def test_risk_reference_requires_real_fixed_quality_and_same_scope(self):
        objects = self.project_rules({'require_risk_refs': True})
        quality_body = {'format': 'vsc.quality-plan/v1', 'project_id': self.p, 'requirements': [], 'inputs': [], 'attempts': [],
            'risks': [{'id': 'R', 'hypothesis': 'bounded interaction', 'stop_condition': 'two attempts',
                'scope': objects['episode'], 'shot_ids': [objects['shot']]}]}
        quality = self.write('create_artifact', {'artifact_key': 'quality', 'artifact_type': 'quality-plan',
            'document': quality_body, 'object_ids': [objects['episode']]})
        self.approve(quality)
        def shot(ids, dependency=True, body_extra=None):
            return self.write('create_artifact', {'artifact_key': 'shots', 'artifact_type': 'shot-plan',
                'document': {'format': 'vsc.continuity-plan/v1', 'project_id': self.p, 'sequence_id': objects['sequence'],
                    'quality_plan': {'id': quality['id'], 'sha256': quality['sha256']},
                    'shots': [dict({'id': objects['shot'], 'duration_ms': 1000, 'risk_ids': ids}, **(body_extra or {}))]},
                'dependency_ids': [quality['id']] if dependency else [], 'object_ids': [objects['episode']]})
        valid = shot(['R']); self.approve(valid)
        for invalid in (shot(['missing']), shot(['R'], False), shot(['R'], body_extra={'risks': [{'id': 'R'}]})):
            with self.assertRaises(ResourceError):
                self.approve(invalid)
        other = copy.deepcopy(quality_body); other['risks'][0]['scope'] = 'other-episode'
        q2 = self.write('create_artifact', {'artifact_key': 'quality', 'artifact_type': 'quality-plan',
            'document': other, 'object_ids': [objects['episode']]})
        with self.assertRaises(ResourceError):
            self.approve(q2)
        bad = self.write('create_artifact', {'artifact_key': 'shots', 'artifact_type': 'shot-plan',
            'document': {'format': 'vsc.continuity-plan/v1', 'project_id': self.p, 'sequence_id': objects['sequence'],
                'quality_plan': {'id': q2['id'], 'sha256': q2['sha256']}, 'shots': [{'id': objects['shot'], 'duration_ms': 1000, 'risk_ids': ['R']}]},
            'dependency_ids': [q2['id']], 'object_ids': [objects['episode']]})
        with self.assertRaises(ResourceError):
            self.approve(bad)

    def test_original_pg_gate_checks_current_rules_and_fixed_render_projection(self):
        from vsc.project.pg_workflow import check_gate
        rules = {'duration': {'target_ms': 1000, 'tolerance_ms': 0}, 'subtitle': {'mixed_spacing': True}}
        objects = self.project_rules(rules, [{'id': 'post', 'required': ['edit-timeline']}])
        body = {'format': 'vsc.timeline/v1', 'project_id': self.p, 'scope': objects['episode'],
            'render_plan': {'format': 'vsc.remotion-render-plan/v1', 'project_id': self.p,
                'composition': {'id': 'Gate', 'width': 320, 'height': 240, 'fps': 30, 'duration_in_frames': 30},
                'segments': [{'id': 'image', 'kind': 'image', 'source': 'fixture.png', 'source_shot_id': objects['shot'],
                    'from_frame': 0, 'duration_in_frames': 30}]}}
        missing = self.write('create_artifact', {'artifact_key': 'edit', 'artifact_type': 'edit-timeline',
            'document': body, 'object_ids': [objects['episode']]})
        with self.assertRaises(ResourceError):
            self.approve(missing)
        body['render_plan']['creative_rules'] = rules
        fixed = self.write('create_artifact', {'artifact_key': 'edit', 'artifact_type': 'edit-timeline',
            'document': body, 'object_ids': [objects['episode']]})
        self.approve(fixed)
        self.assertTrue(check_gate(self.service, self.p, 'post', objects['episode'])['passed'])
        self.brief(objects, {'duration': {'target_ms': 2000}}, approve=True)
        self.assertFalse(check_gate(self.service, self.p, 'post', objects['episode'])['passed'])

    def test_gate_and_original_context_recheck_current_approved_rule_sources(self):
        objects = self.hierarchy()
        script = self.script(objects, 1000)
        self.approve(script)
        self.artifact(objects=[objects['shot']])
        self.artifact('state', 'scene-state', [objects['scene']], {'state_versions': [{'scene_id': objects['scene']}]})
        chosen = self.select(self.candidate(objects['shot'], self.media()))
        before = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertTrue(before['ready'], before['gaps'])
        draft = self.brief(objects, {'duration': {'target_ms': 2000}})
        self.assertTrue(self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')['ready'])
        self.approve(draft)
        blocked = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertFalse(blocked['ready'])
        self.assertIn('creative_rules_failed', str(blocked['gaps']))
        fixed = self.script(objects, 2000, dependencies=[draft]); self.approve(fixed)
        # The updated structured screenplay carries the approved rule source;
        # a legacy generic shot specification receives no invented new gate.
        recovered = self.service.compile_shot_context(self.p, objects['shot'], 'video_clip')
        self.assertTrue(recovered['ready'], recovered['gaps'])
        self.assertTrue(any(row.get('artifact_type') == 'vsc.creative_rules' for row in recovered['semantic_inputs']))

    def test_original_pg_sound_approval_rechecks_new_parameters_fixed_sources_and_media(self):
        import uuid
        objects = self.hierarchy()
        media_id = self.media('SFX', modality='audio')
        media = self.service.get_media(self.p, media_id)
        source = self.service.list_sources(self.p)['items'][0]
        self.media('Unrelated source', modality='audio')
        unrelated = next(row for row in self.service.list_sources(self.p)['items'] if row['id'] != source['id'])
        body = {'format': 'vsc.sound-cue-sheet/v1', 'project_id': self.p, 'sequence_id': objects['sequence'],
            'duration_ms': 1000, 'music_cues': [], 'dialogue_cues': [], 'ambience_beds': [], 'boundaries': [],
            'sfx_cues': [{'id': 'FX', 'start_ms': 0, 'end_ms': 500, 'purpose': 'synthetic source check',
                'usage_rights': 'owned', 'media': {'id': media_id, 'sha256': media['sha256']},
                'source_ref': {'id': source['id'], 'sha256': source['sha256']}}]}
        def register(document):
            return self.write('create_artifact', {'artifact_key': 'sound', 'artifact_type': 'vsc.sound_plan',
                'document': document, 'object_ids': [objects['sequence']]})
        valid = register(body); self.approve(valid)
        for invalid in (
            dict(body, music_cues=[{'id': 'M', 'bpm': 0}]),
            dict(body, sfx_cues=[dict(body['sfx_cues'][0], source_ref={'id': str(uuid.uuid4()), 'sha256': '0' * 64})]),
            dict(body, sfx_cues=[dict(body['sfx_cues'][0], source_ref={'id': unrelated['id'], 'sha256': unrelated['sha256']})]),
            dict(body, sfx_cues=[dict(body['sfx_cues'][0], media={'id': 'bad-id', 'sha256': media['sha256']})]),
            dict(body, sfx_cues=[dict(body['sfx_cues'][0], media={'path': 'arbitrary.wav', 'sha256': media['sha256']})])):
            with self.subTest(document=invalid):
                with self.assertRaises(ResourceError) as rejected:
                    self.approve(register(invalid))
                self.assertIn(rejected.exception.code, {'invalid_contract', 'creative_rules_failed'})
        self.write('decide_rights', {'media_id': media_id, 'outcome': 'revoked', 'reason': 'Synthetic rights withdrawal'})
        with self.assertRaises(ResourceError):
            self.approve(register(body))
        legacy = dict(body); legacy.pop('sfx_cues')
        self.approve(register(legacy))
