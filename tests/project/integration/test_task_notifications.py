"""Original worker facts, late old tasks, personal reading and stable recovery."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import io
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid
import support.paths
from support.paths import ROOT
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.access_control import Principal,set_principal,reset_principal
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class TaskNotificationTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-task-notice-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service.storage=LocalStorage(self.root/'storage')
        self.owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**self.owner));self.addCleanup(reset_principal,token)

    @contextmanager
    def as_identity(self,binding):
        token=set_principal(Principal(**binding))
        try:yield
        finally:reset_principal(token)

    def imports(self,count=1,title='原上传'):
        sha=hashlib.sha256(b'x').hexdigest()
        return self.write('create_media_import',dict(title=title,files=[dict(filename=title+str(i)+'.txt',size_bytes=1,sha256=sha) for i in range(count)],rights='unknown',source_evidence=''))

    def test_late_old_task_beyond_latest_hundred_and_stable_pages(self):
        old=self.imports(title='旧任务');old_item=self.service.get_media_import(self.p,old['id'])['items'][0]
        for n in range(3):self.imports(60,'新批次'+str(n))
        revision=self.rev;first=self.service.get_task_notifications(self.p,limit=17);self.assertEqual(first['unread_count'],181)
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        self.assertEqual(self.service.get_task_notifications(self.p,limit=17)['through_sequence'],first['through_sequence'])
        self.service.read_task_notifications(self.p,{'through_sequence':first['through_sequence']})
        self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],0)
        extra=self.imports(2,'游标之后');second=self.service.get_task_notifications(self.p,limit=17,cursor=first['next_cursor'])
        self.assertTrue(set(r['id'] for r in first['items']).isdisjoint(r['id'] for r in second['items']))
        self.assertTrue(all(r['sequence']<=first['through_sequence'] for r in second['items']))
        uploaded=self.service.upload_import_chunk(self.p,old['id'],old_item['id'],0,b'x',actor='test-human');self.rev=uploaded['revision']
        self.write('process_media_import_item',dict(batch_id=old['id'],item_id=old_item['id']))
        notices=self.service.get_task_notifications(self.p,limit=10,unread_only=True)
        late=next(r for r in notices['items'] if r['origin_id']==old_item['id']);self.assertEqual(late['observed_status'],'completed')
        self.assertGreater(late['sequence'],first['through_sequence']);self.assertIn('task_id='+old_item['id'],late['task_href'])
        original=self.service.get_task_origin(self.p,'import',old_item['id'])['task'];self.assertEqual(original['target_id'],old['id'])
        self.assertFalse(any(r['id']==old_item['id'] for r in self.service.get_task_center(self.p,limit=100)['items']))

    def test_identity_project_read_isolation_and_idempotent_read_receipt(self):
        self.imports(2);first=self.service.get_task_notifications(self.p,limit=1);event=first['items'][0]
        other_identity=self.service.ensure_local_access('notice-second-member')
        with self.as_identity(other_identity):
            self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],2)
            with self.assertRaises(ResourceError):self.service.get_task_notifications(self.p,cursor=first['next_cursor'])
        self.assertEqual(self.service.read_task_notifications(self.p,{'ids':[event['id']]})['marked_count'],1)
        self.assertEqual(self.service.read_task_notifications(self.p,{'ids':[event['id']]})['marked_count'],0)
        with self.as_identity(other_identity):self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],2)
        other=self.service.create_project(dict(name='另一项目'),actor='test-human')['id']
        with self.assertRaises(ResourceError):self.service.read_task_notifications(other,{'ids':[event['id']]})
        with self.assertRaises(ResourceError):self.service.get_task_origin(other,'import',event['origin_id'])
        self.assertEqual(self.service.get_task_notifications(other)['unread_count'],0)

    def test_original_render_worker_failure_without_project_revision_is_discovered(self):
        from support.fixtures.media import production_media
        from vsc.post.first_cut_worker import FirstCutWorker
        objects=self.hierarchy();staged=self.service.storage.stage_upload(io.BytesIO(production_media()['png']),'source.png')
        media=self.write('register_media',dict(staged_upload=staged['staged_upload'],rights='unknown',source={'kind':'fixture','content':'synthetic pixels'}))
        doc=dict(format='vsc.edit-workspace/v1',width=128,height=128,fps=24,clips=[dict(id='one',media_id=media['id'],in_frame=0,out_frame=12,volume=1)],audio=[],captions=[])
        edit=self.write('save_edit_workspace',dict(episode_id=objects['episode'],edit_revision=0,document=doc));queued=self.write('request_edit_export',dict(edit_version_id=edit['edit_version_id']))
        self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],0);revision=self.rev
        fixed=self.service.get_media(self.p,media['id']);location=next(row for row in fixed['locations'] if row['storage']=='local');self.service.storage.verify(location['object_key'],fixed['sha256']).write_bytes(b'corrupted fixture')
        finished=FirstCutWorker(self.store,self.service.storage).run_once(self.p);self.assertEqual(finished['status'],'failed',finished)
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        notice=self.service.get_task_notifications(self.p)['items'][0];self.assertEqual(notice['origin_id'],queued['id']);self.assertEqual(notice['observed_status'],'failed');self.assertTrue(notice['error'])

    def test_batch_partial_completion_is_not_reported_as_all_success(self):
        from vsc.assets.text_tools import COMMON,DEFAULTS
        class Host:
            name='isolated-notification-host'
            def available(self):return True
            def generate(self,tool,action,document,references):
                if document['source_text'].startswith('失败'):raise ResourceError('synthetic failure','text_host_failed')
                return dict(analysis='明确分析',category='短剧',channel='家庭',card_start_line=1,card_end_line=2)
        self.service.text_tool_host=Host();self.addCleanup(delattr,self.service,'text_tool_host');units=[]
        for index,title in enumerate(('成功片段','失败片段')):
            unit=self.write('save_text_tool',dict(tool='scoring',group_key='notices',unit_key=str(index),title=title,ordinal=index,episode_id=None,base_version_id=None,document={**deepcopy(COMMON),**deepcopy(DEFAULTS['scoring']),'source_text':title+'\n第二行'}));units.append(unit['unit_id'])
        batch=self.write('create_text_batch',dict(tool='scoring',action='analyze',unit_ids=units,auto_accept=False))
        for _ in range(3):self.write('process_text_batch',dict(batch_id=batch['id']))
        notice=next(r for r in self.service.get_task_notifications(self.p)['items'] if r['kind']=='text_batch')
        self.assertEqual(notice['outcome'],'partial');self.assertEqual(notice['progress']['completed'],1);self.assertEqual(notice['progress']['failed'],1)
        self.assertEqual(notice['current_status'],'running');self.assertEqual(notice['observed_status'],'running')
        fixed=self.service.get_task_origin(self.p,'text_batch',batch['id'])['task'];self.assertEqual(len(fixed['children']),2)
        self.write('stop_text_batch',dict(batch_id=batch['id']))
        stopped=next(r for r in self.service.get_task_notifications(self.p)['items'] if r['kind']=='text_batch')
        self.assertEqual(stopped['outcome'],'stopped');self.assertEqual(stopped['observed_status'],'stopped')

    def test_http_viewer_can_read_personal_notices_without_project_edit_authority(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        self.imports();preview=self.service.access_migration_preview(self.p,self.owner['workspace_id'])
        def command(action,payload):return self.service.access_command(action,payload,expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
        command('assign-project',dict(project_id=self.p,workspace_id=self.owner['workspace_id'],preview_sha256=preview['sha256']))
        secret=secrets.token_urlsafe(32);credential=secrets.token_urlsafe(32)
        command('invitation',dict(scope='project',scope_id=self.p,role='viewer',secret=secret,expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        viewer=self.service.accept_access_invitation(dict(invitation_secret=secret,credential_secret=credential,display_name='通知只读成员'))
        app=create_app(dict(projects_root=str(self.root/'projects'),allowed_hosts=['testserver'],allowed_origins=['http://testserver'],access_token='local-secret',human_identity='test-human',background_enabled=False),service=self.service)
        with TestClient(app) as client:
            url='/api/v1/projects/'+self.p+'/task-notifications'
            self.assertEqual(client.get(url).status_code,403)
            response=client.post('/api/v1/access/login',json={'secret':credential},headers={'Origin':'http://testserver'});self.assertEqual(response.status_code,200,response.text)
            headers={'Origin':'http://testserver','X-CSRF-Token':response.json()['csrf_token']};value=client.get(url);self.assertEqual(value.status_code,200,value.text)
            event=value.json()['items'][0];body={'payload':{'ids':[event['id']]}}
            self.assertEqual(client.post(url+'/read',json=body).status_code,403)
            revision=self.service.get_project(self.p)['revision'];written=client.post(url+'/read',json=body,headers=headers);self.assertEqual(written.status_code,200,written.text)
            self.assertEqual(client.get(url).json()['unread_count'],0);self.assertEqual(self.service.get_project(self.p)['revision'],revision)
            denied=client.post('/api/v1/projects/'+self.p+'/objects',json={'payload':{'kind':'work','display_code':'FORBIDDEN'},'expected_revision':revision,'idempotency_key':'not-authorized'},headers=headers);self.assertEqual(denied.status_code,403)
        self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],1)

    def test_unknown_receipt_notifies_original_attempt_without_resubmitting(self):
        from vsc.assets.text_tools import COMMON,DEFAULTS
        class Host:
            name='isolated-unknown-host';calls=0
            def available(self):return True
            def generate(self,*args):self.calls+=1;raise TimeoutError('isolated timeout')
        host=Host();self.service.text_tool_host=host;self.addCleanup(delattr,self.service,'text_tool_host')
        unit=self.write('save_text_tool',dict(tool='novel',group_key='unknown',unit_key='one',title='未知原任务',ordinal=0,episode_id=None,base_version_id=None,document={**deepcopy(COMMON),**deepcopy(DEFAULTS['novel']),'body':'固定人工稿'}))
        payload=dict(unit_id=unit['unit_id'],input_version_id=unit['id'],action='body',new_attempt=True)
        first=self.write('run_text_tool',payload);self.assertEqual(first['status'],'submission_unknown')
        notice=self.service.get_task_notifications(self.p)['items'][0];self.assertEqual(notice['origin_id'],first['id']);self.assertEqual(notice['observed_status'],'submission_unknown')
        self.service.read_task_notifications(self.p,{'ids':[notice['id']]})
        repeated=self.write('run_text_tool',payload);self.assertEqual(repeated['id'],first['id']);self.assertEqual(host.calls,1)
        self.assertEqual(self.service.get_task_notifications(self.p)['unread_count'],0)
        self.assertEqual(self.service.get_task_origin(self.p,'text',first['id'])['task']['target_id'],unit['unit_id'])

    def test_empty_migration_rollback_and_immutable_typed_notification_history(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text,update,insert
        from sqlalchemy.exc import IntegrityError
        from support.fixtures.postgres import isolated_postgres
        from vsc.adapters.persistence.postgres import schema as S
        with isolated_postgres(TEST_URL) as engine:
            cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
            with engine.begin() as conn:
                cfg.attributes['connection']=conn;command.downgrade(cfg,'0042_community_publication');self.assertIsNone(conn.scalar(text("SELECT to_regclass('task_notification_events')")));command.upgrade(cfg,'head')
        self.imports();event=self.service.get_task_notifications(self.p)['items'][0]
        self.service.read_task_notifications(self.p,{'ids':[event['id']]})
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(update(S.task_notification_events).where(S.task_notification_events.c.project_id==self.p).values(observed_status='succeeded'))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(update(S.task_notification_reads).where(S.task_notification_reads.c.project_id==self.p).values(identity_id=str(uuid.uuid4())))
        other=self.service.create_project({'name':'foreign-scope'},actor='test-human')['id']
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(insert(S.task_notification_events).values(project_id=other,id=str(uuid.uuid4()),kind='import',media_import_item_id=event['origin_id'],source_token='0'*64,observed_status='awaiting_upload'))
        cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
        with self.engine.connect() as conn:
            cfg.attributes['connection']=conn
            with self.assertRaises(IntegrityError):
                with conn.begin():command.downgrade(cfg,'0042_community_publication')
            self.assertEqual(conn.scalar(text('SELECT count(*) FROM task_notification_events WHERE project_id=:p'),{'p':self.p}),1)
