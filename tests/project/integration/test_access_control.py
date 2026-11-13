"""Real PostgreSQL identities, HTTP scope, revocation locks and original review decisions."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json,secrets,tempfile,threading,time,unittest,uuid
from pathlib import Path
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.access_control import Principal,set_principal,reset_principal
from vsc.assets.resource_service import ResourceError,Conflict

@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class AccessControlTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.temp=tempfile.TemporaryDirectory(prefix='vsc-access-test-');self.addCleanup(self.temp.cleanup)
        self.owner=self.service.ensure_local_access('test-human');self.token=set_principal(Principal(**self.owner));self.addCleanup(reset_principal,self.token)
        self.secret=secrets.token_urlsafe(32)

    def command(self,action,payload,key=None):
        revision=self.service.access_snapshot()['access_revision']
        from vsc.assets.access_control import current_principal
        return self.service.access_command(action,payload,expected_revision=revision,idempotency_key=key or uuid.uuid4().hex,actor=current_principal().actor)

    def assign(self,p=None,workspace=None):
        p=p or self.p;workspace=workspace or self.owner['workspace_id'];preview=self.service.access_migration_preview(p,workspace)
        return self.command('assign-project',{'project_id':p,'workspace_id':workspace,'preview_sha256':preview['sha256']})

    def invite(self,role='editor',scope='project',target=None):
        secret=secrets.token_urlsafe(32);credential=secrets.token_urlsafe(32)
        row=self.command('invitation',{'scope':scope,'scope_id':target or self.p,'role':role,'secret':secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        binding=self.service.accept_access_invitation({'invitation_secret':secret,'credential_secret':credential,'display_name':'工程成员'})
        return binding,credential,row

    @contextmanager
    def as_member(self,binding):
        token=set_principal(Principal(**binding))
        try:yield
        finally:reset_principal(token)

    def app(self,**config):
        from vsc.interfaces.web.app import create_app
        return create_app({'projects_root':self.temp.name,'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'local-secret','human_identity':'test-human','background_enabled':False,**config},service=self.service)

    def client_login(self,client,credential=None):
        endpoint='/api/v1/access/login' if credential else '/api/v1/session'
        response=client.post(endpoint,json={'secret':credential} if credential else {'token':'local-secret'},headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code,200,response.text)
        return {'Origin':'http://testserver','X-CSRF-Token':response.json()['csrf_token']}

    def canvas(self,text='固定画布'):
        return self.write('create_creative_canvas',{'title':'共享工程画布','document':{'nodes':[{'id':'text1','type':'text','text':text,'x':0,'y':0}], 'edges':[]}})

    def share(self,canvas,mode='view'):
        secret=secrets.token_urlsafe(32)
        row=self.command('share',{'project_id':self.p,'canvas_version_id':canvas['version_id'],'mode':mode,'secret':secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        return row,secret

    def test_two_identities_project_reads_writes_and_old_session_revocation(self):
        from fastapi.testclient import TestClient
        self.assign();member,credential,_=self.invite('viewer')
        with self.as_member(member):
            own=self.service.create_project({'name':'成员独立项目'},actor=member['actor'])
        with self.assertRaises(ResourceError):self.service.authorize_access(own['id'])
        with TestClient(self.app()) as client:
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,403)
            headers=self.client_login(client,credential)
            rows=client.get('/api/v1/projects').json()['items'];self.assertEqual({r['id'] for r in rows},{self.p,own['id']})
            self.assertTrue(next(r for r in rows if r['id']==self.p)['read_only'])
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,200)
            response=client.post('/api/v1/projects/'+self.p+'/objects',headers=headers,json={'payload':{'kind':'work','display_code':'W'},'expected_revision':self.rev,'idempotency_key':'viewer-write'})
            self.assertEqual(response.status_code,403,response.text)
            self.command('member',{'scope':'project','scope_id':self.p,'identity_id':member['identity_id'],'role':'viewer','active':False})
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,403)
            self.assertEqual(client.get('/api/v1/projects/'+own['id']+'/tree').status_code,200)
            self.assertEqual(client.post('/api/v1/projects/'+self.p+'/objects',headers=headers,json={'payload':{},'expected_revision':self.rev,'idempotency_key':'again'}).status_code,403)

    def test_invitation_one_use_credential_revocation_and_no_actor_impersonation(self):
        from fastapi.testclient import TestClient
        self.assign();member,credential,invite=self.invite('editor')
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.service.create_object(self.p,{'kind':'work','display_code':'X'},actor='test-human',expected_revision=self.rev,idempotency_key='spoof')
            credential_id=self.service.access_snapshot()['credentials'][0]['id']
            self.command('revoke-credential',{'credential_id':credential_id})
        with self.assertRaises(ResourceError):self.service.authenticate_access(credential)
        with TestClient(self.app()) as client:
            response=client.post('/api/v1/access/login',json={'secret':credential,'actor':'test-human'},headers={'Origin':'http://testserver'})
            self.assertEqual(response.status_code,422)
        with self.assertRaises(Conflict):self.command('member',{'scope':'workspace','scope_id':self.owner['workspace_id'],'identity_id':self.owner['identity_id'],'role':'viewer','active':False})

    def test_explicit_migration_workspace_hierarchy_and_fixed_preview(self):
        studio=self.command('workspace',{'name':'工程工作室','parent_id':None})['workspace_id']
        child=self.command('workspace',{'name':'工程子工作室','parent_id':studio})['workspace_id']
        self.assertEqual(self.service.access_scope(self.p)['workspace_id'],self.owner['workspace_id'])
        preview=self.service.access_migration_preview(self.p,child)
        self.write('create_object',{'kind':'work','display_code':'NEW'})
        with self.assertRaises(Conflict):self.command('assign-project',{'project_id':self.p,'workspace_id':child,'preview_sha256':preview['sha256']})
        self.assign(workspace=child)
        member,_,_=self.invite('editor',scope='workspace',target=studio)
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.service.authorize_access(self.p)
        self.command('member',{'scope':'workspace','scope_id':studio,'identity_id':member['identity_id'],'role':'owner','active':True})
        with self.as_member(member):self.assertIn('manage',self.service.access_scope(self.p)['capabilities'])

    def test_fixed_share_revocation_and_guest_library_and_run_denial(self):
        from fastapi.testclient import TestClient
        self.assign();canvas=self.canvas();shared,secret=self.share(canvas)
        with TestClient(self.app()) as client:
            headers=self.client_login(client,secret)
            read=client.get('/api/v1/access/share-view');self.assertEqual(read.status_code,200,read.text);self.assertEqual(read.json()['document']['nodes'][0]['text'],'固定画布')
            self.assertNotIn('job_id',read.json()['document']['nodes'][0])
            endpoint='/api/v1/projects/'+self.p+'/creative-canvas-versions/'+canvas['version_id']
            self.assertEqual(client.get(endpoint).status_code,200)
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,403)
            self.assertEqual(client.get('/api/v1/library').status_code,403)
            self.assertEqual(client.get('/api/v1/asset-center',headers=headers).status_code,403)
            self.assertEqual(client.post('/api/v1/projects/'+self.p+'/production-batch/execute',headers=headers,json={'payload':{},'expected_revision':self.rev,'idempotency_key':'guest'}).status_code,403)
            self.command('revoke-share',{'share_id':shared['share_id']})
            self.assertEqual(client.get('/api/v1/access/share-view').status_code,403)
            self.assertEqual(client.get(endpoint).status_code,403)

    def test_edit_share_original_canvas_conflict_and_revoked_old_payload(self):
        from fastapi.testclient import TestClient
        self.assign();canvas=self.canvas();shared,secret=self.share(canvas,'edit')
        with TestClient(self.app()) as client:
            headers=self.client_login(client,secret);base='/api/v1/projects/'+self.p
            current=client.get('/api/v1/access/share-view').json();doc=current['document'];doc['nodes'][0]['text']='协作手改'
            body={'payload':{'title':current['title'],'canvas_revision':current['version'],'document':doc},'expected_revision':current['project_revision'],'idempotency_key':'shared-save'}
            saved=client.put(base+'/creative-canvases/'+canvas['id'],headers=headers,json=body)
            self.assertEqual(saved.status_code,200,saved.text);self.rev=saved.json()['revision']
            self.assertEqual(client.put(base+'/creative-canvases/'+canvas['id'],headers=headers,json=body).json(),saved.json())
            stale=client.put(base+'/creative-canvases/'+canvas['id'],headers=headers,json=dict(body,idempotency_key='different'))
            self.assertEqual(stale.status_code,409,stale.text)
            self.assertEqual(client.get('/api/v1/access/share-view').json()['document']['nodes'][0]['text'],'协作手改')
            self.command('revoke-share',{'share_id':shared['share_id']})
            self.assertEqual(client.put(base+'/creative-canvases/'+canvas['id'],headers=headers,json=body).status_code,403)

    def test_revocation_waits_for_authorized_write_then_blocks_later_receipt_replay(self):
        self.assign();member,_,_=self.invite('editor');entered=threading.Event();release=threading.Event();revoked=threading.Event();errors=[]
        def writer():
            with self.as_member(member):
                try:self.store._mutate(self.p,'create_object',{'synthetic':True},expected_revision=self.rev,idempotency_key='held-write',actor=member['actor'],callback=lambda c,p:(entered.set(),release.wait(5),{'done':True})[-1])
                except Exception as exc:errors.append(exc)
        def revoke():
            with self.as_member(self.owner):
                try:self.command('member',{'scope':'project','scope_id':self.p,'identity_id':member['identity_id'],'role':'editor','active':False});revoked.set()
                except Exception as exc:errors.append(exc)
        first=threading.Thread(target=writer);first.start();self.assertTrue(entered.wait(3));second=threading.Thread(target=revoke);second.start();self.assertFalse(revoked.wait(.15));release.set();first.join(5);second.join(5);self.assertFalse(errors,errors);self.assertTrue(revoked.is_set())
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.store._mutate(self.p,'create_object',{'synthetic':True},expected_revision=0,idempotency_key='held-write',actor=member['actor'],callback=lambda c,p:{})

    def test_optional_review_uses_original_media_review_and_resubmission(self):
        self.assign();objects=self.hierarchy();media=self.media();candidate=self.candidate(objects['shot'],media,role='storyboard')['candidate_id']
        self.command('review-policy',{'project_id':self.p,'lanes':['storyboard']})
        submission=self.write('submit_team_review',{'candidate_id':candidate,'lane':'storyboard'})
        reviewer,_,_=self.invite('reviewer')
        with self.as_member(reviewer):
            result=self.service.commit_team_review(self.p,{'submission_id':submission['submission_id'],'outcome':'needs_changes','reason':'需要改善构图'},expected_revision=self.rev,idempotency_key='review-one',actor=reviewer['actor']);self.rev=result['revision']
        history=self.service.get_review_history(self.p,media_id=media)
        self.assertTrue(any(r['note'].get('reason')=='需要改善构图' or r['note'].get('body')=='需要改善构图' for r in history['items']),history)
        again=self.write('submit_team_review',{'candidate_id':candidate,'lane':'storyboard','supersedes_id':submission['submission_id']})
        self.assertNotEqual(again['submission_id'],submission['submission_id'])
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    def test_workspace_resources_follow_project_membership_and_return_names(self):
        studio=self.command('workspace',{'name':'可读工作室','parent_id':None})['workspace_id']
        self.assign(workspace=studio)
        media=self.media('workspace-visible')
        snapshot=self.service.access_snapshot()
        project=next(row for row in snapshot['projects'] if row['id']==self.p)
        self.assertEqual(project['workspace_name'],'可读工作室')
        self.assertTrue(all(row['scope_name'] for row in snapshot['members']))
        value=self.service.access_workspace_resources(studio,query='workspace-visible',limit=1)
        self.assertEqual(value['total'],1)
        self.assertEqual(value['items'][0]['id'],media)
        member,_,_=self.invite('viewer',scope='workspace',target=studio)
        with self.as_member(member):
            self.assertEqual(self.service.access_workspace_resources(studio)['total'],1)
            with self.assertRaises(ResourceError):self.service.access_workspace_resources(self.owner['workspace_id'])
        self.command('member',{'scope':'workspace','scope_id':studio,'identity_id':member['identity_id'],'role':'viewer','active':False})
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.service.access_workspace_resources(studio)

    def test_discovery_returns_actual_canvas_and_does_not_leak_other_member_project(self):
        from fastapi.testclient import TestClient
        self.assign();canvas=self.canvas('可继续的创作')
        self.write('publish_canvas_template',{'canvas_id':canvas['id'],'canvas_revision':canvas['canvas_revision'],'title':'固定模板'})
        member,credential,_=self.invite('viewer')
        with self.as_member(member):
            private=self.service.create_project({'name':'成员私人创作'},actor=member['actor'])
            self.service.create_creative_canvas(private['id'],{'title':'不应泄漏','document':{'nodes':[],'edges':[]}},actor=member['actor'],expected_revision=0,idempotency_key='private-canvas')
        with TestClient(self.app()) as client:
            headers=self.client_login(client)
            response=client.get('/api/v1/discovery',headers=headers);self.assertEqual(response.status_code,200,response.text)
            data=response.json()
            self.assertTrue(any(row['target_id']==canvas['id'] and 'task_target='+canvas['id'] in row['href'] for row in data['recent']))
            self.assertFalse(any(row['project_id']==private['id'] for row in data['recent']))
            self.assertTrue(any(row['title']=='固定模板' for row in data['templates']))
            self.assertTrue(data['skills']);self.assertTrue(data['tutorials'])
            tutorial=client.get('/api/v1/discovery/tutorials/'+data['tutorials'][0]['id'],headers=headers)
            self.assertEqual(tutorial.status_code,200,tutorial.text);self.assertTrue(tutorial.json()['content'])

    def test_review_filters_and_pages_keep_candidate_and_submission_together(self):
        self.assign();objects=self.hierarchy()
        first=self.candidate(objects['shot'],self.media('review-first'),role='storyboard')['candidate_id']
        second=self.candidate(objects['shot'],self.media('review-second'),role='storyboard')['candidate_id']
        self.command('review-policy',{'project_id':self.p,'lanes':['storyboard']})
        submitted=self.write('submit_team_review',{'candidate_id':first,'lane':'storyboard'})
        pending=self.service.team_review_queue(self.p,'storyboard',status='pending',episode_id=objects['episode'],limit=1)
        self.assertEqual(pending['total'],1);self.assertEqual(pending['candidates'][0]['id'],first)
        self.assertEqual(pending['submissions'][0]['id'],submitted['submission_id'])
        unsubmitted=self.service.team_review_queue(self.p,'storyboard',status='unsubmitted',query='second')
        self.assertEqual([row['id'] for row in unsubmitted['candidates']],[second]);self.assertEqual(unsubmitted['submissions'],[])
        first_page=self.service.team_review_queue(self.p,'storyboard',limit=1)
        second_page=self.service.team_review_queue(self.p,'storyboard',limit=1,offset=first_page['next_offset'])
        self.assertEqual({first_page['candidates'][0]['id'],second_page['candidates'][0]['id']},{first,second})
        self.write('commit_team_review',{'submission_id':submitted['submission_id'],'outcome':'pass','reason':'可进入后续选用'})
        passed=self.service.team_review_queue(self.p,'storyboard',status='pass')
        self.assertEqual([row['id'] for row in passed['candidates']],[first])
        self.assertEqual(self.service.team_review_queue(self.p,'storyboard',status='pending')['total'],0)

    def test_permissions_use_real_request_and_local_auto_login_remains(self):
        from fastapi.testclient import TestClient
        with TestClient(self.app(local_auto_session=True)) as client:
            # TestClient's host must emulate the actual loopback bootstrap consumer.
            response=client.get('/api/v1/session');self.assertEqual(response.status_code,403)
        with TestClient(self.app(local_auto_session=True),client=('127.0.0.1',50000)) as client:
            response=client.get('/api/v1/session');self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['actor'],'test-human')
            self.assertEqual(client.get('/api/v1/projects/'+self.p+'/tree').status_code,200)
            self.assertEqual(client.post('/api/v1/session/logout',headers={'Origin':'http://testserver','X-CSRF-Token':response.json()['csrf_token']}).status_code,200)
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:conn.execute(update(S.access_identities).where(S.access_identities.c.id==self.owner['identity_id']).values(actor='forged-label'))

    def test_configured_seats_block_invitation_acceptance_atomically(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();provider='access_seat_'+uuid.uuid4().hex
        self.service.register_provider({'id':provider,'base_url':'https://example.invalid','auth_ref':'ISOLATED_ONLY'},actor='test-human')
        model=self.service.register_model({'provider_id':provider,'model_key':'synthetic','model_version':'1','modality':'image','capabilities':{'purposes':['identity_ref']}},actor='test-human')['id']
        document=dict(plan_key='isolated-access',title='隔离席位合同',amount_minor=100,currency='TST',credits=100,bucket_kind='credit',validity_days=2,checkout_minutes=10,purposes=['identity_ref'],rates=[dict(model_id=model,unit='images',credits_per_unit=1)],refund_policy='unused_order_only',max_concurrent_jobs=1,invoice_enabled=False,seat_limit=2,watermark_required=False,renewal_policy='manual_from_payment')
        self.write('configure_commerce_plan',{'document':document,'base_version_id':None,'metering_enabled':True})
        member,_,_=self.invite('viewer')
        self.assertTrue(self.store.access_member_valid(self.p,member['actor']))
        secret=secrets.token_urlsafe(32);credential=secrets.token_urlsafe(32)
        invitation=self.command('invitation',{'scope':'project','scope_id':self.p,'role':'viewer','secret':secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        with self.assertRaises(ResourceError) as error:self.service.accept_access_invitation({'invitation_secret':secret,'credential_secret':credential,'display_name':'超限成员'})
        self.assertEqual(error.exception.code,'seat_limit_exceeded')
        with self.engine.connect() as conn:
            self.assertIsNone(conn.execute(select(S.access_invitations.c.accepted_by).where(S.access_invitations.c.id==invitation['invitation_id'])).scalar_one())
            self.assertFalse(conn.execute(select(S.access_identities.c.id).where(S.access_identities.c.display_name=='超限成员')).first())
        self.command('member',{'scope':'project','scope_id':self.p,'identity_id':member['identity_id'],'role':'viewer','active':False})
        replacement=self.service.accept_access_invitation({'invitation_secret':secret,'credential_secret':credential,'display_name':'空位加入成员'})
        self.assertTrue(self.store.access_member_valid(self.p,replacement['actor']))
        self.assertFalse(self.store.access_member_valid(self.p,member['actor']))

    def test_edit_share_preserves_hidden_original_job_binding(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();self.seed_generation_timeline_render()
        with self.engine.connect() as conn:job=conn.execute(select(S.generation_jobs.c.id).where(S.generation_jobs.c.project_id==self.p)).scalar_one()
        canvas=self.write('create_creative_canvas',{'document':{'nodes':[{'id':'video','type':'video','job_id':job,'text':'原任务正文'}],'edges':[]}});_,secret=self.share(canvas,'edit')
        with TestClient(self.app()) as client:
            headers=self.client_login(client,secret);opened=client.get('/api/v1/access/share-view').json()
            self.assertNotIn('job_id',opened['document']['nodes'][0]);opened['document']['nodes'][0]['text']='分享方的编辑'
            body={'payload':{'canvas_revision':opened['version'],'title':opened['title'],'document':opened['document']},'expected_revision':opened['project_revision'],'idempotency_key':'share-keeps-hidden-job'}
            result=client.put('/api/v1/projects/'+self.p+'/creative-canvases/'+canvas['id'],headers=headers,json=body);self.assertEqual(result.status_code,200,result.text)
        current=self.service.get_creative_canvas(self.p,canvas['id']);self.assertEqual(current['document']['nodes'][0]['job_id'],job);self.assertEqual(current['document']['nodes'][0]['text'],'分享方的编辑')

    def test_existing_member_accepts_another_team_without_second_identity(self):
        self.assign();member,_,_=self.invite('viewer')
        studio=self.command('workspace',{'name':'另一工作室','parent_id':None})['workspace_id']
        secret=secrets.token_urlsafe(32);credential=secrets.token_urlsafe(32)
        self.command('invitation',{'scope':'workspace','scope_id':studio,'role':'editor','secret':secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        with self.as_member(member):
            body={'invitation_secret':secret,'credential_secret':credential,'display_name':'保留原身份','use_current_identity':True}
            joined=self.service.accept_access_invitation(body);self.assertEqual(joined['identity_id'],member['identity_id']);self.assertEqual(joined['actor'],member['actor'])
            replay=self.service.accept_access_invitation(body);self.assertEqual(replay,joined)
            self.assertIn('editor',self.service.authorize_workspace(studio,'edit')['roles'])
            self.assertEqual(len(self.service.access_snapshot()['credentials']),2)

    def test_personal_workspace_rejects_new_members_and_keeps_explicit_legacy_members(self):
        from sqlalchemy import insert,select
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();other=self.service.ensure_local_access('personal-scope-other-'+uuid.uuid4().hex)
        payload={'scope':'workspace','scope_id':self.owner['workspace_id'],'identity_id':other['identity_id'],'role':'viewer','active':True}
        with self.assertRaises(ResourceError) as error:self.command('member',payload)
        self.assertEqual(error.exception.code,'personal_workspace_membership')
        with self.assertRaises(ResourceError):self.command('invitation',{'scope':'workspace','scope_id':self.owner['workspace_id'],'role':'viewer','secret':secrets.token_urlsafe(32),'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        self.invite('viewer')
        # A synthetic legacy membership remains until a user explicitly removes it.
        with self.engine.begin() as conn:conn.execute(insert(S.access_workspace_members).values(workspace_id=self.owner['workspace_id'],identity_id=other['identity_id'],role='viewer',active=True))
        self.command('profile',{'display_name':self.owner['actor'],'preferences':{}})
        with self.engine.connect() as conn:self.assertTrue(conn.execute(select(S.access_workspace_members.c.active).where(S.access_workspace_members.c.workspace_id==self.owner['workspace_id'],S.access_workspace_members.c.identity_id==other['identity_id'])).scalar_one())
        self.command('member',{**payload,'active':False})
        with self.assertRaises(ResourceError):self.command('member',payload)

    def test_new_team_project_uses_workspace_role_and_personal_project_keeps_owner(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();studio=self.command('workspace',{'name':'团队项目授权测试','parent_id':None})['workspace_id']
        member,_,_=self.invite('editor',scope='workspace',target=studio)
        with self.as_member(member):
            team=self.service.create_project({'name':'由团队编辑创建'},actor=member['actor'],workspace_id=studio)
            self.assertEqual(self.service.access_scope(team['id'])['roles'],['editor'])
        with self.engine.connect() as conn:
            self.assertFalse(conn.execute(select(S.access_project_members).where(S.access_project_members.c.project_id==team['id'])).first())
        self.command('member',{'scope':'workspace','scope_id':studio,'identity_id':member['identity_id'],'role':'editor','active':False})
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.service.authorize_access(team['id'])
        personal=self.service.create_project({'name':'个人项目创建者所有权'},actor=self.owner['actor'])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.access_project_members.c.role).where(S.access_project_members.c.project_id==personal['id'],S.access_project_members.c.identity_id==self.owner['identity_id'])).scalar_one(),'owner')

    def test_http_creation_defaults_personal_and_uses_only_explicit_team_target(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        studio=self.command('workspace',{'name':'历史会话团队','parent_id':None})['workspace_id']
        target=self.command('workspace',{'name':'明确归属团队','parent_id':None})['workspace_id']
        with TestClient(self.app()) as client:
            headers=self.client_login(client)
            # A legacy tab may retain a workspace choice; it never owns a new project implicitly.
            switched=client.post('/api/v1/access/switch-workspace',json={'workspace_id':studio},headers=headers)
            self.assertEqual(switched.status_code,200,switched.text)
            for endpoint,payload,id_field in (('/api/v1/projects',{'name':'空间一致性创建'},'id'),('/api/v1/projects/empty-canvas',{'mode':'empty_canvas'},'project_id')):
                with self.subTest(endpoint=endpoint):
                    key=uuid.uuid4().hex
                    personal=client.post(endpoint,json={'payload':payload,'idempotency_key':key},headers=headers)
                    self.assertEqual(personal.status_code,200,personal.text)
                    replay=client.post(endpoint,json={'payload':payload,'idempotency_key':key},headers=headers)
                    self.assertEqual(replay.json(),personal.json())
                    conflicting=client.post(endpoint,json={'payload':payload,'idempotency_key':key,'workspace_id':target},headers=headers)
                    self.assertEqual(conflicting.status_code,409,conflicting.text)
                    team=client.post(endpoint,json={'payload':payload,'idempotency_key':uuid.uuid4().hex,'workspace_id':target},headers=headers)
                    self.assertEqual(team.status_code,200,team.text)
                    for response,owner_container in ((personal,self.owner['workspace_id']),(team,target)):
                        with self.engine.connect() as conn:self.assertEqual(conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==response.json()[id_field])).scalar_one(),owner_container)

    def test_team_editor_http_empty_canvas_creation_and_viewer_rejection(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        studio=self.command('workspace',{'name':'空画布团队权限测试','parent_id':None})['workspace_id']
        for role in ('editor','viewer'):
            member,credential,_=self.invite(role,scope='workspace',target=studio)
            with self.subTest(role=role),TestClient(self.app()) as client:
                headers=self.client_login(client,credential)
                with self.engine.connect() as conn:count=conn.execute(select(func.count()).select_from(S.projects)).scalar_one()
                response=client.post('/api/v1/projects/empty-canvas',json={'payload':{'mode':'empty_canvas'},'idempotency_key':uuid.uuid4().hex,'workspace_id':studio},headers=headers)
                if role=='editor':
                    self.assertEqual(response.status_code,200,response.text);project=response.json()['project_id']
                    with self.engine.connect() as conn:
                        self.assertEqual(conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==project)).scalar_one(),studio)
                        self.assertFalse(conn.execute(select(S.access_project_members).where(S.access_project_members.c.project_id==project)).first())
                    self.assertEqual(client.get('/api/v1/projects/'+project+'/creative-canvases/'+response.json()['canvas_id']).status_code,200)
                else:
                    self.assertEqual(response.status_code,403,response.text)
                    with self.engine.connect() as conn:self.assertEqual(conn.execute(select(func.count()).select_from(S.projects)).scalar_one(),count)

    def test_trusted_creation_always_binds_personal_owner_and_deactivation_keeps_references(self):
        from sqlalchemy import select,update,delete
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        actor='retained-owner-'+uuid.uuid4().hex;key=uuid.uuid4().hex
        token=set_principal(None)
        try:
            project=self.service.create_project({'name':'可信创建的归属保留'},actor=actor,idempotency_key=key)
            self.assertEqual(self.service.create_project({'name':'可信创建的归属保留'},actor=actor,idempotency_key=key),project)
        finally:reset_principal(token)
        with self.engine.connect() as conn:
            binding=conn.execute(select(S.access_projects).where(S.access_projects.c.project_id==project['id'])).mappings().one()
            workspace=conn.execute(select(S.access_workspaces).where(S.access_workspaces.c.id==binding['workspace_id'])).mappings().one()
            owner=conn.execute(select(S.access_identities).where(S.access_identities.c.id==workspace['created_by'])).mappings().one()
            self.assertEqual(workspace['kind'],'personal');self.assertEqual(owner['actor'],actor)
        with self.engine.begin() as conn:conn.execute(update(S.access_identities).where(S.access_identities.c.id==owner['id']).values(active=False))
        with self.assertRaises(IntegrityError),self.engine.begin() as conn:conn.execute(delete(S.access_identities).where(S.access_identities.c.id==owner['id']))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==project['id'])).scalar_one(),workspace['id'])
            self.assertEqual(conn.execute(select(S.access_workspaces.c.created_by).where(S.access_workspaces.c.id==workspace['id'])).scalar_one(),owner['id'])
            self.assertEqual(conn.execute(select(S.projects.c.created_by).where(S.projects.c.id==project['id'])).scalar_one(),actor)
        with self.assertRaises(ResourceError):self.service.ensure_local_access(actor)

    def test_invitation_preview_http_existing_identity_team_landing_and_expiry(self):
        from fastapi.testclient import TestClient
        from sqlalchemy import select,func,insert
        from vsc.assets.access_control import secret_hash
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();member,credential,_=self.invite('viewer')
        studio=self.command('workspace',{'name':'邀请目标团队','parent_id':None})['workspace_id']
        secret=secrets.token_urlsafe(32);new_credential=secrets.token_urlsafe(32)
        invitation=self.command('invitation',{'scope':'workspace','scope_id':studio,'role':'editor','secret':secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        with self.engine.connect() as conn:count=conn.execute(select(func.count()).select_from(S.access_identities)).scalar_one()
        with TestClient(self.app()) as client:
            preview=client.post('/api/v1/access/invitation-preview',json={'invitation_secret':secret},headers={'Origin':'http://testserver'})
            self.assertEqual(preview.status_code,200,preview.text);self.assertEqual(preview.json()['target_name'],'邀请目标团队');self.assertEqual(preview.json()['role'],'editor');self.assertEqual(preview.headers['cache-control'],'no-store')
            with self.engine.connect() as conn:self.assertEqual(conn.execute(select(func.count()).select_from(S.access_identities)).scalar_one(),count)
            headers=self.client_login(client,credential)
            body={'invitation_secret':secret,'credential_secret':new_credential,'display_name':'沿用账户','use_current_identity':True}
            joined=client.post('/api/v1/access/join',json=body,headers=headers)
            self.assertEqual(joined.status_code,200,joined.text);value=joined.json()
            self.assertEqual(value['identity_id'],member['identity_id']);self.assertEqual(value['workspace_id'],studio)
            self.assertEqual(value['joined_workspace_id'],studio);self.assertIsNone(value['joined_project_id']);self.assertEqual(value['target_name'],'邀请目标团队')
            self.assertEqual(client.get('/api/v1/session').json()['workspace_id'],studio)
            with self.engine.connect() as conn:self.assertEqual(conn.execute(select(func.count()).select_from(S.access_identities)).scalar_one(),count)
            # Authentication still defaults to the account's personal creation space.
            self.assertNotEqual(self.service.authenticate_access(new_credential)['workspace_id'],studio)
            project_secret=secrets.token_urlsafe(32)
            self.command('invitation',{'scope':'project','scope_id':self.p,'role':'viewer','secret':project_secret,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
            project_preview=client.post('/api/v1/access/invitation-preview',json={'invitation_secret':project_secret},headers={'Origin':'http://testserver'})
            self.assertEqual(project_preview.json()['target_name'],self.project['name'])
            joined_project=client.post('/api/v1/access/join',json={**body,'invitation_secret':project_secret,'credential_secret':secrets.token_urlsafe(32)},headers={'Origin':'http://testserver'}).json()
            self.assertEqual(joined_project['joined_project_id'],self.p);self.assertIsNone(joined_project['joined_workspace_id'])
            self.assertEqual(joined_project['workspace_id'],member['workspace_id'])
            expired_secret=secrets.token_urlsafe(32)
            with self.engine.begin() as conn:conn.execute(insert(S.access_invitations).values(id=str(uuid.uuid4()),workspace_id=studio,project_id=None,role='viewer',secret_sha256=secret_hash(expired_secret),expires_at=datetime.now(timezone.utc)-timedelta(seconds=1),created_by=self.owner['identity_id']))
            expired=client.post('/api/v1/access/invitation-preview',json={'invitation_secret':expired_secret},headers={'Origin':'http://testserver'})
            self.assertEqual(expired.status_code,403,expired.text)

    def test_transfer_preview_names_permission_changes_direct_grants_and_live_shares(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        a=self.command('workspace',{'name':'转出团队','parent_id':None})['workspace_id'];b=self.command('workspace',{'name':'转入团队','parent_id':None})['workspace_id']
        self.assign(workspace=a)
        lost,_,_=self.invite('viewer',scope='workspace',target=a);gained,_,_=self.invite('reviewer',scope='workspace',target=b);direct,_,_=self.invite('editor')
        canvas=self.canvas();share,_=self.share(canvas)
        preview=self.service.access_migration_preview(self.p,b);plan=preview['plan']
        by_id={row['identity_id']:row for row in plan['access_changes']}
        self.assertEqual(by_id[lost['identity_id']]['change'],'lost');self.assertEqual(by_id[gained['identity_id']]['change'],'gained')
        self.assertEqual(by_id[direct['identity_id']]['change'],'retained');self.assertEqual(by_id[direct['identity_id']]['display_name'],'工程成员')
        self.assertEqual(plan['shares'][0]['id'],share['share_id']);self.assertEqual(plan['shares'][0]['canvas_title'],'共享工程画布')
        self.command('member',{'scope':'workspace','scope_id':b,'identity_id':gained['identity_id'],'role':'editor','active':True})
        with self.assertRaises(Conflict):self.command('assign-project',{'project_id':self.p,'workspace_id':b,'preview_sha256':preview['sha256']})
        preview=self.service.access_migration_preview(self.p,b)
        payload={'project_id':self.p,'workspace_id':b,'preview_sha256':preview['sha256']};key=uuid.uuid4().hex
        first=self.command('assign-project',payload,key);self.assertEqual(self.command('assign-project',payload,key),first)
        for binding,allowed in ((lost,False),(gained,True),(direct,True)):
            with self.as_member(binding):
                if allowed:self.assertIn('read',self.service.access_scope(self.p)['capabilities'])
                else:
                    with self.assertRaises(ResourceError):self.service.access_scope(self.p)
        with self.engine.connect() as conn:
            self.assertFalse(conn.execute(select(S.access_shares.c.revoked).where(S.access_shares.c.id==share['share_id'])).scalar_one())
            self.assertTrue(conn.execute(select(S.access_project_members.c.active).where(S.access_project_members.c.project_id==self.p,S.access_project_members.c.identity_id==direct['identity_id'])).scalar_one())
        self.assertEqual(self.service.get_creative_canvas(self.p,canvas['id'])['version_id'],canvas['version_id'])

    def test_workspace_member_removal_preserves_then_explicitly_revokes_legacy_direct_owner(self):
        from fastapi.testclient import TestClient
        studio=self.command('workspace',{'name':'移除预览团队','parent_id':None})['workspace_id'];self.assign(workspace=studio)
        member,_,_=self.invite('editor',scope='workspace',target=studio)
        self.command('member',{'scope':'project','scope_id':self.p,'identity_id':member['identity_id'],'role':'owner','active':True})
        canvas=self.canvas();share,_=self.share(canvas)
        with TestClient(self.app()) as client:
            headers=self.client_login(client)
            response=client.post('/api/v1/access/workspaces/'+studio+'/member-removal-preview',json={'identity_id':member['identity_id']},headers=headers)
            self.assertEqual(response.status_code,200,response.text);preview=response.json()
        self.assertEqual(preview['plan']['retained_project_grants'],[{'project_id':self.p,'project_name':self.project['name'],'role':'owner','can_revoke':True}])
        payload={'scope':'workspace','scope_id':studio,'identity_id':member['identity_id'],'role':'editor','active':False}
        self.command('member',{**payload,'preview_sha256':preview['sha256'],'revoke_project_access':False})
        with self.as_member(member):self.assertIn('owner',self.service.access_scope(self.p)['roles'])
        self.command('member',{**payload,'active':True})
        with self.assertRaises(Conflict):self.command('member',{**payload,'preview_sha256':preview['sha256'],'revoke_project_access':True})
        with self.as_member(member):self.assertIn('owner',self.service.access_scope(self.p)['roles'])
        preview=self.service.access_member_removal_preview(studio,member['identity_id']);key=uuid.uuid4().hex
        final={**payload,'preview_sha256':preview['sha256'],'revoke_project_access':True}
        removed=self.command('member',final,key);self.assertEqual(removed['revoked_project_ids'],[self.p]);self.assertEqual(self.command('member',final,key),removed)
        with self.as_member(member):
            with self.assertRaises(ResourceError):self.service.access_scope(self.p)
        self.assertFalse(next(row for row in self.service.access_snapshot()['shares'] if row['id']==share['share_id'])['revoked'])
        self.command('member',{'scope':'project','scope_id':self.p,'identity_id':self.owner['identity_id'],'role':'owner','active':True})
        last=self.service.access_member_removal_preview(studio,self.owner['identity_id'])
        self.assertFalse(last['plan']['retained_project_grants'][0]['can_revoke'])
        with self.assertRaises(Conflict) as error:self.command('member',{**payload,'identity_id':self.owner['identity_id'],'role':'owner','preview_sha256':last['sha256'],'revoke_project_access':True})
        self.assertEqual(error.exception.code,'last_owner')
        self.assertIn('owner',self.service.authorize_workspace(studio)['roles'])
        self.assertIn('owner',self.service.access_scope(self.p)['roles'])


    def test_fixed_share_members_exact_set_commits_atomically_and_rejects_extension(self):
        from sqlalchemy import insert,select,update,delete,text
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        self.assign();shared_media=self.media('sealed-shared');private=self.media('sealed-private')
        canvas=self.write('create_creative_canvas',{'title':'fixed members','document':{'nodes':[
            {'id':'a','type':'image','media_id':shared_media},
            {'id':'b','type':'image','media_id':shared_media},
            {'id':'note','type':'text','text':'no media'}],'edges':[]}})
        share,secret=self.share(canvas)
        with self.engine.connect() as conn:
            source=dict(conn.execute(select(S.access_shares).where(S.access_shares.c.id==share['share_id'])).mappings().one())
            self.assertEqual(conn.execute(select(S.access_share_media.c.media_id).where(S.access_share_media.c.share_id==share['share_id'])).scalars().all(),[shared_media])
        for members in ([],[private],[shared_media,private]):
            with self.subTest(members=members),self.assertRaises(IntegrityError) as failure:
                with self.engine.begin() as conn:
                    identifier=str(uuid.uuid4())
                    conn.execute(insert(S.access_shares).values(dict(source,id=identifier,secret_sha256=uuid.uuid4().hex*2)))
                    for mid in members:conn.execute(insert(S.access_share_media).values(project_id=self.p,share_id=identifier,media_id=mid))
            self.assertEqual(failure.exception.orig.sqlstate,'23514')
        with self.assertRaises(IntegrityError) as failure:
            with self.engine.begin() as conn:conn.execute(insert(S.access_share_media).values(project_id=self.p,share_id=share['share_id'],media_id=private))
        self.assertEqual(failure.exception.orig.sqlstate,'23514')
        guest=self.service.authenticate_access(secret)
        with self.as_member(guest):
            self.service.authorize_access(self.p,'read','media',shared_media)
            with self.assertRaises(ResourceError):self.service.authorize_access(self.p,'read','media',private)
        for statement in (update(S.access_share_media).where(S.access_share_media.c.share_id==share['share_id']).values(media_id=private),delete(S.access_share_media).where(S.access_share_media.c.share_id==share['share_id'])):
            with self.assertRaises(IntegrityError) as failure:
                with self.engine.begin() as conn:conn.execute(statement)
            self.assertEqual(failure.exception.orig.sqlstate,'23514')
        with self.engine.begin() as conn:
            # Parent then complete members is deliberately legal in one transaction.
            identifier=str(uuid.uuid4());conn.execute(insert(S.access_shares).values(dict(source,id=identifier,secret_sha256=uuid.uuid4().hex*2)))
            conn.execute(insert(S.access_share_media).values(project_id=self.p,share_id=identifier,media_id=shared_media))
            conn.execute(text('SET CONSTRAINTS access_share_members_sealed IMMEDIATE'))
        edit_share,edit_secret=self.share(canvas,'edit')
        self.write('save_creative_canvas',dict(canvas_id=canvas['id'],canvas_revision=canvas['canvas_revision'],title='new current media',document={'nodes':[{'id':'private','type':'image','media_id':private}],'edges':[]}))
        with self.as_member(self.service.authenticate_access(edit_secret)):
            self.service.authorize_access(self.p,'read','media',private)
        with self.as_member(guest):
            with self.assertRaises(ResourceError):self.service.authorize_access(self.p,'read','media',private)
        with self.engine.connect() as conn:
            self.assertTrue(conn.execute(text('SELECT vsc_access_share_members_match(:p,:s)'),dict(p=self.p,s=edit_share['share_id'])).scalar_one())

    def test_share_seal_migration_preflight_rejects_dirty_legacy_without_rewriting(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import insert,select,text
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        from support.paths import ROOT
        self.assign();shared=self.media('migration-shared');private=self.media('migration-private')
        canvas=self.write('create_creative_canvas',{'title':'migration pin','document':{'nodes':[{'id':'shared','type':'image','media_id':shared}],'edges':[]}})
        share,_=self.share(canvas);cfg=Config(str(ROOT/'migrations/postgres/alembic.ini'))
        with self.engine.connect() as conn:
            before=conn.execute(select(S.access_share_media).where(S.access_share_media.c.share_id==share['share_id'])).all()
            conn.rollback()
            transaction=conn.begin()
            try:
                cfg.attributes['connection']=conn;command.downgrade(cfg,'0031_text_tool_copies')
                conn.execute(insert(S.access_share_media).values(project_id=self.p,share_id=share['share_id'],media_id=private))
                with self.assertRaises(IntegrityError) as failure:
                    with conn.begin_nested():command.upgrade(cfg,'0032_fixed_member_seals')
                self.assertEqual(failure.exception.orig.sqlstate,'23514')
                self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),'0031_text_tool_copies')
                self.assertIsNone(conn.execute(text("SELECT to_regprocedure('vsc_access_share_members_match(uuid,uuid)')")).scalar_one())
                self.assertEqual(len(conn.execute(select(S.access_share_media).where(S.access_share_media.c.share_id==share['share_id'])).all()),2)
            finally:transaction.rollback()
            transaction=conn.begin()
            try:
                command.downgrade(cfg,'0031_text_tool_copies');command.upgrade(cfg,'0032_fixed_member_seals')
                self.assertEqual(conn.execute(select(S.access_share_media).where(S.access_share_media.c.share_id==share['share_id'])).all(),before)
            finally:transaction.rollback()
        self.assertTrue(self.store.check_schema()['ready'])
