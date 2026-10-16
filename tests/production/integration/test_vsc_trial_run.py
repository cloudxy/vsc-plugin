"""Pre-animatic trial authorization through the real run/budget seam, offline."""
import copy
import json
import unittest
from unittest import mock

from support.fixtures.production import ProductionFixture
from support.fixtures.project import FixedRunFixture
from vsc.knowledge import learning
from vsc.production import run_trial, run_quality
import vsc_artifacts as artifacts
import vsc_budget as budget
import vsc_production as production
import vsc_run as formal
import vsc_state as state_module


class TrialRunTests(ProductionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fixture = FixedRunFixture(self.project)
        self.fixture.state['profile_snapshot']['stages'].insert(0, {'id': 'script', 'required': ['vsc.screenplay']})
        self.fixture.state['profile_sha256'] = state_module.profile_digest(self.fixture.state['profile_snapshot'])
        self.fixture.write_state()
        self.batch['jobs'] = self.batch['jobs'][:2]
        self.batch['jobs'][0]['args'].update(purpose='candidate', shot='SH-001', moment='entry')
        bible = self.fixture.register('vsc.asset_bible', production.read(self.project / 'bible.json'), stage='design')
        scene = self.fixture.register('vsc.scene_state', production.read(self.project / 'state.json'), stage='design')
        script = self.fixture.register('vsc.screenplay', {'format': 'vsc.screenplay/v1',
            'trial_prompts': {job['id']: job['args']['prompt'] for job in self.batch['jobs']}}, stage='script')
        shots = self.fixture.register('vsc.shot_plan', {'shots': [{'id': 'SH-001'}]}, stage='design')
        self.inputs = [bible, scene, script, shots]
        for job in self.batch['jobs']:
            job['args'].update(bible={'path': bible['path']}, state={'path': scene['path']})
        self.batch_path = self.project / 'batch.json'
        self.batch_path.write_text(json.dumps(self.batch))
        plan = production.build_plan(self.project, self.batch)
        state = self.fixture.read_state()
        capability = {'id': 'C-001', 'name': 'Synthetic contact trial', 'kind': 'action',
            'method': 'one bounded contact', 'limits': 'one shot', 'allowed_roles': ['generation-producer'],
            'tags': [], 'status': 'pilot', 'origin': 'imported_method',
            'import_review': {'by': 'synthetic human', 'note': 'fixture import review'},
            'decision': {'by': 'synthetic human', 'note': 'fixture pilot decision'}}
        context_path = self.project / 'context.json'
        context_path.write_text(json.dumps({'format': 'vsc.role-context/v1', 'fixture': 'fixed synthetic context'}))
        context_sha = artifacts.digest(context_path)
        versions = [learning.artifact_snapshot(row) for row in self.inputs]
        state['contexts'] = [{'id': 'CT-001', 'path': 'context.json', 'sha256': context_sha,
                              'sha256_16': context_sha[:16], 'input_versions': versions}]
        trial = {'id': 'TR-001', 'capability_id': capability['id'], 'context_id': 'CT-001',
            'context_sha256': context_sha, 'context_sha256_16': context_sha[:16],
            'method_sha256': learning.method_digest(capability), 'input_versions': versions}
        state['learning'] = {'capabilities': [capability], 'trials': [trial], 'observations': []}
        state_module.write_json(self.project / 'vsc.json', state)
        self.quality = {'format': 'vsc.quality-plan/v1', 'project_id': state['project_id'],
            'run_binding': {'plan_sha256': plan['plan_sha256'], 'job_ids': ['image', 'first']},
            'requirements': [], 'inputs': [], 'attempts': [],
            'risks': [{'id': 'contact', 'hypothesis': 'contact can be controlled', 'stop_condition': 'two jobs'}]}
        for index, job in enumerate(self.batch['jobs']):
            self.quality['inputs'].append({'id': job['id'], 'job_id': job['id'], 'channel': 'request',
                'ref': {'path': 'batch.json', 'sha256': artifacts.digest(self.batch_path), 'pointer': f'/jobs/{index}/args'}})
            self.quality['requirements'].append({'id': job['id'], 'priority': 'must', 'criterion': 'fixed action',
                'tolerance': 'exact prompt', 'source': {'path': script['path'], 'sha256': script['sha256'],
                    'pointer': '/trial_prompts/' + job['id']},
                'bindings': [{'input_id': job['id'], 'pointer': '/prompt', 'equals_source': True}]})
        self.quality_path = self.project / 'quality.json'
        self.quality_path.write_text(json.dumps(self.quality))
        self.data = {'format': formal.FORMAT, 'project_id': state['project_id'], 'scope': 'project', 'phase': 'trial',
            'batch': {'path': 'batch.json', 'sha256': artifacts.digest(self.batch_path)},
            'plan_sha256': plan['plan_sha256'], 'approved_inputs': [{'id': a['id'], 'sha256': a['sha256']} for a in self.inputs],
            'operations': {formal.operation(j): formal.job_units(j) for j in plan['jobs']}, 'review_after': ['image'],
            'quality_plan': {'path': 'quality.json', 'sha256': artifacts.digest(self.quality_path)},
            'trial': {'trial_id': trial['id'], 'context_sha256': context_sha, 'method_sha256': trial['method_sha256'],
                'hypothesis': 'one contact is controllable', 'criteria': 'hand and prop meet in usable interval',
                'stop_condition': 'at most two fixed operations, no automatic resubmission', 'max_remote_jobs': 2,
                'allowed_shot_ids': ['SH-001'], 'allowed_asset_ids': [row['id'] for row in production.read(self.project / bible['path'])['entities']]}}
        self.item = self.fixture.register('vsc.production_run', self.data, self.inputs)
        budget.configure(self.project, {'remote_jobs': 2, 'images': 1, 'video_seconds': 5}, 'synthetic human', 'bounded trial')
        for module in (formal, artifacts, state_module, run_trial):
            patch = mock.patch.object(module, 'validate_artifact', side_effect=self.fixture.validator)
            patch.start()
            self.addCleanup(patch.stop)

    def errors(self, data=None):
        return formal.project_errors(data or self.data, self.project, self.fixture.read_state(), self.item)

    def test_trial_runs_before_animatic_using_script_gate_and_shared_budget(self):
        self.assertEqual(self.errors(), [])
        state = self.fixture.read_state()
        self.assertFalse(any(row['type'] == 'vsc.animatic' for row in state['artifacts']))
        result = formal.execute(self.project, self.item['id'], self.runner)
        self.assertEqual(result['status'], 'awaiting_review')
        candidates = [row for row in self.fixture.read_state()['artifacts'] if row.get('run_id') == self.item['id']]
        self.assertEqual(len(candidates), 1)
        self.assertEqual((candidates[0]['status'], candidates[0]['production_phase'], candidates[0]['trial_id']),
                         ('draft', 'trial', 'TR-001'))
        self.assertTrue({a['id'] for a in self.inputs} <= set(candidates[0]['depends_on']))
        with budget.ledger(self.project) as ledger:
            self.assertEqual(budget.usage(ledger)['remote_jobs'], 2)

    def test_missing_run_approval_and_script_gate_never_submit(self):
        state = self.fixture.read_state()
        next(row for row in state['artifacts'] if row['id'] == self.item['id'])['status'] = 'draft'
        state_module.write_json(self.project / 'vsc.json', state)
        with self.assertRaisesRegex(ValueError, 'run 无效'):
            formal.execute(self.project, self.item['id'], self.runner)
        state = self.fixture.read_state()
        next(row for row in state['artifacts'] if row['type'] == 'vsc.screenplay')['status'] = 'draft'
        state_module.write_json(self.project / 'vsc.json', state)
        with mock.patch.object(formal, 'load_run', return_value=(state, self.item, self.data)):
            with self.assertRaisesRegex(ValueError, '质量门'):
                formal.execute(self.project, self.item['id'], self.runner)
        self.assertEqual(self.calls, [])

    def test_trial_limits_context_assets_and_method_are_enforced(self):
        for change, expected in [({'max_remote_jobs': 1}, '限定次数'),
            ({'allowed_shot_ids': ['SH-OTHER']}, '限定镜头'),
            ({'allowed_asset_ids': ['主角']}, '限定资产'),
            ({'method_sha256': 'f' * 64}, '摘要不匹配')]:
            data = copy.deepcopy(self.data)
            data['trial'].update(change)
            self.assertTrue(any(expected in error for error in self.errors(data)), self.errors(data))
        (self.project / 'context.json').write_text('{}')
        self.assertTrue(any('上下文' in error for error in self.errors()))

    def test_quality_drift_or_missing_actual_request_blocks_before_provider(self):
        self.quality['inputs'].pop()
        self.quality_path.write_text(json.dumps(self.quality))
        with self.assertRaisesRegex(ValueError, '制作前检查'):
            formal.execute(self.project, self.item['id'], self.runner)
        self.assertEqual(self.calls, [])
        data = copy.deepcopy(self.data)
        data['quality_plan']['sha256'] = artifacts.digest(self.quality_path)
        self.assertTrue(any('全部实际请求' in error for error in self.errors(data)))

    def test_quality_cannot_cover_a_different_request_with_same_job_id(self):
        different = copy.deepcopy(self.batch['jobs'][0]['args'])
        different['prompt'] = 'unapproved substitute'
        requests = {j['id']: j['args'] for j in self.batch['jobs']}
        requests['image'] = different
        errors = run_quality.quality_errors(self.data, self.project, self.fixture.read_state(), self.item, requests)
        self.assertTrue(any('实际固定输入' in error for error in errors))

    def test_trial_candidate_requires_explicit_adoption_and_animatic_gate(self):
        formal.execute(self.project, self.item['id'], self.runner)
        state = self.fixture.read_state()
        candidate = next(row for row in state['artifacts'] if row.get('run_id') == self.item['id'])
        ref = {'id': candidate['id'], 'sha256': candidate['sha256']}
        selection = {'items': [{'source': {'artifact': ref}}]}
        errors = run_trial.adoption_errors(selection, self.project, state, {'scope': 'project'})
        self.assertTrue(any('trial_adoptions' in error for error in errors))
        selection['trial_adoptions'] = [{'artifact': ref, 'reason': 'synthetic human adopts this interval'}]
        self.assertTrue(any('animatic Gate' in error for error in run_trial.adoption_errors(
            selection, self.project, state, {'scope': 'project'})))
        with mock.patch.object(state_module, 'gate_problems', return_value=[]):
            self.assertEqual(run_trial.adoption_errors(selection, self.project, state, {'scope': 'project'}), [])

    def test_optional_quality_does_not_change_old_run_contract(self):
        old = copy.deepcopy(self.data)
        old.pop('trial')
        old.pop('quality_plan')
        old['phase'] = 'production'
        self.assertEqual(formal.validation_errors(old), [])
        self.assertEqual(run_quality.quality_errors(old, self.project, {}, {}, {}), [])


if __name__ == '__main__':
    unittest.main()
