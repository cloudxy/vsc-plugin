"""Real original queues, decoded media and first-cut continuation; no paid host."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from support.fixtures.intelligent_batch import IntelligentBatchSetup
from vsc.assets.resource_service import ResourceError


class OfflineVideo:
    def __init__(self, data):
        self.data, self.submits = data, 0

    def submit(self, request):
        from vsc.production.providers import JobHandle
        self.submits += 1
        return JobHandle('offline', 'video', None, {'offline_fixture': True})

    def parse_result(self, raw):
        from vsc.production.providers import GeneratedAsset
        return [GeneratedAsset('video', inline_bytes=self.data)]

    def poll(self, handle):
        from vsc.production.providers import JobStatus
        return JobStatus('succeeded', raw={'offline_fixture': True})


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, 'requires isolated PostgreSQL')
class EpisodeFirstCutTests(IntelligentBatchSetup, ResourceStoreFixture, unittest.TestCase):
    def unit(self, key, shot):
        row = super().unit(key, shot)
        row['professional']['sound_route'] = 'native'
        return row

    def setUp(self):
        self.project = self.service.create_project(dict(name='离线工作消费闭环',
            profile_snapshot=dict(profile_id='vsc.synthetic',version='1',stages=[],contract_policy='production-v2')),actor='test-human')
        self.p, self.rev = self.project['id'], 0
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.adapters.persistence.postgres.episode_work import EpisodeWorkRepository
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-episode-first-cut-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service.storage = LocalStorage(self.root/'storage')
        self.repo = EpisodeWorkRepository(self.store)
        self.objects = self.hierarchy()
        self.write('configure_budget',dict(limits={'remote_jobs':20,'video_seconds':100},reason='仅离线合成夹具额度'))
        self.flow = self.write('create_intelligent_workflow', dict(episode_id=self.objects['episode'],
            title='离线首版闭环', route='storyboard_video', script_text='固定离线测试剧本。'))['id']

    def media(self, name, **kw):
        from PIL import Image
        data = BytesIO()
        Image.new('RGB', (128,128), 'blue').save(data, format='PNG')
        staged = self.service.storage.stage_upload(BytesIO(data.getvalue()), 'reference.png')
        return self.write('register_media', dict(staged_upload=staged['staged_upload'], name=name,
            rights='owned', source={'kind':'test-owned','content':'offline test image'}))['id']

    def batch(self, *, auto=True, overdue=False, blocked=False, count=1):
        request = self.prepared(blocked=blocked)
        if count != 1:
            request['preparation']['count'] = count
            saved = self.write('prepare_intelligent_drafts', {**{k:request[k] for k in
                ('workflow_id','version_id','unit_keys','purpose')},**request['preparation']})
            request['items'] = [dict(unit_key=i['unit_key'],draft_artifact_id=i['draft_artifact_id'])
                for i in saved['items'] if not i['gaps']]
        request['auto_first_cut'] = auto
        if overdue:
            request['execution_policy']['first_draft_due_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        preview = self.service.preview_intelligent_work_batch(self.p, request)
        return self.write('generate_intelligent_work_batch', dict(request=request, preview_sha256=preview['preview_sha256']))

    def video(self):
        target = self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=128x128:rate=24',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-c:v','libx264',
            '-pix_fmt','yuv420p','-c:a','aac',str(target)], check=True, capture_output=True)
        return target.read_bytes()

    def counts(self):
        from sqlalchemy import select, func
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:
            return {name: conn.scalar(select(func.count()).select_from(getattr(S,name)).where(
                getattr(S,name).c.project_id==self.p)) for name in ('generation_jobs','edit_revisions','edit_render_jobs')}

    def test_runtime_original_jobs_reach_one_decoded_first_cut_and_restart_does_not_repeat(self):
        from vsc.production.runtime import GenerationRuntime
        from vsc.post.first_cut_worker import FirstCutWorker
        batch = self.batch()
        provider = OfflineVideo(self.video())
        runtime = GenerationRuntime(self.service, lambda *_: provider, project_id=self.p,
            interval_seconds=.02, poll_seconds=.02, retry_seconds=.1, max_retry_seconds=.2)
        runtime.start()
        self.addCleanup(runtime.stop, 5)
        deadline = time.monotonic()+25
        while time.monotonic()<deadline:
            state = self.repo.status(self.p,batch['id'])
            if state.get('render_job_id'):break
            time.sleep(.05)
        runtime.stop()
        self.assertEqual(state['status'],'queued',dict(state=state,health=runtime.health()))
        self.assertEqual(provider.submits,2)
        self.assertEqual(self.counts(),dict(generation_jobs=2,edit_revisions=1,edit_render_jobs=1))
        rendered = FirstCutWorker(self.store,self.service.storage).run_once(self.p)
        self.assertEqual(rendered['status'],'succeeded',rendered)
        complete = self.repo.status(self.p,batch['id'])
        self.assertEqual(complete['status'],'succeeded')
        self.assertEqual(complete['professional_review'],'not_reviewed')
        before = self.service.get_project(self.p)['revision']
        self.assertEqual(self.service.advance_episode_first_cuts(self.p),[])
        self.repo.advance(self.p,batch['id'])
        self.assertEqual(self.service.get_project(self.p)['revision'],before)
        self.assertEqual(self.counts(),dict(generation_jobs=2,edit_revisions=1,edit_render_jobs=1))
        artifact = self.service.get_artifact_version(self.p,batch['id'])
        fixed = json.loads(artifact['document'])
        self.assertEqual(len(fixed['runs']),2)
        edit = self.service.get_edit_workspace(self.p,self.objects['episode'])
        self.assertEqual(len(edit['current']['document']['clips']),2)
        self.assertTrue(edit['current']['document']['professional_inputs'])

    def test_due_records_one_gap_milestone_without_empty_output_or_duplicate_jobs(self):
        batch = self.batch(overdue=True,blocked=True)
        first = self.repo.advance(self.p,batch['id'])
        revision = self.service.get_project(self.p)['revision']
        self.assertTrue(first['overdue'])
        self.assertTrue(first['deadline_receipt_id'])
        self.assertIn('batch_unit_blocked',[gap['code'] for gap in first['gaps']])
        second = self.repo.advance(self.p,batch['id'])
        self.assertEqual(second['deadline_receipt_id'],first['deadline_receipt_id'])
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        self.assertEqual(self.counts(),dict(generation_jobs=2,edit_revisions=0,edit_render_jobs=0))

    def test_user_edit_is_preserved_and_forged_or_manual_batch_cannot_authorize_render(self):
        batch = self.batch()
        # This is an explicit user edit, even while original jobs are waiting.
        self.write('save_edit_workspace',dict(episode_id=self.objects['episode'],edit_revision=0,
            document={'format':'vsc.edit-workspace/v1','width':128,'height':128,'fps':24,'clips':[],'audio':[],'captions':[]}))
        result = self.repo.advance(self.p,batch['id'])
        self.assertEqual(result['status'],'edit_changed')
        self.assertEqual(self.counts(),dict(generation_jobs=2,edit_revisions=1,edit_render_jobs=0))
        self.rev = self.service.get_project(self.p)['revision']
        original = self.service.get_artifact_version(self.p,batch['id'])
        forged = self.write('create_artifact',dict(artifact_key='forged-batch',artifact_type='intelligent-work-batch',
            document=json.loads(original['document']),object_ids=[self.objects['episode']]))
        with self.assertRaises(ResourceError) as error:self.repo.advance(self.p,forged['id'])
        self.assertEqual(error.exception.code,'batch_authorization_missing')
        self.assertNotIn(forged['id'],[r['id'] for r in self.repo.pending(self.p)])

    def test_failed_alternative_candidate_does_not_block_original_successful_selection(self):
        from vsc.production.resource_worker import ResourceWorker
        from vsc.production.providers import JobStatus
        batch = self.batch(count=2)
        success = OfflineVideo(self.video())
        class FailedVideo(OfflineVideo):
            def poll(self, handle):return JobStatus('failed',error_code='offline_failure')
        failure = FailedVideo(b'')
        worker = ResourceWorker(self.service, lambda job,_:failure if job['candidate_no']%2 else success)
        for _ in range(4):self.assertIsNotNone(worker.run_once(self.p))
        result = self.repo.advance(self.p,batch['id'])
        self.assertEqual(result['status'],'queued',result)
        self.assertEqual(sorted(job['status'] for job in result['jobs']),['failed','failed','succeeded','succeeded'])
        self.assertEqual((success.submits,failure.submits),(2,2))
        self.assertEqual(self.counts(),dict(generation_jobs=4,edit_revisions=1,edit_render_jobs=1))
        self.repo.advance(self.p,batch['id'])
        self.assertEqual(self.counts()['edit_render_jobs'],1)

    def test_keyset_scan_visits_fifty_first_batch_without_losing_waiting_predecessors(self):
        # Use the original submission API for every receipt. No provider runs.
        from copy import deepcopy
        request = self.prepared(blocked=True)
        request['auto_first_cut'] = True
        batches = []
        for _ in range(51):
            preview = self.service.preview_intelligent_work_batch(self.p,request)
            batches.append(self.write('generate_intelligent_work_batch',
                dict(request=deepcopy(request),preview_sha256=preview['preview_sha256']))['id'])
        page = self.repo.pending(self.p)
        self.assertEqual(len(page),50)
        last = self.repo.pending(self.p,after=page[-1]['scan_cursor'])
        self.assertEqual([r['id'] for r in last],[batches[-1]])
        self.assertEqual(self.repo.pending(self.p,after=last[-1]['scan_cursor']),[])
        first_cycle = self.service.advance_episode_first_cuts(self.p)
        second_cycle = self.service.advance_episode_first_cuts(self.p)
        self.assertEqual(len(first_cycle),50)
        self.assertEqual([r['batch_artifact_id'] for r in second_cycle],[batches[-1]])
        # The cursor is ephemeral. The third cycle revisits still-waiting work.
        self.assertEqual(len(self.service.advance_episode_first_cuts(self.p)),50)
        self.assertEqual(self.counts(),dict(generation_jobs=102,edit_revisions=0,edit_render_jobs=0))

    def test_background_continuation_keeps_original_identity_and_respects_revocation(self):
        from sqlalchemy import update
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from vsc.adapters.persistence.postgres import schema as S
        identity = self.service.ensure_local_access('test-human')
        def restore_test_identity():
            with self.engine.begin() as conn:
                conn.execute(update(S.access_identities).where(S.access_identities.c.id==identity['identity_id']).values(active=True))
        self.addCleanup(restore_test_identity)
        token = set_principal(Principal(**identity))
        try:batch = self.batch(overdue=True)
        finally:reset_principal(token)
        body = json.loads(self.service.get_artifact_version(self.p,batch['id'])['document'])
        self.assertEqual(body['continuation_principal']['identity_id'],identity['identity_id'])
        with self.engine.begin() as conn:
            conn.execute(update(S.access_identities).where(S.access_identities.c.id==identity['identity_id']).values(active=False))
        revision = self.service.get_project(self.p)['revision']
        with self.assertRaises(ResourceError) as error:self.repo.advance(self.p,batch['id'])
        self.assertEqual(error.exception.code,'access_denied')
        self.assertEqual(self.service.get_project(self.p)['revision'],revision)
        self.assertEqual(self.counts(),dict(generation_jobs=2,edit_revisions=0,edit_render_jobs=0))
