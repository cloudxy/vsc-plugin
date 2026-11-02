"""Queued novel tasks freeze bounded professional methods in original authorities."""
from copy import deepcopy
import json,unittest,uuid
from unittest.mock import patch
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.text_tools import COMMON,DEFAULTS
from vsc.assets.resource_service import ResourceError


class NovelHost:
    name='synthetic-novel-role-host/v1'
    def __init__(self):self.calls=[]
    def available(self):return True
    def generate(self,tool,action,document,references,*,materials=None):
        self.calls.append(dict(tool=tool,action=action,document=deepcopy(document),references=deepcopy(references),materials=deepcopy(materials)))
        return {action:'固定专业方法下的合成建议'}


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class TextRoleMaterialsTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.service.text_tool_host=NovelHost()
    def save(self,tool='novel',**changes):
        return self.write('save_text_tool',dict(tool=tool,group_key='material-test',unit_key=uuid.uuid4().hex,title='固定原文单元',ordinal=0,episode_id=None,base_version_id=None,document={**deepcopy(COMMON),**deepcopy(DEFAULTS[tool]),'source_text':'第1章 起点\n出门。',**changes}))
    def test_direct_attempt_pins_manifest_once_and_sends_actual_materials(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        saved=self.save();request=dict(unit_id=saved['unit_id'],input_version_id=saved['id'],action='body')
        first=self.write('run_text_tool',request,idempotency_key='same-novel-attempt');second=self.write('run_text_tool',request,idempotency_key='same-novel-attempt')
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['status'],'completed');host=self.service.text_tool_host;self.assertEqual(len(host.calls),1)
        run=self.service.get_text_tool_attempt(self.p,first['id']);packet=self.service.get_artifact_version(self.p,run['materials_artifact_id'])
        self.assertEqual(run['role_materials_manifest'],host.calls[0]['materials']['manifest']);self.assertTrue(host.calls[0]['materials']['materials']);self.assertEqual(host.calls[0]['references'],[])
        self.assertEqual(packet['artifact_type'],'text-tool-role-materials')
        with self.engine.connect() as conn:
            links=list(conn.execute(select(S.text_tool_attempt_inputs.c.version_id).where(S.text_tool_attempt_inputs.c.project_id==self.p,S.text_tool_attempt_inputs.c.attempt_id==run['id'])).scalars())
            self.assertEqual(links,[packet['id']]);self.assertEqual(self.store._one(conn,S.text_tool_attempts,self.p,run['id'])['input_count'],1)
        self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['body'],'')

    def test_queued_body_and_qa_share_queue_time_packet_and_original_input_dependencies(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        baseline=self.save(synopsis='离家',core_setting='小镇',target_episodes=1)
        plan=self.write('create_novel_plan',dict(unit_id=baseline['unit_id'],version_id=baseline['id'],episodes=[dict(title='第一集',chapter_start=1,chapter_end=1,outline='出门')]))
        child=self.service.get_text_tool(self.p,plan['episodes'][0]['unit_id'])
        created=self.write('create_text_batch',dict(tool='novel',action='body',unit_ids=[child['id']],auto_accept=True,overwrite=False,qa_unit_id=baseline['unit_id']))
        batch=self.service.get_text_batch(self.p,created['id']);packet=self.service.get_artifact_version(self.p,batch['materials_artifact_id']);doc=json.loads(packet['document'])
        self.assertEqual(set(doc['actions']),{'body','qa_notes'});self.assertEqual(self.service.text_tool_host.calls,[])
        with self.engine.connect() as conn:
            deps=set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(S.artifact_dependencies.c.project_id==self.p,S.artifact_dependencies.c.artifact_id==packet['id'])).scalars())
            self.assertEqual(deps,{baseline['id'],child['current_version_id']})
        for _ in range(2):done=self.write('process_text_batch',dict(batch_id=batch['id']))
        self.assertEqual(done['status'],'completed');self.assertEqual(len(self.service.text_tool_host.calls),2)
        for item,call in zip(done['items'],self.service.text_tool_host.calls):
            run=self.service.get_text_tool_attempt(self.p,item['attempt_id']);self.assertEqual(run['materials_artifact_id'],packet['id']);self.assertEqual(call['materials']['manifest'],doc['actions'][item['action']])
            self.assertFalse(any(r['id']==packet['id'] for r in call['references']))
        self.assertEqual(self.service.get_text_tool(self.p,child['id'])['document']['body'],'固定专业方法下的合成建议')

    def test_queue_manifest_drift_fails_before_host_and_old_other_tools_remain_compatible(self):
        from sqlalchemy import insert
        from vsc.adapters.persistence.postgres import schema as S
        saved=self.save(body='保留人工正文');created=self.write('create_text_batch',dict(tool='novel',action='body',unit_ids=[saved['unit_id']],auto_accept=True,overwrite=True))
        batch=self.service.get_text_batch(self.p,created['id']);packet=json.loads(self.service.get_artifact_version(self.p,batch['materials_artifact_id'])['document'])
        def changed(role,skill,task,**kw):
            self.assertEqual(kw['expected_manifest'],packet['actions']['body']);raise ResourceError('fixed material changed','role_materials_changed')
        with patch('vsc.production.role_materials.compile_role_materials',side_effect=changed):failed=self.write('process_text_batch',dict(batch_id=batch['id']))
        self.assertEqual(failed['items'][0]['status'],'failed');self.assertEqual(failed['items'][0]['error_code'],'role_materials_changed');self.assertEqual(self.service.text_tool_host.calls,[])
        self.assertEqual(self.service.get_text_tool(self.p,saved['unit_id'])['document']['body'],'保留人工正文')
        run=self.service.get_text_tool_attempt(self.p,failed['items'][0]['attempt_id']);self.assertEqual(run['status'],'failed')
        # Existing no-manifest tasks retain their original recovery identity.
        legacy=self.save(body='旧人工稿');identifier=str(uuid.uuid4())
        with self.engine.begin() as conn:conn.execute(insert(S.text_tool_attempts).values(project_id=self.p,id=identifier,unit_id=legacy['unit_id'],input_version_id=legacy['id'],action='body',backend='legacy-host',status='submission_unknown',created_by='test-human'))
        old=self.write('run_text_tool',dict(unit_id=legacy['unit_id'],input_version_id=legacy['id'],action='body',new_attempt=True));self.assertEqual(old['id'],identifier);self.assertNotIn('role_materials_manifest',old)
        class LegacyTranslationHost:
            name='four-argument-host'
            def available(self):return True
            def generate(self,tool,action,document,references):return {'body':'legacy translation result'}
        self.service.text_tool_host=LegacyTranslationHost();translation=self.save('translation',target_language='English')
        result=self.write('run_text_tool',dict(unit_id=translation['unit_id'],input_version_id=translation['id'],action='translate'));self.assertEqual(result['status'],'completed');self.assertNotIn('materials_artifact_id',result)
