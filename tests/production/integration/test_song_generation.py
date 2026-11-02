"""Official-shaped transport + actual original worker/storage/HTTP consumers."""
from datetime import datetime,timedelta,timezone
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid
import wave

import support.paths
from support.fixtures.resource_store import ResourceStoreFixture,HAS_DB_DEPS,TEST_URL
from vsc.assets.resource_service import ResourceError


@unittest.skipUnless(TEST_URL and HAS_DB_DEPS and shutil.which('ffmpeg') and shutil.which('ffprobe'),'requires isolated PostgreSQL and real audio decoding')
class SongGenerationTests(ResourceStoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        from vsc.adapters.storage.local.store import LocalStorage
        from vsc.production.resource_settings import PRESETS,ResourceSettings
        self.temp=tempfile.TemporaryDirectory(prefix='vsc-song-test-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service.storage=LocalStorage(self.root/'media');self.objects=self.hierarchy()
        preset=next(p for p in PRESETS if p['id']=='mureka-song');self.model=ResourceSettings(self.store).save({**{k:v for k,v in preset.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        self.write('configure_budget',dict(limits={'remote_jobs':4,'audio_jobs':4},reason='isolated song worker test'))
        audio=io.BytesIO()
        with wave.open(audio,'wb') as stream:stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\0\0'*32000)
        self.content=audio.getvalue();self.lyrics='[Verse]\nThe morning light\n[Chorus]\nWe find our way'

    def policy(self):
        now=datetime.now(timezone.utc)
        return dict(version='bounded-v1',first_draft_due_at=(now+timedelta(minutes=10)).isoformat(),stop_submitting_at=(now+timedelta(minutes=30)).isoformat(),max_attempts_per_purpose=1,max_repair_rounds=0,authorization={'mode':'new_batch','reason':'isolated official-shaped song verification'})

    def draft(self):
        return dict(tool='music_lyrics',episode_id=self.objects['episode'],title='Fixed original lyrics',prompt='gentle piano',style='female vocal',lyrics=self.lyrics,model_id=self.model)

    def queue(self):
        draft=self.write('save_creative_tool_draft',dict(document=self.draft(),base_draft_id=None))
        self.write('prepare_creative_tool_work',dict(draft_version_id=draft['id']));request=dict(draft_version_id=draft['id'],execution_policy=self.policy());quote=self.service.preview_creative_tool_run(self.p,request);self.assertTrue(quote['ready'],quote)
        run=self.write('generate_creative_tool_work',dict(request=request,preview_sha256=quote['preview_sha256']))
        return draft,run

    def adapter(self,transport):
        import httpx
        from vsc.adapters.providers.mureka import mureka_factory
        client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(client.close)
        return lambda job,storage:mureka_factory(job,storage,client=client,read_key=lambda:'isolated-mureka-key')

    def test_http_song_quote_original_worker_storage_recovery_and_reuse(self):
        import httpx
        from fastapi.testclient import TestClient
        from vsc.interfaces.web.app import create_app
        from vsc.production.resource_worker import ResourceWorker
        app=create_app(dict(projects_root=str(self.root/'projects'),media_root=str(self.service.storage.root),access_token='isolated-token',human_identity='test-human',allowed_hosts=['testserver'],allowed_origins=['http://testserver'],background_enabled=False),service=self.service)
        with TestClient(app) as client:
            login=client.post('/api/v1/session',json={'token':'isolated-token'},headers={'Origin':'http://testserver'});self.assertEqual(login.status_code,200,login.text)
            headers={'Origin':'http://testserver','X-CSRF-Token':login.json()['csrf_token']};base='/api/v1/projects/'+self.p
            def post(path,payload,mutation=True):
                body={'payload':payload}
                if mutation:body.update(expected_revision=self.service.get_project(self.p)['revision'],idempotency_key=uuid.uuid4().hex)
                response=client.post(base+'/creative-tools'+path,json=body,headers=headers);self.assertEqual(response.status_code,200,response.text);return response.json()
            draft=post('/drafts',dict(document=self.draft(),base_draft_id=None));fixed=post('/work-input',dict(draft_version_id=draft['id']))
            work=json.loads(self.service.get_artifact_version(self.p,fixed['draft_version_id'])['document']);self.assertEqual(work['mode'],'audio_song');self.assertEqual(work['lyrics'],self.lyrics)
            request=dict(draft_version_id=draft['id'],execution_policy=self.policy());quote=post('/preview',request,False);self.assertTrue(quote['ready'],quote)
            self.assertEqual(quote['generation_quote']['jobs'][0]['native_units'],{'remote_jobs':1,'audio_jobs':1})
            run=post('/generate',dict(request=request,preview_sha256=quote['preview_sha256']));job_id=run['jobs'][0]['id'];calls=[];downloads=[]
            terminal=dict(id='official-task-1',created_at=1677610602,finished_at=1677610652,model='mureka-9.5',status='succeeded',choices=[dict(index=0,id='official-song-1',url='https://cdn.example.test/song.mp3',wav_url='https://cdn.example.test/song.wav',duration=2000,lyrics_sections=[dict(section_type='verse',start=0,end=2000,lines=[dict(start=0,end=2000,text='The morning light',words=[])])])])
            def transport(request):
                calls.append((request.method,str(request.url),json.loads(request.content) if request.content else None))
                return httpx.Response(200,json=dict(id='official-task-1',model='mureka-9.5',status='preparing') if request.method=='POST' else terminal)
            def download(url,path):
                downloads.append(url)
                if len(downloads)==1:raise OSError('isolated first transfer interruption')
                path.write_bytes(self.content)
            worker=ResourceWorker(self.service,self.adapter(transport),download=download)
            worker.run_once(self.p)
            with self.assertRaises(OSError):worker.run_once(self.p,poll=True)
            pending=self.service.get_generation_job(self.p,job_id);self.assertEqual(pending['status'],'running');self.assertEqual(pending['raw_response'],terminal)
            worker.run_once(self.p,poll=True);job=self.service.get_generation_job(self.p,job_id);self.assertEqual(job['status'],'succeeded');self.assertEqual([c[0] for c in calls],['POST','GET']);self.assertEqual(calls[0][2]['n'],1);self.assertEqual(calls[0][2]['lyrics'],self.lyrics);self.assertNotIn(self.lyrics,calls[0][2]['prompt'])
            worker.run_once(self.p);worker.run_once(self.p,poll=True);self.assertEqual(len(calls),2)
            post('/advance',dict(run_version_id=run['run_version_id']),False)
            options=client.get(base+'/creative-tools',params={'object_id':self.objects['episode']}).json();cap=next(t for t in options['tools'] if t['id']=='music_lyrics');self.assertEqual(cap['mode'],'provider')
            output=next(o for o in options['local_outputs'] if o.get('run_version_id')==run['run_version_id']);media=output['outputs'][0];self.assertEqual(media['modality'],'audio')
            detail=self.service.get_media(self.p,media['id']);self.assertEqual(detail['duration_ms'],2000);self.assertEqual(detail['probe']['decode']['mode'],'complete')
            response=client.get(base+'/media/'+media['id']+'/content?download=true');self.assertEqual(response.status_code,200);self.assertEqual(response.content,self.content)
            post('/use-output',dict(output_version_id=output['id'],media_id=media['id'],target='editing',edit_revision=0,audio_purpose='music'))
            edit=self.service.get_edit_workspace(self.p,self.objects['episode']);self.assertEqual(edit['current']['document']['audio'][0]['media_id'],media['id'])
            mv=post('/drafts',dict(base_draft_id=None,document=dict(tool='mv',episode_id=self.objects['episode'],audio_media_id=media['id'],lrc='[00:00.000]The morning light',prompt='A quiet street')))
            plan=post('/compile-mv',dict(document=dict(tool='mv',episode_id=self.objects['episode'],audio_media_id=media['id'],lrc='[00:00.000]The morning light',prompt='A quiet street')),False)
            self.assertEqual(plan['plan']['audio_media_id'],media['id']);self.assertEqual(plan['plan']['audio_duration_ms'],2000);self.assertEqual(len(calls),2)

    def test_unknown_submission_keeps_original_identity_and_never_resubmits(self):
        import httpx
        from vsc.production.resource_worker import ResourceWorker
        _,run=self.queue();calls=[]
        def transport(request):calls.append(request);raise httpx.ReadTimeout('isolated unknown acceptance',request=request)
        worker=ResourceWorker(self.service,self.adapter(transport))
        with self.assertRaises(httpx.ReadTimeout):worker.run_once(self.p)
        job=self.service.get_generation_job(self.p,run['jobs'][0]['id']);self.assertEqual(job['status'],'submission_unknown');self.assertIsNone(job['external_task_id'])
        self.assertIsNone(worker.run_once(self.p));self.assertIsNone(worker.run_once(self.p,poll=True));self.assertEqual(len(calls),1)
        self.assertEqual(job['request_payload']['lyrics'],self.lyrics)

    def test_song_fixed_inputs_reject_plain_music_model_and_unmapped_references(self):
        from vsc.production.resource_settings import ResourceSettings,PRESETS
        other=next(p for p in PRESETS if p['id']=='volcengine-seed-audio');model=ResourceSettings(self.store).save({**{k:v for k,v in other.items() if k not in {'id','label'}},'enabled':True},'test-human')['id']
        value=dict(self.draft(),model_id=model)
        draft=self.write('save_creative_tool_draft',dict(document=value,base_draft_id=None));self.write('prepare_creative_tool_work',dict(draft_version_id=draft['id']))
        quote=self.service.preview_creative_tool_run(self.p,dict(draft_version_id=draft['id'],execution_policy=self.policy()));self.assertFalse(quote['ready']);self.assertIn('model_capability_mismatch',{g['code'] for g in quote['gaps']})
        value=dict(self.draft(),script_line_ids=['some-dialogue'])
        updated=self.write('save_creative_tool_draft',dict(document=value,base_draft_id=draft['id']))
        with self.assertRaises(ResourceError) as caught:self.write('prepare_creative_tool_work',dict(draft_version_id=updated['id']))
        self.assertEqual(caught.exception.code,'song_inputs_unsupported');self.assertEqual(self.service.list_generation_jobs(self.p)['total'],0)
