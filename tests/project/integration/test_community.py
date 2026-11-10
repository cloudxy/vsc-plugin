"""Isolated original PG/HTTP transactions; distribution is injected, never networked."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib,json,secrets,tempfile,unittest,uuid
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.access_control import Principal,set_principal,reset_principal
from vsc.assets.resource_service import ResourceError,Conflict
from vsc.adapters.providers.distribution import DistributionReceipt

class FixtureDistribution:
    def __init__(self):self.submissions=[];self.queries=[];self.cancelled=[];self.fail_submit=False
    def submit(self,request):
        self.submissions.append(request)
        if self.fail_submit:raise TimeoutError('receipt lost')
        return DistributionReceipt('submitted','synthetic-remote')
    def query(self,key):self.queries.append(key);return DistributionReceipt('completed','synthetic-remote','https://example.invalid/synthetic')
    def cancel(self,key):self.cancelled.append(key);return DistributionReceipt('cancelled',key)

@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'isolated PostgreSQL required')
class CommunityTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        self.project=self.service.create_project({'name':'Synthetic community','profile_snapshot':{'profile_id':'vsc.synthetic','version':'1','stages':[],'contract_policy':'production-v2'}},actor='test-human');self.p,self.rev=self.project['id'],0
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        from vsc.adapters.storage.local.store import LocalStorage
        self.service.storage=LocalStorage(self.temp.name);self.owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**self.owner));self.addCleanup(reset_principal,token)
        self.assign(self.p);self.rev=self.service.get_project(self.p)['revision'];self.adapter=FixtureDistribution();self.service.distribution_adapters={'fixture':self.adapter}
    def command(self,action,payload):return self.service.access_command(action,payload,expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex,actor='test-human')
    def assign(self,p):
        preview=self.service.access_migration_preview(p,self.owner['workspace_id']);self.command('assign-project',dict(project_id=p,workspace_id=self.owner['workspace_id'],preview_sha256=preview['sha256']))
    @contextmanager
    def identity(self,binding):
        token=set_principal(Principal(**binding))
        try:yield
        finally:reset_principal(token)
    def invite(self,role):
        secret=secrets.token_urlsafe(32);self.command('invitation',dict(scope='project',scope_id=self.p,role=role,secret=secret,expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        return self.service.accept_access_invitation(dict(invitation_secret=secret,credential_secret=secrets.token_urlsafe(32),display_name='Synthetic '+role))
    def original_media(self,modality='image',rights='owned'):
        from support.fixtures.resources import png_bytes
        data=png_bytes() if modality=='image' else b'synthetic fixed video bytes';sha=hashlib.sha256(data).hexdigest();key=sha+'.bin';Path(self.temp.name,key).write_bytes(data)
        return self.write('register_media',dict(name='Synthetic '+modality,modality=modality,sha256=sha,size_bytes=len(data),mime_type='image/png' if modality=='image' else 'video/mp4',duration_ms=5000 if modality=='video' else None,storage='local',object_key=key,rights=rights,source={'kind':'fixture','content':'synthetic owned evidence'}))['id']
    def rule(self):
        rules=self.service.community_snapshot(self.p)['rules']
        return rules[0]['id'] if rules else self.write('save_community_rule',dict(base_version_id=None,title='Synthetic local rule',body='Synthetic content and authorized use only.'))['id']
    def publication(self,media=None,template=None,rule=None):return self.write('save_community_publication',dict(publication_id=None,base_version_id=None,title='Synthetic work '+self.p,description='Fixed local evidence',scope='workspace',rule_id=rule or self.rule(),media_id=media,template_id=template))
    def transition(self,row,status):return self.write('set_community_publication_state',dict(version_id=row['version_id'],base_event_id=row['event_id'],status=status,reason='Synthetic explicit action'))
    def channel(self):return self.write('save_distribution_channel',dict(channel_key='fixture',base_version_id=None,name='Isolated channel',adapter='fixture',endpoint='https://example.invalid',credential_env='VSC_SYNTHETIC_DISTRIBUTION',enabled=True))
    def action(self,row,action,key=None):
        result=self.service.run_distribution(self.p,row['id'],action,{'request_sha256':row['request_sha256']},actor='test-human',expected_revision=self.rev,idempotency_key=key or uuid.uuid4().hex);self.rev=result['revision'];return result
    def test_fixed_versions_rights_reports_and_moderation(self):
        media=self.original_media();rule=self.rule();draft=self.publication(media,rule=rule);self.assertEqual(self.service.community_feed(query=self.p)['total'],0)
        published=self.transition(draft,'published');self.assertEqual(self.service.community_feed(query=self.p)['total'],1)
        viewer=self.invite('viewer')
        with self.identity(viewer):
            report=self.service.report_community_publication(self.p,dict(version_id=draft['version_id'],reason='Synthetic reported concern'),actor=viewer['actor'],expected_revision=self.rev,idempotency_key='viewer-report');self.rev=report['revision']
            with self.assertRaises(ResourceError):self.service.moderate_community_publication(self.p,dict(version_id=draft['version_id'],report_id=report['id'],base_decision_id=None,action='restrict',reason='unauthorized'),actor=viewer['actor'],expected_revision=self.rev,idempotency_key='bad-mod')
        decision=self.write('moderate_community_publication',dict(version_id=draft['version_id'],report_id=report['id'],base_decision_id=None,action='restrict',reason='Synthetic restriction'))
        self.assertEqual(self.service.community_feed(query=self.p)['total'],0)
        with self.assertRaises(ResourceError):self.service.community_content(self.p,draft['version_id'])
        self.write('moderate_community_publication',dict(version_id=draft['version_id'],report_id=report['id'],base_decision_id=decision['id'],action='release',reason='Synthetic review reversed restriction'))
        detail=self.service.community_detail(self.p,draft['id']);self.assertEqual(detail['status'],'withdrawn');self.assertEqual(len(detail['events']),4)
        self.write('save_community_rule',dict(base_version_id=rule,title='Next rule',body='Next fixed rule'))
        self.assertEqual(self.service.community_snapshot(self.p)['reports'][0]['rule_id'],rule)
        unknown=self.original_media(rights='unknown');bad=self.publication(unknown,rule=rule)
        with self.assertRaises(ResourceError):self.transition(bad,'published')
    def test_distribution_unknown_queries_original_request_and_cancellation(self):
        publication=self.publication(self.original_media());self.transition(publication,'published');channel=self.channel()
        request=self.write('prepare_distribution',dict(version_id=publication['version_id'],channel_id=channel['id'],caption='Synthetic confirmed caption'))
        self.adapter.fail_submit=True;first=self.action(request,'execute','same-submit');self.assertEqual(first['status'],'unknown');self.assertEqual(len(self.adapter.submissions),1)
        with self.assertRaises(ResourceError):self.action(request,'cancel')
        with self.assertRaises(Conflict):self.write('prepare_distribution',dict(version_id=publication['version_id'],channel_id=channel['id'],caption='attempted duplicate'))
        second=self.action(request,'execute','same-submit');self.assertEqual(second['status'],'completed');self.assertEqual(len(self.adapter.submissions),1);self.assertEqual(len(self.adapter.queries),1)
        self.assertEqual([x['status'] for x in second['events']],['prepared','submitting','unknown','completed'])
        pub2=self.publication(self.original_media());self.transition(pub2,'published');r2=self.write('prepare_distribution',dict(version_id=pub2['version_id'],channel_id=channel['id'],caption='Cancel before submit'));self.assertEqual(self.action(r2,'cancel')['status'],'cancelled');self.assertEqual(len(self.adapter.submissions),1)
    def test_unconfigured_adapter_and_http_original_content(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        pub=self.publication(self.original_media());self.transition(pub,'published')
        channel=self.write('save_distribution_channel',dict(channel_key='missing',base_version_id=None,name='No credential',adapter='http-json-v1',endpoint='https://example.invalid',credential_env='VSC_NEVER_CONFIGURED_TEST_KEY',enabled=True))
        req=self.write('prepare_distribution',dict(version_id=pub['version_id'],channel_id=channel['id'],caption=''))
        with self.assertRaises(ResourceError):self.action(req,'execute')
        self.assertEqual(self.service.distribution_detail(self.p,req['id'])['status'],'prepared')
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver'],access_token='test',human_identity='test-human',background_enabled=False),service=self.service)
        with TestClient(app) as client:
            session=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json();headers={'X-CSRF-Token':session['csrf_token'],'Origin':'http://testserver'}
            response=client.get('/api/v1/community',headers=headers);self.assertEqual(response.status_code,200,response.text)
            response=client.get('/api/v1/projects/'+self.p+'/community-versions/'+pub['version_id']+'/content');self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.content.startswith(b'\x89PNG'))
            self.assertEqual(client.post('/api/v1/projects/'+self.p+'/community-rules',json={}).status_code,403)
    def test_cross_project_template_clones_typed_domains_and_rolls_back(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.spatial_scene import default_scene
        from vsc.post.edit_workspace import FORMAT as EDIT_FORMAT
        hierarchy=self.hierarchy();image=self.original_media();video=self.original_media('video')
        spatial=self.write('create_spatial_scene',dict(mode='blocking',episode_id=hierarchy['episode'],scene_id=hierarchy['scene'],title='Fixed staging',document=default_scene()))
        edit=self.write('save_edit_workspace',dict(episode_id=hierarchy['episode'],edit_revision=0,document=dict(format=EDIT_FORMAT,width=720,height=1280,fps=24,clips=[dict(id='clip',media_id=image,in_frame=0,out_frame=24,shot_id=hierarchy['shot'])],audio=[],captions=[])))
        tool=self.write('save_creative_tool_draft',dict(base_draft_id=None,document=dict(tool='extract_frame',episode_id=hierarchy['episode'],source_media_id=video,title='Fixed tool')))
        nodes=[dict(id='media',type='image',media_id=image),dict(id='spatial',type='director',domain_object_id=spatial['id'],domain_version_id=spatial['version_id']),dict(id='edit',type='edit',domain_object_id=edit['id'],domain_version_id=edit['edit_version_id']),dict(id='tool',type='processing',domain_object_id=tool['id'],domain_version_id=tool['id'])]
        canvas=self.write('create_creative_canvas',dict(title='Fixed template',episode_id=hierarchy['episode'],document=dict(nodes=nodes,edges=[])))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='Cross project template'))
        target=self.service.create_project({'name':'Target project'},actor='test-human')['id'];self.assign(target);rev=self.service.get_project(target)['revision'];payload=dict(source_project_id=self.p,template_id=template['id'],episode_id=None,title='Copied canvas')
        preview=self.service.preview_canvas_template_copy(target,payload);self.assertEqual(preview['domain_counts'],dict(spatial=1,tool=1,edit=1));self.assertEqual(len(preview['media']),2)
        result=self.service.copy_fixed_canvas_template(target,payload,actor='test-human',expected_revision=rev,idempotency_key='fixed-copy');replay=self.service.copy_fixed_canvas_template(target,payload,actor='test-human',expected_revision=rev,idempotency_key='fixed-copy');self.assertEqual(replay,result)
        copied=self.service.get_creative_canvas(target,result['id']);self.assertEqual(result['media_count'],2);self.assertEqual(result['domain_count'],3);self.assertFalse(result['provider_submitted'])
        self.assertNotEqual(copied['episode_id'],hierarchy['episode']);self.assertTrue(all(n['job_id'] is None for n in copied['document']['nodes']))
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(S.template_copy_domains).where(S.template_copy_domains.c.project_id==target)),3)
            fixed=c.execute(select(S.edit_revisions).where(S.edit_revisions.c.project_id==target)).mappings().one();self.assertNotIn('shot_id',fixed['document']['clips'][0]);self.assertNotEqual(fixed['document']['clips'][0]['media_id'],image)
            self.assertEqual(c.scalar(select(func.count()).select_from(S.generation_jobs).where(S.generation_jobs.c.project_id==target)),0)
        payload['episode_id']=copied['episode_id']
        with self.assertRaises(Conflict):self.service.copy_fixed_canvas_template(target,payload,actor='test-human',expected_revision=result['revision'],idempotency_key='no-overwrite')
        self.assertEqual(self.service.get_project(target)['revision'],result['revision'])

    def test_http_draft_keeps_published_version_until_explicit_replacement(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        media=self.original_media();rule=self.rule();viewer=self.invite('viewer')
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver'],access_token='test',human_identity='test-human',background_enabled=False),service=self.service)
        with TestClient(app) as client:
            session=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json();headers={'X-CSRF-Token':session['csrf_token'],'Origin':'http://testserver'};base='/api/v1/projects/'+self.p
            def post(path,payload,key=None):
                response=client.post(base+path,json=dict(payload=payload,expected_revision=self.rev,idempotency_key=key or uuid.uuid4().hex),headers=headers)
                self.assertEqual(response.status_code,200,response.text);result=response.json();self.rev=result['revision'];return result
            def state(row,status,key=None):return post('/community-publications/state',dict(version_id=row['version_id'],base_event_id=row['event_id'],status=status,reason='Explicit fixed version action'),key)
            content=dict(publication_id=None,base_version_id=None,title='HTTP live '+self.p,description='Published first',scope='workspace',rule_id=rule,media_id=media,template_id=None)
            first=post('/community-publications',content);live=state(first,'published')
            second=post('/community-publications',dict(content,publication_id=first['id'],base_version_id=first['version_id'],description='Unsaved-to-public second'))
            feed=client.get('/api/v1/community',params={'query':self.p},headers=headers).json();self.assertEqual(feed['items'][0]['version']['id'],first['version_id'])
            snapshot=client.get(base+'/community').json();self.assertEqual(snapshot['publications'][0]['version']['id'],second['version_id']);self.assertEqual(snapshot['publications'][0]['published_version']['version']['id'],first['version_id'])
            self.assertEqual(client.get(base+'/community-versions/'+first['version_id']+'/content').status_code,200)
            with self.identity(viewer):
                self.assertEqual(self.service.community_snapshot(self.p)['publications'][0]['version']['id'],first['version_id'])
                self.assertEqual(self.service.community_detail(self.p,first['id'])['version']['id'],first['version_id'])
                with self.assertRaises(ResourceError):self.service.community_detail(self.p,first['id'],second['version_id'])
            published=state(second,'published','publish-replacement');before=self.rev
            # The exact same request recovers its committed receipt and creates no extra withdrawal.
            replay=post('/community-publications/state',dict(version_id=second['version_id'],base_event_id=second['event_id'],status='published',reason='Explicit fixed version action'),'publish-replacement');self.assertEqual(replay,published);self.assertEqual(self.rev,before)
            old=client.get(base+'/community-publications/'+first['id'],params={'version_id':first['version_id']}).json();self.assertEqual(old['status'],'withdrawn');self.assertEqual(len(old['events']),3)
            self.assertEqual(client.get(base+'/community-versions/'+first['version_id']+'/content').status_code,409)
            state(published,'withdrawn');self.assertEqual(client.get('/api/v1/community',params={'query':self.p},headers=headers).json()['total'],0)
            for version in (first['version_id'],second['version_id']):self.assertEqual(client.get(base+'/community-versions/'+version+'/content').status_code,409)
            self.assertEqual(client.get(base+'/community-publications/'+first['id']).json()['history'][0]['id'],second['version_id'])

    def test_prepared_cancel_loses_race_to_submission_without_false_receipt(self):
        from unittest.mock import patch
        pub=self.publication(self.original_media());self.transition(pub,'published');channel=self.channel();request=self.write('prepare_distribution',dict(version_id=pub['version_id'],channel_id=channel['id'],caption='Concurrent cancellation'))
        repo=self.service._community();original_read=repo.distribution;started=[False]
        def read_then_submit(p,identifier):
            result=original_read(p,identifier)
            if not started[0]:
                started[0]=True
                repo.start_distribution(p,dict(request_id=identifier,request_sha256=request['request_sha256']),actor='test-human',expected_revision=self.rev,idempotency_key='concurrent-submit')
            return result
        with patch.object(self.service,'_community',return_value=repo),patch.object(repo,'distribution',side_effect=read_then_submit):
            with self.assertRaises(Conflict):self.action(request,'cancel')
        row=original_read(self.p,request['id']);self.assertEqual(row['status'],'submitting');self.assertEqual([e['status'] for e in row['events']],['prepared','submitting']);self.assertEqual(self.adapter.cancelled,[])

    def test_copied_rights_keep_expiry_and_follow_revocation(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        media=self.original_media();expiry=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        original=self.service.get_media(self.p,media)
        self.write('decide_rights',dict(media_id=media,outcome='licensed',scope={'purposes':['*']},expires_at=expiry,source_id=original['sources'][0]['source_id'],reason='Temporary synthetic license'))
        card=self.write('save_asset_card',dict(name='Licensed character',asset_kind='character',base_revision=0,forms=[dict(form_key='master',name='Fixed form',base_version_id=None,media_id=media)]))
        target=self.service.create_project({'name':'Rights target'},actor='test-human')['id'];self.assign(target)
        payload=dict(source_project_id=self.p,source_asset_id=card['id'],form_version_ids=[card['forms'][0]['version_id']])
        copied=self.service.copy_asset_card(target,payload,expected_revision=self.service.get_project(target)['revision'],idempotency_key='rights-copy',actor='test-human');target_media=self.service.get_asset_card(target,copied['id'])['forms'][0]['media_id']
        with self.engine.connect() as c:
            rights=self.store._latest(c,S.rights_decisions,target,'media_id',target_media);self.assertEqual(rights['expires_at'],datetime.fromisoformat(expiry))
        self.write('decide_rights',dict(media_id=media,outcome='restricted',scope={'purposes':[]},source_id=original['sources'][0]['source_id'],reason='Synthetic revoked source'))
        with self.engine.connect() as c:
            _,gaps=self.store._usable(c,target,target_media,'publish');self.assertIn('copy_source_rights_restricted',gaps)
        target_card=self.service.get_asset_card(target,copied['id'])
        with self.assertRaises(ResourceError):self.service.copy_asset_card(self.p,dict(source_project_id=target,source_asset_id=copied['id'],form_version_ids=[target_card['forms'][0]['version_id']]),expected_revision=self.rev,idempotency_key='revoked-recopy',actor='test-human')

    def test_template_copy_checks_cross_project_source_and_parent_lifecycle(self):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        hierarchy=self.hierarchy()
        canvas=self.write('create_creative_canvas',dict(episode_id=hierarchy['episode'],document={'nodes':[],'edges':[]}))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='Cross-project lifecycle'))
        target=self.service.create_project({'name':'Lifecycle target'},actor='test-human')['id'];self.assign(target)
        revision=self.service.get_project(target)['revision'];payload=dict(source_project_id=self.p,template_id=template['id'],episode_id=None,title='Fresh copy')
        for typ,identifier in [('canvas',canvas['id']),('object',hierarchy['episode']),('object',hierarchy['work']),('project',self.p)]:
            with self.subTest(source=typ,identifier=identifier):
                self.write('management_command',dict(operation='trash',target_type=typ,target_id=identifier,reason='Pause source'))
                for method in ('copy_canvas_template','copy_fixed_canvas_template'):
                    with self.subTest(method=method),self.assertRaises(ResourceError):
                        getattr(self.service,method)(target,payload,actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
                with self.assertRaises(ResourceError):self.service.preview_canvas_template_copy(target,payload)
                self.assertEqual(self.service.get_project(target)['revision'],revision)
                with self.engine.connect() as c:self.assertEqual(c.scalar(select(func.count()).select_from(S.creative_canvases).where(S.creative_canvases.c.project_id==target)),0)
                self.assertEqual(self.service.get_creative_canvas_version(self.p,canvas['version_id'])['id'],canvas['version_id'])
                self.write('management_command',dict(operation='restore',target_type=typ,target_id=identifier,reason='Resume source'))
        for method in ('copy_canvas_template','copy_fixed_canvas_template'):
            copied=getattr(self.service,method)(target,payload,actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex);revision=copied['revision']
            self.assertEqual(copied['source_version_id'],canvas['version_id'])
        # Preview must also honor a recycled destination, before any copy is proposed.
        result=self.service.management_command(target,dict(operation='trash',target_type='project',target_id=target,reason='Pause target'),actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
        with self.assertRaises(ResourceError):self.service.preview_canvas_template_copy(target,payload)
        self.assertEqual(self.service.get_project(target)['revision'],result['revision'])

    def test_template_copies_wait_for_source_recycle_transaction_and_recheck(self):
        from concurrent.futures import ThreadPoolExecutor,TimeoutError
        from threading import Event
        from unittest.mock import patch
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='Concurrent source'))
        targets=[]
        for method in ('copy_canvas_template','copy_fixed_canvas_template'):
            p=self.service.create_project({'name':method},actor='test-human')['id'];self.assign(p)
            targets.append((method,p,self.service.get_project(p)['revision']))
        locked,release=Event(),Event();original=self.store._management_protections;revision=self.rev
        def hold(c,p,ids,**kw):
            if p==self.p:
                locked.set()
                if not release.wait(10):raise RuntimeError('source recycle test timed out')
            return original(c,p,ids,**kw)
        def trash():
            with self.identity(self.owner):
                return self.service.management_command(self.p,dict(operation='trash',target_type='canvas',target_id=canvas['id'],reason='Concurrent source recycle'),actor='test-human',expected_revision=revision,idempotency_key=uuid.uuid4().hex)
        def copy(item):
            method,target,rev=item
            with self.identity(self.owner):
                return getattr(self.service,method)(target,dict(source_project_id=self.p,template_id=template['id'],episode_id=None,title='Must wait'),actor='test-human',expected_revision=rev,idempotency_key=uuid.uuid4().hex)
        with patch.object(self.store,'_management_protections',side_effect=hold),ThreadPoolExecutor(max_workers=3) as pool:
            recycling=pool.submit(trash);self.assertTrue(locked.wait(10));copies=[pool.submit(copy,item) for item in targets]
            try:
                for pending in copies:
                    with self.assertRaises(TimeoutError):pending.result(timeout=.2)
            finally:release.set()
            self.assertEqual(recycling.result(timeout=10)['state'],'trashed')
            for pending in copies:
                with self.assertRaises(ResourceError) as caught:pending.result(timeout=10)
                self.assertEqual(caught.exception.code,'object_recycled')
        for method,target,rev in targets:
            self.assertEqual(self.service.get_project(target)['revision'],rev)
            with self.engine.connect() as c:self.assertEqual(c.scalar(select(func.count()).select_from(S.creative_canvases).where(S.creative_canvases.c.project_id==target)),0)

    def test_template_copy_holds_source_lock_until_target_commit(self):
        from concurrent.futures import ThreadPoolExecutor,TimeoutError
        from threading import Event
        from unittest.mock import patch
        canvas=self.write('create_creative_canvas',dict(document={'nodes':[],'edges':[]}))
        template=self.write('publish_canvas_template',dict(canvas_id=canvas['id'],canvas_revision=1,title='Copy before recycle'))
        original=self.store._insert_canvas_version
        for method in ('copy_canvas_template','copy_fixed_canvas_template'):
            with self.subTest(method=method):
                target=self.service.create_project({'name':'Locked copy target'},actor='test-human')['id'];self.assign(target)
                target_revision=self.service.get_project(target)['revision'];source_revision=self.rev;locked,release=Event(),Event()
                def hold(c,project,*args,**kw):
                    if project['id']==target:
                        locked.set()
                        if not release.wait(10):raise RuntimeError('copy transaction test timed out')
                    return original(c,project,*args,**kw)
                def copy():
                    with self.identity(self.owner):return getattr(self.service,method)(target,dict(source_project_id=self.p,template_id=template['id'],episode_id=None,title='Fixed before recycle'),actor='test-human',expected_revision=target_revision,idempotency_key=uuid.uuid4().hex)
                def trash():
                    with self.identity(self.owner):return self.service.management_command(self.p,dict(operation='trash',target_type='canvas',target_id=canvas['id'],reason='Wait for copy'),actor='test-human',expected_revision=source_revision,idempotency_key=uuid.uuid4().hex)
                with patch.object(self.store,'_insert_canvas_version',side_effect=hold),ThreadPoolExecutor(max_workers=2) as pool:
                    copying=pool.submit(copy);self.assertTrue(locked.wait(10));recycling=pool.submit(trash)
                    try:
                        with self.assertRaises(TimeoutError):recycling.result(timeout=.2)
                    finally:release.set()
                    result=copying.result(timeout=10);trashed=recycling.result(timeout=10)
                self.assertEqual(result['source_version_id'],canvas['version_id']);self.assertEqual(trashed['state'],'trashed');self.rev=trashed['revision']
                self.assertEqual(self.service.get_creative_canvas(target,result['id'])['id'],result['id'])
                self.write('management_command',dict(operation='restore',target_type='canvas',target_id=canvas['id'],reason='Next independent race'))


class DistributionPortTests(unittest.TestCase):
    def test_configured_json_port_fixed_key_and_safe_unknown(self):
        import os,httpx
        from unittest.mock import patch
        from vsc.adapters.providers.distribution import HttpDistributionAdapter
        calls=[]
        def handle(request):
            calls.append(request);return httpx.Response(200,json={'status':'submitted','remote_id':'remote'}) if request.method=='POST' else httpx.Response(404)
        with patch.dict(os.environ,{'VSC_PORT_FIXTURE':'synthetic'}),httpx.Client(transport=httpx.MockTransport(handle)) as client:
            adapter=HttpDistributionAdapter(dict(endpoint='https://example.invalid',credential_env='VSC_PORT_FIXTURE'),client)
            self.assertEqual(adapter.submit({'request_key':'fixed'}).status,'submitted');self.assertEqual(adapter.query('fixed').status,'unknown')
        self.assertEqual(json.loads(calls[0].content)['request_key'],'fixed');self.assertTrue(str(calls[1].url).endswith('/submissions/by-key/fixed'))
    def test_http_query_errors_remain_recoverable_not_remote_failure(self):
        import os,httpx
        from unittest.mock import patch
        from vsc.adapters.providers.distribution import HttpDistributionAdapter,DistributionUnknown
        for status in (302,401,429,404,503):
            with self.subTest(http_status=status),patch.dict(os.environ,{'VSC_PORT_FIXTURE':'synthetic'}),httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status))) as client:
                adapter=HttpDistributionAdapter(dict(endpoint='https://example.invalid',credential_env='VSC_PORT_FIXTURE'),client)
                try:receipt=adapter.query('same-original-key')
                except DistributionUnknown:continue
                self.assertEqual(receipt.status,'unknown')
        with patch.dict(os.environ,{'VSC_PORT_FIXTURE':'synthetic'}),httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'status':'failed','error_code':'remote_rejected'}))) as client:
            adapter=HttpDistributionAdapter(dict(endpoint='https://example.invalid',credential_env='VSC_PORT_FIXTURE'),client)
            self.assertEqual(adapter.query('same-original-key').status,'failed')


class CommunityFrontendTests(unittest.TestCase):
    def test_scope_change_cancels_not_sent_report_and_isolates_copy_receipts(self):
        import shutil,subprocess
        from support.paths import ROOT
        if not shutil.which('node'):self.skipTest('Node required for deterministic event races')
        source=r'''
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{Document,Element}=require('./tests/support/fixtures/frontend/panel_dom.cjs');
const document=new Document('');document.head=document.createElement('head');document.body.append(document.head);globalThis.document=document;
const memory=new Map();globalThis.sessionStorage={getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:require('node:crypto').webcrypto});globalThis.Option=function(title,value){const n=document.createElement('option');n.textContent=title;n.value=value;return n;};
Object.defineProperty(Element.prototype,'isConnected',{get(){let n=this;while(n.parentElement)n=n.parentElement;return n===document.body;}});
Element.prototype.showModal=function(){this.open=true;};Element.prototype.close=function(){this.open=false;return this.dispatch('close');};
const module=await import(pathToFileURL('src/vsc/interfaces/web/static/community.js').href);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const root=document.createElement('section');document.body.append(root);
const button=(r,title)=>{const b=r.querySelectorAll('button').find(n=>n.textContent===title);assert.ok(b,title);return b;},field=(r,label)=>r.querySelectorAll('input').concat(r.querySelectorAll('select'),r.querySelectorAll('textarea')).find(n=>n.getAttribute('aria-label')===label);
const revisionRead=deferred(),requests=[],notices=[];let session={actor:'human',csrf:'csrf',projectId:'current',revision:1};
const published={id:'publication',created_by:'owner',version:{id:'version',title:'Other project work',version:1,media_id:'media',scope:'workspace'},status:'published',modality:'image',events:[{id:'event',status:'published',reason:'',created_at:'2026-11-01'}],rule:{title:'Rule',version:1,body:'Fixed rule'},history:[]};
const snapshot=()=>({revision:1,capabilities:['read'],identity_id:'viewer',publications:[],rules:[],channels:[],reports:[],distributions:[]});
const ctx={session:()=>session,notice:m=>notices.push(m),setRevision:()=>{},api:async(url,options)=>{requests.push({url,options});if(options?.method==='POST')return {revision:2};if(url==='/api/v1/projects/other/community')return revisionRead.promise;if(url.startsWith('/api/v1/community?'))return {items:[{...published,project_id:'other',project_name:'Other'}],projects:[],total:1,next_offset:null};return snapshot();}};
const ui=module.createCommunity(root,ctx);await ui.load({projectId:'current'});await button(root,'举报此版本').onclick();let dialog=root.querySelector('dialog');field(dialog,'举报事实与依据').value='Original report';await field(dialog,'举报事实与依据').oninput();const report=button(dialog,'提交举报').onclick();await Promise.resolve();
session={...session,projectId:'next'};await ui.load({projectId:'next'});revisionRead.resolve({revision:9});await report;assert.equal(requests.filter(x=>x.options?.method==='POST').length,0);assert.equal(notices.length,0);assert.equal([...memory.keys()].filter(k=>k.startsWith('vsc-community-pending:')).length,0);ui.suspend();
root.replaceChildren();const firstCopy=deferred(),secondCopy=deferred();let copyCount=0;const calls=[];
const copyCtx={session:()=>session,notice:m=>notices.push(m),api:async(url,options)=>{calls.push({url,options});if(url.endsWith('/tree'))return {nodes:[]};if(url.endsWith('/canvas-template-copy-preview'))return {source_version:1,node_count:1,media:[],domain_counts:{spatial:0,tool:0,edit:0},new_episode_count:0,revision:3};if(url.endsWith('/canvas-template-copies'))return ++copyCount===1?firstCopy.promise:secondCopy.promise;throw Error(url);}};
await module.openTemplateCopy(root,copyCtx,{id:'template',project_id:'source',title:'Source'},[{id:'A',name:'A',capabilities:['edit']},{id:'B',name:'B',capabilities:['edit']}]);dialog=root.querySelector('dialog');let target=field(dialog,'目标项目');
await button(dialog,'预览复制内容').onclick();const sent=button(dialog,'确认复制固定模板').onclick();await Promise.resolve();target.value='B';await target.onchange();field(dialog,'副本名称').value='Keep B title';await field(dialog,'副本名称').oninput();await button(dialog,'预览复制内容').onclick();assert.equal(button(dialog,'确认复制固定模板').disabled,false);
firstCopy.resolve({id:'copy-A'});await sent;assert.equal(button(dialog,'确认复制固定模板').disabled,false);assert.equal(dialog.querySelectorAll('a').length,0);assert.equal(field(dialog,'副本名称').value,'Keep B title');assert.equal(memory.has('vsc-template-copy:human:A:source:template'),false);
target.value='A';await target.onchange();await button(dialog,'预览复制内容').onclick();const failed=button(dialog,'确认复制固定模板').onclick();await Promise.resolve();target.value='B';await target.onchange();const pendingB={payload:{title:'B original'},expected_revision:3,idempotency_key:'B-fixed'};memory.set('vsc-template-copy:human:B:source:template',JSON.stringify(pendingB));secondCopy.reject(Object.assign(new Error('A conflict'),{status:409}));await failed;
assert.deepEqual(JSON.parse(memory.get('vsc-template-copy:human:B:source:template')),pendingB);assert.equal(field(dialog,'副本名称').value,'Keep B title');assert.ok(!dialog.textContent.includes('A conflict'));assert.equal(memory.has('vsc-template-copy:human:A:source:template'),false);
console.log('PASS real module event races; deterministic DOM fixture, not browser acceptance');
'''
        result=subprocess.run(['node','--input-type=module','-e',source],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
