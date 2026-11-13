"""Original memory proposal/human-session decisions reach the next planner."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS,TEST_URL,ResourceStoreFixture
from vsc.assets.resource_service import ResourceError
from vsc.kernel.catalog import role_cards
from vsc.project.role_runtime import bind_packet


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class IntelligentMemoryTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy()
        self.flow=self.write('create_intelligent_workflow',dict(episode_id=self.objects['episode'],title='记忆消费者夹具',
            route='storyboard',script_text='合成角色在同一场景内观察固定道具。'))['id']

    def propose(self,episode,content,role='asset-director'):
        source=self.artifact('memory-source-'+uuid.uuid4().hex,kind='synthetic-evidence',objects=[episode])
        source_sha=self.service.get_artifact_version(self.p,source)['sha256']
        packet=bind_packet(dict(format='vsc.role-context/v2',context_id='memory-'+uuid.uuid4().hex,project={'project_id':self.p},
            revision=self.rev,scope=episode,role=role_cards()[role],task='资产锚点连续性复盘',
            inputs=[{'id':source,'sha256':source_sha}],source_refs=[],approved_memories=[],approved_capabilities=[],pilot_capabilities=[],rules=['固定来源']),
            host='isolated-test',actor='agent:'+role+':'+uuid.uuid4().hex)
        self.write('create_role_dispatch',{'packet':packet})
        dispatch=packet['dispatch'];identity=dict(dispatch_id=dispatch['id'],instance_id=dispatch['instance_id'],role_id=role,context_sha256=packet['context_sha256'])
        self.write('consume_role_dispatch',dict(identity,packet=packet),actor=dispatch['actor'])
        result=dict(role_id=role,role_sha256=dispatch['role_sha256'],context_id=packet['context_id'],context_sha256=packet['context_sha256'],
            dispatch_id=dispatch['id'],instance_id=dispatch['instance_id'],result_refs=[],memory_proposals=[dict(kind='lesson',content=content,
                tags=['资产','锚点'],sources=[dict(kind='artifact',id=source,sha256=source_sha)],association_complete=True)])
        returned=self.write('return_role_dispatch',dict(identity,result=result,return_key='memory-proposal'),actor=dispatch['actor'])
        proposal=returned['memory_proposals'][0]
        self.assertEqual(proposal['status'],'draft')
        return proposal['version_id']

    def human_decide(self,version_id,outcome='approved'):
        # Use the actual session/CSRF/confirmed HTTP path, not a human-looking label.
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        item=next(row for row in self.service.list_role_memories(self.p)['items'] if row['version_id']==version_id)
        payload=dict(version_id=version_id,content_sha256=item['content_sha256'],outcome=outcome,reason='隔离测试中的显式人工会话确认')
        with self.assertRaises(ResourceError) as denied:self.write('decide_role_memory',payload,actor='human:label-only')
        self.assertEqual(denied.exception.code,'human_confirmation_required')
        with tempfile.TemporaryDirectory() as directory:
            app=create_app({'projects_root':directory,'access_token':'isolated-memory-token','human_identity':'test-human','background_enabled':False},service=self.service)
            with TestClient(app,base_url='http://127.0.0.1') as client:
                origin={'Origin':'http://127.0.0.1:8765'}
                login=client.post('/api/v1/session',json={'token':'isolated-memory-token'},headers=origin)
                self.assertEqual(login.status_code,200,login.text)
                headers=dict(origin,**{'X-CSRF-Token':login.json()['csrf_token']})
                body=dict(payload=payload,confirmed=True,expected_revision=self.rev,idempotency_key='human-memory-'+uuid.uuid4().hex)
                endpoint='/api/v1/projects/'+self.p+'/role-memory-decisions'
                unconfirmed=client.post(endpoint,json=dict(body,confirmed=False),headers=headers)
                self.assertEqual(unconfirmed.status_code,422,unconfirmed.text)
                response=client.post(endpoint,json=body,headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['status'],outcome)
                self.rev=response.json()['revision']

    def task(self):
        current=self.service.get_intelligent_workflow(self.p,self.flow)
        return self.write('create_intelligent_task',dict(workflow_id=self.flow,base_version_id=current['version']['id'],stage='assets',message='资产锚点连续性：固定道具颜色与位置，读取已确认的方法'))

    def run_host(self,task):
        from vsc.production.intelligent_production import GrokBuildIntelligentPlanner
        self.service.intelligent_planner=GrokBuildIntelligentPlanner();captured=[]
        def runner(command,**kw):
            blocks=json.loads(Path(command[command.index('--prompt-file')+1]).read_text())
            text=blocks[0]['text'];captured.append(json.loads(text[text.index('{"role_context"'):]))
            return SimpleNamespace(returncode=0,stdout=json.dumps(dict(message='读取固定经验后的工程建议',questions=['请确认本次参考的明确用途'],assets=[],units=[])))
        with patch.object(GrokBuildIntelligentPlanner,'available',return_value=True),patch('vsc.production.role_planner._run_bounded',side_effect=runner):
            result=self.service.execute_intelligent_task(self.p,task['id'])
        self.rev=self.service.get_project(self.p)['revision']
        return result,captured

    def test_only_human_approved_same_role_episode_memory_reaches_fixed_packet_and_host(self):
        accepted=self.propose(self.objects['episode'],'资产锚点连续性：固定道具颜色与位置。已确认的方法甲。')
        self.human_decide(accepted)
        draft=self.propose(self.objects['episode'],'资产锚点连续性：未批准的草稿乙。')
        other=self.write('create_object',dict(kind='episode',parent_id=self.objects['work'],display_code='MEMORY-E2',ordinal=1))['id']
        cross=self.propose(other,'资产锚点连续性：另一分集的方法丙。');self.human_decide(cross)
        wrong_role=self.propose(self.objects['episode'],'资产锚点连续性：导演私有方法丁。',role='director');self.human_decide(wrong_role)
        task=self.task();packet=self.service.get_role_dispatch(self.p,task['dispatch_id'])['packet']
        self.assertEqual([row['version_id'] for row in packet['approved_memories']],[accepted])
        self.assertEqual(packet['retrieval']['budget_chars'],2200)
        self.assertLessEqual(packet['retrieval']['used_chars'],2200)
        result,captured=self.run_host(task)
        self.assertIn(result['status'],{'planned','needs_input'});self.assertEqual(len(captured),1)
        self.assertEqual(captured[0]['role_context']['approved_memories'],packet['approved_memories'])
        serialized=json.dumps(captured[0],ensure_ascii=False)
        self.assertIn('已确认的方法甲',serialized)
        for excluded in ('未批准的草稿乙','另一分集的方法丙','导演私有方法丁'):self.assertNotIn(excluded,serialized)
        self.assertNotIn(draft,[row['version_id'] for row in packet['approved_memories']])

    def test_retired_after_dispatch_fails_before_host_and_new_task_excludes_it(self):
        accepted=self.propose(self.objects['episode'],'资产锚点连续性：固定道具颜色与位置。可撤回方法。')
        self.human_decide(accepted);task=self.task()
        packet=self.service.get_role_dispatch(self.p,task['dispatch_id'])['packet']
        self.assertEqual([row['version_id'] for row in packet['approved_memories']],[accepted])
        self.human_decide(accepted,'retired')
        result,captured=self.run_host(task)
        self.assertEqual(captured,[]);self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'context_memory_invalid')
        replay,captured=self.run_host(task)
        self.assertEqual(captured,[]);self.assertEqual(replay['id'],result['id'])
        new_task=self.task();new_packet=self.service.get_role_dispatch(self.p,new_task['dispatch_id'])['packet']
        self.assertEqual(new_packet['approved_memories'],[])

