"""Direct copy through original service/API and isolated PostgreSQL transactions."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import secrets
import tempfile
import unittest
import uuid
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture, HAS_DB_DEPS, TEST_URL
from vsc.assets.access_control import Principal, set_principal, reset_principal
from vsc.assets.resource_service import ResourceError, Conflict


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS, 'isolated PostgreSQL required')
class DirectCanvasCopyTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service.storage = LocalStorage(self.temp.name)
        self.owner = self.service.ensure_local_access('test-human')
        token = set_principal(Principal(**self.owner)); self.addCleanup(reset_principal, token)
        self.assign(self.p)
        self.rev = self.service.get_project(self.p)['revision']

    def command(self, action, payload):
        return self.service.access_command(action, payload,
            expected_revision=self.service.access_snapshot()['access_revision'],
            idempotency_key=uuid.uuid4().hex, actor='test-human')

    def assign(self, p):
        preview = self.service.access_migration_preview(p, self.owner['workspace_id'])
        self.command('assign-project', dict(project_id=p, workspace_id=self.owner['workspace_id'], preview_sha256=preview['sha256']))

    @contextmanager
    def identity(self, binding):
        token = set_principal(Principal(**binding))
        try: yield
        finally: reset_principal(token)

    def invite(self, p, role, identity=None):
        secret = secrets.token_urlsafe(32)
        self.command('invitation', dict(scope='project', scope_id=p, role=role, secret=secret,
            expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        if identity:
            with self.identity(identity):
                return self.service.accept_access_invitation(dict(invitation_secret=secret,credential_secret=secrets.token_urlsafe(32),display_name='Direct copy member',use_current_identity=True))
        return self.service.accept_access_invitation(dict(invitation_secret=secret,
            credential_secret=secrets.token_urlsafe(32), display_name='Direct copy '+role))

    def write_at(self, p, method, payload, **kw):
        result = getattr(self.service, method)(p, payload, expected_revision=self.service.get_project(p)['revision'],
            idempotency_key=kw.pop('idempotency_key', uuid.uuid4().hex), actor=kw.pop('actor','test-human'), **kw)
        if p == self.p: self.rev = result['revision']
        return result

    def target(self):
        p = self.service.create_project(dict(name='Direct copy target'), actor='test-human')['id']
        self.assign(p)
        work = self.write_at(p, 'create_object', dict(kind='work', display_code='WK', ordinal=0))['id']
        ep = self.write_at(p, 'create_object', dict(kind='episode', parent_id=work, display_code='EP', ordinal=0))['id']
        return p, ep

    def original_media(self, modality='image'):
        from support.fixtures.resources import png_bytes
        data = png_bytes() if modality=='image' else ('fixed '+modality).encode()
        sha = hashlib.sha256(data).hexdigest(); Path(self.temp.name,sha+'.bin').write_bytes(data)
        return self.write('register_media', dict(name='Fixed '+modality, modality=modality,
            sha256=sha,size_bytes=len(data),mime_type={'image':'image/png','video':'video/mp4','audio':'audio/wav'}[modality],
            duration_ms=5000 if modality!='image' else None,storage='local',object_key=sha+'.bin',rights='owned',
            source={'kind':'fixture','content':'Synthetic evidence'}))['id']

    def canvas(self, nodes=None, episode_id=None, edges=None):
        saved = self.write('create_creative_canvas', dict(title='Fixed canvas',episode_id=episode_id,
            document=dict(nodes=nodes or [dict(id='text',type='text',text='Fixed text')],edges=edges or [],
                viewport=dict(x=36,y=-42,zoom=.75))))
        return self.service.get_creative_canvas(self.p,saved['id'])

    def payload(self, canvas, episode):
        return dict(source_project_id=canvas['project_id'],source_canvas_id=canvas['id'],
            source_version_id=canvas['version_id'],source_sha256=canvas['sha256'],episode_id=episode,title='Copied canvas')

    def copy(self, p, payload, key=None, revision=None, actor='test-human'):
        return self.service.copy_direct_canvas(p,payload,actor=actor,
            expected_revision=self.service.get_project(p)['revision'] if revision is None else revision,
            idempotency_key=key or uuid.uuid4().hex)

    def counts(self,p):
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as c:
            tables=(S.media_items,S.creative_canvases,S.creative_canvas_versions,S.spatial_scenes,S.edit_workspaces,
                S.artifact_versions,S.canvas_direct_copies,S.canvas_direct_copy_media,S.canvas_direct_copy_domains,
                S.command_receipts,S.generation_jobs,S.canvas_templates)
            return {t.name:c.scalar(select(func.count()).select_from(t).where(t.c.project_id==p)) for t in tables}

    def test_complete_domains_new_ids_same_bytes_and_receipt(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        from vsc.assets.spatial_scene import default_scene
        from vsc.post.edit_workspace import FORMAT
        o=self.hierarchy(); image=self.original_media(); video=self.original_media('video'); audio=self.original_media('audio')
        spatial_body=default_scene();spatial_body['objects'].append(dict(id='ref',kind='reference',media_id=image))
        spatial=self.write('create_spatial_scene',dict(mode='blocking',episode_id=o['episode'],scene_id=o['scene'],title='Staging',document=spatial_body))
        edit=self.write('save_edit_workspace',dict(episode_id=o['episode'],edit_revision=0,document=dict(format=FORMAT,width=720,height=1280,fps=24,
            clips=[dict(id='clip',media_id=image,in_frame=2,out_frame=26,shot_id=o['shot'])],
            audio=[dict(id='audio',media_id=audio,in_frame=0,out_frame=20,at_frame=2,volume=.5)],
            captions=[dict(start_frame=0,end_frame=12,text='Fixed caption')])) )
        tool=self.write('save_creative_tool_draft',dict(base_draft_id=None,document=dict(tool='extract_frame',episode_id=o['episode'],source_media_id=video,title='Tool')))
        nodes=[dict(id='prompt',type='text',text='Fixed prompt',group='group',x=-20,y=80),
            dict(id='image',type='image',media_id=image,params={'seed':17},x=280,y=80),
            dict(id='again',type='image',media_id=image,x=280,y=400),
            dict(id='spatial',type='director',domain_object_id=spatial['id'],domain_version_id=spatial['version_id']),
            dict(id='edit',type='edit',domain_object_id=edit['id'],domain_version_id=edit['edit_version_id']),
            dict(id='tool',type='processing',domain_object_id=tool['id'],domain_version_id=tool['id'])]
        original=self.canvas(nodes,o['episode'],[dict(id='edge',source='prompt',target='image',port='prompt')]); p,ep=self.target()
        payload=self.payload(original,ep); before=self.counts(p); revision=self.service.get_project(p)['revision']
        preview=self.service.preview_direct_canvas_copy(p,payload);self.assertEqual((preview['media_count'],preview['domain_count']),(3,3))
        with patch.object(self.store,'_insert_canvas_version',side_effect=ResourceError('Synthetic failure after domains')),self.assertRaises(ResourceError):
            self.copy(p,payload,'complete-rollback',revision)
        self.assertEqual(self.counts(p),before)
        self.assertFalse(self.service.get_operation_receipt(p,'complete-rollback','test-human')['found'])
        result=self.copy(p,payload,'complete-copy',revision);self.assertEqual(result,self.copy(p,payload,'complete-copy',revision))
        self.assertEqual(result['revision'],revision+1);self.assertEqual(result['canvas_revision'],1);self.assertFalse(result['provider_submitted'])
        copied=self.service.get_creative_canvas(p,result['id']);self.assertEqual(copied['episode_id'],ep)
        self.assertEqual(copied['document']['viewport'],original['document']['viewport'])
        old_nodes,new_nodes=original['document']['nodes'],copied['document']['nodes']
        for old,new in zip(old_nodes,new_nodes):
            self.assertNotEqual(old['id'],new['id']);self.assertIsNone(new['job_id'])
            for key in ('type','title','text','params','group','x','y'):self.assertEqual(old[key],new[key])
        self.assertEqual(new_nodes[1]['media_id'],new_nodes[2]['media_id']);self.assertNotEqual(new_nodes[1]['media_id'],image)
        edge=copied['document']['edges'][0];self.assertEqual((edge['source'],edge['target']),(new_nodes[0]['id'],new_nodes[1]['id']));self.assertNotEqual(edge['id'],'edge')
        with self.engine.connect() as c:
            mappings=c.execute(select(S.canvas_direct_copy_media).where(S.canvas_direct_copy_media.c.copy_id==result['copy_id'])).mappings().all()
            self.assertEqual(len(mappings),3)
            for m in mappings:
                self.assertEqual(self.store._media(c,self.p,m['source_media_id'])['blob_id'],self.store._media(c,p,m['target_media_id'])['blob_id'])
            fixed=c.execute(select(S.edit_revisions).where(S.edit_revisions.c.project_id==p)).mappings().one()
            self.assertNotIn('shot_id',fixed['document']['clips'][0]);self.assertNotEqual(fixed['document']['clips'][0]['id'],'clip')
            self.assertEqual(fixed['document']['audio'][0]['at_frame'],2)
            body=self.store._one(c,S.artifact_versions,p,new_nodes[-1]['domain_version_id'])['document']
            import json
            body=json.loads(bytes(body));self.assertFalse(body['generated']);self.assertEqual(body['input']['episode_id'],ep)
            self.assertEqual(body['input']['script_line_ids'],[])
        after=self.counts(p);self.assertEqual(after['canvas_templates'],before['canvas_templates']);self.assertEqual(after['generation_jobs'],before['generation_jobs'])
        self.assertEqual(self.service.get_creative_canvas(self.p,original['id'])['sha256'],original['sha256'])
        with self.assertRaises(Conflict):self.copy(p,dict(payload,title='Changed'),'complete-copy')
        with self.assertRaisesRegex(ResourceError,'已有剪辑稿'):self.copy(p,payload)
        self.assertEqual(self.counts(p),after)

    def test_same_project_new_episode_and_fixed_old_version(self):
        o=self.hierarchy();media=self.original_media();original=self.canvas([dict(id='image',type='image',media_id=media)],o['episode'])
        ep=self.write('create_object',dict(kind='episode',parent_id=o['work'],ordinal=1,display_code='EP2'))['id']
        self.write('save_creative_canvas',dict(canvas_id=original['id'],canvas_revision=1,title='New head',document=dict(nodes=[],edges=[])))
        result=self.copy(self.p,self.payload(original,ep));copied=self.service.get_creative_canvas(self.p,result['id'])
        self.assertEqual(len(copied['document']['nodes']),1);self.assertNotEqual(copied['document']['nodes'][0]['media_id'],media)
        self.assertEqual(result['source_version_id'],original['version_id'])
        with self.assertRaisesRegex(ResourceError,'同集'):self.copy(self.p,self.payload(original,o['episode']))

    def test_bad_identity_sha_revision_bytes_and_atomic_failure(self):
        from vsc.adapters.persistence.postgres.canvas_copy import FixedCanvasClone
        image=self.original_media();original=self.canvas([dict(id='image',type='image',media_id=image)]);other=self.canvas();p,ep=self.target();payload=self.payload(original,ep);before=self.counts(p)
        invalid=[dict(payload,source_canvas_id=other['id']),dict(payload,source_sha256='0'*64),dict(payload,episode_id=str(uuid.uuid4()))]
        for value in invalid:
            with self.subTest(payload=value),self.assertRaises(ResourceError):self.copy(p,value)
            self.assertEqual(self.counts(p),before)
        with self.assertRaises(Conflict):self.copy(p,payload,revision=0)
        clone=FixedCanvasClone.clone_plan
        def fail_after_clone(*args,**kw):
            clone(*args,**kw);raise ResourceError('Synthetic failure after domain writes')
        with patch.object(FixedCanvasClone,'clone_plan',fail_after_clone),self.assertRaisesRegex(ResourceError,'Synthetic failure'):
            self.copy(p,payload,'rollback-intent')
        self.assertEqual(self.counts(p),before)
        self.assertFalse(self.service.get_operation_receipt(p,'rollback-intent','test-human')['found'])
        media=self.service.get_media(self.p,image);path=Path(self.temp.name,media['locations'][0]['object_key']);path.write_bytes(b'wrong bytes')
        with self.assertRaises(ResourceError):self.copy(p,payload)
        self.assertEqual(self.counts(p),before)

    def test_receipt_recovers_after_source_acl_rights_and_bytes_change(self):
        image=self.original_media();original=self.canvas([dict(id='image',type='image',media_id=image)]);p,ep=self.target();payload=self.payload(original,ep)
        result=self.copy(p,payload,'lost-response');self.write('decide_rights',dict(media_id=image,outcome='restricted',reason='Synthetic revocation',scope={'purposes':[]}))
        media=self.service.get_media(self.p,image);Path(self.temp.name,media['locations'][0]['object_key']).write_bytes(b'gone')
        original_require=self.store._access_require
        def revoke(c,project,*args,**kwargs):
            if project==self.p:raise ResourceError('source revoked','access_denied',403)
            return original_require(c,project,*args,**kwargs)
        with patch.object(self.store,'_access_require',side_effect=revoke):
            self.assertEqual(self.copy(p,payload,'lost-response',0),result)
            with self.assertRaises(ResourceError):self.copy(p,payload,'new-intent')
        self.assertEqual(self.service.get_operation_receipt(p,'lost-response','test-human')['response'],result)

    def test_http_copy_preview_and_viewer_denial(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        original=self.canvas();p,ep=self.target();payload=self.payload(original,ep)
        app=create_app(dict(projects_root=self.temp.name,allowed_hosts=['testserver'],allowed_origins=['http://testserver'],access_token='test',human_identity='test-human',background_enabled=False),service=self.service)
        with TestClient(app) as client:
            session=client.post('/api/v1/session',json={'token':'test'},headers={'Origin':'http://testserver'}).json()
            headers={'X-CSRF-Token':session['csrf_token'],'Origin':'http://testserver'};base='/api/v1/projects/'+p+'/canvas-copies'
            body=dict(payload=payload,expected_revision=self.service.get_project(p)['revision'],idempotency_key='http-copy')
            response=client.post(base+'/preview',json=dict(payload=payload),headers=headers);self.assertEqual(response.status_code,200,response.text)
            response=client.post(base,json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);result=response.json()
            self.assertEqual(client.post(base,json=body,headers=headers).json(),result)
            fetched=client.get('/api/v1/projects/'+p+'/creative-canvases/'+result['id']).json();self.assertEqual(fetched['episode_id'],ep)
            self.assertEqual(client.post(base,json=body).status_code,403)
        viewer=self.invite(p,'viewer')
        with self.identity(viewer),self.assertRaises(ResourceError):self.copy(p,payload,actor=viewer['actor'])
        for principal in (Principal(**dict(self.owner,share_id=str(uuid.uuid4()))),Principal(**dict(self.owner,api_key_id=str(uuid.uuid4())))):
            token=set_principal(principal)
            try:
                with self.assertRaisesRegex(ResourceError,'项目会话'):self.copy(p,payload)
            finally:reset_principal(token)

    def test_source_viewer_target_editor_and_source_read_denial(self):
        original=self.canvas();p,ep=self.target();payload=self.payload(original,ep)
        viewer=self.invite(self.p,'viewer');self.invite(p,'editor',viewer)
        with self.identity(viewer):result=self.copy(p,payload,'member-copy',actor=viewer['actor'])
        self.assertEqual(result['source_version_id'],original['version_id'])
        self.command('member',dict(scope='project',scope_id=self.p,identity_id=viewer['identity_id'],role='viewer',active=False))
        with self.identity(viewer):
            self.assertEqual(self.copy(p,payload,'member-copy',0,viewer['actor']),result)
            with self.assertRaises(ResourceError):self.copy(p,payload,actor=viewer['actor'])
        self.command('member',dict(scope='project',scope_id=p,identity_id=viewer['identity_id'],role='editor',active=False))
        with self.identity(viewer),self.assertRaises(ResourceError):self.copy(p,payload,'member-copy',0,viewer['actor'])
        other=self.invite(p,'editor')
        with self.identity(other),self.assertRaises(ResourceError):self.copy(p,payload,actor=other['actor'])

    def test_live_rights_follow_direct_copy_chain(self):
        from vsc.adapters.persistence.postgres.copy_lineage import copy_media_gaps,source_projects_for_copy
        image=self.original_media();original=self.canvas([dict(id='image',type='image',media_id=image)]);p,ep=self.target()
        first=self.copy(p,self.payload(original,ep));fixed=self.service.get_creative_canvas(p,first['id']);q,qe=self.target()
        second=self.copy(q,self.payload(fixed,qe));mid=self.service.get_creative_canvas(q,second['id'])['document']['nodes'][0]['media_id']
        source=self.service.get_media(q,mid)
        derived=self.write_at(q,'register_media',dict(name='Local derived output',modality='image',sha256=source['sha256'],
            size_bytes=source['size_bytes'],mime_type=source['mime_type'],storage='local',object_key=source['locations'][0]['object_key'],
            rights='owned',source={'kind':'fixture','content':'Synthetic output registration'}))['id']
        self.write_at(q,'create_media_operation',dict(operation_type='fixture-transform',recipe_version='1',tool='fixture',tool_version='1',
            inputs=[dict(media_id=mid)],outputs=[dict(media_id=derived)]))
        self.write('decide_rights',dict(media_id=image,outcome='restricted',reason='Synthetic origin revocation',scope={'purposes':[]}))
        with self.engine.connect() as c:
            self.assertIn('copy_source_rights_restricted',copy_media_gaps(self.store,c,q,mid,'video_clip'))
            self.assertIn('copy_source_rights_restricted',self.store._usable(c,q,derived,'video_clip')[1])
            self.assertIn(self.p,source_projects_for_copy(c,q));self.assertIn(p,source_projects_for_copy(c,q))
        r,re=self.target()
        with self.assertRaises(ResourceError):self.copy(r,self.payload(fixed,re))

    def test_multiple_domain_episodes_and_edit_versions_reject_before_write(self):
        from vsc.assets.spatial_scene import default_scene
        from vsc.post.edit_workspace import FORMAT
        o=self.hierarchy();ep2=self.write('create_object',dict(kind='episode',parent_id=o['work'],ordinal=1,display_code='EP2'))['id']
        a=self.write('create_spatial_scene',dict(mode='previs',episode_id=o['episode'],title='First',document=default_scene()))
        b=self.write('create_spatial_scene',dict(mode='previs',episode_id=ep2,title='Second',document=default_scene()))
        fixed=self.canvas([dict(id='a',type='spatial',domain_object_id=a['id'],domain_version_id=a['version_id']),dict(id='b',type='spatial',domain_object_id=b['id'],domain_version_id=b['version_id'])])
        p,ep=self.target();before=self.counts(p)
        with self.assertRaisesRegex(ResourceError,'多个分集'):self.copy(p,self.payload(fixed,ep))
        image=self.original_media();doc=dict(format=FORMAT,width=720,height=1280,fps=24,clips=[dict(id='clip',media_id=image,in_frame=0,out_frame=24)],audio=[],captions=[])
        e1=self.write('save_edit_workspace',dict(episode_id=o['episode'],edit_revision=0,document=doc));e2=self.write('save_edit_workspace',dict(episode_id=o['episode'],edit_revision=1,document=doc))
        fixed=self.canvas([dict(id='a',type='edit',domain_object_id=e1['id'],domain_version_id=e1['edit_version_id']),dict(id='b',type='edit',domain_object_id=e2['id'],domain_version_id=e2['edit_version_id'])])
        with self.assertRaisesRegex(ResourceError,'多个固定剪辑'):self.copy(p,self.payload(fixed,ep))
        self.assertEqual(self.counts(p),before)

    def test_recycled_source_domain_and_target_ancestors_block_new_copy(self):
        from vsc.assets.spatial_scene import default_scene
        o=self.hierarchy();domain=self.write('create_spatial_scene',dict(mode='previs',episode_id=o['episode'],title='Domain',document=default_scene()))
        original=self.canvas([dict(id='domain',type='spatial',domain_object_id=domain['id'],domain_version_id=domain['version_id'])])
        p,ep=self.target();payload=self.payload(original,ep)
        before=self.counts(p)
        for kind,identifier in [('object',o['episode']),('object',o['work']),('canvas',original['id']),('project',self.p)]:
            with self.subTest(source_kind=kind):
                self.write_at(self.p,'management_command',dict(operation='trash',target_type=kind,target_id=identifier,reason='Synthetic source recycle'))
                with self.assertRaises(ResourceError):self.copy(p,payload)
                self.assertEqual(self.counts(p),before)
                self.write_at(self.p,'management_command',dict(operation='restore',target_type=kind,target_id=identifier,reason='Synthetic source restore'))
        target_work=next(row['id'] for row in self.service.get_project_tree(p)['nodes'] if row['kind']=='work')
        for kind,identifier in [('object',ep),('object',target_work),('project',p)]:
            with self.subTest(target_kind=kind):
                self.write_at(p,'management_command',dict(operation='trash',target_type=kind,target_id=identifier,reason='Synthetic target recycle'))
                state=self.counts(p)
                with self.assertRaises(ResourceError):self.copy(p,payload)
                self.assertEqual(self.counts(p),state)
                self.write_at(p,'management_command',dict(operation='restore',target_type=kind,target_id=identifier,reason='Synthetic target restore'))
        result=self.copy(p,payload,'before-recycle')
        self.write_at(self.p,'management_command',dict(operation='trash',target_type='project',target_id=self.p,reason='Synthetic after commit'))
        self.assertEqual(self.copy(p,payload,'before-recycle',0),result)

    def test_reciprocal_project_copy_uses_sorted_locks(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        original=self.canvas();p,ep=self.target()
        other=self.write_at(p,'create_creative_canvas',dict(title='Other source',episode_id=ep,document=dict(nodes=[dict(id='t',type='text',text='Other')],edges=[])))
        other=self.service.get_creative_canvas(p,other['id'])
        o=self.hierarchy();barrier=Barrier(2)
        jobs=[(p,self.payload(original,ep)),(self.p,self.payload(other,o['episode']))]
        frozen=[(target,payload,self.service.get_project(target)['revision']) for target,payload in jobs]
        def run(item):
            target,payload,revision=item
            with self.identity(self.owner):
                barrier.wait(timeout=5)
                return self.copy(target,payload,revision=revision)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run,item) for item in frozen]
            results=[future.result(timeout=20) for future in futures]
        self.assertEqual({r['project_id'] for r in results},{p,self.p})
        for result in results:self.assertEqual(result['canvas_revision'],1)

    def test_selected_job_output_kept_and_unselected_results_rejected(self):
        from sqlalchemy import select,insert,update
        from vsc.adapters.persistence.postgres import schema as S
        # Existing production fixture creates only local synthetic task facts.
        # Byte verification is covered separately with controlled local storage.
        self.service.storage=None
        self.seed_generation_timeline_render()
        with self.engine.connect() as c:
            job=c.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p)).mappings().one()
            output=c.scalar(select(S.job_outputs.c.media_id).where(S.job_outputs.c.project_id==self.p,S.job_outputs.c.job_id==job['id']))
        second=self.media('Another output',modality='video')
        with self.engine.begin() as c:c.execute(insert(S.job_outputs).values(project_id=self.p,id=str(uuid.uuid4()),job_id=job['id'],media_id=second,asset_type='video'))
        selected=self.canvas([dict(id='video',type='video',job_id=job['id'],media_id=output)])
        unselected=self.canvas([dict(id='video',type='video',job_id=job['id'])]);p,ep=self.target()
        with self.assertRaisesRegex(ResourceError,'放回节点'):self.copy(p,self.payload(unselected,ep))
        result=self.copy(p,self.payload(selected,ep));fixed=self.service.get_creative_canvas(p,result['id'])
        self.assertEqual(result['media_count'],1);self.assertIsNone(fixed['document']['nodes'][0]['job_id'])
        self.assertEqual(self.service.get_media(p,fixed['document']['nodes'][0]['media_id'])['sha256'],self.service.get_media(self.p,output)['sha256'])
        # Status is a mutable task fact; selected fixed media remains copyable.
        with self.engine.begin() as c:c.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id==self.p,S.generation_jobs.c.id==job['id']).values(status='submission_unknown'))
        self.assertEqual(self.copy(p,self.payload(selected,ep))['media_count'],1)
        with self.assertRaisesRegex(ResourceError,'尚未结束'):self.copy(p,self.payload(unselected,ep))

    def test_tool_input_media_cannot_escape_locked_dependency_checks(self):
        import json
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        o=self.hierarchy();video=self.original_media('video')
        draft=self.write('save_creative_tool_draft',dict(base_draft_id=None,document=dict(tool='extract_frame',episode_id=o['episode'],source_media_id=video,title='Fixed tool')))
        with self.engine.connect() as c:body=json.loads(bytes(self.store._one(c,S.artifact_versions,self.p,draft['id'])['document']))
        p,ep=self.target();before=self.counts(p)
        wrong=deepcopy(body);wrong['media'][0]['sha256']='0'*64
        artifact=self.write('create_artifact',dict(artifact_key='wrong-pin',artifact_type='creative-tool-draft',document=wrong,object_ids=[o['episode']]))
        canvas=self.canvas([dict(id='tool',type='processing',domain_object_id=artifact['id'],domain_version_id=artifact['id'])])
        with self.assertRaisesRegex(ResourceError,'媒体摘要'):self.copy(p,self.payload(canvas,ep))
        unpinned=deepcopy(body);unpinned['media']=[]
        artifact=self.write('create_artifact',dict(artifact_key='missing-pin',artifact_type='creative-tool-draft',document=unpinned,object_ids=[o['episode']]))
        canvas=self.canvas([dict(id='tool',type='processing',domain_object_id=artifact['id'],domain_version_id=artifact['id'])])
        self.write('decide_rights',dict(media_id=video,outcome='restricted',scope={'purposes':[]},reason='Synthetic restricted input slot'))
        with self.assertRaisesRegex(ResourceError,'当前不可复制'):self.copy(p,self.payload(canvas,ep))
        self.assertEqual(self.counts(p),before)
