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
from urllib.parse import parse_qs,urlparse
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

    def generation_record(self,shot_id,status='failed',working=False):
        """Original task facts only; no generation adapter or remote request."""
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        draft=None
        if working:
            draft=self.write('create_artifact',dict(artifact_key='notice-draft:'+uuid.uuid4().hex,
                artifact_type='classic-production-draft',document=dict(shot_id=shot_id,mode='image_text',references=[])))
            with self.engine.begin() as conn:
                project=self.store._project(conn,self.p,lock=True)
                run=self.store._create_artifact(conn,project,dict(artifact_key='notice-run:'+uuid.uuid4().hex,
                    artifact_type='workbench-generation-run',document={'workbench_draft':{'id':draft['id'],'sha256':draft['sha256']}}))
                conn.execute(insert(S.workbench_run_inputs).values(project_id=self.p,id=str(uuid.uuid4()),run_version_id=run['id'],
                    shot_id=shot_id,draft_version_id=draft['id'],draft_sha256=draft['sha256'],output_kind='image'))
        else:
            run=self.write('create_artifact',dict(artifact_key='notice-run:'+uuid.uuid4().hex,
                artifact_type='production-run',document={'synthetic_notification_fixture':True}))
        provider='notice-fixture-'+uuid.uuid4().hex;model=str(uuid.uuid4());identifier=str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(S.providers).values(id=provider,name='isolated notification fixture',modality='image',
                base_url='https://example.invalid',auth_ref='none',enabled=True,rate_limit={}))
            conn.execute(insert(S.provider_models).values(id=model,provider_id=provider,model_key='fixture',modality='image',
                model_version='1',capabilities={},default_params={},cost_rule={},enabled=True))
            conn.execute(insert(S.generation_jobs).values(project_id=self.p,id=identifier,run_version_id=run['id'],
                shot_id=shot_id,purpose='first_frame',modality='image',candidate_no=0,provider_id=provider,model_id=model,
                model_version='1',request_payload={},request_sha256='0'*64,context_sha256='0'*64,
                idempotency_key=identifier,status=status,attempt=1))
        return dict(id=identifier,run_id=run['id'],draft_id=draft['id'] if draft else None)

    def test_generation_uses_fixed_canvas_producer_and_episode_without_retargeting_later_uses(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        objects=self.hierarchy()
        episode=self.write('create_object',dict(kind='episode',display_code='CANVAS_EPISODE',parent_id=objects['work'],ordinal=1))['id']
        for producer in ('run','preparation','working_input','later_use_only'):
            with self.subTest(producer=producer):
                job=self.generation_record(objects['shot'],working=producer=='working_input')
                canvas_episode=objects['episode'] if producer=='preparation' else episode
                canvas=self.write('create_creative_canvas',dict(episode_id=canvas_episode,document=dict(
                    nodes=[dict(id='output',type='image',job_id=job['id'] if producer=='preparation' else None)],edges=[])))
                with self.engine.begin() as conn:
                    facts=dict(project_id=self.p,version_id=canvas['version_id'],node_key='output')
                    if producer=='run':
                        conn.execute(insert(S.creative_canvas_runs).values(**facts,id=str(uuid.uuid4()),artifact_id=job['run_id'],preview_sha256='1'*64))
                    elif producer=='preparation':
                        conn.execute(insert(S.creative_canvas_preparations).values(**facts,id=str(uuid.uuid4()),job_id=job['id'],
                            input_sha256='1'*64,prompt='isolated fixture',params={},gaps=[],created_by='test-human'))
                if producer=='working_input':
                    with self.engine.begin() as conn:
                        conn.execute(insert(S.canvas_generation_inputs).values(**facts,draft_version_id=job['draft_id'],shot_id=objects['shot']))
                later=self.write('create_creative_canvas',dict(episode_id=objects['episode'],document=dict(
                    nodes=[dict(id='later',type='image',job_id=job['id'])],edges=[])))
                original=self.service.get_task_origin(self.p,'generation',job['id'])['task']
                notice=next(row for row in self.service.get_task_notifications(self.p,limit=100)['items'] if row['origin_id']==job['id'])
                self.assertEqual(notice['href'],original['href'])
                params=parse_qs(urlparse(notice['href']).query)
                self.assertEqual(params['task_id'],[job['id']]);self.assertTrue(notice['is_current_event'])
                if producer=='later_use_only':
                    self.assertEqual(params['page'],['candidates']);self.assertEqual(params['scope'],[objects['shot']])
                    self.assertNotIn('focus_node_key',params)
                else:
                    self.assertEqual(params['page'],['creative-canvas']);self.assertEqual(params['task_target'],[canvas['id']])
                    self.assertEqual(params['focus_node_key'],['output']);self.assertEqual(params['episode'],[canvas_episode])
                    scoped=self.service.get_task_center(self.p,kind='generation',episode_id=canvas_episode)['items']
                    self.assertIn(job['id'],{row['id'] for row in scoped})
                    if canvas_episode!=objects['episode']:
                        shot_scoped=self.service.get_task_center(self.p,kind='generation',episode_id=objects['episode'])['items']
                        self.assertNotIn(job['id'],{row['id'] for row in shot_scoped})
                self.assertNotEqual(original['target_id'],later['id'])

    def test_canvas_turn_origin_and_history_keep_current_errors_separate(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        class UnknownPlanner:
            name='isolated-unknown-canvas'
            def available(self):return True
            def generate(self,*args):raise TimeoutError('synthetic unknown receipt')
        objects=self.hierarchy();canvas=self.write('create_creative_canvas',dict(episode_id=objects['episode'],
            document=dict(nodes=[dict(id='target',type='image')],edges=[])))
        turn=self.write('create_canvas_agent_turn',dict(canvas_id=canvas['id'],canvas_revision=1,message='固定隔离任务',
            skill_id='vsc-assets',target_node_id='target'))
        self.service.canvas_agent_backend=UnknownPlanner();self.addCleanup(delattr,self.service,'canvas_agent_backend')
        result=self.service.execute_canvas_agent_turn(self.p,turn['id']);self.rev=self.service.get_project(self.p)['revision']
        self.assertEqual(result['status'],'submission_unknown')
        first=self.service.get_task_notifications(self.p)['items'][0]
        self.assertEqual(first['error'],'canvas_agent_submission_unknown');self.assertTrue(first['is_current_event'])
        params=parse_qs(urlparse(first['href']).query)
        self.assertEqual(params['task_target'],[canvas['id']]);self.assertEqual(params['agent_turn'],[turn['id']])
        self.assertEqual(params['focus_node_key'],['target']);self.assertEqual(params['episode'],[objects['episode']])
        self.assertEqual(first['href'],self.service.get_task_origin(self.p,'canvas',turn['id'])['task']['href'])
        self.write('decide_canvas_agent_turn',dict(turn_id=turn['id'],outcome='stop',reason='隔离测试明确停止'))
        stopped=self.service.get_task_notifications(self.p)['items'][0]
        self.assertEqual(stopped['observed_status'],'stopped')
        # A changed current error is another source observation even if its
        # status is unchanged; no historical error snapshot is invented.
        with self.engine.begin() as conn:
            conn.execute(update(S.canvas_agent_turns).where(S.canvas_agent_turns.c.project_id==self.p,
                S.canvas_agent_turns.c.id==turn['id']).values(error='synthetic-current-error'))
        items=self.service.get_task_notifications(self.p)['items'];old=next(row for row in items if row['id']==first['id'])
        self.assertFalse(old['is_current_event']);self.assertIsNone(old['error'])
        self.assertEqual(old['observed_status'],'submission_unknown');self.assertEqual(old['current_status'],'stopped')
        self.assertEqual(old['current_error'],'synthetic-current-error')
        current=items[0];self.assertTrue(current['is_current_event']);self.assertEqual(current['error'],'synthetic-current-error')
        previous=next(row for row in items if row['id']==stopped['id'])
        self.assertFalse(previous['is_current_event']);self.assertIsNone(previous['error'])
        self.assertEqual(len(self.service.get_task_notifications(self.p)['items']),len(items))

    def test_generation_attempt_changes_discover_one_new_observation(self):
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        objects=self.hierarchy();job=self.generation_record(objects['shot'],status='submission_unknown')
        first=self.service.get_task_notifications(self.p)['items'][0]
        with self.engine.begin() as conn:
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p,
                S.generation_jobs.c.id==job['id']).values(attempt=2))
        revision=self.rev;value=self.service.get_task_notifications(self.p)
        self.assertEqual(len(value['items']),2);self.assertEqual(value['items'][0]['observed_status'],'submission_unknown')
        self.assertTrue(value['items'][0]['is_current_event'])
        self.assertFalse(next(row for row in value['items'] if row['id']==first['id'])['is_current_event'])
        self.assertEqual(self.service.get_task_notifications(self.p)['through_sequence'],value['through_sequence'])
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)

    def test_lyrics_notification_returns_to_original_tool_request(self):
        class Planner:
            name='isolated-notice-lyrics';calls=0
            def available(self):return True
            def generate(self,*args):self.calls+=1;return dict(title='隔离歌词',lyrics='合成文字建议',notes='无供应商调用')
        objects=self.hierarchy();planner=Planner();self.service.lyric_planner=planner;self.addCleanup(delattr,self.service,'lyric_planner')
        draft=self.write('save_creative_tool_draft',dict(base_draft_id=None,document=dict(tool='lyrics',
            episode_id=objects['episode'],prompt='隔离主题',lyrics='人工原稿')))
        request=self.write('create_creative_lyrics',dict(draft_version_id=draft['id'],new_attempt=False))
        self.rev=self.service.get_project(self.p)['revision']
        notice=self.service.get_task_notifications(self.p)['items'][0];params=parse_qs(urlparse(notice['href']).query)
        self.assertEqual(notice['origin_id'],request['id']);self.assertEqual(params['page'],['creative-tools'])
        self.assertEqual(params['tool'],['lyrics']);self.assertEqual(params['task_target'],[request['id']])
        self.assertEqual(params['episode'],[objects['episode']]);self.assertEqual(planner.calls,1)
        self.assertEqual(notice['href'],self.service.get_task_origin(self.p,'lyrics',request['id'])['task']['href'])

    def test_concurrent_discovery_keeps_one_event_and_later_observations_unread(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        self.imports(2);revision=self.rev;barrier=Barrier(2)
        def discover():
            with self.as_identity(self.owner):
                barrier.wait(timeout=10)
                return self.service.get_task_notifications(self.p)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(discover) for _ in range(2)];first,second=[future.result(timeout=20) for future in futures]
        self.assertEqual({row['id'] for row in first['items']},{row['id'] for row in second['items']})
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(S.task_notification_events).where(S.task_notification_events.c.project_id==self.p)),2)
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        self.imports(title='读取位置之后');self.service.get_task_notifications(self.p)
        self.service.read_task_notifications(self.p,{'through_sequence':first['through_sequence']})
        self.assertEqual(self.service.get_task_notifications(self.p,unread_only=True)['unread_count'],1)

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
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        self.imports(2);first=self.service.get_task_notifications(self.p,limit=1);event=first['items'][0]
        other_identity=self.service.ensure_local_access('notice-second-member')
        with self.engine.begin() as conn:
            conn.execute(insert(S.access_project_members).values(project_id=self.p,identity_id=other_identity['identity_id'],role='viewer',active=True))
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
        from sqlalchemy import event,update
        from vsc.adapters.persistence.postgres import schema as S
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
        with self.engine.begin() as conn:
            conn.execute(update(S.text_tool_batch_items).where(S.text_tool_batch_items.c.project_id==self.p,
                S.text_tool_batch_items.c.batch_id==batch['id'],S.text_tool_batch_items.c.status=='failed').values(error_code='changed-batch-error'))
        changed=self.service.get_task_notifications(self.p)['items']
        latest=next(row for row in changed if row['kind']=='text_batch')
        self.assertNotEqual(latest['id'],notice['id']);self.assertTrue(latest['is_current_event'])
        historical=next(row for row in changed if row['id']==notice['id'])
        self.assertFalse(historical['is_current_event']);self.assertNotIn('progress',historical);self.assertNotIn('outcome',historical)
        self.write('stop_text_batch',dict(batch_id=batch['id']))
        statements=[]
        def record(conn,cursor,statement,parameters,context,executemany):statements.append(statement.lower())
        event.listen(self.engine,'before_cursor_execute',record)
        try:page=self.service.get_task_notifications(self.p)
        finally:event.remove(self.engine,'before_cursor_execute',record)
        stopped=next(r for r in page['items'] if r['kind']=='text_batch')
        self.assertEqual(stopped['outcome'],'stopped');self.assertEqual(stopped['observed_status'],'stopped')
        old=next(row for row in page['items'] if row['id']==latest['id'])
        self.assertEqual(old['observed_status'],'running');self.assertEqual(old['current_status'],'stopped')
        self.assertNotIn('outcome',old);self.assertNotIn('progress',old)
        self.assertEqual(sum('group by text_tool_batch_items.batch_id, text_tool_batch_items.status' in sql for sql in statements),1)

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
            def generate(self,*args,materials=None):self.calls+=1;raise TimeoutError('isolated timeout')
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
