"""Working state uses real PostgreSQL constraints without manufacturing approvals."""
import copy
import hashlib
import json
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import Conflict, ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class WorkingStateTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.objects=self.hierarchy()

    def video(self,name='working video'):
        sha=hashlib.sha256(name.encode()).hexdigest()
        return self.write('register_media',dict(name=name,modality='video',sha256=sha,size_bytes=10,
            mime_type='video/mp4',storage='local',object_key=sha+'.mp4',duration_ms=7000,
            rights='owned',source={'kind':'test-owned','content':'synthetic working state test'}))['id']

    def choice(self,media,shot=None):
        return self.write('propose_binding',dict(target_object_id=shot or self.objects['shot'],
            media_id=media,role='video_take',slot_key='main'))['candidate_id']

    def select_working(self,candidate,base=None,**more):
        return self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='video',
            candidate_id=candidate,base_version_id=base,**more))

    def test_working_clear_trim_does_not_create_formal_approval(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        media=self.video();candidate=self.choice(media)
        selected=self.select_working(candidate)
        cropped=self.select_working(candidate,selected['id'],event_kind='trim',trim_in_ms=0,trim_out_ms=5110)
        self.assertEqual(cropped['trim_out_ms'],5110)
        clear=self.select_working(None,cropped['id'])
        values=self.service.list_working_selections(self.p,episode_id=self.objects['episode'])['items']
        self.assertEqual(len(values),1);self.assertIsNone(values[0]['candidate_id']);self.assertEqual(values[0]['id'],clear['id'])
        with self.engine.connect() as conn:
            for table in (S.media_reviews,S.binding_decisions,S.current_bindings,S.artifact_decisions):
                self.assertEqual(conn.execute(select(func.count()).select_from(table).where(table.c.project_id==self.p)).scalar_one(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.binding_candidates).where(S.binding_candidates.c.project_id==self.p)).scalar_one(),1)
        with self.assertRaises(Conflict):self.select_working(candidate,selected['id'])
        with self.assertRaises(ResourceError):self.select_working(candidate,clear['id'],trim_out_ms=7001)

    def test_wrong_shot_and_direct_database_scope_are_rejected(self):
        from sqlalchemy import insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        other=self.write('create_object',dict(kind='shot',display_code='SHOT2',parent_id=self.objects['sequence'],ordinal=1))['id']
        candidate=self.choice(self.video(),other)
        with self.assertRaises(ResourceError):self.select_working(candidate)
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(insert(S.working_selection_versions).values(project_id=self.p,id=str(uuid.uuid4()),shot_id=self.objects['shot'],
                output_kind='video',version=1,candidate_id=candidate,event_kind='select',trim_in_ms=0,trim_out_ms=7000,created_by='test'))

    def test_two_real_transactions_cannot_overwrite_same_selection_baseline(self):
        candidate=self.choice(self.video());base=self.select_working(candidate)
        revision=self.rev;barrier=threading.Barrier(2)
        def update_one(clear):
            barrier.wait(timeout=10)
            try:
                return self.service.save_working_selection(self.p,dict(shot_id=self.objects['shot'],output_kind='video',
                    candidate_id=None if clear else candidate,base_version_id=base['id']),
                    expected_revision=revision,idempotency_key=uuid.uuid4().hex,actor='test-human')
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(update_one,True);b=pool.submit(update_one,False);results=[a.result(timeout=20),b.result(timeout=20)]
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(results.count('conflict'),1)
        self.assertEqual(len(self.service.list_working_selections(self.p,shot_id=self.objects['shot'])['items']),1)

    def test_late_generation_cannot_override_new_run_or_explicit_clear(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        image=self.media('automatic input');draft=self.draft(image)
        output=self.video('automatic output');candidate=self.choice(output)
        model=str(uuid.uuid4());provider='working-'+uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider,name='offline fixture',modality='video',base_url='https://example.invalid',auth_ref='none',enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model,provider_id=provider,model_key='offline',model_version='1',modality='video',capabilities={},default_params={},cost_rule={},enabled=True))
        def run(base=None):
            def work(conn,project):
                artifact=self.store._create_artifact(conn,project,dict(artifact_key='working-'+uuid.uuid4().hex,
                    artifact_type='workbench-generation-run',document={'workbench_draft':{'id':draft['id'],'sha256':draft['sha256']},'approved_inputs':[]},object_ids=[self.objects['shot']]))
                conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p,id=str(uuid.uuid4()),run_version_id=artifact['id'],
                    shot_id=self.objects['shot'],draft_version_id=draft['id'],draft_sha256=draft['sha256'],output_kind='video',base_selection_version_id=base))
                job=dict(project_id=self.p,id=str(uuid.uuid4()),run_version_id=artifact['id'],shot_id=self.objects['shot'],purpose='video_clip',modality='video',
                    candidate_no=0,provider_id=provider,model_id=model,model_version='1',request_payload={},request_sha256='0'*64,context_sha256='0'*64,
                    idempotency_key=uuid.uuid4().hex,status='succeeded',attempt=0)
                conn.execute(insert(S.generation_jobs).values(**job))
                conn.execute(insert(S.job_outputs).values(project_id=self.p,id=str(uuid.uuid4()),job_id=job['id'],media_id=output,asset_type='video'))
                return {'job':job}
            result=self.store._mutate(self.p,'test_working_run',{},expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human',callback=work)
            self.rev=result['revision'];return result['job']
        def complete(job):
            result=self.store._mutate(self.p,'test_working_complete',{},expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor='test-human',
                callback=lambda conn,project:self.store._auto_select_working_candidate(conn,project,job,candidate))
            self.rev=result['revision'];return result
        old=run();new=run()
        self.assertEqual(complete(old)['reason'],'newer_working_run')
        chosen=complete(new);self.assertTrue(chosen['selected'])
        clear=self.select_working(None,chosen['id'])
        self.assertEqual(complete(new)['reason'],'working_selection_changed')
        current=self.service.list_working_selections(self.p,shot_id=self.objects['shot'])['items'][0]
        self.assertEqual(current['id'],clear['id']);self.assertIsNone(current['candidate_id'])

    def test_episode_aliases_and_source_versions_do_not_drift(self):
        from sqlalchemy import select,update,insert
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        source=self.write('create_object',dict(kind='asset',asset_kind='character',display_code='SOURCE',title='Source'))['id']
        spec=str(uuid.uuid4())
        specs=[dict(id=spec,asset_id=source,variant_key='default')]
        self.write('create_artifact',dict(artifact_key='source-spec',artifact_type='asset-bible',document={'asset_specs':specs},
            object_ids=[source],asset_specs=specs))
        image=self.media('source image')
        other=self.write('create_object',dict(kind='episode',display_code='E2',parent_id=self.objects['work'],ordinal=1))['id']
        payload=dict(episode_id=self.objects['episode'],base_revision=0,asset_key='cat',name='本集猫',asset_kind='character',
            forms=[dict(form_key='costume',name='常服',base_version_id=None,source_asset_id=source,spec_id=spec,media_id=image)])
        first=self.write('save_episode_asset',payload)
        second=self.write('save_episode_asset',dict(payload,episode_id=other,name='第二集猫'))
        changed=dict(payload,id=first['id'],base_revision=1,name='本集新别名',forms=[])
        self.write('save_episode_asset',changed)
        fixed=first['forms'][0]['version_id']
        with self.engine.connect() as conn:
            row=conn.execute(select(S.episode_asset_form_versions).where(S.episode_asset_form_versions.c.project_id==self.p,
                S.episode_asset_form_versions.c.id==fixed)).mappings().one()
        self.assertEqual(row['asset_name'],'本集猫')
        self.assertEqual(self.service.list_episode_assets(self.p,other)['items'][0]['name'],'第二集猫')
        self.assertNotEqual(first['forms'][0]['id'],second['forms'][0]['id'])
        with self.assertRaises(ResourceError):self.write('save_episode_asset',dict(changed,episode_id=other,base_revision=2))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.episode_assets).where(S.episode_assets.c.project_id==self.p,S.episode_assets.c.id==first['id']).values(episode_id=other))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.episode_asset_form_versions).where(S.episode_asset_form_versions.c.project_id==self.p,
                S.episode_asset_form_versions.c.id==fixed).values(asset_name='rewrite'))

    def draft(self,media,**ref_fields):
        sha=self.service.get_media(self.p,media)['sha256']
        return self.write('save_classic_draft',dict(base_draft_id=None,document=dict(shot_id=self.objects['shot'],mode='single',
            references=[dict(role='first_frame',media_id=media,sha256=sha,**ref_fields)],prompt='fixed work input')))

    def test_classic_refs_are_complete_sealed_and_preserve_scope(self):
        from sqlalchemy import insert,select,update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        image=self.media('draft input');draft=self.draft(image)
        refs=self.service.get_classic_draft_inputs(self.p,draft['id'])
        self.assertFalse(refs['gaps']);self.assertEqual(refs['items'][0]['media_id'],image)
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            row=dict(refs['items'][0]);row.update(id=str(uuid.uuid4()),ordinal=1,role='last_frame',reference_key='extra')
            conn.execute(insert(S.classic_draft_media).values(**row))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:
            conn.execute(update(S.classic_draft_media).where(S.classic_draft_media.c.project_id==self.p,
                S.classic_draft_media.c.draft_version_id==draft['id']).values(display_name='changed'))
        bad=dict(shot_id=self.objects['shot'],mode='single',references=[dict(role='first_frame',media_id=image,
            sha256=self.service.get_media(self.p,image)['sha256'])])
        with self.assertRaises(ResourceError):
            self.write('create_artifact',dict(artifact_key='unprojected',artifact_type='classic-production-draft',document=bad,object_ids=[self.objects['shot']]))

    def test_intelligent_inputs_accept_working_or_local_form_without_formal_approval(self):
        from vsc.adapters.persistence.postgres import schema as S
        image=self.media('intelligent working image')
        candidate=self.write('propose_binding',dict(target_object_id=self.objects['shot'],media_id=image,role='first_frame',slot_key='main'))
        chosen=self.write('save_working_selection',dict(shot_id=self.objects['shot'],output_kind='image',candidate_id=candidate['candidate_id'],base_version_id=None))
        workflow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],script_text='本集工作剧本'))
        data=self.service.get_intelligent_workflow(self.p,workflow['id']);state=copy.deepcopy(data['state'])
        state['units']=[dict(unit_key='shot1',kind='shot',title='本镜',description='工作镜头',duration_ms=7000,segments=[],
            skip_reason='',lineart_purpose='reference_image',shot_id=self.objects['shot'],spatial_version_id=None)]
        def save_link(link):
            state['media']=[dict(unit_key='shot1',purpose='reference_image',media_id=image,decision_id=None,spatial_export_id=None,**link)]
            def work(conn,project):
                wf,base=self.store._intelligent_version(conn,self.p,workflow['id'])
                return self.store._insert_intelligent_version(conn,project,wf,state,'test-human',base)
            r=self.store._mutate(self.p,'test_intelligent_working',{},callback=work,actor='test-human',expected_revision=self.rev,idempotency_key=uuid.uuid4().hex)
            self.rev=r['revision'];return r
        save_link({'working_selection_version_id':chosen['id']})
        asset=self.write('save_episode_asset',dict(episode_id=self.objects['episode'],base_revision=0,asset_key='local',name='本集参考',asset_kind='character',
            forms=[dict(form_key='main',name='原图',base_version_id=None,media_id=image)]))
        form=asset['forms'][0]['version_id'];save_link({'episode_asset_form_version_id':form})
        with self.assertRaises(ResourceError):save_link({'episode_asset_form_version_id':form,'working_selection_version_id':chosen['id']})
        other=self.write('create_object',dict(kind='episode',display_code='OTHER',parent_id=self.objects['work'],ordinal=1))['id']
        other_asset=self.write('save_episode_asset',dict(episode_id=other,base_revision=0,asset_key='local',name='别集参考',asset_kind='character',
            forms=[dict(form_key='main',name='原图',base_version_id=None,media_id=image)]))
        with self.assertRaises(ResourceError):save_link({'episode_asset_form_version_id':other_asset['forms'][0]['version_id']})
        with self.engine.connect() as conn:
            from sqlalchemy import select,func
            self.assertEqual(conn.execute(select(func.count()).select_from(S.binding_decisions).where(S.binding_decisions.c.project_id==self.p)).scalar_one(),0)

    def test_migrated_schema_matches_authoritative_metadata(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.schema_working_state import WORKING_STATE_TABLES
        scoped=set(WORKING_STATE_TABLES)|{'intelligent_assets','intelligent_media'}
        def include_object(obj,name,type_,reflected,compare_to):
            return name in scoped if type_=='table' else getattr(getattr(obj,'table',None),'name',None) in scoped
        with self.engine.connect() as conn:
            differences=compare_metadata(MigrationContext.configure(conn,opts={'include_object':include_object}),S.metadata)
        self.maxDiff=None
        self.assertEqual(differences,[])

    def test_edit_source_matches_fixed_clip_and_survives_new_choice(self):
        from sqlalchemy import insert,update,select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import digest
        media=self.video('fixed edit source');candidate=self.choice(media);chosen=self.select_working(candidate)
        def freeze(include_relation=True):
            def work(conn,project):
                workspace=str(uuid.uuid4());version=str(uuid.uuid4());item=self.store._media(conn,self.p,media)
                document=dict(format='vsc.edit-workspace/v1',width=720,height=1280,fps=24,audio=[],captions=[],
                    clips=[dict(id='clip',shot_id=self.objects['shot'],media_id=media,in_frame=0,out_frame=168,
                        working_selection_version_id=chosen['id'])])
                conn.execute(insert(S.edit_workspaces).values(project_id=self.p,id=workspace,episode_id=self.objects['episode'],title='working cut',revision=1))
                conn.execute(insert(S.edit_revisions).values(project_id=self.p,id=version,workspace_id=workspace,version=1,
                    document=document,sha256=digest(document),member_count=1,created_by='test-human'))
                conn.execute(insert(S.edit_revision_media).values(project_id=self.p,id=str(uuid.uuid4()),edit_version_id=version,
                    media_id=media,shot_id=self.objects['shot'],blob_id=item['blob_id'],blob_sha256=item['sha256'],clip_key='clip',
                    track='clips',ordinal=0,source_in_frame=0,source_out_frame=168,offset_frame=0,modality='video'))
                if include_relation:
                    conn.execute(insert(S.edit_revision_working_selections).values(project_id=self.p,id=str(uuid.uuid4()),
                        edit_version_id=version,clip_key='clip',selection_version_id=chosen['id']))
                conn.execute(update(S.edit_workspaces).where(S.edit_workspaces.c.project_id==self.p,S.edit_workspaces.c.id==workspace).values(current_version_id=version))
                return {'edit_version_id':version}
            result=self.store._mutate(self.p,'test_fixed_working_edit',{},callback=work,actor='test-human',expected_revision=self.rev,idempotency_key=uuid.uuid4().hex)
            self.rev=result['revision'];return result
        with self.assertRaises(ResourceError):freeze(False)
        fixed=freeze();self.select_working(None,chosen['id'])
        with self.engine.connect() as conn:
            source=conn.execute(select(S.edit_revision_working_selections.c.selection_version_id).where(
                S.edit_revision_working_selections.c.project_id==self.p,S.edit_revision_working_selections.c.edit_version_id==fixed['edit_version_id'])).scalar_one()
        self.assertEqual(source,chosen['id'])

    def test_audio_run_input_does_not_create_working_image_video_choice(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        draft=self.write('create_artifact',dict(artifact_key='audio-draft',artifact_type='classic-production-draft',
            document=dict(shot_id=self.objects['shot'],mode='audio_music',references=[]),object_ids=[self.objects['shot']]))
        def work(conn,project):
            run=self.store._create_artifact(conn,project,dict(artifact_key='audio-run',artifact_type='workbench-generation-run',
                document={'workbench_draft':{'id':draft['id'],'sha256':draft['sha256']}},object_ids=[self.objects['shot']]))
            conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p,id=str(uuid.uuid4()),run_version_id=run['id'],
                shot_id=self.objects['shot'],draft_version_id=draft['id'],draft_sha256=draft['sha256'],output_kind='audio',base_selection_version_id=None))
            return run
        result=self.store._mutate(self.p,'test_audio_run',{},callback=work,actor='test-human',expected_revision=self.rev,idempotency_key=uuid.uuid4().hex)
        self.rev=result['revision']
        self.assertEqual(self.service.list_working_selections(self.p,shot_id=self.objects['shot'])['items'],[])

    def test_real_0033_upgrade_and_explicit_legacy_backfill(self):
        from sqlalchemy import create_engine,text
        from alembic import command
        from alembic.config import Config
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        url=TEST_URL.replace('postgresql://','postgresql+psycopg://',1)
        schema='vsc_test_legacy_'+uuid.uuid4().hex;admin=create_engine(url);engine=None
        try:
            with admin.begin() as conn:conn.execute(text('CREATE SCHEMA "'+schema+'"'))
            engine=create_engine(url,connect_args={'options':'-csearch_path='+schema})
            config=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:
                config.attributes['connection']=conn;command.upgrade(config,'head')
            fixture=ResourceStoreFixture();fixture.store=PostgresResourceStore(engine=engine);fixture.service=ResourceService(fixture.store);fixture.setUp()
            objects=fixture.hierarchy();media=fixture.media('legacy input');sha=fixture.service.get_media(fixture.p,media)['sha256']
            # Seed the historical hierarchy before removing the newer copy
            # graph tables; legacy draft setup below runs in actual 0033.
            with engine.begin() as conn:
                config.attributes['connection']=conn;command.downgrade(config,'0033_creative_tool_imports')
                self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),'0033_creative_tool_imports')
                self.assertIsNone(conn.execute(text("SELECT to_regclass('classic_draft_media')")).scalar_one())
            # 0033 has no copy-source graph tables. Restrict this historical
            # fixture writer to its sole project; runtime guards stay intact.
            from unittest.mock import patch
            with patch('vsc.adapters.persistence.postgres.copy_lineage.source_projects_for_copy',return_value=[fixture.p]):
                legacy=fixture.write('create_artifact',dict(artifact_key='legacy-classic',artifact_type='classic-production-draft',
                    document=dict(shot_id=objects['shot'],mode='single',references=[dict(role='first_frame',media_id=media,sha256=sha)]),object_ids=[objects['shot']]))
            with engine.begin() as conn:
                config.attributes['connection']=conn;command.upgrade(config,'head')
            self.assertTrue(fixture.service.get_classic_draft_inputs(fixture.p,legacy['id'])['legacy'])
            backfill=fixture.write('backfill_classic_draft_inputs',{'draft_version_id':legacy['id']},idempotency_key='legacy-once')
            self.assertEqual(backfill['count'],1)
            self.assertFalse(fixture.service.get_classic_draft_inputs(fixture.p,legacy['id'])['gaps'])
            again=fixture.service.backfill_classic_draft_inputs(fixture.p,{'draft_version_id':legacy['id']},
                actor='test-human',expected_revision=fixture.rev-1,idempotency_key='legacy-once')
            self.assertEqual(again,backfill)
        finally:
            if engine:engine.dispose()
            with admin.begin() as conn:conn.execute(text('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE'))
            admin.dispose()


if __name__=='__main__':unittest.main()
