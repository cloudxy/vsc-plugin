"""CT-0110 isolated PostgreSQL source-job facts and safe schema cutover."""
import unittest
import uuid
from sqlalchemy import insert, select, update, delete, text, inspect
from sqlalchemy.exc import IntegrityError
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.adapters.persistence.postgres import schema as S
from vsc.adapters.persistence.postgres.values import digest


def uid(): return str(uuid.uuid4())


def migrate(conn, target, direction='upgrade'):
    cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'));cfg.attributes['connection']=conn
    getattr(command,direction)(cfg,target)


_UNSET=object()


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class EditSourceJobSchemaTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.job_no=0
        self.video=self.media('fixed source video',modality='video')
        self.run=self.write('create_artifact',dict(artifact_key='schema-run',artifact_type='synthetic-schema-run',document={'source':'database constraint fixture'}))['id']
        self.provider='source-job-'+uuid.uuid4().hex;self.model=uid()
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=self.provider,name='offline source schema',modality='video',base_url='https://example.invalid',auth_ref='none',enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=self.model,provider_id=self.provider,model_key='offline',model_version='1',modality='video',capabilities={},default_params={},cost_rule={},enabled=True))

    def job(self,shot=None,media=None,status='succeeded',purpose='video_clip',project=None,run=None):
        self.job_no+=1;identifier=uid();p=project or self.p
        with self.engine.begin() as conn:
            conn.execute(insert(S.generation_jobs).values(project_id=p,id=identifier,run_version_id=run or self.run,
                shot_id=shot or self.objects['shot'],purpose=purpose,modality='video',candidate_no=self.job_no,
                provider_id=self.provider,model_id=self.model,model_version='1',request_payload={},
                request_sha256='0'*64,context_sha256='0'*64,idempotency_key=uid(),status=status,attempt=0))
            conn.execute(insert(S.job_outputs).values(project_id=p,id=uid(),job_id=identifier,media_id=media or self.video,asset_type='video'))
        return identifier

    def edit(self,conn,job=None,body_job=_UNSET,shot=None,body_shot=_UNSET,media=None,track='clips',episode=None):
        shot=shot or self.objects['shot'];episode=episode or self.objects['episode'];media=media or self.video
        workspace=conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id==self.p,S.edit_workspaces.c.episode_id==episode)).mappings().first()
        if workspace is None:
            workspace={'id':uid()};conn.execute(insert(S.edit_workspaces).values(project_id=self.p,**workspace,episode_id=episode,title='Source-job constraint edit',revision=0))
        version=conn.scalar(text('SELECT coalesce(max(version),0)+1 FROM edit_revisions WHERE project_id=:p AND workspace_id=:w'),dict(p=self.p,w=workspace['id']))
        clip=dict(id='fixed-clip',media_id=media,shot_id=shot if body_shot is _UNSET else body_shot,in_frame=0,out_frame=24)
        pin=job if body_job is _UNSET else body_job
        if pin is not None:clip['source_job_id']=pin
        document={'clips':[], 'audio':[]};document[track]=[clip]
        identifier=uid();conn.execute(insert(S.edit_revisions).values(project_id=self.p,id=identifier,workspace_id=workspace['id'],version=version,
            document=document,sha256=digest(document),member_count=1,created_by='test-human'))
        source=self.store._media(conn,self.p,media)
        conn.execute(insert(S.edit_revision_media).values(project_id=self.p,id=uid(),edit_version_id=identifier,media_id=media,
            shot_id=shot,blob_id=source['blob_id'],blob_sha256=source['sha256'],clip_key='fixed-clip',track=track,
            ordinal=0,source_in_frame=0,source_out_frame=24,offset_frame=0,modality='video',source_job_id=job))
        return identifier

    def rejects(self,callback,code='23514'):
        with self.assertRaises(IntegrityError) as rejected:
            with self.engine.begin() as conn:callback(conn)
        self.assertEqual(rejected.exception.orig.sqlstate,code)

    def test_source_job_typed_original_output_body_scope_and_safe_migration(self):
        with self.engine.begin() as conn:legacy=self.edit(conn)
        with self.engine.begin() as conn:
            self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
            self.assertIn('ck_edit_revision_media_job_source',{r['name'] for r in inspect(conn).get_check_constraints('edit_revision_media')})
            old=conn.scalar(select(S.edit_revisions.c.document).where(S.edit_revisions.c.id==legacy))
            migrate(conn,'0046_classic_preferences','downgrade')
            self.assertNotIn('source_job_id',{r['name'] for r in inspect(conn).get_columns('edit_revision_media')})
            migrate(conn,'0047_professional_inputs')
            self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
            self.assertIsNone(conn.scalar(select(S.edit_revision_media.c.source_job_id).where(S.edit_revision_media.c.edit_version_id==legacy)))
            self.assertEqual(conn.scalar(select(S.edit_revisions.c.document).where(S.edit_revisions.c.id==legacy)),old)
        job=self.job();other_job=self.job()
        with self.engine.begin() as conn:
            fixed=self.edit(conn,job);second=self.edit(conn,other_job)
        # Two original jobs may produce the same media; each explicit pin is stable.
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(S.edit_revision_media.c.source_job_id).where(S.edit_revision_media.c.edit_version_id==fixed)),job)
            self.assertEqual(conn.scalar(select(S.edit_revision_media.c.source_job_id).where(S.edit_revision_media.c.edit_version_id==second)),other_job)
        self.rejects(lambda c:self.edit(c,job,body_job=None))
        self.rejects(lambda c:self.edit(c,job,body_job=other_job))
        self.rejects(lambda c:self.edit(c,None,body_job=job))
        self.rejects(lambda c:self.edit(c,uid()),'23503')
        other_media=self.media('other source video',modality='video')
        self.rejects(lambda c:self.edit(c,job,media=other_media),'23503')
        self.rejects(lambda c:self.edit(c,job,track='audio'))
        wrong_shot=self.write('create_object',dict(kind='shot',parent_id=self.objects['sequence'],display_code='OTHER-SHOT',ordinal=1))['id']
        self.rejects(lambda c:self.edit(c,job,shot=wrong_shot))
        self.rejects(lambda c:self.edit(c,job,body_shot=wrong_shot))
        running=self.job(status='running');depth=self.job(purpose='depth')
        self.rejects(lambda c:self.edit(c,running));self.rejects(lambda c:self.edit(c,depth))
        parent=self.objects['work']
        for kind in ('episode','scene','sequence','shot'):
            parent=self.write('create_object',dict(kind=kind,parent_id=parent,display_code='OTHER-'+kind,ordinal=2))['id']
        external_job=self.job(shot=parent)
        self.rejects(lambda c:self.edit(c,external_job,shot=parent))
        foreign=ResourceStoreFixture();foreign.engine=self.engine;foreign.store=self.store;foreign.service=self.service;foreign.setUp()
        objects=foreign.hierarchy();video=foreign.media('foreign source video',modality='video')
        run=foreign.write('create_artifact',dict(artifact_key='foreign-run',artifact_type='synthetic-schema-run',document={}))['id']
        foreign_job=self.job(shot=objects['shot'],media=video,project=foreign.p,run=run)
        self.rejects(lambda c:self.edit(c,foreign_job),'23503')
        for statement in (update(S.edit_revision_media).where(S.edit_revision_media.c.edit_version_id==fixed).values(source_job_id=other_job),
                          delete(S.edit_revision_media).where(S.edit_revision_media.c.edit_version_id==fixed)):
            self.rejects(lambda c,s=statement:c.execute(s))
        self.rejects(lambda c:migrate(c,'0046_classic_preferences','downgrade'))
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(text('SELECT version_num FROM alembic_version')),'0047_professional_inputs')
            self.assertEqual(conn.scalar(select(S.edit_revision_media.c.source_job_id).where(S.edit_revision_media.c.edit_version_id==fixed)),job)
            self.assertEqual(conn.scalar(select(S.edit_revisions.c.document).where(S.edit_revisions.c.id==fixed))['clips'][0]['source_job_id'],job)
