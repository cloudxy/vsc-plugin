"""Synthetic fixed specifications through real isolated PG and job consumers.

No provider submission, media generation, human preference, or creative approval.
"""
import copy
import json
import unittest
import uuid

from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL
from support.fixtures.trial_quality import TrialQualityFixture


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'isolated PostgreSQL required')
class PerformanceSpaceProcessTests(TrialQualityFixture, unittest.TestCase):
    def ensemble(self, process=False):
        self.people = {}
        entities = []
        identities=([('PEG','object'),('JIG','object'),('TABLE','object'),('ROOM','location')] if process else
                    [('A','character'),('B','character'),('C','character'),('ROOM','location')])
        for key, kind in identities:
            identifier=self.write('create_object',dict(kind='asset',display_code=key,asset_kind=kind))['id']
            self.people[key]=identifier
            role='identity_face' if kind=='character' else 'location_master' if kind=='location' else 'prop'
            self.select(self.candidate(identifier,self.media('reference '+key),role=role))
            entity=dict(id=key,kind=kind,name=key,identity=['fixed original '+key],variants={'default':'fixed blue cloth' if kind=='character' else 'fixed room'})
            if kind=='character':entity['expression_baseline']={'description':'relaxed brow and closed mouth'}
            entities.append(entity)
        self.bible_document=dict(format='vsc.asset-bible/v1',project_id=self.p,entities=entities)
        self.approved('ensemble-bible','vsc.asset_bible',self.bible_document)
        snapshot=dict(format='vsc.scene-state/v1',project_id=self.p,scenes=[dict(id='SCENE',location_id='ROOM',
            spatial=dict(frame='floor',unit='m'),baseline=dict(entities={key:dict(position=dict(frame='floor',x=x,y=0),expression='relaxed brow')
                for key,x in [('A',0),('B',2),('C',-2)]}),shots=[dict(id='SHOT',in_frame=['A','B','C'],
                camera=dict(spatial=dict(frame='floor',x=1,y=-3,axis=['A','B'],mirrored=False)),people_check=True,changes={})])])
        if process:
            from vsc.knowledge.recipes import load
            recipe=next(r for r in load()['recipes'] if r['id']=='AR-motion-peg-assembly')
            scene=snapshot['scenes'][0]
            scene['baseline']['entities']={key:dict(position=dict(frame='floor',x=x,y=0),pose='aligned' if key=='PEG' else 'fixed')
                                          for key,x in [('PEG',0),('JIG',0.5),('TABLE',1)]}
            shot=snapshot['scenes'][0]['shots'][0]
            shot['in_frame']=['PEG','JIG','TABLE'];shot['people_check']=False
            shot['camera']['spatial']['axis']=['PEG','JIG']
            shot['changes']={'entities':{'PEG':{'position':dict(frame='floor',x=0.5,y=0),'pose':'seat the final peg'}}}
            shot['process']=copy.deepcopy(recipe['spec']['process'])
            shot['process']['fixed_entities']=['TABLE','JIG']
        self.state_document=snapshot
        self.approved('state','vsc.scene_state',snapshot,object_ids=[self.objects['scene']])
        self.write('create_source_intake',dict(intent='screenplay',title='original synthetic engineering source',
            content='SC1\nThree original figures keep their positions. An original peg seats in its jig.'))
        self.approved('synthetic-animatic','animatic',{'spec':'synthetic engineering animatic; no media or creative approval'})
        self.context=self.service.compile_shot_context(self.p,self.objects['shot'],purpose='video_clip')
        self.assertTrue(self.context['ready'],self.context['gaps'])

    def chain(self):
        from vsc.knowledge.recipes import load
        method=self.approved('ensemble-method','trial-method',{'method':'one actor offers a feint; second withdraws; third blocks the passage without contact'})
        recipe=next(r for r in load()['recipes'] if r['id']=='AR-fight-paper-current-relay')
        params=copy.deepcopy(recipe['spec']['execution']['parameters'])
        bindings={'<A_INSTANCE>':'a','<B_INSTANCE>':'b','<C_INSTANCE>':'c'}
        for node in params['chain']:
            for field in ('actor_instance','counterpart_instance'):node[field]=bindings[node[field]]
        doc=dict(format='vsc.creative-relations/v1',project_id=self.p,
            instances=[dict(key=k.lower(),asset_id=self.people[k],scene_id=self.objects['scene'],shot_id=self.objects['shot']) for k in ('A','B','C')],
            performances=[dict(key='ensemble',domain='combat',method_artifact_id=method['id'],shot_ids=[self.objects['shot']],
                participants=[dict(instance=k,role='fighter') for k in ('a','b','c')],parameters=params)])
        doc['performances'].append(dict(key='paper-trace',domain='vfx',method_artifact_id=method['id'],shot_ids=[self.objects['shot']],
            participants=[dict(instance='a',role='caster'),dict(instance='b',role='target')],
            parameters=copy.deepcopy(recipe['spec']['vfx_execution']['parameters'])))
        return doc,method,params

    def register_chain(self, doc, method, key='ensemble-relations'):
        return self.approved(key,'creative-relations',doc,object_ids=[self.objects['shot']],dependency_ids=[method['id']])

    def bind_request(self, run, logical, execution=None, additional=()):
        from vsc.adapters.persistence.postgres.production_guard import requests_for
        from vsc.adapters.persistence.postgres.values import digest
        body=json.loads(run['document']);body['jobs'][0]['request']=logical
        requests=requests_for(body);body['plan_sha256']=digest(requests)
        if execution:body['professional_bindings']=[dict(execution_id=identifier,job_ids=list(requests))
                                                   for identifier in (execution if isinstance(execution,list) else [execution])]
        request=self.approved('prepared-request','quality-request',logical)
        old=self.service.get_artifact_version(self.p,body['quality_plan']['artifact_id'])
        plan=json.loads(old['document']);plan['run_binding']['plan_sha256']=digest(requests)
        plan['inputs'][0]['ref']=dict(artifact_id=request['id'],sha256=request['sha256'])
        plan['requirements'][0]['bindings'][0]['expected']=logical['prompt']
        state=next((a for a in self.context['artifacts'] if a['artifact_type']=='vsc.scene_state'),None)
        if state and self.state_document['scenes'][0]['shots'][0].get('people_check'):
            plan['requirements'].append(dict(id='people',priority='must',criterion='observe fixed in_frame identities and duplicates; occlusion remains unsure',
                tolerance='three distinct fixed identities',source=dict(artifact_id=state['id'],sha256=state['sha256'],pointer='/scenes/0/shots/0/in_frame'),
                bindings=[dict(input_id='actual',pointer='/prompt',expected=logical['prompt'])]))
        quality=self.approved('prepared-quality','quality-plan',plan)
        body['quality_plan']=dict(artifact_id=quality['id'],sha256=quality['sha256'])
        pins={row['id']:row for row in body['approved_inputs']}
        for row in (request,quality)+tuple(additional):pins[row['id']]=dict(id=row['id'],sha256=row['sha256'])
        body['approved_inputs']=list(pins.values())
        return self.approved('prepared-run','production-run',body,dependency_ids=list(pins))

    def assert_adapter_payload(self, logical):
        from vsc.adapters.providers.volc_ark.provider import VolcArkVideoProvider
        from vsc.production.providers import VideoRequest
        captured=[]
        def offline_transport(path,payload):
            captured.append((path,payload));return {'id':'synthetic-offline-compiler-only'}
        adapter=VolcArkVideoProvider('synthetic-model',lambda media:'asset://'+media,'720p','16:9',transport=offline_transport)
        adapter.submit(VideoRequest(shot_id=self.objects['shot'],purpose='video_clip',context_sha256=self.context['sha256'],
            prompt=logical['prompt'],duration_ms=logical['duration_ms'],first_frame_media_id=logical['first_frame_media_id']))
        self.assertEqual(captured[0][1]['content'][0]['text'],logical['prompt'])
        self.assertIn('asset://'+logical['first_frame_media_id'],json.dumps(captured[0][1]))

    def test_three_same_role_people_chain_reaches_fixed_job_and_submission_guard(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.production_guard import validate_submission
        from vsc.production.performance import prompt_fragment
        from vsc.story.consistency import compile_state_request
        from vsc.assets.resource_service import ResourceError
        self.ensemble()
        doc,method,params=self.chain();spec=self.register_chain(doc,method)
        self.context=self.service.compile_shot_context(self.p,self.objects['shot'],purpose='video_clip')
        self.assertTrue(self.context['request_constraints'])
        with self.engine.connect() as conn:
            executions=list(conn.execute(select(S.execution_instances).where(S.execution_instances.c.project_id==self.p,S.execution_instances.c.artifact_id==spec['id'])).mappings())
            execution=next(row for row in executions if row['domain']=='combat')
            participants=list(conn.execute(select(S.execution_participants).where(S.execution_participants.c.project_id==self.p,S.execution_participants.c.execution_id==execution['id'])).mappings())
        self.assertEqual(len({p['instance_id'] for p in participants}),3)
        self.assertEqual({p['role'] for p in participants},{'fighter'})
        run,_,logical=self.fixture_run(phase='production')
        with self.assertRaises(ResourceError) as missing:self.job(run,logical)
        self.assertEqual(missing.exception.code,'state_constraint_missing')
        prepared=compile_state_request(logical,self.context)
        prepared['prompt']+='\n'+prompt_fragment('combat',params)
        prepared['prompt']+='\n'+prompt_fragment('vfx',doc['performances'][1]['parameters'])
        fixed=self.bind_request(run,prepared,[row['id'] for row in executions],additional=[method])
        job=self.job(fixed,prepared)
        stored=self.service.get_generation_job(self.p,job['id'])
        self.assertEqual(stored['request_payload']['prompt'],prepared['prompt'])
        self.assertIn('counterpart_instance',stored['request_payload']['prompt'])
        self.assertIn(params['world_rule'],stored['request_payload']['prompt'])
        self.assert_adapter_payload(stored['request_payload'])
        from vsc.story.consistency import anchor_pack
        from vsc.adapters.providers.volc_ark.api import checklist
        observations=checklist(anchor_pack(self.bible_document,self.state_document,'SHOT'),None)
        self.assertTrue(any('预期人数=3' in item and 'unsure' in item for item in observations))
        with self.engine.connect() as conn:
            validate_submission(self.store,conn,self.store._project(conn,self.p),stored)

    def test_chain_rejects_missing_cross_project_duplicate_identity_cycles_and_phase_order(self):
        from vsc.assets.resource_service import ResourceError
        self.ensemble();doc,method,_=self.chain()
        for kind in ('missing','unregistered','cycle','phase','duplicate','copied-identity'):
            bad=copy.deepcopy(doc);perf=bad['performances'][0]
            if kind=='missing':perf['parameters']['chain'][1]['actor_instance']=str(uuid.uuid4())
            if kind=='unregistered':perf['parameters']['chain'][1]['actor_instance']='c';perf['participants'].pop()
            if kind=='cycle':perf['parameters']['chain'][0]['after']=[perf['parameters']['chain'][1]['id']]
            if kind=='phase':perf['parameters']['chain'][1]['phases'].reverse()
            if kind=='duplicate':perf['participants'].append(dict(instance='a',role='observer'))
            if kind=='copied-identity':bad['instances'][2]['asset_id']=self.people['A']
            with self.subTest(kind=kind),self.assertRaises(ResourceError):self.register_chain(bad,method,key='bad-'+kind)
        # A real existing instance from another project must not resolve locally.
        other=self.service.create_project({'name':'foreign synthetic'},actor='test-human')['id']
        current_p,current_rev=self.p,self.rev
        try:
            self.p,self.rev=other,0
            hierarchy=self.hierarchy()
            asset=self.write('create_object',dict(kind='asset',display_code='FOREIGN',asset_kind='character'))['id']
            foreign=self.approved('foreign-use','creative-relations',dict(format='vsc.creative-relations/v1',project_id=other,
                instances=[dict(key='foreign',asset_id=asset,scene_id=hierarchy['scene'],shot_id=hierarchy['shot'])]),object_ids=[hierarchy['shot']])
            from sqlalchemy import select
            from vsc.adapters.persistence.postgres import schema as S
            with self.engine.connect() as conn:
                foreign_instance=conn.execute(select(S.asset_use_instances.c.id).where(S.asset_use_instances.c.project_id==other,
                    S.asset_use_instances.c.artifact_id==foreign['id'])).scalar_one()
        finally:
            self.p,self.rev=current_p,current_rev
        bad=copy.deepcopy(doc)
        bad['performances'][0]['parameters']['chain'][1]['actor_instance']=foreign_instance
        with self.assertRaises(ResourceError):self.register_chain(bad,method,key='cross-project')
        self.assertTrue(self.register_chain(doc,method)['id'])

    def test_explicit_process_prepares_real_request_and_advisory_checklist_without_provider(self):
        from vsc.story import consistency as C
        from vsc.adapters.providers.volc_ark.api import checklist
        from vsc.assets.resource_service import ResourceError
        self.ensemble(process=True)
        run,_,logical=self.fixture_run(phase='production')
        with self.assertRaises(ResourceError) as missing:self.job(run,logical)
        self.assertEqual(missing.exception.code,'state_constraint_missing')
        prepared=C.compile_state_request(logical,self.context)
        self.assertEqual(prepared,C.compile_state_request(prepared,self.context))
        self.assertIn('unlisted_changes',prepared['prompt'])
        fixed=self.bind_request(run,prepared)
        job=self.job(fixed,prepared)
        self.assertEqual(job['status'],'created')
        self.assert_adapter_payload(self.service.get_generation_job(self.p,job['id'])['request_payload'])
        pack=C.anchor_pack(self.bible_document,self.state_document,'SHOT')
        observations=checklist(pack,None)
        self.assertTrue(any('预期人数=0' in x for x in observations))
        self.assertTrue(any('过程阶段' in x for x in observations))
        self.assertTrue(any('未列 changes' in x for x in observations))
        # No visual report, media or human preference is fabricated by this check.

    def test_original_pg_contract_entry_rejects_unexplained_axis_and_fixed_object_changes(self):
        from vsc.assets.resource_service import ResourceError
        self.ensemble()
        self.write('create_object',dict(kind='shot',display_code='NEXT',parent_id=self.objects['sequence'],ordinal=1))
        bad=copy.deepcopy(self.state_document)
        later=copy.deepcopy(bad['scenes'][0]['shots'][0]);later['id']='NEXT';later['camera']['spatial']['y']=3
        bad['scenes'][0]['shots'].append(later)
        with self.assertRaises(ResourceError) as crossing:
            self.write('create_artifact',dict(artifact_key='state',artifact_type='vsc.scene_state',document=bad))
        self.assertIn('越轴',str(crossing.exception))
        later['camera']['spatial']['crossing_reason']='a visible orbit establishes the new side'
        fixed=self.approved('state','vsc.scene_state',bad,object_ids=[self.objects['scene']])
        self.assertTrue(fixed['approved'])
        bad=copy.deepcopy(self.state_document);shot=bad['scenes'][0]['shots'][0]
        shot['changes']={'entities':{'A':{'pose':'moves despite being fixed'}}}
        shot['process']=dict(enabled=True,fixed_entities=['A'],direction=dict(frame='floor',axis='x',sign=1),
            beats=[dict(seconds=0,action='align'),dict(seconds=1,action='finish')])
        with self.assertRaises(ResourceError) as fixed_object:
            self.write('create_artifact',dict(artifact_key='state',artifact_type='vsc.scene_state',document=bad))
        self.assertIn('固定物',str(fixed_object.exception))
