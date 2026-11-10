"""Real PostgreSQL direct-copy receipt, sealed mapping and migration constraints."""
from copy import deepcopy
import importlib.util
import os
import unittest
import uuid
from support.fixtures.resource_store import ResourceStoreFixture


class DirectCanvasCopyConstraintTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.objects=self.hierarchy();self.episode=self.objects['episode']
        self.media_id=self.media('direct-constraint-source')
        self.source=self.write('create_creative_canvas',dict(document={'nodes':[dict(id='source-image',type='image',media_id=self.media_id)],'edges':[]}))

    def clone(self, fault=None, nested=False):
        from sqlalchemy import insert,select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import new_id
        p=self.p;key=uuid.uuid4().hex;copy_id=new_id();source=self.source
        def callback(c,project):
            def create_target():
                old=dict(c.execute(select(S.media_items).where(S.media_items.c.project_id==p,S.media_items.c.id==self.media_id)).mappings().one())
                old['id']=self.old_media if fault=='old_media' else new_id();old.pop('created_at')
                if fault=='modality':old['modality']='audio'
                if fault!='old_media':c.execute(insert(S.media_items).values(**old))
                target_media=old['id']
                document=deepcopy(self.store._canvas_document(c,p,self.store._one(c,S.creative_canvas_versions,p,source['version_id'])))
                for node in document['nodes']:
                    node['id']='clone-'+new_id();node['media_id']=target_media if node['media_id'] else None;node['job_id']=None
                canvas=dict(id=new_id(),episode_id=self.episode)
                c.execute(insert(S.creative_canvases).values(project_id=p,created_by='test-human',**canvas))
                result=self.store._insert_canvas_version(c,project,canvas,dict(title='direct copy',document=document),'test-human')
                return result,target_media,old['blob_id']
            if nested:
                with c.begin_nested():result,target_media,blob=create_target()
            else:result,target_media,blob=create_target()
            if fault=='old_canvas':result=dict(result,id=source['id'],version_id=source['version_id'])
            root=dict(project_id=p,id=copy_id,canvas_id=result['id'],canvas_version_id=result['version_id'],source_project_id=p,source_canvas_id=source['id'],source_version_id=source['version_id'],command_key=key,created_by='test-human')
            if fault=='wrong_source_version':root['source_version_id']=result['version_id']
            c.execute(insert(S.canvas_direct_copies).values(**root))
            mapping=dict(project_id=p,id=new_id(),copy_id=copy_id,source_project_id=p,source_media_id=self.media_id,target_media_id=target_media,blob_id=blob,sha256=c.scalar(select(S.media_blobs.c.sha256).where(S.media_blobs.c.id==blob)))
            if fault=='wrong_blob':mapping['blob_id']=new_id()
            if fault=='wrong_source_project':mapping['source_project_id']=new_id()
            if fault!='missing_mapping':c.execute(insert(S.canvas_direct_copy_media).values(**mapping))
            if fault=='extra_mapping':
                # An extra unrelated source and fresh target cannot be hidden by a valid count.
                extra=dict(c.execute(select(S.media_items).where(S.media_items.c.project_id==p,S.media_items.c.id==self.media_id)).mappings().one())
                extra['id']=new_id();extra.pop('created_at',None);c.execute(insert(S.media_items).values(**extra));extra_source=extra['id']
                extra['id']=new_id();extra.pop('created_at',None);c.execute(insert(S.media_items).values(**extra))
                c.execute(insert(S.canvas_direct_copy_media).values(**dict(mapping,id=new_id(),source_media_id=extra_source,target_media_id=extra['id'])))
            response=dict(result,copy_id=copy_id,source_project_id=p,source_canvas_id=source['id'],source_version_id=source['version_id'],media_count=2 if fault=='extra_mapping' else 0 if fault=='missing_mapping' else 1,domain_count=0,provider_submitted=False)
            if fault=='receipt_identity':response['copy_id']=new_id()
            if fault=='missing_receipt':return response
            return response
        if fault=='missing_receipt':
            with self.engine.begin() as c:return callback(c,self.store._project(c,p))
        result=self.store._mutate(p,'wrong_action' if fault=='receipt_action' else 'copy_direct_canvas',{},self.rev,key,'wrong-actor' if fault=='receipt_actor' else 'test-human',callback)
        self.rev=result['revision'];return result

    def test_new_identity_mapping_receipt_and_released_savepoint(self):
        from sqlalchemy import text
        for nested in (False,True):
            with self.subTest(nested=nested):
                result=self.clone(nested=nested)
                self.assertNotEqual(result['id'],self.source['id'])
                with self.engine.connect() as c:
                    self.assertFalse(c.scalar(text("SELECT vsc_direct_copy_new_row(pg_current_xact_id()::text::xid,transaction_timestamp()-interval '1 day')")))
                    self.assertEqual(c.execute(text('SELECT count(*) FROM canvas_direct_copy_media WHERE project_id=:p AND copy_id=:i'),dict(p=self.p,i=result['copy_id'])).scalar_one(),1)
                    self.assertEqual(c.execute(text('SELECT source_media_id<>target_media_id FROM canvas_direct_copy_media WHERE project_id=:p AND copy_id=:i'),dict(p=self.p,i=result['copy_id'])).scalar_one(),True)

    def test_wrong_scope_blob_closure_receipt_and_old_identity_roll_back(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from vsc.assets.resource_service import ResourceError
        self.old_media=self.media('direct-constraint-source')
        for fault in ('modality','old_media','wrong_source_version','wrong_source_project','wrong_blob','missing_mapping','extra_mapping','receipt_identity','receipt_action','receipt_actor','missing_receipt','old_canvas'):
            with self.subTest(fault=fault):
                before=self.service.get_project(self.p)['revision']
                with self.assertRaises((ResourceError,DBAPIError)):self.clone(fault)
                with self.engine.connect() as c:
                    self.assertEqual(c.execute(text('SELECT count(*) FROM canvas_direct_copies WHERE project_id=:p'),dict(p=self.p)).scalar_one(),0)
                self.assertEqual(self.service.get_project(self.p)['revision'],before)

    def test_members_and_root_cannot_mutate_or_append_after_receipt(self):
        from sqlalchemy import insert,select,text
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        result=self.clone()
        for table in ('canvas_direct_copies','canvas_direct_copy_media'):
            for verb in ('UPDATE','DELETE'):
                with self.subTest(table=table,verb=verb),self.assertRaises(DBAPIError),self.engine.begin() as c:
                    sql=('UPDATE '+table+' SET id=id' if verb=='UPDATE' else 'DELETE FROM '+table)+' WHERE project_id=:p'
                    c.execute(text(sql),dict(p=self.p))
        with self.assertRaisesRegex(DBAPIError,'sealed'),self.engine.begin() as c:
            row=dict(c.execute(select(S.canvas_direct_copy_media).where(S.canvas_direct_copy_media.c.project_id==self.p)).mappings().one())
            row['id']=str(uuid.uuid4());c.execute(insert(S.canvas_direct_copy_media).values(**row))
        with self.assertRaisesRegex(DBAPIError,'sealed'),self.engine.begin() as c:
            c.execute(insert(S.canvas_direct_copy_domains).values(project_id=self.p,id=str(uuid.uuid4()),copy_id=result['copy_id'],source_project_id=self.p,source_tool_version_id=str(uuid.uuid4()),target_tool_version_id=str(uuid.uuid4())))

    def test_migration_roundtrip_metadata_old_facts_and_nonempty_downgrade(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres import schema as S
        cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
        # This method's project has no direct copies, but the class schema may
        # contain earlier methods' immutable copies. Use a separate real schema.
        from support.fixtures.postgres import isolated_postgres
        with isolated_postgres(os.environ['VSC_TEST_DATABASE_URL']) as engine:
            from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
            from vsc.assets.resource_service import ResourceService
            service=ResourceService(PostgresResourceStore(engine=engine))
            project=service.create_project({'name':'Legacy template facts'},actor='test-human')['id']
            canvas=service.create_creative_canvas(project,{'document':{'nodes':[],'edges':[]}},actor='test-human',expected_revision=0,idempotency_key='legacy-canvas')
            service.publish_canvas_template(project,dict(canvas_id=canvas['id'],canvas_revision=1,title='Legacy template'),actor='test-human',expected_revision=1,idempotency_key='legacy-template')
            def legacy():
                with engine.connect() as c:return {name:c.scalar(text("SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]'::jsonb) FROM "+name+' t')) for name in ('creative_canvases','creative_canvas_versions','canvas_templates','project_revisions','command_receipts')}
            before=legacy()
            with engine.begin() as c:cfg.attributes['connection']=c;command.downgrade(cfg,'0052_canvas_lifecycle')
            with engine.connect() as c:
                self.assertIsNone(c.scalar(text("SELECT to_regclass('canvas_direct_copies')")))
                self.assertNotIn('canvas_direct_copy_media',c.scalar(text("SELECT pg_get_functiondef('vsc_library_has_imported_ancestor(uuid,uuid)'::regprocedure)")))
            with engine.begin() as c:cfg.attributes['connection']=c;command.upgrade(cfg,'head')
            with engine.connect() as c:
                self.assertEqual(compare_metadata(MigrationContext.configure(c),S.metadata),[])
                self.assertIn('canvas_direct_copy_media',c.scalar(text("SELECT pg_get_functiondef('vsc_library_has_imported_ancestor(uuid,uuid)'::regprocedure)")))
            self.assertEqual(legacy(),before)
        self.clone()
        with self.assertRaisesRegex(DBAPIError,'facts exist'),self.engine.begin() as c:cfg.attributes['connection']=c;command.downgrade(cfg,'0052_canvas_lifecycle')
        with self.engine.connect() as c:self.assertEqual(c.scalar(text('SELECT version_num FROM alembic_version')),'0053_canvas_direct_copies')

    def test_typed_domain_closure_new_identity_and_sealed_domain_rows(self):
        from sqlalchemy import insert,text
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.adapters.persistence.postgres.values import new_id
        from vsc.assets.spatial_scene import default_scene
        from vsc.assets.resource_service import ResourceError
        spatial=self.write('create_spatial_scene',dict(mode='previs',document=default_scene()))
        source=self.write('create_creative_canvas',dict(document={'nodes':[dict(id='space',type='spatial',domain_object_id=spatial['id'],domain_version_id=spatial['version_id'])],'edges':[]}))
        def copy(fault=None):
            copy_id=new_id();key=new_id()
            def work(c,project):
                target=self.store.create_spatial_scene(self.p,dict(mode='previs',episode_id=self.episode,document=default_scene()),actor='test-human',expected_revision=project['revision'],idempotency_key='internal',_transaction=(c,project))
                canvas=dict(id=new_id(),episode_id=self.episode)
                c.execute(insert(S.creative_canvases).values(project_id=self.p,created_by='test-human',**canvas))
                doc={'nodes':[dict(id='new-space',type='spatial',domain_object_id=target['id'],domain_version_id=target['version_id'])],'edges':[]}
                from vsc.assets.creative_canvas import normalize_document
                result=self.store._insert_canvas_version(c,project,canvas,dict(title='typed clone',document=normalize_document(doc)),'test-human')
                c.execute(insert(S.canvas_direct_copies).values(project_id=self.p,id=copy_id,canvas_id=result['id'],canvas_version_id=result['version_id'],source_project_id=self.p,source_canvas_id=source['id'],source_version_id=source['version_id'],command_key=key,created_by='test-human'))
                mapping=dict(project_id=self.p,id=new_id(),copy_id=copy_id,source_project_id=self.p,source_spatial_version_id=spatial['version_id'],target_spatial_version_id=target['version_id'])
                if fault=='old_domain':mapping['target_spatial_version_id']=spatial['version_id']
                if fault=='unpaired':mapping['target_spatial_version_id']=None
                if fault=='two_kinds':mapping.update(source_edit_version_id=new_id(),target_edit_version_id=new_id())
                if fault!='missing':c.execute(insert(S.canvas_direct_copy_domains).values(**mapping))
                return dict(result,copy_id=copy_id,source_project_id=self.p,source_canvas_id=source['id'],source_version_id=source['version_id'],media_count=0,domain_count=0 if fault=='missing' else 1,provider_submitted=False)
            result=self.store._mutate(self.p,'copy_direct_canvas',{},self.rev,key,'test-human',work);self.rev=result['revision'];return result
        for fault in ('old_domain','unpaired','two_kinds','missing'):
            with self.subTest(fault=fault),self.assertRaises((ResourceError,DBAPIError)):copy(fault)
        copy()
        for verb in ('UPDATE','DELETE'):
            with self.subTest(verb=verb),self.assertRaises(DBAPIError),self.engine.begin() as c:
                c.execute(text(('UPDATE canvas_direct_copy_domains SET id=id' if verb=='UPDATE' else 'DELETE FROM canvas_direct_copy_domains')+' WHERE project_id=:p'),dict(p=self.p))

    def test_library_direct_ancestor_cannot_be_hidden_by_owned_rights(self):
        import io,tempfile
        from PIL import Image
        from sqlalchemy import text,select,insert
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceError
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.service.storage=LocalStorage(directory.name)
        data=io.BytesIO();Image.new('RGB',(8,8),'green').save(data,format='PNG')
        staged=self.service.storage.stage_upload(io.BytesIO(data.getvalue()),'owned.png')
        media=self.write('register_media',dict(staged_upload=staged['staged_upload'],rights='owned',rights_scope={'purposes':['*']},source={'kind':'fixture','content':'Synthetic original'}))['id']
        self.write('record_media_check',dict(media_id=media,checker='fixture',criteria_version='1',outcome='pass'))
        description=dict(library_key='direct-library-'+uuid.uuid4().hex,title='Synthetic original',category='image',description='Synthetic public reference',specification={},allowed_purposes=['*'],license={'outcome':'owned','allow_workspace_reuse':True,'evidence':'Synthetic original'})
        version=self.write('publish_library',dict(description,members=[{'media_id':media,'member_key':'reference','role':'first_frame'}]))
        # Reference-mode reuse remains a library ancestor even within one project.
        shot=self.objects['shot']
        borrowed=self.write('use_library',dict(library_version_id=version['library_version_id'],member_key='reference',target_object_id=shot,role='first_frame',select=False))
        source=self.write('create_creative_canvas',dict(document={'nodes':[dict(id='borrowed',type='image',media_id=borrowed['media_id'])],'edges':[]}))
        result=self.write('copy_direct_canvas',dict(source_project_id=self.p,source_canvas_id=source['id'],source_version_id=source['version_id'],source_sha256=source['sha256'],episode_id=self.episode,title='Direct descendant'))
        with self.engine.connect() as c:
            target=c.scalar(select(S.canvas_direct_copy_media.c.target_media_id).where(S.canvas_direct_copy_media.c.project_id==self.p,S.canvas_direct_copy_media.c.copy_id==result['copy_id']))
            self.assertTrue(c.scalar(text('SELECT vsc_library_has_imported_ancestor(CAST(:p AS uuid),CAST(:m AS uuid))'),dict(p=self.p,m=target)))
        item=self.service.get_media(self.p,target)
        self.write('decide_rights',dict(media_id=target,source_id=item['rights']['source_id'],outcome='owned',scope={'purposes':['*']},reason='Synthetic attempted ownership masking'))
        with self.assertRaises(ResourceError) as caught:self.write('publish_library',dict(description,library_key='masked-'+uuid.uuid4().hex,members=[{'media_id':target,'member_key':'masked'}]))
        self.assertEqual(caught.exception.code,'library_republish_not_supported')
        # The database publish edge must reject independently of service checks.
        item=self.service.get_media(self.p,target)
        with self.assertRaises(DBAPIError),self.engine.begin() as c:
            c.execute(insert(S.library_reuses).values(project_id=self.p,id=str(uuid.uuid4()),media_id=target,
                source_id=item['rights']['source_id'],rights_decision_id=item['rights']['id'],library_key=description['library_key'],library_version='1',reuse_mode='publish',library_version_id=version['library_version_id'],member_key='reference',blob_id=item['blob_id']))
