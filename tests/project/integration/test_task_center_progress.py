"""Batch progress projects the original children, including mixed outcomes."""
from copy import deepcopy
import unittest
import uuid
import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.text_tools import COMMON,DEFAULTS
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS,'requires isolated PostgreSQL')
class TaskCenterProgressTests(ResourceStoreFixture,unittest.TestCase):
    def test_batch_children_keep_original_success_failure_and_deep_links(self):
        class Host:
            name='isolated-progress-host'
            def available(self):return True
            def generate(self,tool,action,document,references):
                if document['source_text'].startswith('失败'):raise ResourceError('synthetic failure','text_host_failed')
                return {'analysis':'第一行固定内容的分析','category':'短剧','channel':'家庭','card_start_line':1,'card_end_line':2}
        self.service.text_tool_host=Host();units=[]
        for ordinal,name in enumerate(('成功片段','失败片段')):
            saved=self.write('save_text_tool',dict(tool='scoring',group_key='task-progress',unit_key=uuid.uuid4().hex,
                title=name,ordinal=ordinal,episode_id=None,unit_id=None,base_version_id=None,
                document={**deepcopy(COMMON),**deepcopy(DEFAULTS['scoring']),'source_text':name+'\n第二行'}))
            units.append(saved['unit_id'])
        batch=self.write('create_text_batch',dict(tool='scoring',action='analyze',unit_ids=units,auto_accept=False))
        before=self.service.get_task_center(self.p,kind='text_batch')['items'][0]
        self.assertEqual(before['progress']['pending'],2);self.assertEqual(before['progress']['terminal'],0)
        for _ in range(3):self.write('process_text_batch',{'batch_id':batch['id']})
        original=self.service.get_text_batch(self.p,batch['id'])
        row=self.service.get_task_center(self.p,kind='text_batch')['items'][0]
        self.assertEqual(row['id'],batch['id']);self.assertEqual(row['progress']['completed'],1)
        self.assertEqual(row['progress']['failed'],1);self.assertEqual(row['progress']['terminal'],2)
        self.assertEqual([item['attempt_id'] for item in row['children']],[item['attempt_id'] for item in original['items']])
        self.assertEqual([item['title'] for item in row['children']],['成功片段','失败片段'])
        self.assertTrue(all('tool=scoring' in item['href'] and 'task_target='+item['unit_id'] in item['href'] for item in row['children']))
        self.assertEqual(self.service.get_task_center(self.p,kind='text_batch',offset=1)['items'],[])
        other=self.service.create_project({'name':'另一隔离范围'},actor='test-human')['id']
        self.assertEqual(self.service.get_task_center(other,kind='text_batch')['total'],0)
