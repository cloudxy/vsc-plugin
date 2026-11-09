"""Synthetic image bytes reach the original tool-free Canvas Agent envelope."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_agent import GrokBuildCanvasAgent, execute_agent, prepare_attachments


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plan():
    return dict(message='离线规划',questions=[],actions=[dict(kind='none',title='',text='',source_node_id='')])


class MemoryStorage:
    def __init__(self):
        self.objects={};self.reads=[]

    def read(self,key,sha):
        self.reads.append((key,sha))
        if key not in self.objects:raise ResourceError('受控字节不可读取','media_unavailable')
        raw=self.objects[key]
        if digest(raw)!=sha:raise ResourceError('受控字节摘要不符','media_unavailable')
        return raw


class MediaService:
    def __init__(self):
        self.storage=MemoryStorage();self.media={};self.lookups=[];self.verified=[]

    def add(self,index,modality='image',raw=None):
        identifier='media-'+str(index)
        if raw is None:
            out=io.BytesIO()
            Image.new('RGB',(16,12),(index%256,(index*13)%256,(index*31)%256)).save(out,format='PNG')
            raw=out.getvalue()
        sha=digest(raw);key='controlled-'+identifier;self.storage.objects[key]=raw
        self.media[identifier]=dict(id=identifier,project_id='project',modality=modality,sha256=sha,
            mime_type='image/png' if modality=='image' else 'video/mp4',name=identifier,
            locations=[dict(storage='local',available=True,object_key=key)])
        return dict(id='node-'+str(index),type=modality,media_id=identifier,
            params=dict(marketing_role='material',source_sha256=sha))

    def get_media(self,project,identifier):
        self.lookups.append((project,identifier))
        if identifier not in self.media:raise ResourceError('当前项目没有该媒体','not_found',404)
        return deepcopy(self.media[identifier])

    def _verify_media(self,project,identifier,expected_sha=None,snapshot=None):
        media=snapshot or self.get_media(project,identifier)
        self.verified.append((project,identifier))
        self.storage.read(media['locations'][0]['object_key'],expected_sha or media['sha256'])


class TurnStore:
    """In-memory claim seam only; does not stand in for PG transaction tests."""
    def __init__(self,turn):
        self.turn=deepcopy(turn);self.claims=0

    def claim_canvas_agent_turn(self,project,identifier):
        claimed=self.turn['status']=='queued'
        if claimed:self.turn['status']='running';self.claims+=1
        return dict(deepcopy(self.turn),claimed=claimed)

    def persist_canvas_agent_result(self,project,identifier,result,error):
        self.turn.update(plan=result,error=error,status='result_ready' if result else
            'submission_unknown' if error=='canvas_agent_submission_unknown' else 'failed')

    def get_canvas_agent_turn(self,project,identifier):
        return deepcopy(self.turn)

    def finish_canvas_agent_turn(self,project,payload,**kwargs):
        self.turn['status']='planned'


class CanvasMarketingReferenceTests(unittest.TestCase):
    def setUp(self):
        self.service=MediaService();self.calls=[]

    def turn(self,nodes):
        raw_prompt='\n  原需求：保留商品标签与空白。\r\n'
        method='固定方法正文\n'*1000+'METHOD-END 完整结尾'
        return dict(id='turn',project_id='project',message=raw_prompt,skill_id='vsc-assets',model_ids=[],
            attachments=[],referenced_nodes=[
                dict(id='marketing-brief',type='text',text=raw_prompt,text_excerpt=False,params=dict(marketing_role='brief')),
                dict(id='marketing-method',type='text',text=method,text_excerpt=False,
                    params=dict(marketing_role='method',method_sha256=digest(method.encode('utf-8')))),*nodes])

    def runner(self,command,**kwargs):
        self.calls.append(dict(command=command,blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text())))
        return SimpleNamespace(returncode=0,stdout=json.dumps(plan()))

    def generate(self,turn):
        prepared=prepare_attachments(self.service,'project',turn)
        result=GrokBuildCanvasAgent(executable='synthetic-unused',runner=self.runner).generate({},prepared,'固定Skill正文')
        blocks=self.calls[-1]['blocks'];text=blocks[0]['text']
        payload=json.loads(text[text.index('{"role_context"'):])
        return prepared,result,payload,blocks

    def test_one_eight_fifteen_images_reach_original_envelope_with_full_text_and_sha(self):
        for count in (1,8,15):
            with self.subTest(images=count):
                turn=self.turn([self.service.add(i) for i in range(count)]);original=deepcopy(turn)
                prepared,result,payload,blocks=self.generate(turn)
                image_blocks=[block for block in blocks if block['type']=='image']
                self.assertEqual(len(image_blocks),count)
                self.assertEqual(payload['input']['referenced_nodes'],original['referenced_nodes'])
                self.assertEqual(payload['input']['message'],original['message'])
                self.assertTrue(payload['input']['referenced_nodes'][1]['text'].endswith('METHOD-END 完整结尾'))
                self.assertEqual(turn,original)
                self.assertEqual(prepared['attachments'],[])
                for index,item in enumerate(payload['input']['reference_basis']):
                    self.assertEqual(item['node_id'],'node-'+str(index))
                    self.assertEqual(item['media_id'],'media-'+str(index))
                    self.assertEqual(item['sha256'],self.service.media[item['media_id']]['sha256'])
                    self.assertIn(item['sha256'],blocks[2*index+1]['text'])
                for block in image_blocks:
                    with Image.open(io.BytesIO(base64.b64decode(block['data']))) as image:
                        self.assertEqual(image.format,'JPEG');self.assertLessEqual(max(image.size),1024)
                self.assertEqual(result,plan())
                command=self.calls[-1]['command']
                self.assertEqual(command[command.index('--tools')+1],'')
                self.assertIn('--no-subagents',command);self.assertIn('--disable-web-search',command)

    def test_refs_do_not_use_attachment_slots_and_byte_aliases_are_deduplicated(self):
        nodes=[self.service.add(i) for i in range(15)]
        turn=self.turn(nodes)
        for index in range(15,23):
            node=self.service.add(index);media=self.service.media[node['media_id']]
            turn['attachments'].append(dict(id=media['id'],fixed_sha256=media['sha256']))
        prepared,_,_,blocks=self.generate(turn)
        self.assertEqual(len([b for b in blocks if b['type']=='image']),23)
        self.assertEqual(len(prepared['attachments']),8)
        self.assertEqual(len(prepared['reference_basis']),15)
        original=self.service.media[nodes[0]['media_id']]
        raw=self.service.storage.objects[original['locations'][0]['object_key']]
        alias=self.service.add(99,raw=raw)
        duplicate=self.turn([nodes[0],dict(nodes[0],id='same-media-node'),alias])
        duplicate['attachments']=[dict(id=original['id'],fixed_sha256=original['sha256'])]
        prepared,_,_,blocks=self.generate(duplicate)
        self.assertEqual(len([b for b in blocks if b['type']=='image']),1)
        self.assertEqual(len(prepared['reference_basis']),3)
        self.assertTrue(all(item['image_media_id']==original['id'] for item in prepared['reference_basis']))
        self.assertIn(('project',alias['media_id']),self.service.verified)

    def test_video_is_only_fixed_metadata_and_explicitly_unwatched(self):
        video=self.service.add(1,'video',b'not-decoded-video-placeholder')
        _,_,payload,blocks=self.generate(self.turn([video]))
        self.assertEqual(len(blocks),1)
        basis=payload['input']['reference_basis'][0]
        self.assertEqual(basis['sha256'],video['params']['source_sha256'])
        self.assertIn('未观看',basis['basis']);self.assertIn('未听取',basis['basis'])
        self.assertEqual(self.service.storage.reads,[])

    def test_bad_digest_image_scope_or_missing_bytes_never_call_host(self):
        cases=('changed_sha','bad_sha','bad_image','foreign_project','missing_media','wrong_type','missing_bytes','method_sha','excerpt')
        for case in cases:
            with self.subTest(case=case):
                self.service=MediaService();node=self.service.add(1);turn=self.turn([node])
                media=self.service.media[node['media_id']]
                if case=='changed_sha':node['params']['source_sha256']='0'*64
                elif case=='bad_sha':node['params']['source_sha256']='not-a-sha'
                elif case=='bad_image':
                    node=self.service.add(1,raw=b'not an image');turn=self.turn([node])
                elif case=='foreign_project':media['project_id']='elsewhere'
                elif case=='missing_media':node['media_id']='not-in-project'
                elif case=='wrong_type':media['modality']='video'
                elif case=='missing_bytes':self.service.storage.objects.clear()
                elif case=='method_sha':turn['referenced_nodes'][1]['params']['method_sha256']='0'*64
                elif case=='excerpt':turn['referenced_nodes'][1]['text_excerpt']=True
                # turn() retains its node arguments as the fixed input objects.
                with self.assertRaises(ResourceError):self.generate(turn)
                self.assertEqual(self.calls,[])

    def test_changed_raw_sha_and_decode_failure_have_explicit_errors(self):
        node=self.service.add(1);turn=self.turn([node])
        with patch.object(self.service,'_verify_media'),patch.object(self.service.storage,'read',return_value=b'changed bytes'):
            with self.assertRaises(ResourceError) as caught:prepare_attachments(self.service,'project',turn)
        self.assertEqual(caught.exception.code,'spatial_reference_changed')
        node=self.service.add(2,raw=b'fixed but undecodable')
        with self.assertRaises(ResourceError) as caught:prepare_attachments(self.service,'project',self.turn([node]))
        self.assertEqual(caught.exception.code,'spatial_reference_decode')
        self.assertEqual(self.calls,[])

    def test_encoded_context_budget_refuses_whole_call_without_dropping_images(self):
        turn=self.turn([self.service.add(i) for i in range(15)])
        expected=deepcopy(turn)
        with patch('vsc.production.canvas_agent.REFERENCE_PAYLOAD_MAX_BYTES',1024):
            with self.assertRaises(ResourceError) as caught:self.generate(turn)
        self.assertEqual(caught.exception.code,'canvas_reference_limit')
        self.assertIn('本机',str(caught.exception));self.assertEqual(turn,expected);self.assertEqual(self.calls,[])

    def test_original_claim_persists_preflight_failure_and_unknown_without_retry(self):
        from vsc.bootstrap import repository_root
        from vsc.production.role_materials import compile_role_materials
        skill=(repository_root()/'skills/vsc-assets/SKILL.md').read_bytes()
        manifest=compile_role_materials('asset-director','vsc-assets','vsc-assets')['manifest']
        for kind in ('bad_image','unknown'):
            with self.subTest(kind=kind):
                self.service=MediaService()
                node=self.service.add(1,raw=b'bad image') if kind=='bad_image' else self.service.add(1)
                turn=dict(self.turn([node]),status='queued',mode='manual',dispatch_id='dispatch',skill_sha256=digest(skill))
                self.service.store=TurnStore(turn)
                self.service.get_role_dispatch=lambda *args:dict(packet=dict(parent_brief=dict(content=json.dumps(dict(role_materials_manifest=manifest)))))
                calls=[]
                def runner(command,**kwargs):
                    calls.append(command)
                    raise subprocess.TimeoutExpired(command,120)
                backend=GrokBuildCanvasAgent(executable='synthetic-unused',runner=runner)
                self.service.canvas_agent_backend=backend
                with patch.object(backend,'available',return_value=True):
                    first=execute_agent(self.service,'project','turn');second=execute_agent(self.service,'project','turn')
                self.assertEqual(first,second);self.assertEqual(self.service.store.claims,1)
                self.assertEqual(first['status'],'failed' if kind=='bad_image' else 'submission_unknown')
                self.assertEqual(first['error'],'spatial_reference_decode' if kind=='bad_image' else 'canvas_agent_submission_unknown')
                self.assertEqual(len(calls),0 if kind=='bad_image' else 1)
