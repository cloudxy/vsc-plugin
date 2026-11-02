"""Real editorial revisions, scope/lease failures and decoded first-cut output."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
import zipfile

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import Conflict, ResourceError
from vsc.post.edit_workspace import FORMAT, edit_operation


class EditTransitionRenderTests(unittest.TestCase):
    def test_real_fade_frames_match_preview_and_preserve_duration(self):
        from PIL import Image
        from vsc.post.edit_workspace import FirstCutRenderer,validate_edit
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):self.skipTest('requires FFmpeg')
        with tempfile.TemporaryDirectory(prefix='vsc-transition-') as directory:
            root=Path(directory);source=root/'red.png';Image.new('RGB',(128,128),'red').save(source)
            doc={'format':FORMAT,'width':128,'height':128,'fps':24,'clips':[
                {'id':'a','media_id':'fixed-red','in_frame':0,'out_frame':24,'fade_out_frames':6},
                {'id':'b','media_id':'fixed-red','in_frame':0,'out_frame':24,'fade_in_frames':6}], 'audio':[],'captions':[]}
            self.assertEqual(validate_edit(doc),48)
            output,receipt=FirstCutRenderer().render(doc,{key:{'path':source,'modality':'image'} for key in ('a','b')},root)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vf','scale=1:1','-pix_fmt','rgb24','-fps_mode','passthrough','-f','rawvideo','-'])
            frames=[raw[i:i+3] for i in range(0,len(raw),3)]
            self.assertEqual(len(frames),48);self.assertGreater(frames[10][0],200)
            self.assertLess(max(frames[23]),15);self.assertLess(max(frames[24]),15)
            self.assertGreater(frames[32][0],200);self.assertEqual(receipt['frames'],48)
            self.assertEqual(receipt['clips'][0]['fade_out_frames'],6)
            invalid=copy.deepcopy(doc);invalid['clips'][0]['fade_in_frames']=20
            with self.assertRaisesRegex(ValueError,'不能超过'):validate_edit(invalid)


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires isolated PostgreSQL")
class EditorWorkspaceTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.adapters.persistence.postgres.editor_workspace import EditorWorkspaceRepository
        self.temp = tempfile.TemporaryDirectory(prefix="vsc-first-cut-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = LocalStorage(self.root / "storage")
        self.service.storage = self.storage
        self.repo = EditorWorkspaceRepository(self.store)
        self.objects = self.hierarchy()

    def document(self, media_id):
        return {"format": FORMAT, "width": 128, "height": 128, "fps": 24,
                "clips": [{"id": "clip1", "media_id": media_id, "shot_id": self.objects["shot"],
                           "in_frame": 0, "out_frame": 48, "volume": 1}], "audio": [], "captions": []}

    def save(self, document, revision=0):
        return self.write("save_edit_workspace", {"episode_id": self.objects["episode"],
            "edit_revision": revision, "document": document})

    def seed_media(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("requires FFmpeg/ffprobe")
        source = self.root / "moving.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, capture_output=True)
        with source.open("rb") as stream:
            upload = self.storage.stage_upload(stream, source.name)
        media = self.write("register_media", {"staged_upload": upload["staged_upload"], "name": "动态合成夹具",
            "rights": "owned", "source": {"kind": "test-owned", "content": "generated test pattern"}})
        return media["id"], source

    def test_versions_restore_scope_and_immutable_input_references(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        media = self.media("固定剪辑用料", modality="video")
        original = self.document(media)
        first = self.save(original)
        changed = edit_operation(original, {"action": "split", "clip_id": "clip1", "frame": 24, "new_id": "clip2"})
        changed = edit_operation(changed, {"action": "move", "clip_id": "clip2", "index": 0})
        self.save(changed, 1)
        with self.assertRaises(Conflict):
            self.save(original, 1)
        restored = self.write("save_edit_workspace", {"episode_id": self.objects["episode"],
            "edit_revision": 2, "restore_version_id": first["edit_version_id"]})
        result = self.service.get_edit_workspace(self.p, self.objects["episode"])
        self.assertEqual(result["current"]["document"], original)
        self.assertEqual(result["current"]["version"], 3)
        self.assertNotEqual(restored["edit_version_id"], first["edit_version_id"])
        wrong_episode = self.write("create_object", {"kind": "episode", "parent_id": self.objects["work"], "display_code": "E2", "ordinal": 1})["id"]
        with self.assertRaises(ResourceError):
            self.write("save_edit_workspace", {"episode_id": wrong_episode, "edit_revision": 0, "document": original})
        with self.engine.connect() as conn:
            pins = conn.execute(select(S.edit_revision_media).where(S.edit_revision_media.c.project_id==self.p,
                S.edit_revision_media.c.edit_version_id==first["edit_version_id"])).mappings().all()
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]["media_id"], media)
        self.assertEqual(pins[0]["source_out_frame"], 48)

    def test_selected_clip_archive_uses_fixed_trims_and_excludes_other_clips(self):
        media, _ = self.seed_media()
        document = self.document(media)
        document['clips'][0].update(in_frame=12, out_frame=36)
        document['clips'].append({'id': 'clip2', 'media_id': media, 'in_frame': 36, 'out_frame': 72})
        saved = self.save(document)
        with self.assertRaises(ResourceError):
            self.service.export_edit_workspace(self.p, saved['edit_version_id'], 'clips', ['missing'])
        path, mime, temporary = self.service.export_edit_workspace(self.p, saved['edit_version_id'], 'clips', ['clip1'])
        try:
            self.assertEqual(mime, 'application/zip')
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {'clip-001.mp4', 'manifest.json'})
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['clips'][0]['in_frame'], 12)
                output = self.root / 'downloaded-clip.mp4'
                output.write_bytes(archive.read('clip-001.mp4'))
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-of', 'json', str(output)]))
            self.assertAlmostEqual(float(probe['format']['duration']), 1, delta=.1)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True, capture_output=True)
        finally:
            temporary.cleanup()

    def test_export_watermark_uses_configured_policy_and_preserves_preview_source(self):
        from vsc.post.first_cut_worker import FirstCutWorker
        media,source=self.seed_media();saved=self.save(self.document(media))
        job=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']})
        self.assertEqual(FirstCutWorker(self.store,self.storage).run_once(self.p)['status'],'succeeded')
        original,_=self.service.edit_export_content(self.p,job['id'])
        original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
        provider='watermark_'+uuid.uuid4().hex
        self.service.register_provider({'id':provider,'base_url':'https://example.invalid','auth_ref':'OFFLINE_ONLY'},actor='test-human')
        model=self.service.register_model({'provider_id':provider,'model_key':'synthetic','model_version':'1','modality':'image','capabilities':{'purposes':['identity_ref']}},actor='test-human')['id']
        self.rev=self.store.get_project(self.p)['revision']
        document=dict(plan_key='export-test',title='隔离导出合同',amount_minor=100,currency='TST',credits=100,bucket_kind='credit',validity_days=2,checkout_minutes=10,purposes=['identity_ref'],rates=[dict(model_id=model,unit='images',credits_per_unit=1)],refund_policy='none',max_concurrent_jobs=1,invoice_enabled=False,seat_limit=2,watermark_required=True,renewal_policy='none')
        policy=self.write('configure_commerce_plan',{'document':document,'base_version_id':None,'metering_enabled':True})
        marked,fixed=self.service.edit_export_content(self.p,job['id'],for_download=True)
        try:
            self.assertNotEqual(hashlib.sha256(marked.read_bytes()).hexdigest(),original_sha)
            self.assertEqual(fixed['source_sha256'],original_sha)
            self.assertEqual(fixed['export_policy']['price_version_id'],policy['id'])
            subprocess.run(['ffmpeg','-v','error','-i',str(marked),'-f','null','-'],check=True,capture_output=True)
        finally:fixed['_temporary'].cleanup()
        preview,_=self.service.edit_export_content(self.p,job['id'])
        self.assertEqual(hashlib.sha256(preview.read_bytes()).hexdigest(),original_sha)
        path,_,temporary=self.service.export_edit_workspace(self.p,saved['edit_version_id'],'project')
        try:
            with zipfile.ZipFile(path) as archive:self.assertTrue(json.loads(archive.read('manifest.json'))['export_policy']['watermark_required'])
        finally:temporary.cleanup()

    def test_real_first_cut_mixes_captions_and_survives_http_duplicate(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.post.first_cut_worker import FirstCutWorker
        media, source = self.seed_media()
        original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        missing = self.service.seed_edit_workspace(self.p, self.objects["episode"])
        self.assertFalse(missing["document"]["clips"])
        self.assertEqual(len(missing["gaps"]), 1)
        self.write("record_media_check", {"media_id": media, "checker": "actual-ffmpeg", "criteria_version": "1", "outcome": "pass"})
        selected = self.select(self.candidate(self.objects["shot"], media, role="video_take"))
        seed = self.service.seed_edit_workspace(self.p, self.objects["episode"])
        self.assertFalse(seed["gaps"])
        self.assertEqual(seed["dynamic_frames"], 72)
        self.assertEqual(seed["selection_refs"][0]["decision_id"], selected["decision_id"])
        document = self.document(media)
        document["clips"][0].update(in_frame=24, out_frame=48, muted=True)
        document["clips"].append({"id": "clip2", "media_id": media, "in_frame": 0, "out_frame": 24})
        document["audio"] = [{"id": "music1", "media_id": media, "in_frame": 0, "out_frame": 48,
                              "at_frame": 0, "volume": .2, "fade_in": 6, "fade_out": 6}]
        document["captions"] = [{"start_frame": 4, "end_frame": 20, "text": "First cut"}]
        fixed = self.save(document)
        app = create_app({"projects_root": str(self.root / "projects"), "media_root": str(self.storage.root),
            "allowed_hosts": ["testserver"], "allowed_origins": ["http://testserver"],
            "access_token": "test-token", "human_identity": "test-human"}, service=self.service)
        with TestClient(app) as client:
            session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
            headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
            body = {"payload": {"edit_version_id": fixed["edit_version_id"]}, "expected_revision": self.rev,
                    "idempotency_key": "render-once"}
            endpoint = f"/api/v1/projects/{self.p}/edit-exports"
            self.assertEqual(client.post(endpoint, json=body).status_code, 403)
            accepted = client.post(endpoint, headers=headers, json=body)
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(client.post(endpoint, headers=headers, json=body).json(), accepted.json())
            # A new consumer can finish the persistent job after the browser request.
            result = FirstCutWorker(self.store, self.storage).run_once(self.p)
            self.assertEqual(result["status"], "succeeded", self.repo.get(self.p, self.objects["episode"])["renders"])
            response = client.get(endpoint + "/" + result["id"] + "/content")
            self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else "")
            self.assertEqual(response.headers["x-vsc-adoption"], "unapproved-first-cut")
            read = client.get(f"/api/v1/projects/{self.p}/edit-workspace", params={"episode_id": self.objects["episode"]}).json()
            receipt = read["renders"][0]["receipt"]
            self.assertEqual(receipt["dynamic_frames"], 48)
            self.assertEqual(receipt["full_decode"], "passed")
            self.assertEqual(receipt["caption_count"], 1)
            self.assertAlmostEqual(receipt["duration_ms"], 2000, delta=150)
            fixed_download = f"/api/v1/projects/{self.p}/edit-workspace/{fixed['edit_version_id']}/download"
            srt = client.get(fixed_download, params={'kind':'srt'})
            self.assertEqual(srt.status_code, 200, srt.text)
            self.assertIn('00:00:00,167 --> 00:00:00,833', srt.text)
            package = client.get(fixed_download, params={'kind':'project'})
            self.assertEqual(package.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(json.loads(archive.read('edit-workspace.json')), document)
                self.assertEqual(manifest['adoption'], 'unapproved-working-edit')
                self.assertEqual(len([name for name in archive.namelist() if name.startswith('media/')]), 1)
                for row in manifest['inputs'].values():
                    self.assertEqual(hashlib.sha256(archive.read(row['path'])).hexdigest(), row['sha256'])
                self.assertEqual(archive.read('subtitles.srt').decode(), srt.text)
                portable = self.root / 'portable'
                archive.extractall(portable)
            from vsc.post.edit_workspace_export import render_package
            self.assertTrue(render_package(portable).is_file())
            changed = copy.deepcopy(document)
            changed['clips'][0]['volume'] = .8
            (portable/'edit-workspace.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, '固定版本摘要'):
                render_package(portable)
        self.assertIsNone(FirstCutWorker(self.store, self.storage).run_once(self.p))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_sha)

    def test_expired_worker_cannot_publish_and_other_worker_resumes_same_job(self):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from vsc.adapters.persistence.postgres import schema as S
        media = self.media("剪辑租约用料", modality="video")
        fixed = self.save(self.document(media))
        request = self.repo.request(self.p, {"edit_version_id": fixed["edit_version_id"]},
            expected_revision=self.rev, idempotency_key="lease-test", actor="test-human")
        job = self.repo.claim("worker-a", self.p)
        with self.engine.begin() as conn:
            conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==self.p,
                S.edit_render_jobs.c.id==job["id"]).values(claim_until=datetime.now(timezone.utc)-timedelta(seconds=1)))
        resumed = self.repo.claim("worker-b", self.p)
        self.assertEqual(resumed["id"], request["id"])
        self.assertEqual(resumed["attempt"], 2)
        with self.assertRaises(Conflict):
            self.repo.fail(job, "worker-a", "late failure")
        self.repo.fail(resumed, "worker-b", "test stopped")

    def test_canonical_timeline_handoff_keeps_recipe_and_requires_real_approval(self):
        media, source = self.seed_media()
        self.write('record_media_check', {'media_id':media,'checker':'ffprobe','criteria_version':'1','outcome':'pass'})
        selected_binding = self.select(self.candidate(self.objects['shot'],media,role='video_take'))
        origin = self.artifact('owned-input','source-evidence',[self.objects['shot']])
        origin_sha = self.service.get_artifact_version(self.p,origin)['sha256']
        selected = self.write('create_artifact', {'artifact_key':'chosen','artifact_type':'vsc.selected_takes',
            'object_ids':[self.objects['episode']],'dependency_ids':[origin],'document':{
                'format':'vsc.selected-takes/v1','project_id':self.p,'scope':self.objects['episode'],
                'items':[{'id':'take1','shot_id':self.objects['shot'],'take_id':'synthetic-take','output_id':'synthetic-output',
                    'scope':self.objects['episode'],'purpose':'visual','usage_rights':'owned','selected_by':'test-human',
                    'media':{'path':'media/synthetic.mp4','sha256':self.service.get_media(self.p,media)['sha256']},
                    'source':{'kind':'manual','artifact':{'id':origin,'sha256':origin_sha},'imported_by':'test-human','provenance':'owned synthetic test pattern'}}]}})
        self.write('decide_artifact',{'artifact_id':selected['id'],'reason':'合成操作者确认选片清单'})
        doc=self.document(media);doc['clips'][0].update(muted=True,in_frame=12,out_frame=48,fade_in_frames=6,fade_out_frames=8)
        fixed=self.save(doc)
        options=self.service.edit_timeline_options(self.p,fixed['edit_version_id'])
        self.assertEqual([row['id'] for row in options['selected_takes']],[selected['id']])
        request={'edit_version_id':fixed['edit_version_id'],'selected_takes_id':selected['id'],
            'assignments':{'clip1':{'selected_item_id':'take1','binding_decision_id':selected_binding['decision_id'],'audio_role':'none'}}}
        preview=self.service.preview_edit_timeline(self.p,request)
        segment=preview['artifact']['document']['render_plan']['segments'][0]
        self.assertEqual((segment['source_in_frame'],segment['duration_in_frames'],segment['fit']),(12,36,'contain'))
        self.assertEqual((segment['fade_in_frames'],segment['fade_out_frames']),(6,8))
        proposal=self.write('propose_edit_timeline',{'request':request,'preview_sha256':preview['preview_sha256']})
        with self.assertRaises(ResourceError):self.write('freeze_edit_timeline',{'artifact_id':proposal['artifact_id']})
        self.write('decide_artifact',{'artifact_id':proposal['artifact_id'],'reason':'合成操作者批准固定时间线'})
        frozen=self.write('freeze_edit_timeline',{'artifact_id':proposal['artifact_id']})
        actual=self.service.get_timeline(self.p,frozen['id'])
        self.assertEqual(actual['items'][0]['duration_frames'],36)
        self.assertEqual(actual['items'][0]['media'][0]['source_in_frame'],12)
        self.assertEqual(self.service.edit_timeline_options(self.p,fixed['edit_version_id'])['handoffs'][0]['timeline_id'],frozen['id'])
        bad=copy.deepcopy(request);bad['assignments']['clip1']['binding_decision_id']=str(uuid.uuid4())
        with self.assertRaises(ResourceError):self.service.preview_edit_timeline(self.p,bad)

    def test_single_export_cancel_queue_replay_and_scope_http(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.project.resource_catalog import ResourceCatalog
        media=self.media('取消用料',modality='video');saved=self.save(self.document(media))
        job=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']})
        with tempfile.TemporaryDirectory() as root,TestClient(create_app({'allowed_hosts':['testserver'],'allowed_origins':['http://testserver'],'access_token':'edit-test','human_identity':'test-human'},catalog=ResourceCatalog(root,self.service))) as client:
            route=f'/api/v1/projects/{self.p}/edit-exports/{job["id"]}/cancel'
            body={'payload':{'job_id':job['id']},'expected_revision':self.rev,'idempotency_key':'cancel-one'}
            self.assertEqual(client.post(route,json=body).status_code,403)
            login=client.post('/api/v1/session',json={'token':'edit-test'},headers={'origin':'http://testserver'}).json()
            headers={'origin':'http://testserver','x-csrf-token':login['csrf_token']}
            result=client.post(route,json=body,headers=headers);self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['status'],'cancelled');self.assertEqual(result.json(),client.post(route,json=body,headers=headers).json());self.rev=result.json()['revision']
        self.assertIsNone(self.repo.claim('must-not-run',self.p))
        resumed=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']});self.assertEqual(resumed['id'],job['id']);self.assertEqual(resumed['status'],'queued')
        other=self.service.create_project({'name':'其他项目'},actor='test-human')['id']
        with self.assertRaises(ResourceError):self.service.cancel_edit_export(other,{'job_id':job['id']},expected_revision=0,idempotency_key='wrong-project',actor='test-human')

    def test_running_cancel_terminates_real_ffmpeg_retry_and_success_wins(self):
        import threading,time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from vsc.post.edit_workspace import FirstCutRenderer,_run
        from vsc.post.first_cut_worker import FirstCutWorker
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        media,_=self.seed_media();saved=self.save(self.document(media));queued=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']})
        started=threading.Event();processes=[];real_popen=subprocess.Popen
        class SlowLocalRenderer(FirstCutRenderer):
            def render(inner,document,inputs,directory,*,cancelled=None):
                _run(['ffmpeg','-v','error','-nostdin','-re','-f','lavfi','-i','testsrc2=size=128x128:rate=24','-t','60','-f','null','-'],cancelled=cancelled)
                return super().render(document,inputs,directory,cancelled=cancelled)
        def observe(*args,**kw):
            process=real_popen(*args,**kw);processes.append(process);started.set();return process
        worker=FirstCutWorker(self.store,self.storage,renderer=SlowLocalRenderer(),lease_seconds=3)
        with patch('vsc.post.edit_workspace.subprocess.Popen',side_effect=observe),ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(worker.run_once,self.p);self.assertTrue(started.wait(5))
            start=time.monotonic();requested=self.write('cancel_edit_export',{'job_id':queued['id']});self.assertTrue(requested['cancel_requested'])
            result=future.result(timeout=6);self.assertEqual(result['status'],'cancelled');self.assertLess(time.monotonic()-start,5)
        self.assertTrue(processes);self.assertTrue(all(p.poll() is not None for p in processes))
        with self.engine.connect() as conn:old=dict(conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==self.p,S.edit_render_jobs.c.id==queued['id'])).mappings().one())
        self.assertIsNone(old['output_blob_id']);self.assertEqual(old['status'],'cancelled')
        resumed=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']});self.assertEqual(resumed['id'],queued['id'])
        finished=FirstCutWorker(self.store,self.storage).run_once(self.p);self.assertEqual(finished['status'],'succeeded');self.rev=finished['revision']
        with self.assertRaises(Conflict):self.repo.finish(old,worker.worker_id,{'sha256':'a'*64},{})
        cancelled=self.write('cancel_edit_export',{'job_id':queued['id']});self.assertTrue(cancelled['already_completed']);self.assertEqual(cancelled['status'],'succeeded')
        _,content=self.service.edit_export_content(self.p,queued['id']);self.assertEqual(content['sha256'],finished['sha256'])

    def test_cancel_requested_before_finish_discards_success_and_old_lease(self):
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        media=self.media('完成竞态',modality='video');saved=self.save(self.document(media));job=self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']});claim=self.repo.claim('finishing-worker',self.p)
        self.write('cancel_edit_export',{'job_id':job['id']})
        result=self.repo.finish(claim,'finishing-worker',{'sha256':'a'*64},{})
        self.assertEqual(result['status'],'cancelled');self.rev=result['revision']
        self.write('request_edit_export',{'edit_version_id':saved['edit_version_id']});self.repo.claim('new-worker',self.p)
        with self.assertRaises(Conflict):self.repo.fail(claim,'finishing-worker','late failure')
        with self.engine.connect() as conn:row=conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==self.p,S.edit_render_jobs.c.id==job['id'])).mappings().one()
        self.assertEqual(row['status'],'running');self.assertEqual(row['claim_owner'],'new-worker')
