"""Formal inspection and pre-animatic asset preparation, offline transport only."""
import copy
import json
import unittest
from unittest import mock
from _paths import ROOT
from test_vsc_budget import FixedRunFixture
import test_vsc_production as media_fixture
import vsc_artifacts as artifacts
import vsc_audio_run as single
import vsc_budget as budget
import vsc_run as formal
import vsc_state as state_module
import volc_ark as ark


class InspectionRun(unittest.TestCase):
    video=media_fixture.QueueTest.video
    @classmethod
    def setUpClass(cls): media_fixture.QueueTest.setUpClass.__func__(cls)
    def setUp(self):
        media_fixture.QueueTest.setUp(self)
        self.fixture=FixedRunFixture(self.project)
        self.bible=self.fixture.register('vsc.asset_bible',json.loads((self.project/'bible.json').read_text()),stage='animatic')
        self.scene=self.fixture.register('vsc.scene_state',json.loads((self.project/'state.json').read_text()),stage='animatic')
        self.media=self.project/'subject.png'; self.media.write_bytes(self.png)
        request={'kind':'inspect','argv':['--bible',self.bible['path'],'--state',self.scene['path'],'--shot','SH-001','--moment','entry','--media','subject.png']}
        _,self.args,self.binding,self.op,self.bound=single.prepare(self.project,request)
        self.data={'format':formal.FORMAT,'project_id':'test-project','scope':'project','phase':'asset',
            'audio_request':{**request,'binding':self.binding},'plan_sha256':ark.digest_json(self.binding),
            'approved_inputs':[{'id':a['id'],'sha256':a['sha256']} for a in (self.bible,self.scene)],
            'review_after':[],'operations':{self.op:self.bound}}
        self.run=self.fixture.register('vsc.production_run',self.data,[self.bible,self.scene])
        for module in (artifacts,formal,state_module):
            patch=mock.patch.object(module,'validate_artifact',side_effect=self.fixture.validator)
            patch.start();self.addCleanup(patch.stop)
        budget.configure(self.project,self.bound,'synthetic reviewer','one inspection')
        items=self.binding['checklist']
        answer={'results':[{'item':item,'verdict':'pass','evidence':'synthetic offline evidence'} for item in items],'issues':[]}
        self.response={'choices':[{'message':{'content':json.dumps(answer)}}],'usage':{'requests':1}}
    def test_asset_inspect_fixed_run_budget_draft_and_free_resume(self):
        self.assertEqual(single.project_errors(self.data,self.project,self.fixture.read_state(),self.run),[])
        with mock.patch.object(state_module,'gate_problems',return_value=[]) as gate, \
                mock.patch.object(ark,'api_key',return_value='offline-inspection-test'), \
                mock.patch.object(ark,'call',return_value=self.response) as transport, \
                mock.patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('live networking forbidden')):
            result=formal.execute(self.project,self.run['id'])
            gate.assert_called_with(self.project,mock.ANY,'script',None)
            self.assertTrue(result['advisory'])
            self.assertEqual(result['binding'],self.binding)
            self.assertEqual(transport.call_count,1)
            state=self.fixture.read_state()
            imported=[a for a in state['artifacts'] if a['type']=='vsc.visual_check']
            self.assertEqual(len(imported),1); self.assertEqual(imported[0]['status'],'draft')
            formal.execute(self.project,self.run['id'])
            self.assertEqual(transport.call_count,1)
            self.assertEqual(len([a for a in self.fixture.read_state()['artifacts'] if a['type']=='vsc.visual_check']),1)
        with budget.ledger(self.project) as ledger:
            self.assertEqual(budget.usage(ledger)['vision_jobs'],1)
            self.assertEqual(list(ledger['reservations'].values())[0]['status'],'usage_unknown')
    def test_bound_inspection_drift_fails_before_transport(self):
        data=copy.deepcopy(self.data); self.media.write_bytes(self.jpeg)
        self.assertTrue(single.project_errors(data,self.project,self.fixture.read_state(),self.run))
        with mock.patch.object(state_module,'gate_problems',return_value=['synthetic blocked']) as gate, mock.patch.object(ark,'call') as call:
            with self.assertRaisesRegex(ValueError,'质量门'): formal.execute(self.project,self.run['id'])
            call.assert_not_called()
    def test_asset_batch_requires_specs_but_no_future_animatic(self):
        batch=copy.deepcopy(self.batch); batch['jobs']=batch['jobs'][:1]
        path=self.project/'asset-batch.json';path.write_text(json.dumps(batch))
        import vsc_production as production
        plan=production.build_plan(self.project,batch)
        job=plan['jobs'][0]
        data={'format':formal.FORMAT,'project_id':'test-project','scope':'project','phase':'asset',
              'batch':{'path':path.name,'sha256':artifacts.digest(path)},'plan_sha256':plan['plan_sha256'],
              'approved_inputs':[{'id':self.bible['id'],'sha256':self.bible['sha256']}],
              'review_after':[],'operations':{formal.operation(job):formal.job_units(job)}}
        owner=self.fixture.register('vsc.production_run',data,[self.bible])
        self.assertEqual(formal.project_errors(data,self.project,self.fixture.read_state(),owner),[])
        data['phase']='production'
        self.assertTrue(any('animatic' in e for e in formal.project_errors(data,self.project,self.fixture.read_state(),owner)))


if __name__=='__main__': unittest.main()
