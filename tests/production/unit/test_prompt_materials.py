"""Captured prompt transport and service recovery; no real host or DB."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vsc.assets.prompt_assist import PromptAssistServiceMixin
from vsc.production.prompt_assist import GrokBuildPromptAssistant
from vsc.production.role_materials import compile_role_materials


class PromptMaterialsTests(unittest.TestCase):
    def fixture(self,created=True):
        bundle=compile_role_materials('director','vsc-direct','prompt-optimize')
        source={'operation':'optimize','reference_images':[],'dispatch_id':'dispatch','skill_sha256':bundle['materials'][1]['sha256']}
        packet={'role':{'id':'director'},'parent_brief':{'content':json.dumps({'role_materials_manifest':bundle['manifest']})}}
        class Store:
            def __init__(self):self.error=None;self.result=None
            def start_prompt_assist(self,p,payload,claim,**kw):claim['created']=created;return {'id':'request'}
            def get_prompt_assist(self,p,request):return {'id':request,'request':source,'error':self.error,'result':self.result}
            def finish_prompt_assist(self,p,request,result,error,**kw):self.result,self.error=result,error
        class Service(PromptAssistServiceMixin):
            def _validate_write(self,*args,**kw):pass
            def authorize_access(self,*args):pass
            def get_role_dispatch(self,*args):return {'packet':packet}
        service=Service();service.store=Store();calls=[]
        class Backend:
            def available(self):return True
            def generate(self,packet,source,skill,blocks):
                calls.append((packet,source,skill,blocks));return {'text':'fixed result','explanation':'fixed explanation'}
        service.prompt_assistant=Backend()
        request=dict(draft_version_id='draft',draft_sha256='a'*64,operation='optimize',target_language='en',include_references=False)
        return service,request,source,packet,bundle,calls

    def test_first_created_request_passes_fixed_materials_without_mutating_original(self):
        service,request,source,packet,bundle,calls=self.fixture()
        result=service.start_prompt_assist('project',request,actor='actor')
        self.assertEqual(result['result']['text'],'fixed result');self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['_materials'],bundle);self.assertNotIn('_materials',source)
        self.assertEqual(calls[0][2],bundle['materials'][1]['text'])

    def test_replay_of_legacy_request_does_not_compile_or_open_host(self):
        service,request,source,packet,bundle,calls=self.fixture(created=False)
        packet['parent_brief']=None
        with patch('vsc.production.role_materials.compile_role_materials') as compile_materials:
            result=service.start_prompt_assist('project',request,actor='actor')
            service.get_prompt_assist('project','request')
        compile_materials.assert_not_called();self.assertEqual(calls,[])
        self.assertIsNone(packet['parent_brief']);self.assertIsNone(result['result'])

    def test_missing_or_changed_manifest_fails_before_backend(self):
        for defect in ('missing','malformed','changed'):
            with self.subTest(defect=defect):
                service,request,source,packet,bundle,calls=self.fixture()
                if defect=='missing':packet['parent_brief']=None
                elif defect=='malformed':packet['parent_brief']['content']='not-json'
                else:
                    manifest=copy.deepcopy(bundle['manifest']);manifest['sha256']='0'*64
                    packet['parent_brief']['content']=json.dumps({'role_materials_manifest':manifest})
                result=service.start_prompt_assist('project',request,actor='actor')
                self.assertEqual(calls,[])
                self.assertEqual(result['error'],'role_materials_changed' if defect=='changed' else 'role_materials_missing')

    def test_transport_contains_actual_materials_once_and_preserves_source(self):
        service,request,source,packet,bundle,calls=self.fixture()
        source=dict(source,_materials=bundle);seen=[]
        def runner(command,**kw):
            blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text())
            text=blocks[0]['text'];seen.append(json.loads(text[text.index('{"role_context"'):]))
            self.assertEqual(command[command.index('--tools')+1],'');self.assertEqual(command[command.index('--max-turns')+1],'1')
            return SimpleNamespace(returncode=0,stdout='{"text":"suggestion","explanation":"fixed input"}')
        result=GrokBuildPromptAssistant(runner=runner).generate(packet,source,bundle['materials'][1]['text'],[])
        self.assertEqual(result['text'],'suggestion');self.assertEqual(seen[0]['role_materials'],bundle)
        self.assertNotIn('_materials',seen[0]['input']);self.assertIn('_materials',source)
        self.assertNotIn('text',seen[0]['skill'])

