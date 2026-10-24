"""Synthetic PostgreSQL creative relationships and bounded workspace regression."""
import unittest,uuid
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'isolated PostgreSQL required')
class WorkbenchTest(ResourceStoreFixture,unittest.TestCase):
    def test_inline_candidate_pages_pin_media_and_target_without_borrowing_another_shot(self):
        h=self.hierarchy()
        media=self.media('同一参考素材')
        own=[self.candidate(h['shot'],media,slot_key='own-'+str(i))['candidate_id'] for i in range(26)]
        other=self.write('create_object',dict(kind='shot',parent_id=h['sequence'],display_code='OTHER',title='另一镜',ordinal=1))['id']
        foreign=self.candidate(other,media)['candidate_id']
        one=self.query(object_id=h['shot'],section='candidates',entity_id=media,limit=24)['sections']['candidates']
        two=self.query(object_id=h['shot'],section='candidates',entity_id=media,limit=24,offset=one['next_offset'])['sections']['candidates']
        rows=one['items']+two['items']
        self.assertEqual((one['total'],len(one['items']),len(two['items'])),(26,24,2))
        self.assertEqual({row['id'] for row in rows},set(own))
        self.assertNotIn(foreign,{row['id'] for row in rows})
        self.assertTrue(all(row['object_id']==h['shot'] and row['target_title']=='SHOT' for row in rows))

    def test_render_collection_and_time_locator_use_fixed_outputs_and_timeline_not_source_clips(self):
        from vsc.adapters.persistence.postgres.workbench import render_position
        from vsc.assets.resource_service import ResourceError
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.seed_generation_timeline_render()
        renders=self.query(section='renders',limit=1)['sections']['renders']
        self.assertEqual(renders['total'],1)
        output=renders['items'][0]
        self.assertEqual(output['purpose'],'delivery')
        sources=self.query(section='timeline_media')['sections']['timeline_media']['items']
        self.assertNotIn(output['media_id'],[row['media_id'] for row in sources])
        shot=sources[0]['shot_id']
        self.assertEqual(self.query(object_id=shot,section='renders')['sections']['renders']['total'],1)
        position=render_position(self.store,self.p,output['render_id'],2000)
        self.assertEqual(position['timeline_id'],output['timeline_id'])
        self.assertEqual(position['frame'],48)
        self.assertEqual(position['items'][0]['shot_id'],shot)
        self.assertEqual(position['lines'],[])
        self.assertTrue(position['line_message'])
        with self.assertRaises(ResourceError):render_position(self.store,self.p,output['render_id'],100000)
        other=self.service.create_project({'name':'另一项目','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')['id']
        with self.assertRaises(ResourceError):render_position(self.store,other,output['render_id'],0)
        client=TestClient(create_app({'allowed_hosts':['testserver']},service=self.service))
        response=client.get(f'/api/v1/projects/{self.p}/renders/{output["render_id"]}/position',params={'time_ms':2000})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['items'][0]['shot_id'],shot)

    def test_self_protection_uses_one_instance_and_a_real_fixed_method(self):
        """Exercise the documented handoff through PG, not prompt text assertions."""
        import copy
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        from vsc.knowledge.learning import method_digest
        from vsc.production.performance import FIELDS

        h=self.hierarchy()
        actor=self.write('create_object',dict(kind='asset',display_code='CASTER',asset_kind='character'))['id']
        package=dict(format='vsc.capability-method/v1',name='Synthetic self protection',kind='vfx',
            method='A hand gesture forms a shield; contact precedes the ripple; damage remains.',
            limits='Synthetic contract check only, not provider or quality evidence.',
            allowed_roles=['asset-director','generation-producer'],tags=['shield'])
        package['method_sha256']=method_digest(package)
        method=self.write('create_artifact',dict(artifact_key='shield-method',artifact_type='capability-method',document=package))
        params={key:'explicit '+key for key in FIELDS['vfx']}
        params.update(purpose='protect the caster',acceptance='beam stops at shield before ripple',
            fallback='redesign coverage',route='generation',
            layers=[dict(name='shield',purpose='show blocking surface',occlusion='between beam and caster')])
        doc=dict(format='vsc.creative-relations/v1',project_id=self.p,
            instances=[dict(key='self',asset_id=actor,scene_id=h['scene'],shot_id=h['shot'])],
            performances=[dict(key='shield',domain='vfx',method_artifact_id=method['id'],shot_ids=[h['shot']],
                participants=[dict(instance='self',role=role) for role in ('caster','target')],parameters=params)])

        def register(document,dependencies):
            return self.write('create_artifact',dict(artifact_key='shield-execution',artifact_type='creative-relations',
                document=document,object_ids=[h['shot']],dependency_ids=dependencies))

        with self.assertRaises(ResourceError) as unapproved:
            register(doc,[method['id']])
        self.assertEqual(unapproved.exception.code,'professional_execution_invalid')
        self.write('decide_artifact',dict(artifact_id=method['id'],reason='Synthetic test decision only'))
        with self.assertRaises(ResourceError) as missing_dependency:
            register(doc,[])
        self.assertEqual(missing_dependency.exception.code,'creative_dependency_missing')

        unrelated=self.write('create_artifact',dict(artifact_key='unrelated',artifact_type='note',document={'method':'not a method artifact'}))
        self.write('decide_artifact',dict(artifact_id=unrelated['id'],reason='Synthetic unrelated test decision'))
        wrong=copy.deepcopy(doc)
        wrong['performances'][0]['method_artifact_id']=unrelated['id']
        with self.assertRaises(ResourceError) as wrong_type:
            register(wrong,[unrelated['id']])
        self.assertEqual(wrong_type.exception.code,'professional_execution_invalid')
        for identifier in ('effects-layers','0'*64):
            wrong=copy.deepcopy(doc)
            wrong['performances'][0]['method_artifact_id']=identifier
            with self.subTest(identifier=identifier),self.assertRaises(ResourceError):
                register(wrong,[])

        fixed=register(doc,[method['id']])
        with self.engine.connect() as conn:
            execution=conn.execute(select(S.execution_instances).where(
                S.execution_instances.c.project_id==self.p,S.execution_instances.c.artifact_id==fixed['id'])).mappings().one()
            participants=list(conn.execute(select(S.execution_participants).where(
                S.execution_participants.c.project_id==self.p,S.execution_participants.c.execution_id==execution['id'])).mappings())
        self.assertEqual(execution['method_artifact_id'],method['id'])
        self.assertEqual({row['role'] for row in participants},{'caster','target'})
        self.assertEqual(len({row['instance_id'] for row in participants}),1)
        ordinary=copy.deepcopy(doc)
        ordinary['performances']=[dict(key='sneak',domain='action',shot_ids=[h['shot']],
            participants=[dict(instance='self',role='actor')],parameters={'purpose':'move behind cover'})]
        self.assertTrue(register(ordinary,[])['id'])

    def test_attempts_read_frozen_request_events_and_scope(self):
        self.seed_generation_timeline_render()
        jobs=self.query(section='jobs')['sections']['jobs']['items']
        row=jobs[0]
        value=self.query(section='job_attempts',entity_id=row['id'])['sections']['job_attempts']
        self.assertEqual(value['total'],1)
        attempt=value['items'][0]
        self.assertEqual(attempt['id'],row['id'])
        self.assertIsInstance(attempt['plan_params'],dict)
        self.assertEqual(attempt['plan_params'].get('logical_request',attempt['plan_params'])['prompt'],'固定画面')
        self.assertTrue(attempt['events'])
        self.assertTrue(all('evidence' in event for event in attempt['events']))
        self.assertEqual(len(attempt['outputs']),1)
        self.assertEqual(self.query(object_id=row['shot_id'],section='job_attempts')['sections']['job_attempts']['total'],1)
        other=self.write('create_object',dict(kind='asset',display_code='OTHER',asset_kind='prop'))['id']
        self.assertEqual(self.query(object_id=other,section='job_attempts')['sections']['job_attempts']['total'],0)

    def query(self,**opts):
        from vsc.adapters.persistence.postgres.workbench import query_workbench
        return query_workbench(self.store,self.p,**opts)

    def seed(self):
        h=self.hierarchy()
        a=self.write('create_object',dict(kind='asset',display_code='CUP',title='杯子',asset_kind='prop'))['id']
        line=str(uuid.uuid4())
        script=self.artifact('script','screenplay',[h['scene']],{'script_lines':[dict(id=line,scene_id=h['scene'],line_key='L1',line_kind='action',text='放下杯子') ]})
        coverage=self.artifact('coverage','coverage-plan',[h['shot']],{'line_coverage':[dict(shot_id=h['shot'],line_id=line,start_char=0,end_char=4)]})
        doc=dict(format='vsc.creative-relations/v1',project_id=self.p,
            instances=[dict(key=k,asset_id=a,scene_id=h['scene'],shot_id=h['shot'],state={'position':pos}) for k,pos in [('left','左'),('right','右')]],
            interactions=[dict(subject='left',object='right',relation='touches')],
            performances=[dict(key='put',domain='action',shot_ids=[h['shot']],participants=[dict(instance='left',role='prop')],parameters={'purpose':'放下'})],
            cues=[dict(key='silence',kind='silence',scope_object_id=h['scene'],line_id=line,shots=[dict(shot_id=h['shot'])],parameters={'purpose':'停顿'})])
        registered=self.write('create_artifact',dict(artifact_key='relations',artifact_type='creative-relations',document=doc,object_ids=[h['scene']],dependency_ids=[script]))
        return h,a,line,doc,registered

    def test_instances_cues_scope_versions_pagination_and_search(self):
        h,a,line,doc,registered=self.seed()
        first=self.query(object_id=h['shot'])
        self.assertEqual(first['summary']['instances'],2)
        self.assertEqual(first['summary']['cues'],1)
        self.assertEqual(first['sections']['instances']['items'][0]['version_status'],'draft')
        self.write('decide_artifact',dict(artifact_id=registered['id'],reason='测试决定'))
        page=self.query(object_id=h['scene'],section='instances',limit=1)
        self.assertEqual((page['sections']['instances']['scope_total'],page['sections']['instances']['loaded_count']),(2,1))
        self.assertTrue(page['sections']['instances']['truncated'])
        self.assertTrue(page['sections']['instances']['items'][0]['current'])
        self.assertEqual(self.query(section='instances',entity_id=a)['sections']['instances']['total'],2)
        found=self.query(section='lines',query='杯子')['sections']['lines']
        self.assertEqual(found['total'],1)
        self.assertEqual(found['items'][0]['line_id'],line)
        scoped=self.query(object_id=h['shot'],section='cue_shots')['sections']['cue_shots']['items'][0]
        self.assertEqual(scoped['shot_id'],h['shot'])
        self.assertIn('SHOT',scoped['title'])
        self.assertEqual(len(self.query(object_id=h['shot'])['ancestors']),4)
        from vsc.assets.resource_service import Conflict
        with self.assertRaises(Conflict):self.query(revision=0)

    def test_reject_cross_project_wrong_scope_and_untyped_references(self):
        from vsc.assets.resource_service import ResourceError
        h,a,line,doc,r=self.seed()
        doc['instances'][0]['state']['asset_id']=a
        with self.assertRaises(ResourceError):
            self.write('create_artifact',dict(artifact_key='bad',artifact_type='creative-relations',document=doc,object_ids=[h['shot']]))
        doc['instances'][0]['state'].pop('asset_id')
        other=self.service.create_project(dict(name='other',profile_snapshot={'profile_id':'vsc.synthetic','version':'1','stages':[]}),actor='test')['id']
        with self.assertRaises(ResourceError):
            self.service.create_artifact(other,dict(artifact_key='bad',artifact_type='creative-relations',document=dict(doc,project_id=other),project_wide=True),expected_revision=0,idempotency_key=str(uuid.uuid4()),actor='test')
        self.assertEqual(self.query()['summary']['instances'],2)

    def test_immutable_projection_and_explicit_omission(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        h,a,line,doc,r=self.seed()
        row=self.query(section='instances')['sections']['instances']['items'][0]
        with self.assertRaises(DBAPIError),self.engine.begin() as conn:
            conn.execute(text('UPDATE asset_use_instances SET label=:v WHERE project_id=:p AND id=:id'),dict(v='rewrite',p=self.p,id=row['id']))
        with self.assertRaises(DBAPIError),self.engine.begin() as conn:
            conn.execute(text('DELETE FROM sound_cues WHERE project_id=:p'),dict(p=self.p))
        # Omission is a proposal until the owning fixed version is approved.
        source=self.query(section='lines')['sections']['lines']['items'][0]['artifact_id']
        source=source['id'] if isinstance(source,dict) else source
        d=self.write('create_artifact',dict(artifact_key='omission',artifact_type='creative-relations',document=dict(format='vsc.creative-relations/v1',project_id=self.p,dispositions=[dict(line_id=line,disposition='omit',reason='省略动作')]),object_ids=[h['scene']],dependency_ids=[source]))
        self.assertFalse(self.query(section='dispositions')['sections']['dispositions']['items'][0]['approved_current'])
        self.write('decide_artifact',dict(artifact_id=d['id'],reason='真实测试决定'))
        self.assertTrue(self.query(section='dispositions')['sections']['dispositions']['items'][0]['approved_current'])

    def test_all_sections_and_entire_scope_media_search(self):
        from vsc.adapters.persistence.postgres.workbench import QUERIES
        h,a,line,doc,r=self.seed()
        for number in range(4):self.media('candidate-%d'%number)
        for section in QUERIES:
            self.query(section=section,limit=1)
        result=self.query(section='materials',query='candidate-3',limit=1)['sections']['materials']
        self.assertEqual(result['scope_total'],4)
        self.assertEqual(result['filtered_total'],1)
        self.assertEqual(result['items'][0]['title'],'candidate-3')
        self.assertIn('renditions',result['items'][0])

    def test_creative_graph_nodes_modes_scope_counts(self):
        from vsc.adapters.persistence.postgres.resource_graph import query_graph
        h,a,line,doc,r=self.seed()
        graph=query_graph(self.store,self.p,focus='line:'+line,mode='creative',limit=100,depth=3)
        self.assertIn('cue',{n['kind'] for n in graph['nodes']})
        self.assertIn('line_coverage',{e['kind'] for e in graph['edges']})
        scoped=query_graph(self.store,self.p,object_id=h['shot'],mode='usage',limit=30)
        self.assertEqual(scoped['groups_scope'],'object_scope')
        self.assertEqual(next(g for g in scoped['groups'] if g['kind']=='instance')['scope_total'],2)

    def test_migrated_metadata_and_nullable_cue_range(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import DBAPIError
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
        self.assertEqual(self.store.check_schema()['migration'],S.SCHEMA_REVISION)
        h,a,line,doc,r=self.seed()
        cue=self.query(section='cues')['sections']['cues']['items'][0]['id']
        # SQL CHECK must reject partial ranges even when SQL three-valued logic is involved.
        with self.assertRaises(DBAPIError),self.engine.begin() as conn:
            conn.execute(insert(S.cue_shots).values(project_id=self.p,id=str(uuid.uuid4()),cue_id=cue,shot_id=h['shot'],start_ms=1,end_ms=None))

    def test_cue_and_omission_scope_cannot_escape(self):
        from vsc.assets.resource_service import ResourceError
        h,a,line,doc,r=self.seed()
        for wrong in [dict(cues=[dict(key='bad',kind='silence',scope_object_id=a)]),dict(dispositions=[dict(line_id=line,disposition='omit',reason='bad scope')])]:
            with self.assertRaises(ResourceError):
                self.write('create_artifact',dict(artifact_key='out-of-scope',artifact_type='creative-relations',document=dict(format='vsc.creative-relations/v1',project_id=self.p,**wrong),object_ids=[h['shot']],dependency_ids=[self.query(section='lines')['sections']['lines']['items'][0]['artifact_id']]))

    def test_impact_excludes_candidates_and_preserves_unchanged_evidence(self):
        from types import SimpleNamespace
        from vsc.assets.resource_impact import ResourceImpact
        catalog=SimpleNamespace(_reader=lambda p:None,service=self.service)
        h=self.hierarchy()
        media=self.media('candidate-only')
        candidate=self.candidate(h['shot'],media)
        report=ResourceImpact(catalog).query(self.p,source='media:'+media)
        self.assertEqual(report['consumers'],[])
        self.select(candidate)
        report=ResourceImpact(catalog).query(self.p,source='media:'+media,replacement='media:'+media)
        self.assertGreater(report['summary']['unaffected'],0)
        source=self.artifact('source','generic',[h['shot']])
        replacement=self.artifact('replacement','generic',[h['shot']])
        child=self.write('create_artifact',dict(artifact_key='consumer',artifact_type='generic',document={'input':'fixed'},object_ids=[h['shot']],dependency_ids=[source]))
        report=ResourceImpact(catalog).query(self.p,source='artifact:'+source,replacement='artifact:'+replacement)
        self.assertEqual(report['comparison']['status'],'unchanged')
        self.assertEqual(report['consumers'][0]['classification'],'unaffected')
        self.assertEqual(report['consumers'][0]['entity_id'],child['id'])

    def test_cross_shot_cue_keeps_one_identity_and_fixed_sync_versions(self):
        h=self.hierarchy()
        shots=[h['shot']]
        for n in (1,2):
            shots.append(self.write('create_object',dict(kind='shot',display_code='S'+str(n),parent_id=h['sequence'],ordinal=n))['id'])
        subtitle=self.artifact('subtitle-sync','subtitle',[h['scene']])
        self.write('create_artifact',dict(artifact_key='sound',artifact_type='creative-relations',object_ids=[h['scene']],dependency_ids=[subtitle],
            document=dict(format='vsc.creative-relations/v1',project_id=self.p,cues=[dict(key='ambience',kind='ambience',scope_object_id=h['scene'],subtitle_version_id=subtitle,
                shots=[dict(shot_id=sid,start_ms=0,end_ms=5000) for sid in shots]) ])))
        cues=self.query(object_id=h['scene'],section='cues')['sections']['cues']['items']
        self.assertEqual(len(cues),1)
        self.assertEqual(cues[0]['shot_count'],3)
        self.assertEqual(cues[0]['subtitle_version_id'],subtitle)
        self.assertEqual(self.query(section='cue_shots',entity_id=cues[0]['id'])['sections']['cue_shots']['total'],3)

    def test_approved_filter_includes_current_and_historical_versions(self):
        h=self.hierarchy()
        first=self.artifact('versioned','generic',[h['shot']])
        second=self.artifact('versioned','generic',[h['shot']])
        approved=self.query(section='versions',status='approved')['sections']['versions']
        self.assertEqual(approved['total'],2)
        self.assertEqual({row['version_status'] for row in approved['items']},{'approved'})
        current=self.query(section='versions',status='current')['sections']['versions']
        self.assertEqual(current['total'],1)
        self.assertEqual(current['items'][0]['id'],second)
        self.assertTrue(current['items'][0]['current'])

    def test_partial_character_coverage_is_visible_without_rebinding(self):
        h=self.hierarchy();line=str(uuid.uuid4())
        self.artifact('script','screenplay',[h['scene']],{'script_lines':[dict(id=line,scene_id=h['scene'],line_key='LONG',line_kind='action',text='abcdef')]})
        self.artifact('coverage','coverage-plan',[h['shot']],{'line_coverage':[dict(shot_id=h['shot'],line_id=line,start_char=2,end_char=4)]})
        row=self.query(section='lines')['sections']['lines']['items'][0]
        self.assertEqual(row['uncovered_ranges'],[[0,2],[4,6]])
        self.assertEqual(row['current_coverage_count'],1)
        self.assertFalse(row['coverage_truncated'])

    def test_material_page_preserves_preview_reference_without_locations(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        media=self.media('preview-image')
        row=self.store.get_media(self.p,media)
        with self.engine.begin() as conn:
            conn.execute(insert(S.media_renditions).values(project_id=self.p,id=str(uuid.uuid4()),media_id=media,blob_id=row['blob_id'],purpose='thumbnail',recipe_version='1',tool='synthetic',tool_version='1',parameters={},source_blob_id=row['blob_id'],source_sha256=row['sha256'],request_sha256='f'*64))
        result=self.query(section='materials')['sections']['materials']['items'][0]
        self.assertEqual(result['renditions'][0]['purpose'],'thumbnail')
        self.assertNotIn('locations',result['renditions'][0])
