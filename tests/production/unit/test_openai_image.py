"""No live requests: actual multipart body, PNG bytes and fixed-source validation."""
from __future__ import annotations
import base64
from dataclasses import asdict
from email import policy
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import httpx
from PIL import Image
from vsc.adapters.providers.openai_image import OpenAIImageProvider, openai_image_factory, validate_inpaint_bytes
from vsc.assets.resource_service import ResourceError
from vsc.production.providers import ImageRequest, JobHandle
from vsc.production.image_tools import render_reference


def png(size=(64,64), color=(30,50,90,255)):
    data=io.BytesIO();Image.new('RGBA',size,color).save(data,format='PNG');return data.getvalue()


class OpenAIImageTests(unittest.TestCase):
    def setUp(self):
        self.source=png(); image=Image.new('RGBA',(64,64),(255,255,255,255))
        image.putpixel((20,20),(255,255,255,0));stream=io.BytesIO();image.save(stream,format='PNG');self.mask=stream.getvalue()
        self.contents={'source':self.source,'mask':self.mask}
        self.digests={key:hashlib.sha256(value).hexdigest() for key,value in self.contents.items()}
        self.rows=[{'media_id':key,'blob_sha256':self.digests[key],'role':role,'locations':[{'storage':'local','available':True,'object_key':key}]} for key,role in [('source','operation_source'),('mask','operation_mask')]]
        self.storage=SimpleNamespace(read=lambda key,digest:self.contents[key])
        self.request=SimpleNamespace(**{**asdict(ImageRequest('shot','image_edit','a'*64,'将圈选的区域改成红色',width=1024,height=1024)), 'operation':'inpaint','source_media_id':'source','source_sha256':self.digests['source'],'mask_media_id':'mask','mask_sha256':self.digests['mask']})

    def adapter(self,handler):
        return OpenAIImageProvider('gpt-image-1.5','account',self.rows,self.storage,client=httpx.Client(transport=httpx.MockTransport(handler)),read_key=lambda:'test-only')

    def test_multipart_keeps_source_and_alpha_mask_separate_and_poll_never_resubmits(self):
        calls=[]
        def transport(request):
            calls.append(request)
            self.assertEqual(str(request.url),'https://api.openai.com/v1/images/edits')
            message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.read())
            parts={part.get_param('name',header='content-disposition'):part for part in message.iter_parts()}
            self.assertEqual(parts['image'].get_payload(decode=True),self.source)
            self.assertEqual(parts['mask'].get_payload(decode=True),self.mask)
            mask=Image.open(io.BytesIO(parts['mask'].get_payload(decode=True)))
            self.assertEqual(mask.getpixel((20,20))[3],0);self.assertEqual(mask.getpixel((0,0))[3],255)
            self.assertEqual(parts['n'].get_payload(decode=True),b'1')
            self.assertNotIn('response_format',parts)
            return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png((1024,1024))).decode()}]})
        adapter=self.adapter(transport);handle=adapter.submit(self.request)
        self.assertIsNone(handle.external_task_id)
        for _ in range(2):self.assertEqual(adapter.poll(handle).status,'succeeded')
        self.assertEqual(len(calls),1)
        self.assertEqual(adapter.parse_result(handle.raw)[0].modality,'image')

    def test_fixed_hash_role_dimensions_and_alpha_are_verified_before_http(self):
        adapter=self.adapter(lambda request:self.fail('invalid input reached HTTP'))
        for field in ['source_sha256','mask_sha256']:
            with self.subTest(field=field):
                request=SimpleNamespace(**vars(self.request));setattr(request,field,'f'*64)
                with self.assertRaisesRegex(ResourceError,'固定输入'):adapter.preflight(request)
        self.contents['mask']=png()
        with self.assertRaisesRegex(ResourceError,'摘要已改变'):adapter.preflight(self.request)
        for mask in [png((32,32)),png()]:
            with self.subTest(mask_length=len(mask)),self.assertRaises(ResourceError):validate_inpaint_bytes(self.source,mask)
        stream=io.BytesIO();Image.new('L',(64,64),0).save(stream,format='PNG')
        with self.assertRaises(ResourceError):validate_inpaint_bytes(self.source,stream.getvalue())
        self.contents['mask']=self.mask;self.rows[1]['role']='reference_image'
        with self.assertRaises(ResourceError):adapter.preflight(self.request)

    def test_unknown_receipt_does_not_create_status_query_or_retry(self):
        calls=[]
        def timeout(request):calls.append(request);raise httpx.ReadTimeout('lost',request=request)
        adapter=self.adapter(timeout)
        with self.assertRaises(ResourceError) as error:adapter.submit(self.request)
        self.assertEqual(error.exception.code,'image_edit_receipt_unknown')
        with self.assertRaises(ResourceError):adapter.poll(JobHandle('account','gpt-image-1.5',None,{}))
        self.assertEqual(len(calls),1)
        for status in [302,401,429,503]:
            with self.subTest(status=status),self.assertRaises(ResourceError):self.adapter(lambda request:httpx.Response(status)).submit(self.request)

    def test_export_keeps_black_white_contract_and_adds_fixed_alpha_mask(self):
        document={'id':'edit','source_media_id':'source','source_sha256':self.digests['source'],'source_modality':'image','time_ms':0,'width':64,'height':64,'operations':[{'id':'stroke','tool':'mask','points':[[.5,.5]],'width':.1,'color':'#ffffff'}]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.png';path.write_bytes(self.source)
            outputs={row['role']:row['bytes'] for row in render_reference(path,document)}
        grayscale=Image.open(io.BytesIO(outputs['mask']));alpha=Image.open(io.BytesIO(outputs['inpaint-mask']))
        self.assertEqual(grayscale.mode,'L');self.assertEqual(grayscale.getpixel((32,32)),255)
        self.assertEqual(alpha.mode,'RGBA');self.assertEqual(alpha.getpixel((32,32))[3],0)
        self.assertEqual(alpha.getpixel((0,0))[3],255)
        validate_inpaint_bytes(self.source,outputs['inpaint-mask'])

    def test_factory_rejects_foreign_endpoint_account_and_defaults(self):
        provider={'base_url':'https://api.openai.com/v1','auth_ref':'OPENAI_API_KEY','configuration':{'supplier':'openai','product':'images','plan':'api','execution':'api'}}
        job={'provider':provider,'provider_id':'account','modality':'image','purpose':'image_edit','model':{'model_key':'gpt-image-1.5','default_params':{}},'input_media':self.rows}
        self.assertIsInstance(openai_image_factory(job,self.storage),OpenAIImageProvider)
        for name,value in [('base_url','https://foreign.invalid/v1'),('auth_ref','ARK_AGENT_PLAN_API_KEY')]:
            with self.subTest(name=name),self.assertRaises(ResourceError):openai_image_factory({**job,'provider':{**provider,name:value}},self.storage)
        with self.assertRaises(ResourceError):openai_image_factory({**job,'model':{**job['model'],'default_params':{'unknown':1}}},self.storage)
