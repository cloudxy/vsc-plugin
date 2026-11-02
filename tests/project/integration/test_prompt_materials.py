"""Original immutable prompt dispatch manifest and replay in isolated PostgreSQL."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS,TEST_URL,ResourceStoreFixture
from vsc.bootstrap import repository_root
from vsc.production.role_materials import compile_role_materials


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL,'requires isolated PostgreSQL')
class PromptMaterialsTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.objects=self.hierarchy();self.calls=[]
        calls=self.calls
        class Backend:
            def available(self):return True
            def generate(self,packet,source,skill,blocks):
                calls.append((packet,source,skill,blocks));return {'text':'fixed suggestion','explanation':'material consumer'}
        self.service.prompt_assistant=Backend()
        draft=self.write('save_classic_draft',dict(base_draft_id=None,document=dict(shot_id=self.objects['shot'],mode='text',references=[],prompt='固定提示')))
        self.request=dict(draft_version_id=draft['id'],draft_sha256=draft['sha256'],operation='optimize',target_language='en',include_references=False)

    def test_original_dispatch_manifest_and_same_request_replay_use_one_host_call(self):
        result=self.write('start_prompt_assist',self.request,idempotency_key='prompt-material-original')
        self.assertEqual(result['status'],'completed');self.assertEqual(len(self.calls),1)
        packet=self.service.get_role_dispatch(self.p,result['request']['dispatch_id'])['packet']
        fixed=json.loads(packet['parent_brief']['content'])
        bundle=compile_role_materials('director','vsc-direct','prompt-optimize',expected_manifest=fixed['role_materials_manifest'])
        self.assertEqual(self.calls[0][1]['_materials'],bundle)
        self.assertEqual(fixed['draft_sha256'],self.request['draft_sha256'])
        replay=self.service.start_prompt_assist(self.p,self.request,expected_revision=0,idempotency_key='prompt-material-original',actor='test-human')
        self.assertEqual(replay['id'],result['id']);self.assertEqual(len(self.calls),1)
        self.assertNotIn('_materials',replay['request'])

    def test_reference_drift_after_original_dispatch_blocks_host_and_replay_does_not_resubmit(self):
        bundle=compile_role_materials('director','vsc-direct','prompt-optimize')
        with tempfile.TemporaryDirectory(prefix='vsc-prompt-materials-') as directory:
            root=Path(directory)
            for row in bundle['materials']:
                target=root/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(repository_root()/row['path'],target)
            ref=next(row for row in bundle['materials'] if row['kind']=='reference')
            original_get=self.service.get_role_dispatch
            def changed(*args,**kw):
                result=original_get(*args,**kw)
                target=root/ref['path'];target.write_text(target.read_text()+'\nchanged reference')
                return result
            with patch('vsc.production.role_materials.repository_root',return_value=root),patch.object(self.service,'get_role_dispatch',side_effect=changed):
                result=self.write('start_prompt_assist',self.request,idempotency_key='prompt-material-drift')
                replay=self.service.start_prompt_assist(self.p,self.request,expected_revision=0,idempotency_key='prompt-material-drift',actor='test-human')
            self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'role_materials_changed')
            self.assertEqual(result['id'],replay['id']);self.assertEqual(self.calls,[])

    def test_legacy_request_get_and_replay_do_not_backfill_manifest_or_call_host(self):
        from vsc.project.role_runtime import bind_packet
        def legacy(packet,**kw):return bind_packet(dict(packet,parent_brief=None),**kw)
        claim={'created':False}
        with patch('vsc.project.role_runtime.bind_packet',side_effect=legacy):
            original=self.store.start_prompt_assist(self.p,self.request,claim=claim,expected_revision=self.rev,
                idempotency_key='prompt-legacy',actor='test-human')
        self.assertTrue(claim['created'])
        with patch('vsc.production.role_materials.compile_role_materials') as compile_materials:
            read=self.service.get_prompt_assist(self.p,original['id'])
            replay=self.service.start_prompt_assist(self.p,self.request,expected_revision=0,idempotency_key='prompt-legacy',actor='test-human')
        compile_materials.assert_not_called();self.assertEqual(self.calls,[])
        self.assertEqual(read['status'],'submission_unknown');self.assertEqual(replay['id'],read['id'])
        packet=self.service.get_role_dispatch(self.p,read['request']['dispatch_id'])['packet']
        self.assertIsNone(packet['parent_brief'])

