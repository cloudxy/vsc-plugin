"""Fixed case metadata reaches the original tool-free role transport only."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from vsc.assets.marketing_cases import case_spec_to_params
from vsc.assets.resource_service import ResourceError
from vsc.production.canvas_agent import GrokBuildCanvasAgent, prepare_attachments


# Golden 18-field protocol fixture shared with the backend; no runtime catalog
# read or dependency on a local /tmp file is needed by this test module.
FIXED_CASE = dict(
    schema='vsc.marketing-case/v1',id='skyproduction:approved_092da543e904e7ca',version=1,
    sha256='25dd8536d74c328802001d91cf1181d782ef288275c72369f4f511940605bd99',
    source_origin='https://api-v6.skyproduction.cn',template_key='approved_092da543e904e7ca',
    group_key='approved_092da543e904e7ca',category_name='品牌心智',category_label='品牌心智',
    group_name='屏幕里的复古时装广告',group_description='将时装广告嵌入电视播放画面，用片中片结构赋予品牌复古经典感。',
    video_name='屏幕里的复古时装广告',
    cover_url='https://static.skyproduction.cn/motioncomic/marketing-studio/approved-20261106/approved_092da543e904e7ca.mp4?x-oss-process=video/snapshot,t_0,f_jpg,w_360,m_fast',
    video_url='https://static.skyproduction.cn/motioncomic/marketing-studio/approved-20261106/approved_092da543e904e7ca.mp4',
    width=720,height=1280,
    evidence_id='ev_ed3d5933ac43c48a05edab5a180e992d887fbf67a112773ca5746bad07504288',
    evidence_body_sha256='b63f65822884093ca67a060293d775a88525d1bdc8d25d4ac48f7e1ebb165806')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class CanvasMarketingCaseTests(unittest.TestCase):
    def setUp(self):
        self.media={};self.objects={};self.prompts=[]
        self.storage=SimpleNamespace(read=Mock(side_effect=self.read))
        self.service=SimpleNamespace(storage=self.storage,get_media=Mock(side_effect=self.get_media),
            _verify_media=Mock(side_effect=lambda p,m,**kw:self.read(m,self.media[m]['sha256'])))

    def read(self,key,sha):
        raw=self.objects[key]
        if digest(raw)!=sha:raise ResourceError('固定字节摘要不符','media_unavailable')
        return raw

    def get_media(self,project,media_id):
        self.assertEqual(project,'project')
        return deepcopy(self.media[media_id])

    def image(self,index):
        out=io.BytesIO();Image.new('RGB',(12,9),(index*7,index*9,index*11)).save(out,format='PNG')
        raw=out.getvalue();identifier='image-'+str(index);sha=digest(raw);self.objects[identifier]=raw
        self.media[identifier]=dict(id=identifier,project_id='project',modality='image',sha256=sha,
            locations=[dict(storage='local',available=True,object_key=identifier)])
        return dict(id='material-'+str(index),type='image',media_id=identifier,
            params=dict(marketing_role='material',source_sha256=sha))

    def turn(self,with_case=True,images=0):
        prompt='\n  原始需求保持空白与商品文字。\r\n'
        method='完整固定方法，不截断。\n'*600+'METHOD-END'
        params=dict(marketing_role='brief',skill_id='vsc-assets',marketing_request_sha256='a'*64)
        if with_case:params.update(case_spec_to_params(FIXED_CASE))
        return dict(id='turn',skill_id='vsc-assets',message=prompt,model_ids=[],attachments=[],
            referenced_nodes=[dict(id='marketing-brief',type='text',text=prompt,text_excerpt=False,params=params),
                dict(id='marketing-method',type='text',text=method,text_excerpt=False,
                    params=dict(marketing_role='method',method_sha256=digest(method.encode('utf-8')))),
                *[self.image(i) for i in range(images)]])

    def runner(self,command,**kwargs):
        blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text(encoding='utf-8'))
        self.prompts.append((command,blocks))
        return SimpleNamespace(returncode=0,stdout=json.dumps(dict(message='离线建议',questions=[],
            actions=[dict(kind='none',title='',text='',source_node_id='')])))

    def generate(self,turn):
        prepared=prepare_attachments(self.service,'project',turn)
        GrokBuildCanvasAgent(executable='unused-synthetic',runner=self.runner).generate({},prepared,'固定Skill正文')
        command,blocks=self.prompts[-1];text=blocks[0]['text'];payload=json.loads(text[text.index('{"role_context"'):])
        return prepared,payload,blocks,command

    def test_complete_case_raw_method_and_fifteen_image_bytes_reach_original_prompt(self):
        turn=self.turn(images=15);original=deepcopy(turn)
        prepared,payload,blocks,command=self.generate(turn)
        source=payload['input']
        self.assertEqual(source['marketing_case'],FIXED_CASE);self.assertEqual(len(source['marketing_case']),18)
        self.assertEqual(source['message'],original['message'])
        self.assertEqual(source['referenced_nodes'],original['referenced_nodes'])
        self.assertEqual(len(source['referenced_nodes']),17)
        self.assertEqual(prepared['attachments'],[])
        self.assertTrue(source['referenced_nodes'][1]['text'].endswith('METHOD-END'))
        self.assertEqual(len([b for b in blocks if b['type']=='image']),15)
        for block in blocks:
            if block['type']=='image':
                with Image.open(io.BytesIO(base64.b64decode(block['data']))) as image:
                    self.assertEqual(image.format,'JPEG')
        self.assertTrue(all(item['sha256']==self.media[item['media_id']]['sha256'] for item in prepared['reference_basis']))
        self.assertIn('外部目录元数据',source['case_basis']);self.assertIn('私有方法未知',source['case_basis'])
        self.assertIn('未观看',source['case_basis']);self.assertIn('未听取',source['case_basis'])
        self.assertEqual(turn,original)
        self.assertEqual(command[command.index('--tools')+1],'')
        self.assertIn('--no-subagents',command);self.assertIn('--disable-web-search',command)

    def test_fixed_case_does_not_read_removed_unavailable_or_upgraded_catalog(self):
        for state in ('removed','unavailable','upgraded'):
            with self.subTest(state=state):
                # Any call would fail this test, even a call whose result is ignored.
                with patch('vsc.assets.marketing_cases.load_catalog',side_effect=AssertionError(state)) as load, \
                        patch('vsc.assets.marketing_cases.resolve_case',side_effect=AssertionError(state)) as resolve:
                    prepared,payload,_,_=self.generate(self.turn())
                load.assert_not_called();resolve.assert_not_called()
                self.assertEqual(prepared['marketing_case'],FIXED_CASE)
                self.assertEqual(payload['input']['marketing_case']['sha256'],FIXED_CASE['sha256'])

    def test_partial_unknown_changed_or_ambiguous_case_params_fail_before_host(self):
        for change in ('missing','unknown','sha','description','version_type','schema','duplicate_brief'):
            with self.subTest(change=change):
                turn=self.turn();params=turn['referenced_nodes'][0]['params']
                if change=='missing':del params['marketing_case_evidence_id']
                elif change=='unknown':params['marketing_case_other']='unrecognized'
                elif change=='sha':params['marketing_case_sha256']='0'*64
                elif change=='description':params['marketing_case_group_description']='未经固定的改文'
                elif change=='version_type':params['marketing_case_version']=True
                elif change=='schema':params['marketing_case_schema']='other'
                else:turn['referenced_nodes'].append(dict(deepcopy(turn['referenced_nodes'][0]),id='another-brief'))
                with self.assertRaises(ResourceError) as caught:self.generate(turn)
                self.assertEqual(caught.exception.code,'canvas_marketing_case_reference' if change=='duplicate_brief' else 'invalid_marketing_case')
                self.assertEqual(self.prompts,[])

    def test_legacy_without_case_keeps_raw_method_refs_and_eight_attachments(self):
        turn=self.turn(with_case=False)
        for i in range(8):
            node=self.image(i);media=self.media[node['media_id']]
            turn['attachments'].append(dict(id=media['id'],fixed_sha256=media['sha256']))
        original=deepcopy(turn)
        with patch('vsc.assets.marketing_cases.load_catalog',side_effect=AssertionError('legacy must not read catalog')) as load:
            prepared,payload,blocks,_=self.generate(turn)
        load.assert_not_called();self.assertIsNone(prepared['marketing_case'])
        self.assertEqual(payload['input']['message'],original['message'])
        self.assertEqual(payload['input']['referenced_nodes'],original['referenced_nodes'])
        self.assertEqual(prepared['attachments'],original['attachments'])
        self.assertEqual(len([b for b in blocks if b['type']=='image']),8)
        self.assertEqual(turn,original)

    def test_case_urls_remain_metadata_only_and_cannot_override_fixed_basis(self):
        turn=self.turn();turn.update(marketing_case=dict(forged=True),case_basis='视频已经看完')
        prepared,payload,blocks,_=self.generate(turn)
        self.assertEqual(prepared['marketing_case'],FIXED_CASE)
        self.assertEqual(payload['input']['marketing_case']['video_url'],FIXED_CASE['video_url'])
        self.assertIn('未观看',payload['input']['case_basis']);self.assertIn('URL仅作元数据',prepared['case_basis'])
        self.assertEqual(prepared['_media_blocks'],[]);self.assertEqual(len(blocks),1)
        self.assertEqual(prepared['reference_basis'],[]);self.assertEqual(prepared['attachments'],[])
        self.service.get_media.assert_not_called();self.service._verify_media.assert_not_called()
        self.storage.read.assert_not_called()
