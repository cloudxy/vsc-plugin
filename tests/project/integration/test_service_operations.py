"""Real isolated PG, HTTP and ZIP; no external services or provider submissions."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import io,json,secrets,tempfile,threading,time,unittest,uuid,zipfile
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.access_control import Principal,set_principal,reset_principal
from vsc.assets.resource_service import ResourceError,Conflict

@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'isolated PostgreSQL required')
class ServiceOperationsTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        self.project=self.service.create_project({'name':'服务合同隔离测试','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[],'contract_policy':'production-v2'}},actor='test-human');self.p,self.rev=self.project['id'],0
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        from vsc.adapters.storage.local.store import LocalStorage
        self.service.storage=LocalStorage(self.temp.name)
        self.owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**self.owner));self.addCleanup(reset_principal,token)
        preview=self.service.access_migration_preview(self.p,self.owner['workspace_id'])
        self.command('assign-project',dict(project_id=self.p,workspace_id=self.owner['workspace_id'],preview_sha256=preview['sha256']))
        self.rev=self.service.get_project(self.p)['revision']

    def command(self,action,payload):
        return self.service.access_command(action,payload,expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')

    @contextmanager
    def as_identity(self,binding):
        token=set_principal(binding if isinstance(binding,Principal) else Principal(**binding))
        try:yield
        finally:reset_principal(token)

    def invite(self,role='viewer'):
        secret=secrets.token_urlsafe(32);credential=secrets.token_urlsafe(32)
        self.command('invitation',dict(scope='project',scope_id=self.p,role=role,secret=secret,expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        return self.service.accept_access_invitation(dict(invitation_secret=secret,credential_secret=credential,display_name='隔离成员'))

    def key(self,caps=None):
        secret=secrets.token_urlsafe(32)
        row=self.write('issue_service_api_key',dict(name='隔离API',secret=secret,capabilities=caps or ['read'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        return row,secret

    def test_api_peer_allowlist_ignores_forwarding_headers_and_rate_limit_is_atomic(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from concurrent.futures import ThreadPoolExecutor
        secret=secrets.token_urlsafe(32)
        self.write('issue_service_api_key',dict(name='限流隔离API',secret=secret,capabilities=['read'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),ip_allowlist=['127.0.0.1'],requests_per_minute=1))
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
        url='/api/v1/service-api/projects/'+self.p+'/jobs'
        with TestClient(app,client=('192.0.2.42',50000)) as client:
            denied=client.get(url,headers={'Authorization':'Bearer '+secret,'X-Forwarded-For':'127.0.0.1'})
            self.assertEqual(denied.status_code,403)
        principal=self.service.authenticate_service_api_key(secret)
        def attempt():
            with self.as_identity(principal):
                try:self.service.service_api_operation(self.p,'jobs',client_ip='127.0.0.1');return 200
                except ResourceError as exc:return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _:attempt(),range(2))),[200,429])
        calls=self.snapshot()['api_calls']
        self.assertEqual(sorted(r['status_code'] for r in calls if r['phase']=='finished'),[200,403,429])
        self.assertEqual(self.snapshot()['api_keys'][0]['ip_allowlist'],['127.0.0.1/32'])

    def test_self_deactivation_previews_ownership_and_revokes_original_credentials(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        owner_request=self.request('account_close')
        preview=self.service.preview_account_close(self.p,{'request_id':owner_request['id']})
        self.assertFalse(preview['ready'])
        self.assertIn('workspace_owner_required',{x['code'] for x in preview['plan']['blockers']})
        member=self.invite('viewer');secret=secrets.token_urlsafe(32);login_secret=secrets.token_urlsafe(32)
        with self.as_identity(member):
            self.service.access_command('credential',{'secret':login_secret},expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key='closing-login',actor=member['actor'])
            args=dict(actor=member['actor'],expected_revision=self.rev,idempotency_key='member-request')
            request=self.service.create_service_request(self.p,dict(kind='account_close',title='停用本人',body='隔离身份测试',contact='',channel='',artifact_id=None,media_id=None,requested_fields=[]),**args);self.rev=request['revision']
            key=self.service.issue_service_api_key(self.p,dict(name='本人key',secret=secret,capabilities=['read'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),actor=member['actor'],expected_revision=self.rev,idempotency_key='closing-key');self.rev=key['revision']
            preview=self.service.preview_account_close(self.p,{'request_id':request['id']});self.assertTrue(preview['ready'])
        with self.assertRaises(ResourceError):self.service.preview_account_close(self.p,{'request_id':request['id']})
        self.command('member',dict(scope='project',scope_id=self.p,identity_id=member['identity_id'],role='viewer',active=True))
        with self.as_identity(member):
            payload=dict(request_id=request['id'],preview_sha256=preview['sha256'],confirm_actor=member['actor'])
            with self.assertRaises(Conflict):self.service.close_service_account(self.p,payload,actor=member['actor'],expected_revision=self.rev,idempotency_key='closing')
            payload['preview_sha256']=self.service.preview_account_close(self.p,{'request_id':request['id']})['sha256']
            from fastapi.testclient import TestClient
            from vsc.interfaces.web.app import create_app
            app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
            with TestClient(app) as client:
                logged=client.post('/api/v1/access/login',json={'secret':login_secret},headers={'Origin':'http://testserver'})
                self.assertEqual(logged.status_code,200)
                session=client.get('/api/v1/session').json()
                response=client.post('/api/v1/projects/'+self.p+'/service-operations/account-close/execute',json=dict(payload=payload,expected_revision=self.rev,idempotency_key='closing'),headers={'Origin':'http://testserver','X-CSRF-Token':session['csrf_token']})
                self.assertEqual(response.status_code,200,response.text);result=response.json();self.rev=result['revision']
            self.assertEqual(result['status'],'account_closed')
            with self.assertRaises(ResourceError):self.service.authorize_access(self.p)
        with self.assertRaises(ResourceError):self.service.authenticate_service_api_key(secret)
        with self.engine.connect() as conn:
            self.assertFalse(conn.execute(select(S.access_identities.c.active).where(S.access_identities.c.id==member['identity_id'])).scalar_one())
            self.assertEqual(conn.execute(select(S.service_request_events.c.status).where(S.service_request_events.c.request_id==request['id']).order_by(S.service_request_events.c.sequence.desc()).limit(1)).scalar_one(),'account_closed')
            self.assertIsNotNone(conn.execute(select(S.projects.c.id).where(S.projects.c.id==self.p)).first())

    def request(self,kind='feedback',**changes):
        data=dict(kind=kind,title='隔离申请',body='仅用于本机工程验收',contact='',channel='',artifact_id=None,media_id=None,requested_fields=['profile','requests','orders'] if kind=='personal_export' else [])
        data.update(changes);return self.write('create_service_request',data)

    def snapshot(self):return self.service.service_operations_snapshot(self.p)

    def test_feedback_personal_scope_and_explicit_management_http(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        own=self.request(feedback_category='bug',title='本人的反馈')
        member=self.invite('viewer');credential=secrets.token_urlsafe(32)
        with self.as_identity(member):
            self.service.access_command('credential',{'secret':credential},expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor=member['actor'])
            payload=dict(kind='feedback',feedback_category='ux',title='成员的反馈',body='合成反馈正文',contact='synthetic@example.invalid',channel='/audit',artifact_id=None,media_id=None,requested_fields=[])
            other=self.service.create_service_request(self.p,payload,expected_revision=self.rev,idempotency_key=uuid.uuid4().hex,actor=member['actor']);self.rev=other['revision']
        # Project ownership does not widen the personal list.
        mine=self.service.service_feedback(self.p)
        self.assertEqual([r['id'] for r in mine['items']],[own['id']]);self.assertTrue(mine['manage'])
        managed=self.service.service_feedback(self.p,scope='manage')
        self.assertEqual(managed['total'],2);self.assertEqual(sum(r['mine'] for r in managed['items']),1)
        self.assertEqual(next(r for r in managed['items'] if r['id']==other['id'])['feedback_category'],'ux')
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/v1/access/login',json={'secret':credential},headers={'Origin':'http://testserver'}).status_code,200)
            headers={'Origin':'http://testserver','X-CSRF-Token':client.get('/api/v1/session').json()['csrf_token']}
            base='/api/v1/projects/'+self.p+'/service-operations'
            response=client.get(base+'/feedback',headers=headers);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual([r['id'] for r in response.json()['items']],[other['id']])
            self.assertEqual(client.get(base+'/feedback?scope=manage',headers=headers).status_code,403)
            self.assertEqual(client.get(base+'/feedback?requester_id='+self.owner['identity_id'],headers=headers).json()['items'][0]['id'],other['id'])
            for query in ('limit=0','offset=-1','status=contacted','scope=all','category=invalid'):
                self.assertEqual(client.get(base+'/feedback?'+query,headers=headers).status_code,422,query)
            forged=client.post(base+'/requests',headers=headers,json=dict(payload=dict(payload,requester_id=self.owner['identity_id']),expected_revision=self.rev,idempotency_key=uuid.uuid4().hex))
            self.assertEqual(forged.status_code,422)
        with self.as_identity(member):
            with self.assertRaises(ResourceError):self.service.service_feedback(self.p,scope='manage')
        for category in ('unknown',[],True):
            with self.subTest(category=category),self.assertRaises(ResourceError):self.request(feedback_category=category)
        with self.assertRaises(ResourceError):self.request('support',feedback_category='bug')

    def test_feedback_pagination_after_user_kind_search_and_latest_status_filters(self):
        first=self.request(title='literal %_ feedback',feedback_category='bug')
        for n in range(104):self.request(title='反馈 %03d'%n,feedback_category='feature')
        for n in range(101):self.request('support',title='较新支持 %03d'%n)
        pages=[self.service.service_feedback(self.p,offset=offset,limit=24) for offset in range(0,105,24)]
        ids=[r['id'] for page in pages for r in page['items']]
        self.assertEqual(len(ids),105);self.assertEqual(len(set(ids)),105);self.assertIn(first['id'],ids)
        self.assertTrue(all(page['total']==105 for page in pages));self.assertIsNone(pages[-1]['next_offset'])
        self.assertEqual(self.service.service_feedback(self.p,query='%_')['total'],1)
        self.assertEqual(self.service.service_feedback(self.p,category='bug')['total'],1)
        self.assertEqual(self.service.service_feedback(self.p,category='uncategorized')['total'],0)
        row=self.service.service_feedback(self.p,query='literal')['items'][0]
        self.write('process_service_request',dict(request_id=first['id'],base_event_id=row['events'][-1]['id'],status='local_approved',reason='已审核；没有伪造联系行为'))
        reviewed=self.service.service_feedback(self.p,status='reviewed')
        self.assertEqual([r['id'] for r in reviewed['items']],[first['id']])
        self.write('process_service_request',dict(request_id=first['id'],base_event_id=reviewed['items'][0]['events'][-1]['id'],status='under_review',reason='继续处理'))
        self.assertEqual(self.service.service_feedback(self.p,status='reviewed')['total'],0)
        self.assertEqual(self.service.service_feedback(self.p,status='processing')['total'],1)

    def test_drama_personal_management_http_and_owner_only_withdraw(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        own=self.request('production_service',title='本人的承制需求')
        member=self.invite('viewer');credential=secrets.token_urlsafe(32)
        with self.as_identity(member):
            self.service.access_command('credential',{'secret':credential},expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor=member['actor'])
            other=self.write('create_service_request',dict(kind='studio',title='成员团队合作',body='代表作品与合作需求',contact='',channel='',artifact_id=None,media_id=None,requested_fields=[]),actor=member['actor'])
        mine=self.service.service_drama_requests(self.p)
        self.assertEqual([r['id'] for r in mine['items']],[own['id']])
        self.assertEqual(mine['items'][0]['status'],'awaiting_configuration')
        managed=self.service.service_drama_requests(self.p,scope='manage')
        self.assertEqual(managed['total'],2);self.assertEqual(sum(r['mine'] for r in managed['items']),1)
        other_row=next(r for r in managed['items'] if r['id']==other['id'])
        with self.assertRaises(ResourceError):self.write('withdraw_service_request',dict(request_id=other['id'],base_event_id=other_row['events'][-1]['id'],reason='禁止代他人撤回'))
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/v1/access/login',json={'secret':credential},headers={'Origin':'http://testserver'}).status_code,200)
            headers={'X-CSRF-Token':client.get('/api/v1/session').json()['csrf_token']}
            url='/api/v1/projects/'+self.p+'/service-operations/drama-requests'
            response=client.get(url,headers=headers);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual([r['id'] for r in response.json()['items']],[other['id']])
            self.assertEqual(client.get(url+'?scope=manage',headers=headers).status_code,403)
            for query in ('limit=0','limit=101','offset=-1','status=completed','scope=all'):
                self.assertEqual(client.get(url+'?'+query,headers=headers).status_code,422,query)
            self.assertEqual(client.get(url+'?requester_id='+self.owner['identity_id'],headers=headers).json()['items'][0]['id'],other['id'])
        with self.as_identity(member):
            with self.assertRaises(ResourceError):self.service.service_drama_requests(self.p,scope='manage')

    def test_drama_pagination_filters_before_limit_and_preserves_events(self):
        first=self.request('studio',title='literal %_ team')
        for n in range(13):self.request('production_service',title='承制 %03d'%n)
        for n in range(101):self.request('feedback',title='较新意见 %03d'%n)
        pages=[self.service.service_drama_requests(self.p,offset=offset,limit=12) for offset in (0,12)]
        ids=[r['id'] for page in pages for r in page['items']]
        self.assertEqual(len(ids),14);self.assertEqual(len(set(ids)),14);self.assertIn(first['id'],ids)
        self.assertTrue(all(page['total']==14 for page in pages));self.assertIsNone(pages[-1]['next_offset'])
        self.assertEqual(self.service.service_drama_requests(self.p,query='%_')['total'],1)
        row=self.service.service_drama_requests(self.p,query='literal')['items'][0]
        event=row['events'][-1]['id']
        payload=dict(request_id=row['id'],base_event_id=event,status='local_approved',reason='内部审核；尚未开始外部承制')
        self.write('process_service_request',payload)
        with self.assertRaises(Conflict):self.write('process_service_request',payload)
        reviewed=self.service.service_drama_requests(self.p,status='reviewed')
        self.assertEqual([r['id'] for r in reviewed['items']],[row['id']]);self.assertEqual(len(reviewed['items'][0]['events']),2)
        self.assertEqual(self.service.service_drama_requests(self.p,status='pending')['total'],13)
        self.write('withdraw_service_request',dict(request_id=row['id'],base_event_id=reviewed['items'][0]['events'][-1]['id'],reason='本人取消'))
        self.assertEqual(self.service.service_drama_requests(self.p,status='closed')['total'],1)
        self.assertEqual(self.service.service_drama_requests(self.p,status='reviewed')['total'],0)
        other=self.service.create_project({'name':'其他项目','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[]}},actor='test-human')
        self.assertEqual(self.service.service_drama_requests(other['id'])['total'],0)

    def test_feedback_migration_preserves_legacy_receipts_and_classifications(self):
        from alembic import command
        from alembic.config import Config
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from sqlalchemy import select,text
        from sqlalchemy.exc import DBAPIError
        from support.fixtures.postgres import isolated_postgres
        from support.paths import ROOT
        from vsc.adapters.persistence.postgres.resource_store import PostgresResourceStore
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.resource_service import ResourceService
        with isolated_postgres(TEST_URL) as engine:
            service=ResourceService(PostgresResourceStore(engine=engine))
            with self.as_identity(Principal()):
                # Use an explicit trusted local identity in the separate schema.
                person=service.ensure_local_access('migration-feedback-owner')
            with self.as_identity(person):
                p=service.create_project({'name':'历史反馈迁移'},actor=person['actor'])['id']
                payload=dict(kind='feedback',title='旧客户端记录',body='原始正文',contact='',channel='/legacy',artifact_id=None,media_id=None,requested_fields=[])
                args=dict(actor=person['actor'],expected_revision=0,idempotency_key='legacy-feedback-command')
                legacy=service.create_service_request(p,payload,**args)
                cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
                with engine.begin() as conn:
                    cfg.attributes['connection']=conn;command.downgrade(cfg,'0056_library_media_lifecycle')
                    before=conn.execute(text('SELECT to_jsonb(r) FROM service_requests r')).scalar_one()
                    command.upgrade(cfg,'head')
                    after=conn.execute(text("SELECT to_jsonb(r)-'feedback_category' FROM service_requests r")).scalar_one()
                    self.assertEqual(before,after)
                    self.assertEqual(compare_metadata(MigrationContext.configure(conn),S.metadata),[])
                self.assertEqual(service.create_service_request(p,payload,**args),legacy)
                self.assertIsNone(service.service_feedback(p)['items'][0]['feedback_category'])
                categorized=service.create_service_request(p,dict(payload,feedback_category='bug'),actor=person['actor'],expected_revision=legacy['revision'],idempotency_key='new-feedback-command')
                with self.assertRaises(DBAPIError):
                    with engine.begin() as conn:
                        cfg.attributes['connection']=conn;command.downgrade(cfg,'0056_library_media_lifecycle')
                with engine.connect() as conn:
                    self.assertEqual(conn.execute(select(S.service_requests.c.feedback_category).where(S.service_requests.c.id==categorized['id'])).scalar_one(),'bug')
                    self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),S.SCHEMA_REVISION)

    def fixed_run(self):
        from vsc.adapters.persistence.postgres.budget_store import native_units,operation_key
        self.write('configure_budget',dict(limits={'remote_jobs':2,'images':2},reason='API原预算隔离验证'))
        asset=self.write('create_object',dict(kind='asset',asset_kind='character',display_code=uuid.uuid4().hex))['id']
        bible=self.artifact('bible-'+asset,'asset-bible',[asset],{'asset_specs':[dict(id=str(uuid.uuid4()),asset_id=asset,variant_key='master')]})
        context=self.service.compile_asset_context(self.p,asset,'identity_ref')
        provider='ops_'+uuid.uuid4().hex;self.service.register_provider(dict(id=provider,base_url='https://example.invalid',auth_ref='OFFLINE_ONLY'),actor='test-human')
        model=self.service.register_model(dict(provider_id=provider,model_key='image',model_version='1',modality='image',capabilities={'purposes':['identity_ref']}),actor='test-human')['id']
        now=datetime.now(timezone.utc);request=dict(shot_id=None,asset_id=asset,purpose='identity_ref',modality='image',prompt='fixed synthetic request')
        document=dict(approved_inputs=[{'id':a['id'],'sha256':a['sha256']} for a in context['artifacts']],jobs=[dict(task_key='one',candidate_no=0,model_id=model,request=request)],operations={operation_key(request,0):native_units(request)},execution_policy=dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=20)).isoformat(),max_attempts_per_purpose=1,max_repair_rounds=0))
        run=self.write('create_artifact',dict(artifact_key='run-'+asset,artifact_type='production-run',document=document,dependency_ids=[bible],object_ids=[asset]))
        self.write('decide_artifact',dict(artifact_id=run['id'],reason='批准隔离固定运行，无实际供应商调用'))
        return run

    def test_api_fixed_scope_hash_only_revocation_and_no_ui_login(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        key,secret=self.key();principal=self.service.authenticate_service_api_key(secret)
        self.assertFalse(principal.local);self.assertFalse(principal.local_read)
        with self.engine.connect() as conn:
            values=[dict(r) for r in conn.execute(select(S.command_receipts).where(S.command_receipts.c.project_id==self.p)).mappings()]
            self.assertNotIn(secret,json.dumps(values,default=str))
            self.assertNotIn(secret,json.dumps(self.snapshot()))
        other=self.service.create_project({'name':'其他隔离项目'},actor='test-human')['id']
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
        with TestClient(app) as client:
            headers={'Authorization':'Bearer '+secret};url='/api/v1/service-api/projects/'+self.p
            self.assertEqual(client.get(url+'/jobs',headers=headers).status_code,200)
            capabilities=client.get(url+'/capabilities',headers=headers)
            self.assertEqual(capabilities.status_code,200,capabilities.text)
            self.assertEqual({row['operation'] for row in capabilities.json()['operations']},{'jobs','job','usage','preview','execute','cancel'})
            self.assertEqual(client.get('/api/v1/service-api/projects/'+other+'/jobs',headers=headers).status_code,403)
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree',headers=headers).status_code,403)
            self.assertEqual(client.post('/api/v1/access/login',json={'secret':secret},headers={'Origin':'http://testserver'}).status_code,403)
            self.write('revoke_service_api_key',{'key_id':key['id']})
            self.assertEqual(client.get(url+'/jobs',headers=headers).status_code,403)
        with self.assertRaises(ResourceError):self.service.authenticate_service_api_key(secret)

    def test_member_removal_and_readonly_key_cannot_execute(self):
        member=self.invite('editor')
        with self.as_identity(member):
            secret=secrets.token_urlsafe(32);row=self.service.issue_service_api_key(self.p,dict(name='成员read',secret=secret,capabilities=['read'],expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),actor=member['actor'],expected_revision=self.rev,idempotency_key='member-key')
            self.rev=row['revision']
        keyprincipal=self.service.authenticate_service_api_key(secret)
        with self.as_identity(keyprincipal):
            with self.assertRaises(ResourceError):self.service.service_api_operation(self.p,'execute',{})
        self.command('member',dict(scope='project',scope_id=self.p,identity_id=member['identity_id'],role='editor',active=False))
        with self.assertRaises(ResourceError):self.service.authenticate_service_api_key(secret)

    def test_api_approved_run_creates_original_job_once_and_cancel_is_local(self):
        run=self.fixed_run();key,secret=self.key(['read','execute']);principal=self.service.authenticate_service_api_key(secret)
        with self.as_identity(principal):
            payload=dict(run_version_id=run['id'],run_sha256=run['sha256'])
            result=self.service.service_api_operation(self.p,'execute',payload)
            self.assertEqual(result['created_count'],1,result);job_id=result['tasks'][0]['job_id']
            replay=self.service.service_api_operation(self.p,'execute',payload);self.assertEqual(replay['tasks'][0]['job_id'],job_id)
            rows=self.service.service_api_operation(self.p,'jobs');self.assertEqual(rows['total'],1)
            self.assertEqual(self.service.service_api_operation(self.p,'jobs',{'offset':1,'limit':1})['items'],[])
            self.assertEqual(self.service.service_api_operation(self.p,'job',{'job_id':job_id})['status'],'created')
            revision=self.service.get_project(self.p)['revision']
            cancelled=self.service.service_api_operation(self.p,'cancel',dict(job_id=job_id,expected_revision=revision,idempotency_key='cancel-created'))
            self.assertEqual(self.service.get_generation_job(self.p,job_id)['status'],'cancelled')
        self.rev=self.service.get_project(self.p)['revision'];second=self.fixed_run()
        with self.as_identity(principal):
            result=self.service.service_api_operation(self.p,'execute',dict(run_version_id=second['id'],run_sha256=second['sha256']))
            submitted_id=result['tasks'][0]['job_id']
        self.rev=self.service.get_project(self.p)['revision'];self.write('update_generation_job',dict(job_id=submitted_id,status='submission_unknown'))
        with self.as_identity(principal):
            self.assertEqual(self.service.service_api_operation(self.p,'usage')['used'],{'remote_jobs':1,'images':1})
            with self.assertRaises(Conflict):self.service.service_api_operation(self.p,'cancel',dict(job_id=submitted_id,expected_revision=self.rev,idempotency_key='cannot-cancel-remote'))
        self.assertTrue(any(c['phase']=='finished' for c in self.snapshot()['api_calls']))

    def test_requests_local_states_no_external_success_and_stale_review(self):
        row=self.request('fcp');self.assertEqual(row['status'],'awaiting_configuration')
        event=self.snapshot()['requests'][0]['events'][-1]
        payload=dict(request_id=row['id'],base_event_id=event['id'],status='local_approved',reason='本地审核，合作服务仍未配置')
        self.write('process_service_request',payload)
        with self.assertRaises(Conflict):self.write('process_service_request',dict(payload,status='rejected'))
        with self.assertRaises(ResourceError):self.write('process_service_request',dict(payload,status='published'))
        self.assertEqual(self.snapshot()['external_services']['fcp'],'unconfigured')
        close=self.request('account_close');self.assertEqual(close['status'],'received')
        with self.engine.connect() as conn:self.assertTrue(self.store._access_identity(conn,self.owner['identity_id'])['active'])

    def test_actual_personal_zip_snapshot_owner_and_tamper_checks(self):
        self.request(body='本人私有反馈');key,secret=self.key();request=self.request('personal_export')
        export=self.write('build_service_export',{'request_id':request['id']})
        raw,sha=self.service.service_export_content(self.p,export['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()),{'personal-data.json','README.txt'})
            document=json.loads(archive.read('personal-data.json'))
        self.assertEqual(document['identity_id'],self.owner['identity_id']);self.assertNotIn(secret,raw.decode('latin1'))
        self.assertNotIn('secret_sha256',json.dumps(document));self.assertNotIn('preferences',document['profile'])
        second=self.write('build_service_export',{'request_id':request['id']});self.assertEqual(export['id'],second['id'])
        member=self.invite('viewer')
        with self.as_identity(member):
            with self.assertRaises(ResourceError):self.service.service_export_content(self.p,export['id'])
        saved=self.service._operations().export_file(self.p,export['id']);self.service.storage.resolve(saved['object_key']).write_bytes(b'tampered')
        with self.assertRaises(ResourceError):self.service.service_export_content(self.p,export['id'])

    def test_missing_storage_keeps_export_request_and_withdraw_is_final(self):
        request=self.request('personal_export');storage=self.service.storage;self.service.storage=None
        try:
            with self.assertRaises(ResourceError):self.write('build_service_export',{'request_id':request['id']})
        finally:self.service.storage=storage
        saved=self.snapshot()['requests'][0];self.assertEqual(saved['status'],'received')
        self.write('withdraw_service_request',dict(request_id=request['id'],base_event_id=saved['events'][-1]['id'],reason='撤回隔离申请'))
        with self.assertRaises(Conflict):self.write('build_service_export',{'request_id':request['id']})

    def test_configuration_announcements_and_distribution_fixed_approval(self):
        config=self.write('configure_service_operations',dict(base_version_id=None,document=dict(support_text='本机支持',terms_url='',privacy_url='',api_documentation='固定范围API')))
        with self.assertRaises(Conflict):self.write('configure_service_operations',dict(base_version_id=None,document=dict(support_text='stale',terms_url='',privacy_url='',api_documentation='')))
        published=self.write('publish_service_announcement',dict(announcement_key='one',base_version_id=None,title='本地公告',body='测试维护窗口',status='published'))
        self.write('publish_service_announcement',dict(announcement_key='one',base_version_id=published['id'],title='本地公告',body='窗口已撤回',status='withdrawn'))
        with self.assertRaises(ResourceError):self.request('distribution')
        artifact=self.artifact('approved-export','render-spec')
        result=self.request('distribution',artifact_id=artifact,channel='待配置平台')
        self.assertEqual(result['status'],'awaiting_configuration')

    def test_key_scope_immutable_and_export_ready_requires_file(self):
        from sqlalchemy import update,insert
        from sqlalchemy.exc import DBAPIError
        from vsc.adapters.persistence.postgres import schema as S
        key,secret=self.key();request=self.request('personal_export')
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:conn.execute(update(S.service_api_keys).where(S.service_api_keys.c.id==key['id']).values(capabilities=['read','execute']))
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as conn:conn.execute(insert(S.service_request_events).values(project_id=self.p,id=str(uuid.uuid4()),request_id=request['id'],sequence=2,status='export_ready',reason='invalid synthetic',created_by=self.owner['identity_id']))

    def test_key_revocation_serializes_with_original_write(self):
        key,secret=self.key(['read','execute']);principal=self.service.authenticate_service_api_key(secret);entered=threading.Event();release=threading.Event();revoked=threading.Event();errors=[]
        def held():
            try:
                with self.as_identity(principal):self.store._mutate(self.p,'create_generation_job',{},expected_revision=self.rev,idempotency_key='held-api-write',actor=principal.actor,callback=lambda c,p:(entered.set(),release.wait(5),{'done':True})[-1])
            except Exception as exc:errors.append(exc)
        def revoke():
            try:
                with self.as_identity(self.owner):
                    from vsc.adapters.persistence.postgres.values import CURRENT_REVISION
                    self.service._operations().revoke_key(self.p,{'key_id':key['id']},expected_revision=CURRENT_REVISION,idempotency_key='concurrent-revoke',actor='test-human');revoked.set()
            except Exception as exc:errors.append(exc)
        a=threading.Thread(target=held);b=threading.Thread(target=revoke);a.start();self.assertTrue(entered.wait(5));b.start();self.assertFalse(revoked.wait(.15));release.set();a.join(5);b.join(5)
        self.assertFalse(errors,errors);self.assertTrue(revoked.is_set())
        with self.as_identity(principal):
            with self.assertRaises(ResourceError):self.store._mutate(self.p,'create_generation_job',{},expected_revision=0,idempotency_key='held-api-write',actor=principal.actor,callback=lambda c,p:{})

    def test_seedance_readonly_verify_tos_signature_network_ping_and_engine_overview(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        run=self.fixed_run();_,secret=self.key(['read','execute']);principal=self.service.authenticate_service_api_key(secret)
        with self.as_identity(principal):
            created=self.service.service_api_operation(self.p,'execute',dict(run_version_id=run['id'],run_sha256=run['sha256']))
            job_id=created['tasks'][0]['job_id']
        self.rev=self.service.get_project(self.p)['revision']
        self.write('update_generation_job',dict(job_id=job_id,status='submitted',external_task_id='a1b2c3d4e5f60718'))
        snap=self.snapshot()
        self.assertIn('engine_overview',snap)
        self.assertGreaterEqual(len(snap['engine_overview']['recent_jobs']),1)
        rev_before=self.service.get_project(self.p)['revision']
        jobs_before=self.service.list_generation_jobs(self.p)['total']
        login_secret=secrets.token_urlsafe(32)
        self.command('credential',{'secret':login_secret})
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver']),service=self.service)
        with TestClient(app) as client:
            logged=client.post('/api/v1/access/login',json={'secret':login_secret},headers={'Origin':'http://testserver'})
            self.assertEqual(logged.status_code,200,logged.text)
            csrf=client.get('/api/v1/session').json()['csrf_token']
            headers={'Origin':'http://testserver','X-CSRF-Token':csrf}
            verified=client.post(f'/api/v1/projects/{self.p}/service-operations/seedance-verify',
                json={'payload':{'task_id':'A1B2C3D4E5F60718','tos_url':'https://tos.example.invalid/v.mp4?X-Tos-Date=20261111T120000Z&X-Tos-Expires=3600&X-Tos-Signature=deadbeef'}},headers=headers)
            self.assertEqual(verified.status_code,200,verified.text)
            body=verified.json()
            self.assertTrue(body['verified']);self.assertTrue(body['read_only']);self.assertEqual(body['credits_consumed'],0)
            self.assertEqual(body['job']['id'],job_id)
            self.assertTrue(body['tos_signature']['signed'])
            ping=client.get(f'/api/v1/projects/{self.p}/service-operations/network-diagnostic/ping?probe=database',headers={'X-CSRF-Token':csrf})
            self.assertEqual(ping.status_code,200,ping.text)
            self.assertTrue(ping.json()['ok'])
            self.assertIn('no-store',ping.headers.get('cache-control',''))
        self.assertEqual(self.service.get_project(self.p)['revision'],rev_before)
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],jobs_before)

if __name__=='__main__':unittest.main()
