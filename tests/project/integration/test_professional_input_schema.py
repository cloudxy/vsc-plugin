"""0047 exact source relations and commit-time seals on real isolated PostgreSQL."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
import unittest
import uuid
from sqlalchemy import insert, select, update, delete, text, inspect, CheckConstraint
from sqlalchemy.exc import IntegrityError
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from support.fixtures.postgres import isolated_postgres
from vsc.adapters.persistence.postgres import schema as S
from vsc.adapters.persistence.postgres.values import canonical, digest
from vsc.production.professional_inputs import KIND_TYPES


def uid(): return str(uuid.uuid4())


def migrate(conn, target, direction='upgrade'):
    cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'));cfg.attributes['connection']=conn
    getattr(command,direction)(cfg,target)


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class ProfessionalInputSchemaTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy()

    def artifact(self, conn, kind='script', document=None, dependencies=()):
        document={} if document is None else document
        raw=canonical(document).encode();identifier=uid();sha=hashlib.sha256(raw).hexdigest()
        conn.execute(insert(S.artifact_versions).values(project_id=self.p,id=identifier,artifact_key='ct105:'+identifier,
            version=1,artifact_type=kind,stage='production',document=raw,mime_type='application/json',sha256=sha,
            project_wide=True,parser_version='synthetic-schema-probe'))
        for source in dependencies:
            conn.execute(insert(S.artifact_dependencies).values(project_id=self.p,artifact_id=identifier,dependency_id=source))
        return dict(id=identifier,sha256=sha)

    def source(self, kind='script'):
        with self.engine.begin() as conn:return self.artifact(conn,kind)

    def rejects(self, callback, code='23514'):
        with self.assertRaises(IntegrityError) as raised:
            with self.engine.begin() as conn:callback(conn)
        self.assertEqual(raised.exception.orig.sqlstate,code)

    def workflow(self):
        flow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='Schema source',route='storyboard',script_text='Synthetic source.'))['id']
        detail=self.service.get_intelligent_workflow(self.p,flow);state=detail['state']
        state['units']=[dict(unit_key='unit1',kind='shot',title='one',description='Fixed shot',duration_ms=1000,
            segments=[dict(start_ms=0,end_ms=1000,text='one')],skip_reason='',lineart_purpose='none',shot_id=self.objects['shot'],spatial_version_id=None)]
        payload=dict(workflow_id=flow,base_version_id=detail['version']['id'],state=state)
        preview=self.service.preview_intelligent_change(self.p,payload)
        self.write('save_intelligent_workflow',dict(payload,impact_sha256=preview['sha256']))
        current=self.service.get_intelligent_workflow(self.p,flow)
        from vsc.production.quotes import fingerprint
        with self.engine.connect() as conn:
            art=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==self.p,S.artifact_versions.c.id==current['version']['artifact_id'])).mappings().one()
        return dict(version_id=current['version']['id'],artifact_id=art['id'],artifact_sha256=art['sha256'],state_sha256=fingerprint(current['state']),unit_key='unit1')

    def draft(self, conn, source=None, project_source=None, shot=None, project=True):
        doc=dict(shot_id=shot or self.objects['shot'],references=[])
        if source is not None:doc['source_workflow']=source
        artifact=self.artifact(conn,'classic-production-draft',doc)
        if project and source is not None:
            conn.execute(insert(S.classic_draft_workflows).values(project_id=self.p,draft_version_id=artifact['id'],**(project_source or source)))
        return artifact

    def edit(self, conn, refs=(), rows=None, audio=None, media=None, source_columns=None):
        workspace=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==self.p,S.edit_workspaces.c.episode_id==self.objects['episode'])).mappings().first()
        if workspace is None:
            workspace=dict(id=uid());conn.execute(insert(S.edit_workspaces).values(project_id=self.p,**workspace,episode_id=self.objects['episode'],title='Schema edit',revision=0))
        version=conn.execute(text('SELECT coalesce(max(version),0)+1 FROM edit_revisions WHERE project_id=:p AND workspace_id=:w'),dict(p=self.p,w=workspace['id'])).scalar_one()
        identifier=uid();doc=dict(clips=[],audio=[audio] if audio else [],professional_inputs=list(refs))
        conn.execute(insert(S.edit_revisions).values(project_id=self.p,id=identifier,workspace_id=workspace['id'],version=version,document=doc,sha256=digest(doc),member_count=1 if audio else 0,created_by='test-human'))
        projected=[dict(ordinal=i,artifact_id=r['id'],artifact_sha256=r['sha256'],kind=r['kind']) for i,r in enumerate(refs)] if rows is None else rows
        for row in projected:conn.execute(insert(S.edit_revision_professional_inputs).values(project_id=self.p,edit_version_id=identifier,**row))
        if audio:
            body=source_columns if source_columns is not None else dict(source_cue_id=audio.get('cue_id'),source_binding_decision_id=audio.get('binding_decision_id'))
            conn.execute(insert(S.edit_revision_media).values(project_id=self.p,id=uid(),edit_version_id=identifier,
                media_id=media['id'],blob_id=media['blob_id'],blob_sha256=media['sha256'],clip_key=audio['id'],track='audio',
                ordinal=0,source_in_frame=audio['in_frame'],source_out_frame=audio['out_frame'],offset_frame=0,modality='audio',**body))
        return identifier

    def test_generic_professional_pins_require_original_dependency_type_sha_and_unique_identity(self):
        source=self.source();ref=dict(source,kind='screenplay')
        with self.engine.begin() as conn:
            good=self.artifact(conn,'professional-test',dict(professional_inputs=[ref]),[source['id']])
            self.draft(conn)
        self.rejects(lambda c:self.artifact(c,'professional-test',dict(professional_inputs=[ref])))
        for changed in (dict(ref,sha256='0'*64),dict(ref,kind='sound_plan'),dict(ref,kind='workflow')):
            self.rejects(lambda c,r=changed:self.artifact(c,'professional-test',dict(professional_inputs=[r]),[source['id']]))
        self.rejects(lambda c:self.artifact(c,'professional-test',dict(professional_inputs=[ref,ref]),[source['id']]))
        with self.engine.connect() as conn:
            for kind,types in KIND_TYPES.items():
                for actual in types:
                    self.assertTrue(conn.scalar(text('SELECT vsc_professional_input_type(:k,:t,true)'),dict(k=kind,t=actual)))
                    self.assertEqual(conn.scalar(text('SELECT vsc_professional_input_type(:k,:t,false)'),dict(k=kind,t=actual)),kind!='workflow')
            self.assertFalse(conn.scalar(text("SELECT vsc_professional_input_type('screenplay','sound-plan',true)")))

    def test_classic_workflow_exact_projection_seals_input_and_original_unit_shot_mapping(self):
        source=self.workflow()
        with self.engine.begin() as conn:
            good=self.draft(conn,source);legacy=self.draft(conn)
        self.rejects(lambda c:self.draft(c,source,project=False))
        self.rejects(lambda c:self.draft(c,source,project_source=dict(source,state_sha256='0'*64)))
        self.rejects(lambda c:self.draft(c,dict(source,state_sha256='not-a-sha')))
        self.rejects(lambda c:self.draft(c,dict(source,artifact_sha256='0'*64)),'23503')
        self.rejects(lambda c:self.draft(c,dict(source,unit_key='missing_unit')),'23503')
        other=self.source('intelligent-workflow-state')
        wrong=dict(source,artifact_id=other['id'],artifact_sha256=other['sha256'])
        self.rejects(lambda c:self.draft(c,wrong))
        shot=self.write('create_object',dict(kind='shot',parent_id=self.objects['sequence'],display_code='SHOT2',ordinal=1))['id']
        self.rejects(lambda c:self.draft(c,source,shot=shot))
        self.rejects(lambda c:c.execute(insert(S.classic_draft_workflows).values(project_id=self.p,draft_version_id=legacy['id'],**source)))
        foreign=self.service.create_project({'name':'Cross-project schema negative'},actor='test-human')['id']
        self.rejects(lambda c:c.execute(insert(S.classic_draft_workflows).values(project_id=foreign,draft_version_id=legacy['id'],**source)),'23503')
        for statement in (update(S.classic_draft_workflows).where(S.classic_draft_workflows.c.draft_version_id==good['id']).values(state_sha256='0'*64),
                          delete(S.classic_draft_workflows).where(S.classic_draft_workflows.c.draft_version_id==good['id'])):
            self.rejects(lambda c,s=statement:c.execute(s))

    def test_edit_professional_members_exact_order_and_no_late_insert_or_mutation(self):
        source=self.source('sound-plan');ref=dict(source,kind='sound_plan')
        with self.engine.begin() as conn:
            good=self.edit(conn,[ref]);legacy=self.edit(conn)
        self.rejects(lambda c:self.edit(c,[ref],rows=[]))
        self.rejects(lambda c:self.edit(c,[ref],rows=[dict(ordinal=1,artifact_id=source['id'],artifact_sha256=source['sha256'],kind='sound_plan')]))
        self.rejects(lambda c:self.edit(c,[dict(ref,kind='screenplay')]))
        self.rejects(lambda c:c.execute(insert(S.edit_revision_professional_inputs).values(project_id=self.p,edit_version_id=legacy,ordinal=0,artifact_id=source['id'],artifact_sha256=source['sha256'],kind='sound_plan')))
        for statement in (update(S.edit_revision_professional_inputs).where(S.edit_revision_professional_inputs.c.edit_version_id==good).values(ordinal=1),
                          delete(S.edit_revision_professional_inputs).where(S.edit_revision_professional_inputs.c.edit_version_id==good)):
            self.rejects(lambda c,s=statement:c.execute(s))

    def test_queued_novel_materials_typed_fixed_complete_and_downgrade_safe(self):
        from copy import deepcopy
        from vsc.assets.text_tools import COMMON, DEFAULTS
        document={**deepcopy(COMMON),**deepcopy(DEFAULTS['novel']),
            'source_text':'第1章 起点\n离家','synopsis':'回家','core_setting':'小城',
            'chapter_start':1,'chapter_end':1,'target_episodes':1}
        baseline=self.write('save_text_tool',dict(tool='novel',group_key='schema',unit_key='baseline',
            title='固定正文及 QA',ordinal=0,episode_id=None,unit_id=None,base_version_id=None,document=document))
        initial=[dict(unit_id=baseline['unit_id'],input_version_id=baseline['id'],action='body')]

        def batch(conn, material, rows, tool='novel'):
            identifier=uid()
            conn.execute(insert(S.text_tool_batches).values(project_id=self.p,id=identifier,tool=tool,
                action='body',auto_accept=True,status='ready',item_count=len(rows),
                created_by='test-human',materials_artifact_id=material))
            for ordinal,row in enumerate(rows):
                conn.execute(insert(S.text_tool_batch_items).values(project_id=self.p,id=uid(),
                    batch_id=identifier,ordinal=ordinal,status='pending',**row))
            return identifier

        with self.engine.begin() as conn:
            legacy=batch(conn,None,initial)
        with self.engine.begin() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
            self.assertIn('ck_text_tool_batches_materials_tool',
                {c['name'] for c in inspect(conn).get_check_constraints('text_tool_batches')})


        # Positive path uses normal producers, including the baseline QA input.
        plan=self.write('create_novel_plan',dict(unit_id=baseline['unit_id'],version_id=baseline['id'],
            episodes=[dict(title='第一集',chapter_start=1,chapter_end=1,outline='离家')]))
        good=self.write('create_text_batch',dict(tool='novel',action='body',auto_accept=True,
            unit_ids=[r['unit_id'] for r in plan['episodes']],qa_unit_id=baseline['unit_id']))
        detail=self.service.get_text_batch(self.p,good['id']);material=detail['materials_artifact_id']
        rows=[{k:r[k] for k in ('unit_id','input_version_id','action')} for r in detail['items']]
        inputs={r['input_version_id'] for r in rows}
        with self.engine.connect() as conn:
            fixed=conn.execute(select(S.artifact_versions).where(S.artifact_versions.c.project_id==self.p,S.artifact_versions.c.id==material)).mappings().one()
            packet=json.loads(bytes(fixed['document']))
            self.assertEqual(fixed['artifact_type'],'text-tool-role-materials')
            self.assertEqual(set(packet['actions']),{'body','qa_notes'})
            self.assertEqual(set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==self.p,S.artifact_dependencies.c.artifact_id==material)).scalars()),inputs)

        def bad_packet(conn, doc=packet, kind='text-tool-role-materials', dependencies=None):
            source=self.artifact(conn,kind,doc,inputs if dependencies is None else dependencies)
            return batch(conn,source['id'],rows)

        self.rejects(lambda c:bad_packet(c,kind='script'))
        for changed in (dict(packet,format='wrong'),dict(packet,tool='translation'),
                        dict(packet,actions={'body':packet['actions']['body']}),
                        dict(packet,actions=dict(packet['actions'],outline={})),
                        dict(packet,actions={'body':[], 'qa_notes':packet['actions']['qa_notes']})):
            self.rejects(lambda c,d=changed:bad_packet(c,doc=d))
        self.rejects(lambda c:bad_packet(c,dependencies=[rows[0]['input_version_id']]))
        extra=self.source()
        self.rejects(lambda c:bad_packet(c,dependencies=inputs|{extra['id']}))
        self.rejects(lambda c:batch(c,material,rows,tool='translation'))
        self.rejects(lambda c:batch(c,uid(),rows),'23503')
        foreign=self.service.create_project({'name':'Cross-project materials negative'},actor='test-human')['id']
        other=self.service.create_artifact(foreign,dict(artifact_key='materials',artifact_type='text-tool-role-materials',document=packet),
            expected_revision=0,idempotency_key=uid(),actor='test-human')
        self.rejects(lambda c:batch(c,other['id'],rows),'23503')
        for identifier,value in ((good['id'],None),(good['id'],extra['id']),(legacy,material)):
            self.rejects(lambda c,i=identifier,v=value:c.execute(update(S.text_tool_batches).where(S.text_tool_batches.c.id==i).values(materials_artifact_id=v)))
        self.rejects(lambda c:c.execute(insert(S.artifact_dependencies).values(project_id=self.p,artifact_id=material,dependency_id=extra['id'])))
        with self.engine.begin() as conn:
            conn.execute(update(S.text_tool_batches).where(S.text_tool_batches.c.id==good['id']).values(status='running'))
        self.rejects(lambda c:migrate(c,'0046_classic_preferences','downgrade'))
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')),'0047_professional_inputs')
            self.assertEqual(conn.scalar(select(S.text_tool_batches.c.materials_artifact_id).where(S.text_tool_batches.c.id==good['id'])),material)
            self.assertEqual(bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==material))),bytes(fixed['document']))

    def test_audio_cue_requires_fixed_sound_plan_original_slot_decision_media_and_body(self):
        audio=self.media('Cue source',modality='audio');other=self.media('Other audio',modality='audio')
        line=uid();lines=[dict(id=line,line_key='L1',scene_id=self.objects['scene'],ordinal=0,text='Fixed line.')]
        script=self.write('create_artifact',dict(artifact_key='cue-script',artifact_type='screenplay',
            document={'script_lines':lines},script_lines=lines))
        covers=[dict(shot_id=self.objects['shot'],line_id=line,start_char=0,end_char=len('Fixed line.'))]
        coverage=self.write('create_artifact',dict(artifact_key='cue-coverage',artifact_type='coverage-plan',
            document={'line_coverage':covers},line_coverage=covers,dependency_ids=[script['id']]))
        with self.engine.connect() as conn:
            coverage_id=conn.scalar(select(S.shot_line_coverage.c.id).where(S.shot_line_coverage.c.project_id==self.p,
                S.shot_line_coverage.c.coverage_version_id==coverage['id'],S.shot_line_coverage.c.line_id==line))
        candidate=self.candidate(self.objects['shot'],audio,role='dialogue_dry',line_coverage_id=coverage_id);decision=self.select(candidate)
        # Use the real creative-relations producer; sound-plan alone cannot
        # author the original typed sound_cues/cue_slots projections.
        source=self.write('create_artifact',dict(artifact_key='cue-plan',artifact_type='creative-relations',
            object_ids=[self.objects['episode']],dependency_ids=[script['id']],document={'format':'vsc.creative-relations/v1','project_id':self.p,
                'cues':[dict(key='cue',label='Episode cue',kind='dialogue',line_id=line,scope_object_id=self.objects['episode'],
                    shots=[dict(shot_id=self.objects['shot'],start_ms=0,end_ms=1000)],slot_ids=[candidate['slot_id']])]}))
        ref=dict(id=source['id'],sha256=source['sha256'],kind='sound_plan')
        with self.engine.connect() as conn:
            cue=conn.scalar(select(S.sound_cues.c.id).where(S.sound_cues.c.project_id==self.p,S.sound_cues.c.artifact_id==source['id']))
            self.assertIsNotNone(cue)
            media=self.store._media(conn,self.p,audio);other_media=self.store._media(conn,self.p,other)
        item=dict(id='audio1',media_id=audio,in_frame=0,out_frame=24,cue_id=cue,binding_decision_id=decision['decision_id'])
        with self.engine.begin() as conn:self.edit(conn,[ref],audio=item,media=media)
        self.rejects(lambda c:self.edit(c,[],audio=item,media=media))
        self.rejects(lambda c:self.edit(c,[ref],audio=dict(item,media_id=other),media=other_media))
        self.rejects(lambda c:self.edit(c,[ref],audio=item,media=media,source_columns=dict(source_cue_id=None,source_binding_decision_id=None)))
        self.rejects(lambda c:self.edit(c,[ref],audio=item,media=media,source_columns=dict(source_cue_id=cue,source_binding_decision_id=None)))


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class ProfessionalInputMigrationTests(unittest.TestCase):
    def test_legacy_null_material_batch_roundtrip_uses_its_own_empty_schema(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.assets.text_tools import COMMON, DEFAULTS
        # A schema-wide downgrade must not share another method's new facts.
        with isolated_postgres(TEST_URL) as engine:
            f=ResourceStoreFixture();f.engine=engine;f.store=PostgresResourceStore(engine=engine);f.service=ResourceService(f.store);f.setUp()
            baseline=f.write('save_text_tool',dict(tool='novel',group_key='legacy',unit_key='one',title='Legacy text',ordinal=0,episode_id=None,base_version_id=None,document={**deepcopy(COMMON),**deepcopy(DEFAULTS['novel']),'body':'Legacy body.'}))
            batch_id=uid()
            with engine.begin() as conn:
                conn.execute(insert(S.text_tool_batches).values(project_id=f.p,id=batch_id,tool='novel',action='body',auto_accept=False,status='ready',item_count=1,created_by='test-human',materials_artifact_id=None))
                conn.execute(insert(S.text_tool_batch_items).values(project_id=f.p,id=uid(),batch_id=batch_id,unit_id=baseline['unit_id'],input_version_id=baseline['id'],ordinal=0,action='body',status='pending'))
            with engine.begin() as conn:
                old=bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==baseline['id'])))
                migrate(conn,'0046_classic_preferences','downgrade')
                self.assertNotIn('materials_artifact_id',{c['name'] for c in inspect(conn).get_columns('text_tool_batches')})
                self.assertEqual(conn.scalar(text('SELECT item_count FROM text_tool_batches WHERE id=:id'),dict(id=batch_id)),1)
                migrate(conn,'0047_professional_inputs')
                self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
                self.assertIsNone(conn.scalar(select(S.text_tool_batches.c.materials_artifact_id).where(S.text_tool_batches.c.id==batch_id)))
                self.assertEqual(bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==baseline['id']))),old)

    def test_single_attempt_material_artifact_refuses_downgrade_without_batch(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        from vsc.production.text_tools import novel_materials_packet
        with isolated_postgres(TEST_URL) as engine:
            f=ResourceStoreFixture();f.engine=engine;f.store=PostgresResourceStore(engine=engine);f.service=ResourceService(f.store);f.setUp()
            packet=novel_materials_packet(['body'])
            fixed=f.write('create_artifact',dict(artifact_key='text-attempt-role-materials:'+uid(),
                artifact_type='text-tool-role-materials',document=packet))
            with engine.connect() as conn:
                self.assertEqual(conn.scalar(text('SELECT count(*) FROM text_tool_batches WHERE materials_artifact_id IS NOT NULL')),0)
                before=bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==fixed['id'])))
            with self.assertRaises(IntegrityError) as rejected:
                with engine.begin() as conn:migrate(conn,'0046_classic_preferences','downgrade')
            self.assertEqual(rejected.exception.orig.sqlstate,'23514')
            with engine.connect() as conn:
                self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')),'0047_professional_inputs')
                self.assertEqual(bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==fixed['id']))),before)
                self.assertEqual(conn.scalar(select(S.artifact_versions.c.sha256).where(S.artifact_versions.c.id==fixed['id'])),fixed['sha256'])
                self.assertEqual(conn.scalar(select(S.projects.c.revision).where(S.projects.c.id==f.p)),f.rev)

    def test_metadata_empty_downgrade_legacy_preservation_and_new_fact_refusal(self):
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.assets.resource_service import ResourceService
        with isolated_postgres(TEST_URL) as engine:
            f=ResourceStoreFixture();f.engine=engine;f.store=PostgresResourceStore(engine=engine);f.service=ResourceService(f.store);f.setUp()
            old=f.write('create_artifact',dict(artifact_key='legacy',artifact_type='script',document='Legacy plain text.'))
            with engine.begin() as conn:
                self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
                for name in ('classic_draft_workflows','edit_revision_professional_inputs','edit_revision_media'):
                    expected={str(c.name) for c in S.metadata.tables[name].constraints if isinstance(c,CheckConstraint)}
                    actual={c['name'] for c in inspect(conn).get_check_constraints(name)}
                    self.assertEqual(expected,actual)
                migrate(conn,'0046_classic_preferences','downgrade')
                self.assertFalse(inspect(conn).has_table('classic_draft_workflows'))
                self.assertNotIn('source_cue_id',{x['name'] for x in inspect(conn).get_columns('edit_revision_media')})
                migrate(conn,'0047_professional_inputs')
                self.assertEqual(bytes(conn.scalar(select(S.artifact_versions.c.document).where(S.artifact_versions.c.id==old['id']))),b'Legacy plain text.')
            new=f.write('create_artifact',dict(artifact_key='new-professional',artifact_type='professional-test',document={'professional_inputs':[dict(id=old['id'],sha256=old['sha256'],kind='screenplay')]},dependency_ids=[old['id']]))
            with self.assertRaises(IntegrityError) as rejected:
                with engine.begin() as conn:migrate(conn,'0046_classic_preferences','downgrade')
            self.assertEqual(rejected.exception.orig.sqlstate,'23514')
            with engine.connect() as conn:
                self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')),'0047_professional_inputs')
                self.assertEqual(conn.scalar(select(S.artifact_versions.c.sha256).where(S.artifact_versions.c.id==new['id'])),new['sha256'])
