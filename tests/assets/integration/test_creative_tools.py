"""Isolated PG/HTTP drafts, MV objects and original editor persistence."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

import support.paths
from support.fixtures.resource_store import HAS_DB_DEPS, TEST_URL, ResourceStoreFixture
from vsc.assets.resource_service import Conflict, ResourceError


@unittest.skipUnless(HAS_DB_DEPS and TEST_URL, "requires isolated PostgreSQL")
class CreativeToolsTests(ResourceStoreFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.objects = self.hierarchy()

    def timed_media(self, modality, duration=4000):
        sha = hashlib.sha256((str(uuid.uuid4()) + modality).encode()).hexdigest()
        return self.write("register_media", dict(name="合成工具素材", modality=modality, sha256=sha,
            size_bytes=20, mime_type="audio/wav" if modality == "audio" else "video/mp4", storage="local",
            object_key=sha+".bin", rights="owned", duration_ms=duration,
            source=dict(kind="test-owned", content="synthetic fixture")))["id"]

    def save(self, tool, base=None, **fields):
        return self.write("save_creative_tool_draft", dict(base_draft_id=base,
            document=dict(tool=tool, episode_id=self.objects["episode"], **fields)))

    def test_standalone_workspace_is_personal_idempotent_and_identity_bound(self):
        from dataclasses import replace
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.assertRaises(ResourceError):self.service.open_creative_tool_workspace(actor='test-human')
        owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**owner));self.addCleanup(reset_principal,token)
        studio=self.service.access_command('workspace',{'name':'工具不应进入此团队','parent_id':None},actor='test-human',
            expected_revision=self.service.access_snapshot()['access_revision'],idempotency_key=uuid.uuid4().hex)['workspace_id']
        studio_token=set_principal(replace(Principal(**owner),workspace_id=studio))
        try:first=self.service.open_creative_tool_workspace(actor='test-human')
        finally:reset_principal(studio_token)
        again=self.service.open_creative_tool_workspace(actor='test-human');self.assertEqual(first['id'],again['id']);self.assertEqual(first['episode_id'],again['episode_id'])
        options=self.service.creative_tools_options(first['id']);self.assertTrue(options['standalone']);self.assertEqual(options['episode']['id'],first['episode_id'])
        self.assertEqual(len(options['episodes']),1)
        with self.engine.connect() as conn:
            binding=conn.execute(select(S.access_projects.c.workspace_id).where(S.access_projects.c.project_id==first['id'])).scalar_one()
        self.assertEqual(binding,owner['workspace_id']);self.assertNotEqual(binding,studio)
        other=self.service.ensure_local_access('second-tool-human');other_token=set_principal(Principal(**other))
        try:
            second=self.service.open_creative_tool_workspace(actor=other['actor']);self.assertNotEqual(second['id'],first['id'])
            with self.assertRaises(ResourceError):self.service.creative_tools_options(first['id'])
        finally:reset_principal(other_token)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires actual media tools')
    def test_standalone_local_output_import_reuses_blob_editor_receipt_and_scope(self):
        from vsc.assets.access_control import Principal,set_principal,reset_principal
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        root,_,target_video,_=self.music_local_fixture();target=self.p;target_objects=dict(self.objects)
        self.write('save_edit_workspace',dict(episode_id=target_objects['episode'],edit_revision=0,document=dict(format='vsc.edit-workspace/v1',width=128,height=128,fps=24,clips=[dict(id='original',media_id=target_video,in_frame=0,out_frame=144,volume=1)],audio=[],captions=[])))
        owner=self.service.ensure_local_access('test-human');token=set_principal(Principal(**owner));self.addCleanup(reset_principal,token)
        workspace=self.service.open_creative_tool_workspace(actor='test-human');self.p=workspace['id'];self.rev=workspace['revision'];self.objects={'episode':workspace['episode_id']}
        with (root/'source.mp4').open('rb') as stream:upload=self.service.storage.stage_upload(stream,'standalone-source.mp4')
        source=self.write('register_media',dict(staged_upload=upload['staged_upload'],rights='owned',source=dict(kind='synthetic-test',content='synthetic source')))['id']
        draft=self.save('separate_audio',source_media_id=source)
        output=self.write('process_creative_tool_local',dict(draft_version_id=draft['id']));member=next(row for row in output['outputs'] if row['modality']=='audio')
        request=dict(source_project_id=self.p,source_artifact_id=output['id'],source_media_id=member['id'],sha256=member['sha256'],episode_id=target_objects['episode'],audio_purpose='dialogue_dry')
        preview=self.service.preview_creative_output_import(target,request);payload=dict(request=request,preview_sha256=preview['preview_sha256']);key='fixed-output-import'
        result=self.service.import_creative_output(target,payload,actor='test-human',expected_revision=preview['revision'],idempotency_key=key)
        repeated=self.service.import_creative_output(target,payload,actor='test-human',expected_revision=preview['revision'],idempotency_key=key);self.assertEqual(repeated,result)
        again=self.service.import_creative_output(target,payload,actor='test-human',expected_revision=result['revision'],idempotency_key='new-key-same-fixed-output');self.assertTrue(again['already_imported']);self.assertEqual(again['media_id'],result['media_id']);self.assertEqual(again['edit_version_id'],result['edit_version_id'])
        copied=self.service.get_media(target,result['media_id']);self.assertEqual(copied['sha256'],member['sha256']);self.assertEqual(copied['rights']['outcome'],'unknown')
        self.assertEqual(copied['blob_id'],self.service.get_media(self.p,member['id'])['blob_id'])
        edit=self.service.get_edit_workspace(target,target_objects['episode'])['current']['document'];self.assertEqual(len(edit['clips']),1);self.assertEqual(edit['audio'][0]['media_id'],copied['id']);self.assertEqual(edit['audio'][0]['at_frame'],0);self.assertEqual(edit['audio'][0]['purpose'],'dialogue_dry')
        second_episode=self.service.create_object(target,dict(kind='episode',parent_id=target_objects['work'],display_code='E2',ordinal=1),actor='test-human',expected_revision=again['revision'],idempotency_key=uuid.uuid4().hex)['id']
        second_request=dict(request,episode_id=second_episode);second_preview=self.service.preview_creative_output_import(target,second_request)
        second=self.service.import_creative_output(target,dict(request=second_request,preview_sha256=second_preview['preview_sha256']),actor='test-human',expected_revision=second_preview['revision'],idempotency_key=uuid.uuid4().hex)
        self.assertEqual(second['media_id'],copied['id'])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.creative_tool_imports).where(S.creative_tool_imports.c.project_id==target)).scalar_one(),2)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.media_items).where(S.media_items.c.project_id==target,S.media_items.c.blob_id==copied['blob_id'])).scalar_one(),1)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.binding_candidates).where(S.binding_candidates.c.project_id==target)).scalar_one(),0)
        with self.assertRaises(ResourceError):self.service.preview_creative_output_import(target,dict(request,sha256='0'*64))
        stranger=self.service.ensure_local_access('stranger-tool-human');other=set_principal(Principal(**stranger))
        try:
            with self.assertRaises(ResourceError):self.service.preview_creative_output_import(target,request)
        finally:reset_principal(other)
        self.rev=self.store.get_project(self.p)['revision'];self.write('management_command',dict(operation='trash',target_type='project',target_id=self.p,reason='synthetic recycled source'))
        with self.assertRaises(ResourceError):self.service.preview_creative_output_import(target,request)

    def music_local_fixture(self):
        import math,struct,wave
        from vsc.adapters.storage.local.store import LocalStorage
        temporary=tempfile.TemporaryDirectory(prefix='vsc-music-tools-');self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        previous=self.service.storage;self.service.storage=LocalStorage(root/'storage');self.addCleanup(lambda:setattr(self.service,'storage',previous))
        audio=root/'clicks.wav';rate=16000
        with wave.open(str(audio),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
            out.writeframes(b''.join(struct.pack('<h',int(24000*math.sin(2*math.pi*660*i/rate)*(1-(i%(rate//2))/(rate*.06))) if i%(rate//2)<rate*.06 else 0) for i in range(rate*8)))
        def register(path):
            with path.open('rb') as stream:upload=self.service.storage.stage_upload(stream,path.name)
            return self.write('register_media',dict(staged_upload=upload['staged_upload'],rights='owned',source=dict(kind='synthetic-test',content='local test patterns')))['id']
        source=root/'source.mp4';replacement=root/'replacement.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=128x128:rate=10','-f','lavfi','-i','sine=frequency=220:sample_rate=48000','-t','6','-c:v','libx264','-crf','0','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True)
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:size=128x128:rate=10','-f','lavfi','-i','sine=frequency=880:sample_rate=48000','-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(replacement)],check=True,capture_output=True)
        return root,register(audio),register(source),register(replacement)

    def test_lyrics_original_dispatch_receipt_acceptance_and_unknown_guard(self):
        import json
        from sqlalchemy import select,func
        from vsc.adapters.persistence.postgres import schema as S
        class Planner:
            name='offline-lyrics';calls=[];unknown=False
            def available(self):return True
            def generate(self,packet,source,skill):
                self.calls.append((packet,source,skill))
                if self.unknown:raise ResourceError('fixture timeout','lyrics_submission_unknown')
                return dict(title='合成歌词',lyrics='测试风声\n测试灯光',notes='仅文本建议，无音频')
        backend=Planner();self.service.lyric_planner=backend;self.addCleanup(lambda:delattr(self.service,'lyric_planner'))
        saved=self.save('lyrics',prompt='写测试主题的原创歌词',lyrics='人工原稿')
        request=dict(draft_version_id=saved['id'],new_attempt=False);key='fixed-lyrics-request'
        run=self.write('create_creative_lyrics',request,idempotency_key=key);self.assertEqual(run['status'],'completed');self.assertEqual(len(backend.calls),1)
        repeated=self.service.create_creative_lyrics(self.p,request,actor='test-human',expected_revision=0,idempotency_key=key);self.assertEqual(repeated['id'],run['id']);self.assertEqual(len(backend.calls),1)
        packet,source,skill=backend.calls[0];self.assertEqual(packet['role']['id'],'music-supervisor');self.assertEqual(source['lyrics'],'人工原稿');self.assertIn('vsc-sound',skill)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(S.dispatch_consumptions).where(S.dispatch_consumptions.c.project_id==self.p)).scalar(),1)
            self.assertEqual(conn.execute(select(func.count()).select_from(S.dispatch_returns).where(S.dispatch_returns.c.project_id==self.p,S.dispatch_returns.c.closed.is_(True))).scalar(),1)
        old=self.service._fixed_creative_tool(self.p,saved['id'])[1]['input'];self.assertEqual(old['lyrics'],'人工原稿')
        adopted=self.write('accept_creative_music_result',dict(result_version_id=run['result_version_id'],base_draft_id=saved['id']))
        self.assertEqual(self.service._fixed_creative_tool(self.p,adopted['id'])[1]['input']['lyrics'],'测试风声\n测试灯光')
        with self.assertRaises(Conflict):self.write('accept_creative_music_result',dict(result_version_id=run['result_version_id'],base_draft_id=adopted['id']))
        backend.unknown=True;unknown=self.write('create_creative_lyrics',dict(draft_version_id=adopted['id'],new_attempt=True))
        count=len(backend.calls);self.assertEqual(unknown['status'],'submission_unknown')
        self.assertEqual(self.write('create_creative_lyrics',dict(draft_version_id=adopted['id'],new_attempt=True))['id'],unknown['id']);self.assertEqual(len(backend.calls),count)
        self.assertEqual(self.service.get_creative_lyrics(self.p,unknown['id'])['status'],'submission_unknown');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires actual media tools')
    def test_local_onsets_editable_segments_original_mv_shots_and_editor(self):
        from unittest.mock import patch
        root,audio,source,replacement=self.music_local_fixture()
        saved=self.save('mv',audio_media_id=audio,visual_media_ids=[source,replacement],prompt='按实际素材剪辑')
        result=self.write('analyze_creative_music',dict(draft_version_id=saved['id'],beats_per_segment=4))
        analysis=result['analysis'];self.assertAlmostEqual(analysis['estimated_tempo_bpm'],120,delta=4);self.assertGreater(len(analysis['onset_times_ms']),10)
        self.assertEqual(analysis['segments'][0]['start_ms'],0);self.assertEqual(analysis['segments'][-1]['end_ms'],8000)
        with patch('vsc.production.music_tools.analyze_audio',side_effect=AssertionError('replayed decoder')):
            self.assertTrue(self.write('analyze_creative_music',dict(draft_version_id=saved['id'],beats_per_segment=4))['already_analyzed'])
        accepted=self.write('accept_creative_music_result',dict(result_version_id=result['id'],base_draft_id=saved['id']))
        value=self.service._fixed_creative_tool(self.p,accepted['id'])[1]['input'];self.assertEqual(value['segments'],analysis['segments'])
        # Actual edit choices remain manual, including an edit to an algorithm boundary.
        value['segments']=[dict(start_ms=0,end_ms=3000,title='人工段一',lyrics='',prompt=''),dict(start_ms=3000,end_ms=8000,title='人工段二',lyrics='',prompt='')]
        value['params']={'visual_segments':[dict(media_id=source,in_ms=500),dict(media_id=source,in_ms=1000)]}
        saved=self.write('save_creative_tool_draft',dict(document=value,base_draft_id=accepted['id']))
        imported=self.write('import_creative_mv',dict(draft_version_id=saved['id']));self.assertEqual(len(imported['shot_ids']),2)
        request=dict(draft_version_id=saved['id']);preview=self.service.preview_creative_mv_edit(self.p,request)
        self.write('apply_creative_mv_edit',dict(request=request,preview_sha256=preview['preview_sha256']))
        edit=self.service.get_edit_workspace(self.p,self.objects['episode'])['current']['document'];self.assertEqual([r['out_frame']-r['in_frame'] for r in edit['clips']],[72,120]);self.assertEqual(edit['audio'][0]['out_frame'],192)
        self.assertEqual([r['shot_id'] for r in edit['clips']],imported['shot_ids'])
        with self.assertRaises(Conflict):self.write('apply_creative_mv_edit',dict(request=request,preview_sha256=preview['preview_sha256']))
        self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
        # The original export worker consumes these exact MV shots, offsets and full audio.
        from vsc.post.first_cut_worker import FirstCutWorker
        fixed=self.service.get_edit_workspace(self.p,self.objects['episode'])['current']
        self.write('request_edit_export',dict(edit_version_id=fixed['id']))
        done=FirstCutWorker(self.store,self.service.storage).run_once(self.p)
        self.assertEqual(done['status'],'succeeded')
        workspace=self.service.get_edit_workspace(self.p,self.objects['episode'])
        self.assertEqual(workspace['renders'][0]['receipt']['full_decode'],'passed')
        output,_=self.service.edit_export_content(self.p,done['id'])
        import json
        probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)],check=True,capture_output=True).stdout)
        self.assertAlmostEqual(float(probe['format']['duration']),8,delta=.1)
        self.assertEqual({r['codec_type'] for r in probe['streams']},{'video','audio'})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires actual media tools')
    def test_real_interval_replace_preserves_outer_frames_duration_audio_and_receipt(self):
        import json
        from unittest.mock import patch
        from vsc.post.local_media_tools import command
        root,audio,source,replacement=self.music_local_fixture();before=hashlib.sha256((root/'source.mp4').read_bytes()).hexdigest()
        ranges=[dict(start_ms=1000,end_ms=2000),dict(start_ms=4000,end_ms=5000)]
        saved=self.save('segment_remake',source_media_id=source,replacement_media_id=replacement,ranges=ranges,params=dict(replacement_in_ms=500,audio_mode='keep_source'))
        result=self.write('process_creative_tool_local',dict(draft_version_id=saved['id']))
        with patch('vsc.post.local_media_tools.process',side_effect=AssertionError('replayed ffmpeg')):
            self.assertEqual(self.write('process_creative_tool_local',dict(draft_version_id=saved['id']))['id'],result['id'])
        media=self.service.get_media(self.p,result['outputs'][0]['id']);location=next(r for r in media['locations'] if r['storage']=='local');path=self.service.storage.verify(location['object_key'],media['sha256'])
        self.assertAlmostEqual(media['duration_ms'],6000,delta=100);self.assertEqual(result['receipt']['audio_mode'],'keep_source')
        def pixels(path,t):return command(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'])
        def preserved(path,at):
            import math
            actual,expected=pixels(path,at),pixels(root/'source.mp4',at);self.assertEqual(len(actual),len(expected))
            mse=sum((a-b)**2 for a,b in zip(actual,expected))/len(actual)
            self.assertGreater(10*math.log10(255**2/max(mse,1e-12)),40,at)
        for at in [.5,2.5,3.5,5.5]:preserved(path,at)
        probe=json.loads(command(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))
        self.assertEqual(next(r['profile'] for r in probe['streams'] if r['codec_type']=='video'),'High')
        for at in [1.5,4.5]:self.assertNotEqual(pixels(path,at),pixels(root/'source.mp4',at),at)
        # Same original 220Hz tone remains in and outside replacements; compare PCM correlation.
        import array,math
        def sound(path):
            data=array.array('f');data.frombytes(command(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-ac','1','-ar','8000','-f','f32le','pipe:1']));return data
        original,processed=sound(root/'source.mp4'),sound(path)
        for at in [.5,1.5,2.5,4.5,5.5]:
            a=original[int(at*8000):int((at+.2)*8000)];b=processed[int(at*8000):int((at+.2)*8000)];corr=sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b));self.assertGreater(corr,.97)
        self.assertEqual(hashlib.sha256((root/'source.mp4').read_bytes()).hexdigest(),before)
        bad=self.save('segment_remake',base=saved['id'],source_media_id=source,replacement_media_id=replacement,ranges=[dict(start_ms=1050,end_ms=2000)],params={})
        with self.assertRaises(ResourceError) as error:self.write('process_creative_tool_local',dict(draft_version_id=bad['id']))
        self.assertEqual(error.exception.code,'local_replace_frame_boundary')
        from sqlalchemy import select
        from vsc.adapters.persistence.postgres import schema as S
        with self.engine.connect() as conn:inputs=list(conn.execute(select(S.operation_inputs.c.role).where(S.operation_inputs.c.project_id==self.p,S.operation_inputs.c.operation_id==result['operation_id'])).scalars())
        self.assertEqual(set(inputs),{'source','replacement'})
        replaced=self.save('segment_remake',base=bad['id'],source_media_id=source,replacement_media_id=replacement,ranges=ranges,params=dict(audio_mode='replace'))
        changed=self.write('process_creative_tool_local',dict(draft_version_id=replaced['id']));item=self.service.get_media(self.p,changed['outputs'][0]['id']);loc=next(r for r in item['locations'] if r['storage']=='local');replaced_audio=sound(self.service.storage.verify(loc['object_key'],item['sha256']))
        for at,expected in [(.5,220),(1.5,880),(2.5,220),(4.5,880),(5.5,220)]:
            window=replaced_audio[int(at*8000):int((at+.25)*8000)];crossings=sum(x<=0<y for x,y in zip(window,window[1:]));self.assertAlmostEqual(crossings/.25,expected,delta=8)
        self.assertEqual(changed['receipt']['source_frame_ranges'],[dict(start_frame=10,end_frame=20),dict(start_frame=40,end_frame=50)])
        # Container timestamps may begin above zero; user ranges remain relative to the first frame.
        from vsc.post.local_media_tools import replace_segments
        shifted=root/'shifted.mp4';outdir=root/'shifted-output';outdir.mkdir()
        command(['ffmpeg','-v','error','-y','-i',str(root/'source.mp4'),'-map','0','-c','copy','-output_ts_offset','2',str(shifted)])
        built,receipt=replace_segments(shifted,root/'replacement.mp4',dict(params={},ranges=ranges),outdir)
        self.assertEqual(receipt['output_duration_ms'],6000)
        for at in [.5,2.5,5.5]:preserved(built[0]['path'],at)

    def test_blocked_tools_preserve_inputs_fixed_media_and_mode_versions(self):
        video = self.timed_media("video")
        first = self.save("depth_motion", source_media_id=video, prompt="动作参考", ranges=[dict(start_ms=0, end_ms=3000)])
        self.save("music_description", prompt="轻柔钢琴")
        options = self.service.creative_tools_options(self.p, self.objects["shot"])
        self.assertEqual(options["episode"]["id"], self.objects["episode"])
        self.assertEqual(len(options["drafts"]), 2)
        draft = next(row for row in options["drafts"] if row["id"] == first["id"])["document"]
        self.assertFalse(draft["generated"])
        self.assertIn("中间视频", draft["blocked_reason"])
        self.assertEqual(draft["media"][0]["duration_ms"], 4000)
        with self.assertRaises(Conflict):
            self.save("depth_motion", source_media_id=video, prompt="stale")
        with self.assertRaises(ResourceError):
            self.save("segment_remake", source_media_id=video, ranges=[dict(start_ms=0, end_ms=5000)])
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        from vsc.adapters.persistence.postgres import schema as S
        media = self.service.get_media(self.p, video)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(update(S.media_blobs).where(S.media_blobs.c.id == media["blob_id"]).values(duration_ms=5000))
        self.assertEqual(self.service._fixed_creative_tool(self.p, first["id"])[1]["media"][0]["duration_ms"], 4000)

    def test_mv_import_is_transactional_idempotent_and_scope_bound(self):
        audio = self.timed_media("audio")
        saved = self.save("mv", audio_media_id=audio, lrc="[00:00]first\n[00:02]second", prompt="合成镜头")
        response = self.write("import_creative_mv", {"draft_version_id": saved["id"]}, idempotency_key="mv-import")
        self.assertEqual(len(response["shot_ids"]), 2)
        self.assertFalse(response["approved"])
        repeated = self.write("import_creative_mv", {"draft_version_id": saved["id"]})
        self.assertEqual(repeated["shot_ids"], response["shot_ids"])
        self.assertTrue(repeated["already_imported"])
        self.assertEqual(len([row for row in self.service.get_project_tree(self.p)["nodes"] if row["kind"] == "shot"]), 3)
        artifact = self.service.get_artifact_version(self.p, response["id"])
        self.assertEqual(artifact["artifact_type"], "shot-plan")
        other = self.write("create_object", dict(kind="episode", parent_id=self.objects["work"], display_code="OTHER", ordinal=1))["id"]
        with self.assertRaises(ResourceError):
            self.write("save_creative_tool_draft", dict(base_draft_id=None, document=dict(tool="speech", episode_id=other, shot_id=self.objects["shot"])))

    def test_music_uses_original_edit_versions_preserves_source_and_conflicts(self):
        video, audio = self.timed_media("video"), self.timed_media("audio", 12000)
        saved = self.save("music_mix", source_media_id=video, audio_media_id=audio,
            music_start_ms=1000, music_end_ms=3000, audio_in_ms=4000, keep_original=True)
        result = self.write("apply_creative_music", dict(draft_version_id=saved["id"], edit_revision=0))
        edit = self.service.get_edit_workspace(self.p, self.objects["episode"])
        self.assertEqual(edit["current"]["id"], result["edit_version_id"])
        document = edit["current"]["document"]
        self.assertEqual(document["audio"][0]["at_frame"], 24)
        self.assertFalse(document["clips"][0]["muted"])
        self.assertEqual(self.service.get_media(self.p, audio)["duration_ms"], 12000)
        with self.assertRaises(Conflict):
            self.write("apply_creative_music", dict(draft_version_id=saved["id"], edit_revision=0))

    def test_http_trusted_session_duplicate_save_and_readback(self):
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        with tempfile.TemporaryDirectory() as root:
            app = create_app(dict(projects_root=root, allowed_hosts=["testserver"], allowed_origins=["http://testserver"], access_token="test-token", human_identity="test-human"), service=self.service)
            with TestClient(app) as client:
                session = client.post("/api/v1/session", headers={"Origin": "http://testserver"}, json={"token": "test-token"}).json()
                headers = {"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]}
                url = "/api/v1/projects/" + self.p + "/creative-tools"
                body = dict(payload=dict(document=dict(tool="music_lyrics", episode_id=self.objects["episode"], lyrics="synthetic words"), base_draft_id=None), expected_revision=self.rev, idempotency_key="http-save")
                self.assertEqual(client.post(url+"/drafts", json=body).status_code, 403)
                saved = client.post(url+"/drafts", json=body, headers=headers)
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(client.post(url+"/drafts", json=body, headers=headers).json(), saved.json())
                read = client.get(url, params={"object_id": self.objects["episode"]})
                self.assertEqual(read.status_code, 200, read.text)
                self.assertEqual(read.json()["drafts"][0]["document"]["input"]["lyrics"], "synthetic words")
                tools = {row["id"]: row for row in read.json()["tools"]}
                self.assertEqual(tools["music_lyrics"]["mode"], "draft_only")
                self.assertTrue(tools["sfx"]["reason"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_video_operation_pins_source_and_proposes_original_bounded_run(self):
        import json
        from datetime import datetime, timedelta, timezone
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_settings import ResourceSettings, PRESETS
        with tempfile.TemporaryDirectory(prefix="vsc-tools-operation-") as directory:
            root = Path(directory)
            storage = self.service.storage = LocalStorage(root / "storage")
            source = root / "source.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=24",
                "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
            with source.open("rb") as stream:
                staged = storage.stage_upload(stream, source.name)
            media = self.write("register_media", dict(staged_upload=staged["staged_upload"], name="编辑合成源片", rights="owned",
                source=dict(kind="test-owned", content="generated pattern")))["id"]
            self.write("record_media_check", dict(media_id=media, checker="actual-ffprobe", criteria_version="1", outcome="pass"))
            self.artifact(objects=[self.objects["shot"]])
            self.artifact("state", "scene-state", [self.objects["scene"]], {"state_versions": [{"scene_id": self.objects["scene"]}]})
            preset = next(row for row in PRESETS if row["id"] == "xai-grok-video-operations")
            model = ResourceSettings(self.store).save(dict({k:v for k,v in preset.items() if k not in {"id", "label"}},
                enabled=True, model_version="isolated-no-submit"), "test-human")
            now = datetime.now(timezone.utc)
            policy = dict(version="bounded-v1", first_draft_due_at=(now+timedelta(minutes=45)).isoformat(),
                stop_submitting_at=(now+timedelta(minutes=60)).isoformat(), max_attempts_per_purpose=2, max_repair_rounds=1)
            for tool in ("video_edit", "video_extend"):
                saved = self.save(tool, source_media_id=media, shot_id=self.objects["shot"], model_id=model["id"], prompt="合成画面调整", duration_ms=3000)
                request = dict(draft_version_id=saved["id"], execution_policy=policy)
                preview = self.service.preview_creative_tool_run(self.p, request)
                self.assertTrue(preview["ready"], preview.get("gaps"))
                result = self.write("propose_creative_tool_run", dict(request=request, preview_sha256=preview["preview_sha256"]))
                artifact = self.service.get_artifact_version(self.p, result["id"])
                self.assertFalse(artifact["approved"])
                document = json.loads(artifact["document"])
                logical = document["series_batch"]["jobs"][0]["request"]
                self.assertEqual(logical["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(logical["source_duration_ms"], 2000)
                self.assertEqual(logical["duration_ms"], 2000 if tool == "video_edit" else 3000)
                self.assertEqual(document["approved_media_inputs"][0]["role"], "operation_source")
                self.assertEqual(self.service.list_generation_jobs(self.p)["total"], 0)
                ranged = self.save(tool, base=saved["id"], source_media_id=media, shot_id=self.objects["shot"], model_id=model["id"],
                    prompt="局部操作不能冒充整片编辑", ranges=[dict(start_ms=0, end_ms=1000)])
                with self.assertRaises(ResourceError) as rejected:
                    self.service.preview_creative_tool_run(self.p, dict(draft_version_id=ranged["id"], execution_policy=policy))
                self.assertEqual(rejected.exception.code, "operation_range_unsupported")
            self.service.storage = None

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_synthetic_music_export_decodes_and_does_not_change_source_bytes(self):
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.post.first_cut_worker import FirstCutWorker
        with tempfile.TemporaryDirectory(prefix="vsc-tools-media-") as directory:
            root = Path(directory)
            storage = self.service.storage = LocalStorage(root / "storage")
            source, music = root / "source.mp4", root / "music.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=24", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000", "-t", "4", str(music)], check=True, capture_output=True)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            ids = []
            for path in (source, music):
                with path.open("rb") as stream:
                    staged = storage.stage_upload(stream, path.name)
                ids.append(self.write("register_media", dict(staged_upload=staged["staged_upload"], name=path.name, rights="owned", source=dict(kind="test-owned", content="generated test pattern")))["id"])
            saved = self.save("music_mix", source_media_id=ids[0], audio_media_id=ids[1], music_start_ms=500, music_end_ms=1500, audio_in_ms=1000)
            fixed = self.write("apply_creative_music", dict(draft_version_id=saved["id"], edit_revision=0))
            self.write("request_edit_export", dict(edit_version_id=fixed["edit_version_id"]))
            done = FirstCutWorker(self.store, storage).run_once(self.p)
            self.assertEqual(done["status"], "succeeded")
            edit = self.service.get_edit_workspace(self.p, self.objects["episode"])
            self.assertEqual(edit["renders"][0]["receipt"]["full_decode"], "passed")
            import array
            import math
            def rms(path, start):
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path), "-t", "0.2",
                    "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
                samples = array.array("h", raw)
                return math.sqrt(sum(x*x for x in samples) / len(samples))
            output, _ = self.service.edit_export_content(self.p, done["id"])
            self.assertLess(rms(output, .1), 10)
            self.assertGreater(rms(output, .8), 500)
            self.assertLess(rms(output, 1.7), 10)
            self.rev = self.service.get_project(self.p)["revision"]
            saved2 = self.save("music_mix", base=saved["id"], source_media_id=ids[0], audio_media_id=ids[1],
                music_start_ms=500, music_end_ms=1500, audio_in_ms=1000, keep_original=True)
            fixed2 = self.write("apply_creative_music", dict(draft_version_id=saved2["id"], edit_revision=1))
            self.write("request_edit_export", dict(edit_version_id=fixed2["edit_version_id"]))
            done2 = FirstCutWorker(self.store, storage).run_once(self.p)
            self.assertEqual(done2["status"], "succeeded")
            output2, _ = self.service.edit_export_content(self.p, done2["id"])
            self.assertGreater(rms(output2, .1), 500)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            self.service.storage = None

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
    def test_local_frames_tracks_regions_lineage_replay_and_original_consumers(self):
        import json
        from unittest.mock import patch
        from vsc.adapters.storage.local.store import LocalStorage
        with tempfile.TemporaryDirectory(prefix="vsc-local-tools-") as directory:
            root = Path(directory)
            storage = self.service.storage = LocalStorage(root / "storage")
            source = root / "source.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=10", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True, capture_output=True)
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            with source.open("rb") as stream: staged = storage.stage_upload(stream, source.name)
            media = self.write("register_media", dict(staged_upload=staged["staged_upload"], rights="owned", source=dict(kind="synthetic", content="local pattern")))["id"]
            base = None
            frames = []
            for mode, at in [("first",0),("current",1000),("last",0)]:
                draft=self.save("extract_frame",base=base,source_media_id=media,params={"frame_mode":mode,"time_ms":at});base=draft["id"]
                result=self.write("process_creative_tool_local",{"draft_version_id":base})
                frames.append(result)
                self.assertEqual(result["receipt"]["selected_time_ms"], {"first":0,"current":1000,"last":1900}[mode])
                with patch("vsc.post.local_media_tools.process", side_effect=AssertionError("must not process twice")):
                    again=self.write("process_creative_tool_local",{"draft_version_id":base})
                self.assertEqual(again["id"], result["id"])
                image=self.service.get_media(self.p,result["outputs"][0]["id"])
                self.assertEqual((image["width"],image["height"]),(128,128))
                self.assertEqual(self.service.get_media_lineage(self.p,image["id"])["inputs"][0]["media_id"],media)
            draft=self.save("separate_audio",source_media_id=media)
            separated=self.write("process_creative_tool_local",{"draft_version_id":draft["id"]})
            self.assertEqual({row["modality"] for row in separated["outputs"]},{"audio","video"})
            for row in separated["outputs"]:
                output=self.service.get_media(self.p,row["id"])
                path=storage.verify(output["locations"][0]["object_key"],output["sha256"])
                probe=json.loads(subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(path)],check=True,capture_output=True).stdout)
                self.assertEqual({stream["codec_type"] for stream in probe["streams"]},{row["modality"]})
            for tool in ("remove_subtitles","remove_watermark"):
                draft=self.save(tool,source_media_id=media,params={"rectangle":{"x":10,"y":10,"width":30,"height":20}},ranges=[{"start_ms":500,"end_ms":1500}])
                result=self.write("process_creative_tool_local",{"draft_version_id":draft["id"]})
                output=self.service.get_media(self.p,result["outputs"][0]["id"])
                self.assertEqual(output["duration_ms"],2000)
                self.assertIn("interpolation",result["receipt"]["method"])
                outpath=storage.verify(output["locations"][0]["object_key"],output["sha256"])
                def pixels(path,at):
                    return subprocess.run(["ffmpeg","-v","error","-ss",str(at),"-i",str(path),"-frames:v","1","-vf","crop=24:14:13:13","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],check=True,capture_output=True).stdout
                def difference(at):
                    a,b=pixels(source,at),pixels(outpath,at)
                    return sum(abs(x-y) for x,y in zip(a,b))/len(a)
                self.assertGreater(difference(1),difference(.1)+2)

            result=frames[0];mid=result["outputs"][0]["id"]
            candidate=self.write("use_creative_tool_output",dict(output_version_id=result["id"],media_id=mid,target="candidate",shot_id=self.objects["shot"]))
            self.assertEqual(self.store.get_binding_candidate(self.p,candidate["id"])["media_id"],mid)
            canvas=self.write("create_creative_canvas",dict(episode_id=self.objects["episode"],title="Synthetic",document={"nodes":[],"edges":[],"viewport":{"x":0,"y":0,"zoom":1}}))
            self.write("use_creative_tool_output",dict(output_version_id=result["id"],media_id=mid,target="canvas",canvas_id=canvas["id"],canvas_revision=1))
            self.assertEqual(self.service.get_creative_canvas(self.p,canvas["id"])["document"]["nodes"][0]["media_id"],mid)
            self.write("use_creative_tool_output",dict(output_version_id=result["id"],media_id=mid,target="editing",edit_revision=0))
            self.assertEqual(self.service.get_edit_workspace(self.p,self.objects["episode"])["current"]["document"]["clips"][0]["media_id"],mid)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
            with self.assertRaises(ResourceError):
                self.write("use_creative_tool_output",dict(output_version_id=result["id"],media_id=media,target="editing",edit_revision=1))
            self.service.storage=None
