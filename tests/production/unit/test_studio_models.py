import base64
import unittest

from vsc.assets.resource_service import ResourceError
from vsc.production.resource_settings import validate_configuration,adapter_available
from vsc.production.studio_models import auth_configuration,is_studio_auth_configuration
from vsc.adapters.providers.studio_auth import StudioAuthImageProvider
from vsc.production.providers import ImageRequest,JobHandle


class StudioModelsTests(unittest.TestCase):
    def test_subscription_shapes_use_existing_login_and_never_an_environment_key(self):
        for provider in ('agy_auth','codex_auth','grok_auth','grok_video_auth'):
            with self.subTest(provider=provider):
                config=validate_configuration(auth_configuration(provider))
                self.assertTrue(adapter_available(config))
                self.assertEqual(config['auth_ref'],'')
        advanced=auth_configuration('grok_video_auth','grok-imagine-video-1.5')
        self.assertTrue(advanced['capabilities']['last_frame'])
        self.assertEqual(advanced['capabilities']['max_reference_images'],14)
        self.assertFalse(auth_configuration('grok_video_auth','grok-imagine-video-1.5-lite')['capabilities']['last_frame'])
        self.assertTrue(adapter_available(validate_configuration(auth_configuration('grok_auth','grok-imagine-image-2.0'))))
        forged=auth_configuration('agy_auth');forged['auth_ref']='OTHER_SERVICE_KEY'
        self.assertFalse(is_studio_auth_configuration(forged))
        with self.assertRaises(ResourceError):validate_configuration(forged)

    def test_auth_adapter_accepts_text_only_and_preserves_the_original_handle(self):
        calls=[]
        job=dict(provider_id='local-config',model=dict(model_key='image-generator'),input_media=[],
                 provider={'configuration':{'tool_id':'api-settings-agy_auth'}})
        provider=StudioAuthImageProvider(job,None,lambda channel,body:(calls.append((channel,body)) or dict(image_url='data:image/png;base64,'+base64.b64encode(b'synthetic-bytes').decode())))
        request=ImageRequest('shot','first_frame','a'*64,'Synthetic image',width=1080,height=1920)
        handle=provider.submit(request)
        self.assertEqual((handle.provider,handle.model),('local-config','image-generator'))
        self.assertEqual(calls[0][1]['aspect_ratio'],'9:16')
        self.assertEqual(calls[0][1]['references'],[])
        self.assertEqual(provider.parse_result(provider.poll(handle).raw)[0].inline_bytes,b'synthetic-bytes')
        with self.assertRaises(ResourceError):provider.poll(JobHandle('another-config','image-generator',None,handle.raw))
        with self.assertRaises(ResourceError):provider.parse_result({'image_url':'https://example.invalid/not-fixed.png'})
        with self.assertRaises(ResourceError):provider.preflight(ImageRequest('shot','first_frame','a'*64,'test',params={'seed':1}))
        with self.assertRaises(ResourceError):StudioAuthImageProvider(job,None,None).preflight(request)

    def test_rejection_and_timeout_keep_original_failure_receipt_without_resubmission(self):
        job=dict(provider_id='local-config',model=dict(model_key='image-generator'),input_media=[],
                 provider={'configuration':{'tool_id':'api-settings-agy_auth'}})
        for http_status,expected in ((403,'failed'),(504,'submission_unknown')):
            with self.subTest(http_status=http_status):
                calls=[]
                def generate(*args):
                    calls.append(args)
                    return dict(error='Sanitized provider reason',http_status=http_status)
                provider=StudioAuthImageProvider(job,None,generate)
                handle=provider.submit(ImageRequest('shot','first_frame','a'*64,'Synthetic image'))
                result=provider.poll(handle)
                self.assertEqual(result.status,expected)
                self.assertEqual(result.raw['error'],'Sanitized provider reason')
                self.assertEqual(result.error_code,'studio_auth_generation_failed')
                self.assertEqual(len(calls),1)
