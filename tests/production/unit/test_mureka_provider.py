"""Mureka's published SongGenerateReq / SongTask / Song shape, no remote calls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from vsc.adapters.providers.mureka import BASE,KEY_ENV,MurekaSongProvider,mureka_factory
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import AudioRequest,JobHandle


class MurekaProviderTests(unittest.TestCase):
    def request(self,**extra):
        return AudioRequest('shot','song','a'*64,'gentle piano, female vocal',lyrics='[Verse]\nA quiet morning\n[Chorus]\nWe walk home',**extra)

    def test_official_shape_single_song_poll_and_lossless_result(self):
        import httpx
        calls=[]
        def transport(request):
            calls.append(request)
            self.assertEqual(request.headers['authorization'],'Bearer isolated-key')
            if request.method=='POST':return httpx.Response(200,json=dict(id='1436211',created_at=1677610602,model='mureka-9.5',status='preparing'))
            return httpx.Response(200,json=dict(id='1436211',model='mureka-9.5',status='succeeded',choices=[dict(index=0,id='song-1',url='https://cdn.example.test/song.mp3',wav_url='https://cdn.example.test/song.wav',duration=180000,lyrics_sections=[dict(section_type='verse',start=0,end=180000,lines=[dict(start=0,end=2000,text='A quiet morning',words=[])])])]))
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            provider=MurekaSongProvider('mureka-9.5','mureka-fixed',client,lambda:'isolated-key')
            request=self.request();handle=provider.submit(request);status=provider.poll(handle);assets=provider.parse_result(status.raw)
        self.assertEqual(json.loads(calls[0].content),dict(model='mureka-9.5',lyrics=request.lyrics,prompt=request.prompt,n=1))
        self.assertEqual(str(calls[1].url),BASE+'/v1/song/query/1436211');self.assertEqual(calls[1].content,b'')
        self.assertEqual(status.status,'succeeded');self.assertEqual(len(assets),1)
        self.assertEqual(assets[0].temporary_uri,'https://cdn.example.test/song.wav');self.assertEqual(assets[0].metadata['duration'],180000)
        self.assertEqual(assets[0].metadata['lyrics_sections'][0]['start'],0)

    def test_unknown_receipt_foreign_id_and_invalid_outputs_fail_closed(self):
        import httpx
        for raw in ({'status':'preparing'}, {'id':42,'status':'preparing'}, {'id':'1','model':'other','status':'preparing'}):
            with self.subTest(submit=raw),httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=raw))) as client:
                with self.assertRaises(ResourceError):MurekaSongProvider('mureka-9.5','m',client,lambda:'isolated-key').submit(self.request())
        for raw in ({'id':'other','status':'succeeded'}, {'id':'1','status':'unrecognized'}):
            with self.subTest(poll=raw),httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=raw))) as client:
                with self.assertRaises(ResourceError):MurekaSongProvider('mureka-9.5','m',client,lambda:'isolated-key').poll(JobHandle('m','mureka-9.5','1'))
        provider=MurekaSongProvider('mureka-9.5','m',read_key=lambda:'isolated-key')
        for raw in ({'status':'streaming','choices':[{'stream_url':'https://cdn.example.test/live'}]}, {'status':'succeeded','choices':[]}, {'status':'succeeded','choices':[{'url':'https://a.test/1'},{'url':'https://a.test/2'}]}, {'status':'succeeded','choices':[{'url':'http://a.test/1'}]}):
            with self.subTest(result=raw),self.assertRaises(ResourceError):provider.parse_result(raw)

    def test_dedicated_disabled_settings_route_and_credentials(self):
        from vsc.production.resource_settings import PRESETS,validate_configuration,public_configuration
        from vsc.adapters.providers.worker_factory import worker_adapter_factory
        preset=next(p for p in PRESETS if p['id']=='mureka-song');self.assertFalse(preset['enabled'])
        payload={k:v for k,v in preset.items() if k not in {'id','label'}}
        with patch.dict('os.environ',{KEY_ENV:'isolated-key'}):
            config=public_configuration(validate_configuration(dict(payload,enabled=True)))
            self.assertEqual(config['connection_status'],'loaded_unverified');self.assertTrue(config['adapter_available']);self.assertNotIn('isolated-key',json.dumps(config))
        for changes in ({'auth_ref':'ARK_AGENT_PLAN_API_KEY'},{'base_url':'https://example.test'},{'default_params':{'n':2}},{'capabilities':{'purposes':['music'],'lyrics':True}}):
            with self.subTest(changes=changes),self.assertRaises(ResourceError):validate_configuration(dict(payload,**changes))
        job=dict(provider_id='m',provider=dict(configuration={k:payload[k] for k in ('supplier','product','plan','execution')},base_url=BASE,auth_ref=KEY_ENV),model=dict(model_key='mureka-9.5',default_params={}),modality='audio',purpose='song')
        self.assertIsInstance(worker_adapter_factory(job,None),MurekaSongProvider)
        with self.assertRaises(ResourceError):mureka_factory(dict(job,purpose='music'),None)
        with self.assertRaises(ResourceError):MurekaSongProvider('mureka-9.5','m',read_key=lambda:'').preflight(self.request())

    def test_song_lyrics_are_typed_fixed_and_not_a_plain_music_prompt(self):
        from vsc.production.run_authorization import normalize_request,validate_capabilities
        from vsc.assets.classic_production import normalize_draft
        from vsc.adapters.persistence.postgres.budget_store import native_units
        raw=dict(prompt='gentle piano',lyrics='[Verse]\nHome tonight')
        logical=normalize_request(raw,'shot','song','audio')
        context={'working_draft':{'id':'fixed'},'working_song':dict(draft_id='fixed',**raw),'media':[]}
        model={'capabilities':{'purposes':['song'],'lyrics':True}}
        self.assertIsNone(validate_capabilities(model,logical,context));self.assertEqual(native_units(logical),{'remote_jobs':1,'audio_jobs':1})
        altered=deepcopy(logical);altered['lyrics']='different'
        with self.assertRaises(ResourceError):validate_capabilities(model,altered,context)
        for request,purpose in (({'prompt':'sing these words'},'song'),(raw,'music'),(dict(raw,params={'n':2}),'song'),(dict(raw,lyrics='x'*5001),'song')):
            with self.subTest(purpose=purpose,keys=list(request)),self.assertRaises(ResourceError):normalize_request(request,'shot',purpose,'audio')
        draft=normalize_draft(dict(mode='audio_song',shot_id='shot',purpose='song',**raw));self.assertEqual(draft['lyrics'],raw['lyrics'])
        with self.assertRaises(ResourceError):normalize_draft(dict(mode='audio',shot_id='shot',purpose='music',**raw))
