"""Official-shaped sample payloads and strict source/time evidence; no network."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json
from types import SimpleNamespace
import unittest

import httpx
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import VideoRequest,JobHandle
from vsc.adapters.providers.credentials import PLAN_BASE
from vsc.production.video_samples import TTL_CHANGE,bind_sample,sample_deadline,validate_sample_binding
from vsc.adapters.providers.volc_ark.sample import upgrade_payload
from vsc.adapters.providers.volc_ark.provider import VolcArkVideoProvider

MODEL='doubao-seedance-2-5-260628'


class VideoSampleTests(unittest.TestCase):
    def source(self,created=None):
        created=created or datetime.now(timezone.utc)-timedelta(minutes=1)
        source=dict(id='media',project_id='project',modality='video',sha256='a'*64,duration_ms=5000,width=854,height=480)
        original=dict(id='job',project_id='project',status='succeeded',modality='video',provider_id='fixed-account',request_sha256='b'*64,external_task_id='cgt-original',request_payload={'draft':True},
            outputs=[{'media_id':'media'}],model={'model_key':MODEL,'default_params':{'resolution':'480p'},'capabilities':{'video_draft':True}},
            raw_response={'id':'cgt-original','model':MODEL,'status':'succeeded','created_at':created.timestamp(),'draft':True,'resolution':'480p'})
        target={'model_key':MODEL,'default_params':{'resolution':'1080p'},'capabilities':{'video_draft':True}}
        return source,original,target

    def binding(self):
        source,original,target=self.source()
        return bind_sample(original,source,target,'fixed-account')

    def request(self,**extra):
        value=asdict(VideoRequest('shot','video_upgrade','c'*64,'原样片升级'))
        value.update(operation='draft_upgrade',source_media_id='media',source_sha256='a'*64,source_duration_ms=5000,draft=False)
        value.update(extra);return SimpleNamespace(**value)

    def test_provider_upgrade_wire_contains_only_native_draft_reference(self):
        bodies=[]
        def handler(request):bodies.append(json.loads(request.content));return httpx.Response(200,json={'id':'cgt-upgraded'})
        client=httpx.Client(transport=httpx.MockTransport(handler));self.addCleanup(client.close)
        def transport(path,payload=None):return client.request('POST' if payload is not None else 'GET',PLAN_BASE+path,json=payload).json()
        adapter=VolcArkVideoProvider(MODEL,lambda _:self.fail('upgrade must not resolve/upload an old input'),'1080p','16:9',True,transport,video_draft=True,sample_binding=self.binding(),provider_id='fixed-account')
        handle=adapter.submit(self.request(params={'return_last_frame':False,'watermark':True,'output_format':'mp4'}))
        self.assertEqual(handle.external_task_id,'cgt-upgraded');self.assertEqual(len(bodies),1)
        self.assertEqual(bodies[0],{'model':MODEL,'content':[{'type':'draft_task','draft_task':{'id':'cgt-original'}}],'resolution':'1080p','draft':False,'return_last_frame':False,'watermark':True,'output_format':'mp4'})
        for name in ['duration','ratio','seed','generate_audio','prompt','omni_reference_task_type']:self.assertNotIn(name,bodies[0])

    def test_draft_is_explicit_480p_capability_not_inferred_from_model(self):
        calls=[];transport=lambda path,payload:(calls.append(payload) or {'id':'cgt-draft'})
        request=self.request(operation=None,source_media_id=None,source_sha256=None,source_duration_ms=None,draft=True,purpose='text_to_video')
        for model,resolution,enabled in [(MODEL,'1080p',True),(MODEL,'480p',False),('doubao-seedance-2-0-260128','480p',True)]:
            with self.subTest(model=model,resolution=resolution,enabled=enabled),self.assertRaises(ResourceError):VolcArkVideoProvider(model,lambda _:None,resolution,'16:9',transport=transport,video_draft=enabled).submit(request)
        self.assertEqual(calls,[])
        VolcArkVideoProvider(MODEL,lambda _:None,'480p','16:9',transport=transport,video_draft=True).submit(request)
        self.assertIs(calls[0]['draft'],True);self.assertEqual(calls[0]['resolution'],'480p');self.assertEqual(calls[0]['duration'],5)
        self.assertEqual(calls[0]['content'][0]['type'],'text')

    def test_ttl_boundary_uses_only_provider_created_at(self):
        before=TTL_CHANGE-timedelta(seconds=1)
        self.assertEqual(sample_deadline(before.timestamp()),before+timedelta(days=7))
        self.assertEqual(sample_deadline(TTL_CHANGE.isoformat()),TTL_CHANGE+timedelta(days=14))
        source,job,target=self.source(TTL_CHANGE)
        binding=bind_sample(job,source,target,'fixed-account',now=TTL_CHANGE+timedelta(days=13))
        with self.assertRaises(ResourceError) as error:validate_sample_binding(binding,provider_id='fixed-account',model_key=MODEL,now=TTL_CHANGE+timedelta(days=14))
        self.assertEqual(error.exception.code,'sample_expired')
        for value in [None,False,'2026-11-02T10:00:00','not-a-date']:
            with self.subTest(value=value),self.assertRaises(ResourceError):sample_deadline(value)
        del job['raw_response']['created_at'];job['created_at']=TTL_CHANGE.isoformat()
        with self.assertRaises(ResourceError):bind_sample(job,source,target,'fixed-account',now=TTL_CHANGE)

    def test_source_account_output_receipt_and_parameter_changes_are_refused(self):
        source,original,target=self.source()
        cases=[]
        for field,value in [('status','running'),('external_task_id',None),('provider_id','another-account'),('outputs',[{'media_id':'foreign'}])]:
            changed=deepcopy(original);changed[field]=value;cases.append(changed)
        changed=deepcopy(original);changed['request_payload']['draft']=False;cases.append(changed)
        changed=deepcopy(original);changed['raw_response']['id']='other-task';cases.append(changed)
        for index,job in enumerate(cases):
            with self.subTest(case=index),self.assertRaises(ResourceError):bind_sample(job,source,target,'fixed-account')
        for params in [{'duration':5},{'generate_audio':True},{'watermark':'false'},{'output_format':'gif'}]:
            with self.subTest(params=params),self.assertRaises(ResourceError):upgrade_payload(self.request(params=params),MODEL,'fixed-account',self.binding(),resolution='1080p',enabled=True)
        with self.assertRaises(ResourceError):upgrade_payload(self.request(reference_media_ids=['old-input']),MODEL,'fixed-account',self.binding(),resolution='1080p',enabled=True)
        with self.assertRaises(ResourceError):upgrade_payload(self.request(source_sha256='f'*64),MODEL,'fixed-account',self.binding(),resolution='1080p',enabled=True)

    def test_unknown_submit_is_one_post_and_poll_never_recreates(self):
        calls=[]
        def timeout(path,payload=None):calls.append((path,payload));raise TimeoutError('receipt unknown')
        adapter=VolcArkVideoProvider(MODEL,lambda _:None,'1080p','16:9',transport=timeout,video_draft=True,sample_binding=self.binding(),provider_id='fixed-account')
        with self.assertRaises(TimeoutError):adapter.submit(self.request())
        self.assertEqual(len(calls),1)
        from vsc.adapters.providers.volc_ark.provider import VolcAdapterError
        with self.assertRaises(VolcAdapterError):adapter.poll(JobHandle('volc_ark',MODEL,None,{}))
        self.assertEqual(len(calls),1)

    def test_shared_normalization_source_resolution_and_output_checks(self):
        from vsc.production.run_authorization import normalize_request,validate_capabilities
        from vsc.production.video_samples import UPGRADE_PROMPT,validate_sample_output
        from vsc.adapters.persistence.postgres.budget_store import native_units
        old=normalize_request({'prompt':'ordinary'},'shot','text_to_video','video')
        self.assertEqual(old,normalize_request({'prompt':'ordinary','draft':False},'shot','text_to_video','video'))
        with self.assertRaises(ResourceError):normalize_request({'prompt':'ordinary','draft':1},'shot','text_to_video','video')
        source,job,model=self.source();source['height']=1080
        with self.assertRaises(ResourceError):bind_sample(job,source,model,'fixed-account')
        logical=normalize_request(dict(prompt=UPGRADE_PROMPT,operation='draft_upgrade',source_media_id='source',source_sha256='a'*64,source_duration_ms=5100,duration_ms=5100),'shot','video_upgrade','video')
        self.assertEqual(native_units(logical),{'remote_jobs':1,'video_seconds':6})
        with self.assertRaises(ResourceError):normalize_request(dict(logical,prompt='new prompt'),'shot','video_upgrade','video')
        with self.assertRaises(ResourceError):normalize_request(dict(logical,sample_binding=self.binding()),'shot','video_upgrade','video')
        validate_sample_output(logical,dict(modality='video',width=1920,height=1080,duration_ms=5100))
        with self.assertRaises(ResourceError):validate_sample_output(logical,dict(modality='video',width=854,height=480,duration_ms=5100))

    def test_real_official_sdk_upgrade_output_format_exact_wire(self):
        from unittest.mock import patch
        from vsc.adapters.providers.volc_ark.official_sdk import OfficialArkTransport,runtime_snapshot
        from vsc.adapters.providers.credentials import KEY_ENV
        body=upgrade_payload(self.request(params={'output_format':'mov'}),MODEL,'fixed-account',self.binding(),resolution='1080p',enabled=True)
        requests=[]
        def handler(request):requests.append(request);return httpx.Response(200,json={'id':'cgt-upgrade-sdk'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client,patch.dict('os.environ',{KEY_ENV:'synthetic-only'}):
            raw=OfficialArkTransport(runtime_snapshot(),{},http_client=client)('/contents/generations/tasks',body)
        self.assertEqual(raw['id'],'cgt-upgrade-sdk');self.assertEqual(len(requests),1)
        self.assertEqual({k:v for k,v in json.loads(requests[0].content).items() if v is not None},body)

    def test_fixed_price_change_rejects_upgrade_quote(self):
        from vsc.production.quotes import quote_request,fingerprint
        from vsc.adapters.persistence.postgres.quotes import check_pinned
        from vsc.production.run_authorization import normalize_request
        from vsc.production.video_samples import UPGRADE_PROMPT
        from vsc.adapters.persistence.postgres.budget_store import native_units,operation_key
        logical=normalize_request(dict(prompt=UPGRADE_PROMPT,operation='draft_upgrade',source_media_id='source',source_sha256='a'*64,source_duration_ms=5000,duration_ms=5000),'shot','video_upgrade','video')
        model=dict(id='model',model_key=MODEL,model_version='1080p',provider_id='account',default_params={'resolution':'1080p'},capabilities={'video_draft':True},cost_rule={'unit':'video_seconds','unit_price':'0.3','currency':'CNY','basis':'cash','source_url':'https://example.test/synthetic-price','source_date':'2026-10-01'})
        quote=quote_request(model,logical,native_units(logical));row=dict(quote,operation=operation_key(logical,0))
        document={'format':'vsc.generation-quote/v1','jobs':[row],'native_units':native_units(logical),'all_prices_known':True,'known_subtotals':{'CNY':'1.5'},'unknown_jobs':0};document['quote_sha256']=fingerprint(document)
        self.assertEqual(check_pinned({'generation_quote':document},model,logical,0)['amount'],'1.5')
        changed=deepcopy(model);changed['cost_rule']['unit_price']='0.4'
        with self.assertRaises(ResourceError) as error:check_pinned({'generation_quote':document},changed,logical,0)
        self.assertEqual(error.exception.code,'generation_quote_stale')
