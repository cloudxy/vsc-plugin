"""Official-shaped transports with controlled image/mask/audio bytes only."""
from dataclasses import dataclass
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

import httpx
from PIL import Image, ImageDraw

from vsc.adapters.providers.fal_avatar import FalAvatarProvider
from vsc.adapters.providers.fal_media import BASE
from vsc.adapters.storage.local.store import LocalStorage
from vsc.assets.resource_service import ResourceError
from vsc.production.digital_human import (AVATAR_MODEL, DETECTION_MODEL, avatar_request_fields,
    audio_duration, detection_request_fields, normalize_selection, performance_prompt, validate_mask_bytes)
from vsc.production.providers import ImageRequest, VideoRequest


@dataclass(frozen=True)
class SubjectVideo(VideoRequest):
    subject_mask_media_id: str | None = None
    subject_mask_sha256: str | None = None


class FalAvatarTests(unittest.TestCase):
    def test_new_mask_fields_do_not_change_existing_video_operation_payloads(self):
        from dataclasses import asdict
        from vsc.production.run_authorization import normalize_request
        value=asdict(VideoRequest('shot','video_edit','a'*64,'Change the light',operation='edit',
            source_media_id='source',source_sha256='b'*64,source_duration_ms=5000))
        normalized=normalize_request(value,'shot','video_edit','video')
        self.assertNotIn('subject_mask_media_id',normalized)
        self.assertEqual(normalized['source_sha256'],'b'*64)
        with self.assertRaises(ResourceError):normalize_request({**value,'subject_mask_media_id':'foreign'},'shot','video_edit','video')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vsc-avatar-unit-'); self.addCleanup(self.temp.cleanup)
        self.storage = LocalStorage(self.temp.name); self.fixed = []; self.contents = {}
        image = io.BytesIO(); Image.new('RGB', (80, 60), (10, 30, 50)).save(image, format='PNG')
        mask = Image.new('L', (80, 60)); ImageDraw.Draw(mask).rectangle((45, 10, 70, 50), fill=255)
        stream = io.BytesIO(); mask.save(stream, format='PNG')
        sound = io.BytesIO()
        with wave.open(sound, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b'\0\0' * 9600)
        for identifier, role, content, mime in [('portrait', 'portrait', image.getvalue(), 'image/png'),
                ('mask', 'subject_mask', stream.getvalue(), 'image/png'), ('speech', 'speech', sound.getvalue(), 'audio/wav')]:
            sha = hashlib.sha256(content).hexdigest(); (Path(self.temp.name) / identifier).write_bytes(content)
            self.contents[identifier] = content
            self.fixed.append(dict(media_id=identifier, role=role, blob_sha256=sha, mime_type=mime,
                locations=[dict(storage='local', available=True, object_key=identifier)]))

    def request(self):
        return SubjectVideo('shot', 'digital_human', 'a' * 64, '右侧人物平静讲话。', ['portrait'],
            {'resolution': '720p', 'turbo_mode': False}, duration_ms=1200,
            reference_audio_media_ids=['speech'], subject_mask_media_id='mask', subject_mask_sha256=self.fixed[1]['blob_sha256'])

    def provider(self, model, fixed, result):
        calls = []; app = '/'.join(model.split('/')[:2]); task = 'fixed-task'
        receipt = dict(request_id=task, status='IN_QUEUE', **{key: BASE + '/' + app + '/requests/' + task + suffix
            for key, suffix in [('response_url', ''), ('status_url', '/status'), ('cancel_url', '/cancel')]})
        def transport(request):
            calls.append(request)
            if request.method == 'POST': return httpx.Response(200, json=receipt)
            if request.url.path.endswith('/status'): return httpx.Response(200, json={'request_id': task, 'status': 'COMPLETED'})
            return httpx.Response(200, json=result)
        client = httpx.Client(transport=httpx.MockTransport(transport)); self.addCleanup(client.close)
        return FalAvatarProvider(model, 'fal-test', fixed, self.storage, client=client, read_key=lambda: 'mock-only'), calls

    def test_avatar_wire_uses_three_fixed_files_and_original_owner_app_receipt(self):
        provider, calls = self.provider(AVATAR_MODEL, self.fixed, {'video': {'url': 'https://controlled.invalid/avatar.mp4'}, 'duration': 1.2})
        handle = provider.submit(self.request()); status = provider.poll(handle)
        body = json.loads(calls[0].content)
        for name, identifier in [('image_url', 'portrait'), ('mask_url', 'mask'), ('audio_url', 'speech')]:
            self.assertEqual(base64.b64decode(body[name].split(',', 1)[1]), self.contents[identifier])
        self.assertEqual(set(body), {'image_url', 'mask_url', 'audio_url', 'prompt', 'resolution', 'turbo_mode'})
        self.assertEqual(handle.raw['status_url'], BASE + '/fal-ai/bytedance/requests/fixed-task/status')
        self.assertEqual(provider.parse_result(status.raw)[0].modality, 'video')
        self.assertEqual([r.method for r in calls], ['POST', 'GET', 'GET'])

    def test_detection_has_one_request_with_stable_multiple_mask_indices(self):
        source = dict(id='portrait', sha256=self.fixed[0]['blob_sha256'], modality='image', width=80, height=60)
        fields = detection_request_fields(source); prompt = fields.pop('prompt')
        request = ImageRequest('shot', 'image_edit', 'a' * 64, prompt, **fields)
        result = {'masks': [{'url': 'https://controlled.invalid/one.png'}, {'url': 'https://controlled.invalid/two.png'}],
                  'metadata': [{'index': 1, 'score': .9, 'box': [.7, .5, .3, .8]}]}
        provider, calls = self.provider(DETECTION_MODEL, [{**self.fixed[0], 'role': 'operation_source'}], result)
        status = provider.poll(provider.submit(request)); outputs = provider.parse_result(status.raw)
        self.assertEqual([r.metadata['subject_index'] for r in outputs], [0, 1])
        self.assertEqual(outputs[1].metadata['subject_metadata']['score'], .9)
        body = json.loads(calls[0].content); self.assertFalse(body['apply_mask']); self.assertTrue(body['return_multiple_masks'])
        self.assertEqual(body['prompt'], 'person'); self.assertEqual(sum(r.method == 'POST' for r in calls), 1)

    def test_no_subject_preserves_completed_receipt_and_never_returns_fake_mask(self):
        provider, calls = self.provider(DETECTION_MODEL, [], {'masks': []})
        raw = {'request_id': 'fixed-task', 'status': 'COMPLETED', 'result': {'masks': []},
               **{k: BASE + '/fal-ai/sam-3/requests/fixed-task' + suffix for k, suffix in [('response_url', ''), ('status_url', '/status'), ('cancel_url', '/cancel')]}}
        with self.assertRaises(ResourceError) as raised: provider.parse_result(raw)
        self.assertEqual(raised.exception.code, 'subject_not_found'); self.assertEqual(raw['status'], 'COMPLETED'); self.assertFalse(calls)

    def test_audio_duration_and_performance_contract_are_exact(self):
        self.assertEqual(audio_duration(29999, {'resolution': '1080p'}), 29999)
        self.assertEqual(audio_duration(59999, {'resolution': '720p'}), 59999)
        for duration, resolution in [(30000, '1080p'), (60000, '720p'), (True, '720p')]:
            with self.subTest(duration=duration), self.assertRaises(ResourceError): audio_duration(duration, {'resolution': resolution})
        self.assertEqual(performance_prompt('表' * 300), '表' * 300)
        with self.assertRaises(ResourceError): performance_prompt('表' * 301)
        provider, _ = self.provider(AVATAR_MODEL, self.fixed, {})
        from dataclasses import replace
        with self.assertRaises(ResourceError): provider.preflight(replace(self.request(), duration_ms=2000))

    def test_subject_masks_reject_alpha_blank_colour_and_mismatched_source(self):
        self.assertGreater(validate_mask_bytes(self.contents['mask'], (80, 60))['selected_pixels'], 0)
        for image in [Image.new('L', (80, 60), 0), Image.new('L', (80, 60), 255),
                      Image.new('RGBA', (80, 60), (255, 255, 255, 0)), Image.new('RGB', (80, 60), (255, 0, 0))]:
            stream = io.BytesIO(); image.save(stream, format='PNG')
            with self.assertRaises(ResourceError): validate_mask_bytes(stream.getvalue(), (80, 60))
        with self.assertRaises(ResourceError): validate_mask_bytes(self.contents['mask'], (60, 80))
        provider, calls = self.provider(AVATAR_MODEL, self.fixed, {})
        from dataclasses import replace
        with self.assertRaises(ResourceError): provider.preflight(replace(self.request(), subject_mask_sha256='f' * 64))
        self.assertFalse(calls)

    def test_selection_and_request_fix_original_mask_audio_and_source(self):
        source = dict(id='portrait', sha256=self.fixed[0]['blob_sha256'], modality='image', width=80, height=60)
        mask = dict(id='mask', sha256=self.fixed[1]['blob_sha256'], modality='image', width=80, height=60)
        audio = dict(id='speech', modality='audio', duration_ms=1200)
        fields = avatar_request_fields(source, audio, mask)
        self.assertEqual(fields['duration_ms'], 1200); self.assertEqual(fields['subject_mask_sha256'], mask['sha256'])
        selection = dict(origin='detected', source_media_id=source['id'], source_sha256=source['sha256'],
                         mask_media_id=mask['id'], mask_sha256=mask['sha256'], job_id='job', output_index=1)
        self.assertEqual(normalize_selection(selection)['output_index'], 1)
        with self.assertRaises(ResourceError): normalize_selection({**selection, 'output_index': -1})
        with self.assertRaises(ResourceError): normalize_selection({**selection, 'export_id': 'other'})
