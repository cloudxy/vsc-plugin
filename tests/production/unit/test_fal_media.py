"""Native queue wire contracts, fixed bytes and recovery; no external calls."""
from dataclasses import replace
import base64
import hashlib
import io
import json
from types import SimpleNamespace
import unittest

import httpx
from PIL import Image
from vsc.adapters.providers.fal_media import BASE, FalMediaProvider, fal_media_factory
from vsc.assets.resource_service import ResourceError
from vsc.production.fal_tools import ENDPOINTS, image_operation_fields, normalize_params, validate_output
from vsc.production.providers import ImageRequest, JobHandle


class FalMediaTests(unittest.TestCase):
    def setUp(self):
        stream = io.BytesIO(); Image.new('RGB', (960, 540), (40, 80, 120)).save(stream, format='PNG')
        self.content = stream.getvalue(); self.digest = hashlib.sha256(self.content).hexdigest()
        self.row = {'media_id': 'source', 'blob_sha256': self.digest, 'role': 'operation_source', 'mime_type': 'image/png',
                    'locations': [{'storage': 'local', 'available': True, 'object_key': 'source'}]}
        self.storage = SimpleNamespace(read=lambda key, digest: self.content)
        self.source = {'id': 'source', 'sha256': self.digest, 'modality': 'image', 'width': 960, 'height': 540}
        self.request = ImageRequest('shot', 'image_edit', 'a' * 64, '保留自然山景',
            **image_operation_fields('panorama', self.source, {}))
        self.receipt = {'request_id': 'task_1', 'status': 'IN_QUEUE', **{name: BASE + '/' + ENDPOINTS['panorama'] + '/requests/task_1' + suffix
            for name, suffix in [('response_url', ''), ('status_url', '/status'), ('cancel_url', '/cancel')]}}

    def adapter(self, transport, model=None):
        return FalMediaProvider(model or ENDPOINTS['panorama'], 'fal-account', [self.row], self.storage,
            client=httpx.Client(transport=httpx.MockTransport(transport)), read_key=lambda: 'fixture-secret-only')

    def test_queue_preserves_original_urls_across_processes_and_maps_native_image_bytes(self):
        calls = []
        def transport(request):
            calls.append(request)
            self.assertEqual(request.headers['authorization'], 'Key fixture-secret-only')
            if request.method == 'POST':
                body = json.loads(request.content)
                self.assertEqual(set(body), {'image_url', 'prompt', 'enable_safety_checker'})
                self.assertEqual(base64.b64decode(body['image_url'].split(',', 1)[1]), self.content)
                self.assertEqual(body['prompt'], self.request.prompt)
                return httpx.Response(200, json={**self.receipt, 'input_echo': body})
            if request.url.path.endswith('/status'):
                return httpx.Response(200, json={'request_id': 'task_1', 'status': 'IN_PROGRESS' if len(calls) == 2 else 'COMPLETED'})
            return httpx.Response(200, json={'image': {'url': 'https://v3.fal.media/output.png', 'width': 200, 'height': 100, 'content_type': 'image/png'}})
        first = self.adapter(transport).submit(self.request)
        self.assertNotIn('input_echo', first.raw)
        status = self.adapter(transport).poll(first)
        self.assertEqual(status.status, 'running')
        self.assertEqual(status.raw['status_url'], self.receipt['status_url'])
        restored = JobHandle(first.provider, first.model, first.external_task_id, json.loads(json.dumps(status.raw)))
        result = self.adapter(transport).poll(restored)
        self.assertEqual(result.status, 'succeeded')
        output = self.adapter(transport).parse_result(result.raw)[0]
        self.assertEqual(output.temporary_uri, 'https://v3.fal.media/output.png')
        self.assertNotIn('width', output.metadata)
        self.assertEqual([r.method for r in calls], ['POST', 'GET', 'GET', 'GET'])

    def test_http_unknown_and_foreign_receipts_cannot_be_terminal_or_resubmitted(self):
        handle = JobHandle('fal-account', ENDPOINTS['panorama'], 'task_1', self.receipt)
        for code in (403, 404, 429, 502, 302):
            with self.subTest(http=code):
                calls = []
                def transport(request):
                    calls.append(request); return httpx.Response(code, headers={'location': 'https://foreign.invalid'})
                with self.assertRaises(ResourceError) as error:
                    self.adapter(transport).poll(handle)
                self.assertEqual(error.exception.code, 'fal_receipt_unknown')
                self.assertEqual([r.method for r in calls], ['GET'])
        for changed in ({'request_id': 'another'}, {'response_url': 'https://evil.invalid/task'}, {'status': 'FAILED'}, {'status_url': self.receipt['status_url'] + '?redirect=evil'}):
            with self.subTest(receipt=changed), self.assertRaises(ResourceError):
                self.adapter(lambda request: httpx.Response(200, json={**self.receipt, **changed})).poll(handle)
        for changed in ({'status_url': 'https://queue.fal.run@evil.invalid/a'}, {'cancel_url': self.receipt['cancel_url'] + '#x'}, {'response_url': self.receipt['response_url'].replace('task_1', 'task_2')}):
            with self.subTest(saved=changed), self.assertRaises(ResourceError):
                self.adapter(lambda request: self.fail('unsafe handle reached transport')).poll(replace(handle, raw={**self.receipt, **changed}))

    def test_only_completed_with_error_is_failure_and_cancel_ack_is_not_terminal(self):
        handle = JobHandle('fal-account', ENDPOINTS['panorama'], 'task_1', self.receipt)
        calls = []
        def transport(request):
            calls.append(request)
            if request.method == 'PUT': return httpx.Response(200, json={'success': True})
            return httpx.Response(200, json={'request_id': 'task_1', 'status': 'COMPLETED', 'error': 'fixture-secret-only failed', 'error_type': 'runner_error'})
        adapter = self.adapter(transport)
        self.assertEqual(adapter.cancel(handle), {'request_id': 'task_1', 'cancel_requested': True})
        status = adapter.poll(handle)
        self.assertEqual(status.status, 'failed'); self.assertNotIn('fixture-secret-only', json.dumps(status.raw))
        self.assertEqual([r.method for r in calls], ['PUT', 'GET'])
        self.assertEqual(calls[0].url.path, '/fal-ai/hunyuan_world/requests/task_1/cancel')

    def test_submit_timeout_invalid_receipt_and_result_have_no_implicit_retry(self):
        calls = []
        def timeout(request):
            calls.append(request); raise httpx.ReadTimeout('lost', request=request)
        with self.assertRaises(ResourceError): self.adapter(timeout).submit(self.request)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ResourceError): self.adapter(lambda request: httpx.Response(200, json={'request_id': 'task_1'})).submit(self.request)
        adapter = self.adapter(lambda request: self.fail('parse_result made HTTP'))
        for result in ({'images': [{'url': 'https://v3.fal.media/a.png'}]}, {'image': {'url': 'http://v3.fal.media/a.png'}},
                       {'image': {'url': 'https://v3.fal.media/a.png', 'content_type': 'video/mp4'}}, {'image': {'url': 'https://v3.fal.media/a.png', 'width': True}}):
            with self.subTest(result=result), self.assertRaises(ResourceError):
                adapter.parse_result({**self.receipt, 'status': 'COMPLETED', 'result': result})

    def test_upscale_uses_native_factor_and_fixed_decoded_shape(self):
        request = ImageRequest('shot', 'image_edit', 'a' * 64, '保持原图细节', **image_operation_fields('upscale', self.source, {'target': '4k'}))
        self.assertEqual((request.width, request.height), (3840, 2160))
        self.assertEqual(request.params['upscale_factor'], 4)
        def transport(wire):
            body = json.loads(wire.content)
            self.assertEqual(body['upscale_factor'], 4); self.assertEqual(body['creativity'], .35); self.assertEqual(body['resemblance'], .6)
            self.assertNotIn('target', body); self.assertFalse(body['sync_mode'])
            return httpx.Response(200, json={key: value.replace('hunyuan_world', 'clarity-upscaler') if isinstance(value, str) else value for key, value in self.receipt.items()})
        self.adapter(transport, ENDPOINTS['upscale']).submit(request)
        validate_output(vars(request), {'modality': 'image', 'width': 3840, 'height': 2160})
        with self.assertRaises(ResourceError): validate_output(vars(request), {'modality': 'image', 'width': 960, 'height': 540})
        with self.assertRaises(ResourceError): image_operation_fields('upscale', self.source, {'target': '8k'})
        for params in ({'upscale_factor': 5}, {'upscale_factor': float('nan')}, {'creativity': True}, {'sync_mode': True}):
            with self.subTest(params=params), self.assertRaises(ResourceError): normalize_params('upscale', params)

    def test_source_hash_role_decode_and_factory_configuration_are_strict(self):
        adapter = self.adapter(lambda request: self.fail('invalid source reached transport'))
        with self.assertRaises(ResourceError): adapter.preflight(replace(self.request, source_sha256='b' * 64))
        self.row['role'] = 'reference_image'
        with self.assertRaises(ResourceError): adapter.preflight(self.request)
        self.row['role'] = 'operation_source'; self.content = b'not an image'
        with self.assertRaises(ResourceError): adapter.preflight(self.request)
        provider = {'base_url': BASE, 'auth_ref': 'FAL_KEY', 'configuration': {'supplier': 'fal', 'product': 'media', 'plan': 'api', 'execution': 'api'}}
        job = {'provider': provider, 'provider_id': 'fal-account', 'modality': 'image', 'purpose': 'image_edit', 'model': {'model_key': ENDPOINTS['panorama'], 'default_params': {}}, 'input_media': [self.row]}
        self.assertIsInstance(fal_media_factory(job, self.storage), FalMediaProvider)
        for name, value in [('base_url', 'https://fal.run'), ('auth_ref', 'ARK_AGENT_PLAN_API_KEY')]:
            with self.subTest(name=name), self.assertRaises(ResourceError): fal_media_factory({**job, 'provider': {**provider, name: value}}, self.storage)
        with self.assertRaises(ResourceError): fal_media_factory({**job, 'model': {**job['model'], 'default_params': {'seed': 3}}}, self.storage)

    def test_panorama_contract_rejects_flat_non_equirectangular_output(self):
        validate_output(vars(self.request), {'modality': 'image', 'width': 1920, 'height': 960})
        for media in ({'modality': 'image', 'width': 1024, 'height': 1024}, {'modality': 'video', 'width': 1920, 'height': 960}):
            with self.subTest(media=media), self.assertRaises(ResourceError): validate_output(vars(self.request), media)
        with self.assertRaises(ResourceError): normalize_params('panorama', {'projection': 'cube'})
