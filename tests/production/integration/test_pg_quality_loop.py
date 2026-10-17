"""Synthetic end-to-end quality authoring and enforcement; no provider calls."""
import copy
import json
import os
import unittest
from support.fixtures.resource_store import HAS_DB_DEPS
from support.fixtures.trial_quality import TrialQualityFixture


@unittest.skipUnless(os.environ.get("VSC_TEST_DATABASE_URL") and HAS_DB_DEPS, "requires isolated PostgreSQL test connection")
class PostgresQualityLoopTests(TrialQualityFixture, unittest.TestCase):
    def test_incomplete_job_missing_output_and_unknown_cost_cannot_be_reported_usable(self):
        from vsc.assets.resource_service import ResourceError
        run, _, logical = self.fixture_run()
        job = self.job(run, logical)
        observation = {'job_id': job['id'], 'criteria_artifact_id': self.script, 'result': 'failed', 'defect_code': 'contact',
            'observation': 'not observed yet', 'position': {}, 'cost_basis': 'unknown'}
        def record(row):
            return self.approved('unknown-observation', 'quality-observation', {'format': 'vsc.quality-observations/v1',
                'project_id': self.p, 'observations': [row]}, dependency_ids=[self.script])
        with self.assertRaises(ResourceError):
            record(observation)
        with self.assertRaises(ResourceError):
            record(dict(observation, result='usable'))
        with self.assertRaises(ResourceError):
            record(dict(observation, result='unknown', cost_amount=0, cost_unit='CNY'))
        self.assertTrue(record(dict(observation, result='unknown'))['id'])

    def test_dance_spec_is_registered_and_consumed_by_actual_fixed_request(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.production_guard import requests_for
        from vsc.adapters.persistence.postgres.values import digest
        from vsc.production.performance import FIELDS, prompt_fragment
        from vsc.assets.resource_service import ResourceError
        music = self.media('fixed beat music', modality='audio')
        self.select(self.candidate(self.objects['shot'], music, role='reference_audio'))
        method = self.approved('dance-method', 'trial-method', {'method': 'pose on fixed music beat'})
        params = {key: 'explicit ' + key for key in FIELDS['dance']}
        params.update(purpose='move on music', acceptance='one pose on fixed beat', fallback='edit to beat', route='generation',
            beats=[{'seconds': 0, 'pose': 'open'}, {'seconds': 1, 'pose': 'close'}])
        spec = self.approved('dance-execution', 'creative-relations', {'format': 'vsc.creative-relations/v1', 'project_id': self.p,
            'performances': [{'key': 'dance', 'domain': 'dance', 'method_artifact_id': method['id'], 'shot_ids': [self.objects['shot']],
                'parameters': params, 'materials': [{'media_id': music, 'role': 'music'}]}]}, object_ids=[self.objects['shot']], dependency_ids=[method['id']])
        self.context = self.service.compile_shot_context(self.p, self.objects['shot'], purpose='video_clip')
        self.assertIn(spec['id'], [a['id'] for a in self.context['artifacts']])
        run, _, logical = self.fixture_run()
        with self.assertRaises(ResourceError) as error:
            self.job(run, logical)
        self.assertEqual(error.exception.code, 'professional_binding_missing')
        with self.engine.connect() as conn:
            ex = conn.execute(select(S.execution_instances).where(S.execution_instances.c.project_id == self.p,
                S.execution_instances.c.artifact_id == spec['id'])).mappings().one()
            model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == self.model)).mappings().one()
        registered = self.service.register_model({'provider_id': model['provider_id'], 'model_key': 'dance-audio', 'model_version': '1', 'modality': 'video',
            'capabilities': {'purposes': ['video_clip'], 'first_frame': True, 'reference_audio': True}}, actor='test-human')
        self.model = registered['id']
        logical.update(prompt=logical['prompt'] + '\n' + prompt_fragment('dance', params), reference_audio_media_ids=[music])
        request = self.approved('dance-request', 'quality-request', logical)
        body = json.loads(run['document'])
        body['jobs'][0]['request'] = logical
        requests = requests_for(body)
        body['plan_sha256'] = digest(requests)
        key = next(iter(requests))
        body['professional_bindings'] = [{'execution_id': ex['id'], 'job_ids': [key]}]
        old_quality = self.service.get_artifact_version(self.p, body['quality_plan']['artifact_id'])
        plan = json.loads(old_quality['document'])
        plan['run_binding']['plan_sha256'] = digest(requests)
        plan['inputs'][0]['ref'] = {'artifact_id': request['id'], 'sha256': request['sha256']}
        plan['requirements'][0]['bindings'][0]['expected'] = logical['prompt']
        quality = self.approved('dance-quality', 'quality-plan', plan)
        body['quality_plan'] = {'artifact_id': quality['id'], 'sha256': quality['sha256']}
        pins = {r['id']: r for r in body['approved_inputs']}
        for row in (method, request, quality):
            pins[row['id']] = {'id': row['id'], 'sha256': row['sha256']}
        body['approved_inputs'] = list(pins.values())
        fixed = self.approved('dance-fixed-run', 'production-run', body, dependency_ids=list(pins))
        self.assertEqual(self.job(fixed, logical)['status'], 'created')

    def repin(self, run, changes=None, additional=(), key='rebound'):
        body = json.loads(run['document'])
        if changes:
            changes(body)
        pins = {r['id']: r for r in body['approved_inputs']}
        for item in additional:
            pins[item['id']] = {'id': item['id'], 'sha256': item['sha256']}
        body['approved_inputs'] = list(pins.values())
        return self.approved(key, 'production-run', body, dependency_ids=list(pins))

    def finish(self, job, name):
        self.write('configure_budget', {'limits': {'remote_jobs': 20, 'video_seconds': 100}, 'reason': 'synthetic maximum'})
        self.write('update_generation_job', {'job_id': job['id'], 'status': 'submitted', 'external_task_id': name})
        media = self.media(name, modality='video')
        self.write('update_generation_job', {'job_id': job['id'], 'status': 'succeeded', 'outputs': [{'media_id': media}]})
        return media

    def test_adjacent_two_shot_trial_requires_each_fixed_context(self):
        from vsc.adapters.persistence.postgres.production_guard import requests_for
        from vsc.adapters.persistence.postgres.values import digest
        from vsc.adapters.persistence.postgres.budget_store import native_units
        from vsc.assets.resource_service import ResourceError
        second = self.write('create_object', {'kind': 'shot', 'display_code': 'SHOT2', 'parent_id': self.objects['sequence'], 'ordinal': 1})['id']
        self.artifact('second-shot', 'shot-plan', [second])
        self.select(self.candidate(second, self.first))
        other = self.service.compile_shot_context(self.p, second, purpose='video_clip')
        run, package, logical = self.fixture_run()
        second_request = dict(logical, shot_id=second)
        request_artifact = self.approved('second-request', 'quality-request', second_request)
        body = json.loads(run['document'])
        body['jobs'].append({'candidate_no': 0, 'request': second_request})
        requests = requests_for(body)
        body['plan_sha256'] = digest(requests)
        body['operations'] = {key: native_units(value) for key, value in requests.items()}
        body['trial'].update(allowed_shot_ids=[self.objects['shot'], second], max_remote_jobs=2,
            shot_contexts={self.objects['shot']: self.context['sha256'], second: other['sha256']})
        plan = json.loads(package['document'])
        plan['run_binding'] = {'plan_sha256': digest(requests), 'job_ids': list(requests)}
        second_key = [key for key in requests if second in key][0]
        plan['inputs'].append({'id': 'second', 'job_id': second_key, 'channel': 'request', 'ref': {'artifact_id': request_artifact['id'], 'sha256': request_artifact['sha256']}})
        plan['requirements'][0]['bindings'].append({'input_id': 'second', 'pointer': '/prompt', 'expected': 'synthetic frame'})
        quality = self.approved('two-quality', 'quality-plan', plan)
        body['quality_plan'] = {'artifact_id': quality['id'], 'sha256': quality['sha256']}
        pins = {r['id']: r for r in body['approved_inputs']}
        for row in other['artifacts'] + [request_artifact, quality]:
            pins[row['id']] = {'id': row['id'], 'sha256': row['sha256']}
        body['approved_inputs'] = list(pins.values())
        two = self.approved('two-shot-run', 'production-run', body, dependency_ids=list(pins))
        self.job(two, logical)
        self.write('create_generation_job', {'run_version_id': two['id'], 'shot_id': second, 'purpose': 'video_clip', 'modality': 'video',
            'model_id': self.model, 'context_sha256': other['sha256'], 'request_payload': second_request})
        from vsc.adapters.persistence.postgres.resource_graph import query_graph
        from vsc.production.repair import compare_repairs
        usage = self.service.get_media_usage(self.p, self.first)
        graph = query_graph(self.store, self.p, focus='media:' + self.first, direction='downstream', mode='impact',
            depth=8, limit=300, revision=usage['revision'])
        repair = compare_repairs({'media_id': self.first, 'options': [{'kind': 'local_edit', 'reason': 'prop repair only'}]}, usage, graph)
        self.assertTrue(repair['choices'][0]['transitive_consumers_to_review'])
        self.assertTrue(any(node['kind'] == 'job' for node in repair['choices'][0]['transitive_consumers_to_review']))
        self.assertFalse(repair['execution_authorized'])
        bad = self.repin(two, lambda doc: doc['trial']['shot_contexts'].update({second: '0' * 64}), key='bad-context')
        with self.assertRaises(ResourceError) as error:
            self.write('create_generation_job', {'run_version_id': bad['id'], 'shot_id': second, 'purpose': 'video_clip', 'modality': 'video',
                'model_id': self.model, 'context_sha256': other['sha256'], 'request_payload': second_request})
        self.assertEqual(error.exception.code, 'trial_context_mismatch')

    def test_cross_run_failure_cannot_reset_by_new_run_or_method_label(self):
        from vsc.assets.resource_service import ResourceError
        from vsc.adapters.persistence.postgres.quality_relations import repeated_failures
        run, _, logical = self.fixture_run()
        method = next(row for row in json.loads(run['document'])['approved_inputs']
            if self.service.get_artifact_version(self.p, row['id'])['artifact_type'] == 'trial-method')
        for number in range(2):
            current = run if number == 0 else self.repin(run, key='renamed-run')
            job = self.job(current, logical)
            output = self.finish(job, 'failed-observation-' + str(number))
            self.approved('observation-' + str(number), 'quality-observation', {'format': 'vsc.quality-observations/v1', 'project_id': self.p,
                'observations': [{'job_id': job['id'], 'media_id': output, 'result': 'failed', 'defect_code': 'contact',
                    'observation': 'hand does not touch prop', 'position': {'seconds': [1, 2]}, 'criteria_artifact_id': self.script,
                    'method_artifact_id': method['id'], 'effort_seconds': 10, 'wait_seconds': None, 'cost_basis': 'unknown'}]},
                dependency_ids=[self.script, method['id']])
        new = self.repin(run, key='third-name')
        with self.assertRaises(ResourceError) as error:
            self.job(new, logical)
        self.assertEqual(error.exception.code, 'repeated_failure_stop')
        with self.engine.connect() as conn:
            self.assertEqual(len(repeated_failures(self.store, conn, self.p, self.objects['shot'], 'video_clip')['contact']), 2)
        changed = self.repin(run, lambda doc: doc.update(route_change={'reason': 'just renamed', 'defect_codes': ['contact'], 'changed_variables': ['label']}), key='same-method')
        with self.assertRaises(ResourceError) as error:
            self.job(changed, logical)
        self.assertEqual(error.exception.code, 'repeated_failure_stop')
        self.assertEqual(self.service.budget_status(self.p)['used']['remote_jobs'], 2)

    def test_real_method_evaluation_resolves_risk_but_environment_drift_blocks(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.production_guard import validate_guard
        from vsc.adapters.persistence.postgres.quality_relations import environment_digest
        from vsc.assets.resource_service import ResourceError
        trial, package, logical = self.fixture_run()
        output = self.finish(self.job(trial, logical), 'evaluation-output')
        baseline = self.media('baseline video', modality='video')
        method = next(row for row in json.loads(trial['document'])['approved_inputs']
            if self.service.get_artifact_version(self.p, row['id'])['artifact_type'] == 'trial-method')
        criteria = self.service.get_artifact_version(self.p, self.script)
        for media in (baseline, output):
            candidate = self.candidate(self.objects['shot'], media, role='video_take')
            self.write('record_review', {'candidate_id': candidate['candidate_id'], 'outcome': 'pass', 'reason': 'synthetic fixed criteria',
                'reviewer_type': 'human', 'criteria_version': criteria['sha256']})
        output_candidate = candidate
        with self.engine.connect() as conn:
            model = dict(conn.execute(select(S.provider_models).where(S.provider_models.c.id == self.model)).mappings().one())
        evaluation_doc = {'format': 'vsc.method-evaluation/v1', 'project_id': self.p, 'method_artifact_id': method['id'],
            'trial_run_id': trial['id'], 'baseline_media_id': baseline, 'output_media_id': output, 'criteria_artifact_id': self.script,
            'result': 'pass', 'observations': 'fixed framing matched baseline with less motion', 'environment_sha256': environment_digest(model, logical)}
        evaluation = self.approved('method-eval', 'method-evaluation', evaluation_doc, dependency_ids=[method['id'], trial['id'], self.script])
        plan = json.loads(package['document'])
        plan['risks'] = [{'id': 'motion', 'hypothesis': 'bounded motion', 'stop_condition': 'two failures',
            'method_artifact_id': method['id'], 'criteria_artifact_id': self.script,
            'evaluation_ref': {'artifact_id': evaluation['id'], 'sha256': evaluation['sha256']}}]
        quality = self.approved('evaluated-quality', 'quality-plan', plan)
        def production(body):
            body.update(phase='production', quality_plan={'artifact_id': quality['id'], 'sha256': quality['sha256']})
            body.pop('trial')
        run = self.repin(trial, production, additional=[trial, evaluation, quality], key='production-with-proof')
        with self.engine.connect() as conn:
            validate_guard(self.store, conn, self.store._project(conn, self.p), run, context=self.context, model=model)
            changed = dict(model, capabilities=dict(model['capabilities'], changed=True))
            with self.assertRaises(ResourceError) as error:
                validate_guard(self.store, conn, self.store._project(conn, self.p), run, context=self.context, model=changed)
            self.assertEqual(error.exception.code, 'quality_plan_blocked')
        bare = dict(evaluation_doc, output_media_id=baseline)
        with self.assertRaises(ResourceError):
            self.approved('fake-eval', 'method-evaluation', bare, dependency_ids=[method['id'], trial['id'], self.script])
        animatic = self.approved('approved-animatic', 'animatic', {'previews': 'synthetic preview'}, stage='animatic')
        self.context = self.service.compile_shot_context(self.p, self.objects['shot'], purpose='video_clip')
        actual = self.repin(run, additional=[animatic], key='formal-ready')
        job = self.job(actual, logical)
        self.assertEqual(job['status'], 'created')
        self.write('record_review', {'candidate_id': output_candidate['candidate_id'], 'outcome': 'fail', 'reason': 'later observed defect',
            'reviewer_type': 'human', 'criteria_version': criteria['sha256']})
        with self.assertRaises(ResourceError) as error:
            self.write('update_generation_job', {'job_id': job['id'], 'status': 'submitted', 'external_task_id': 'must-not-submit'})
        self.assertEqual(error.exception.code, 'quality_plan_blocked')
