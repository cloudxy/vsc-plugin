"""Native SAM3 candidate masks and OmniHuman speaking-subject requests.

Only the existing FAL queue owns submission recovery. Inputs are actual fixed
local bytes; no hosted-path prompt, hidden upload, fallback or automatic retry.
"""
from __future__ import annotations

import base64
import hashlib
import io
from types import SimpleNamespace
from urllib.parse import urlsplit

from vsc.assets.resource_service import ResourceError
from vsc.adapters.providers.fal_media import BASE, KEY_ENV, MAX_INPUT_BYTES, FalMediaProvider
from vsc.production.digital_human import (AVATAR_MODEL, DETECTION_MODEL, DETECTION_PROMPT, MAX_MASKS,
    audio_duration, avatar_params, bounded_number, detection_params, performance_prompt, validate_mask_bytes)
from vsc.production.providers import GeneratedAsset


class FalAvatarProvider(FalMediaProvider):
    def preflight(self, request=None):
        if self.model not in {DETECTION_MODEL, AVATAR_MODEL}:
            raise ResourceError('请选择已核实的主体识别或数字人模型', 'invalid_model_defaults')
        self._key()
        if request is not None:
            self._body(request)

    def _fixed_bytes(self, identifier, role, digest=None):
        row = self.fixed.get(identifier)
        if not row or row.get('role') != role or digest is not None and row.get('blob_sha256') != digest:
            raise ResourceError('主体、mask或音轨不属于本任务固定输入', 'unfixed_reference')
        digest = row.get('blob_sha256')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ResourceError('固定素材缺少真实摘要', 'unfixed_reference')
        location = next((r for r in row.get('locations', []) if r.get('storage') == 'local' and r.get('available')), None)
        if not location:
            raise ResourceError('主体输入在本机不可用', 'media_unavailable')
        content = self.storage.read(location['object_key'], digest)
        if hashlib.sha256(content).hexdigest() != digest or not content or len(content) > MAX_INPUT_BYTES:
            raise ResourceError('固定素材已改变或超过64MiB输入边界', 'avatar_source_invalid')
        return row, location, content

    @staticmethod
    def _uri(content, mime):
        return 'data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii')

    def _body(self, request):
        if self.model == DETECTION_MODEL:
            if (request.purpose != 'image_edit' or getattr(request, 'operation', None) != 'subject_detect' or
                    request.prompt != DETECTION_PROMPT or request.reference_media_ids or
                    any(getattr(request, key, None) for key in ('mask_media_id', 'mask_sha256'))):
                raise ResourceError('主体识别只能处理当前唯一原图', 'subject_inputs_invalid')
            params = detection_params(request.params)
            if len(self.fixed) != 1:
                raise ResourceError('主体识别不能混入其他图片', 'subject_inputs_invalid')
            # Existing source reader checks operation_source and the exact SHA,
            # decodes the image and normalizes EXIF orientation for transport.
            uri, shape = self._source(request)
            if (shape['width'], shape['height']) != (request.width, request.height):
                raise ResourceError('识别请求尺寸与固定原图不符', 'subject_image_invalid')
            return {'image_url': uri, 'prompt': DETECTION_PROMPT, 'point_prompts': [], 'box_prompts': [],
                    'apply_mask': False, 'sync_mode': False, 'output_format': 'png',
                    'return_multiple_masks': True, 'max_masks': params['max_masks'],
                    'include_scores': True, 'include_boxes': True}
        if (self.model != AVATAR_MODEL or request.purpose != 'digital_human' or
                len(request.reference_media_ids) != 1 or len(request.reference_audio_media_ids) != 1 or
                any(getattr(request, key, None) for key in ('operation', 'first_frame_media_id', 'last_frame_media_id', 'keyframes', 'reference_video_media_ids', 'draft'))):
            raise ResourceError('主体数字人需要唯一形象、音轨和固定mask', 'avatar_inputs_invalid')
        params = avatar_params(request.params)
        prompt = performance_prompt(request.prompt)
        image_id, audio_id = request.reference_media_ids[0], request.reference_audio_media_ids[0]
        mask_id, mask_sha = getattr(request, 'subject_mask_media_id', None), getattr(request, 'subject_mask_sha256', None)
        if len({image_id, audio_id, mask_id}) != 3 or set(self.fixed) != {image_id, audio_id, mask_id} or not mask_sha:
            raise ResourceError('数字人须固定三个独立媒体，不能省略或混入其他来源', 'avatar_inputs_invalid')
        image_row, _, _ = self._fixed_bytes(image_id, 'portrait')
        # Reuse the same checked image normalization without changing the
        # persisted portrait role or inventing another media fact.
        reader = FalMediaProvider(self.model, self.provider_id,
            [{**image_row, 'role': 'operation_source'}], self.storage, client=self.client, read_key=self.read_key)
        image_uri, shape = reader._source(SimpleNamespace(source_media_id=image_id, source_sha256=image_row['blob_sha256'], operation='avatar'))
        _, _, mask = self._fixed_bytes(mask_id, 'subject_mask', mask_sha)
        validate_mask_bytes(mask, (shape['width'], shape['height']))
        audio_row, location, audio = self._fixed_bytes(audio_id, 'speech')
        if audio_row.get('mime_type') not in {'audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/aac', 'audio/flac', 'audio/x-flac'}:
            raise ResourceError('驱动文件不是已登记音轨', 'avatar_audio_invalid')
        from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
        try:
            proof = (getattr(self.storage, 'probe', None) or LocalProbeAdapter()).probe(self.storage.verify(location['object_key'], audio_row['blob_sha256']))
        except (OSError, ProbeFailure) as error:
            raise ResourceError('驱动音轨未通过完整解码', 'avatar_audio_invalid') from error
        seconds = proof.get('duration_seconds')
        if (proof.get('sha256') != audio_row['blob_sha256'] or proof.get('decode', {}).get('status') != 'passed' or
                not bounded_number(seconds, .001, 60) or not any(row.get('codec_type') == 'audio' for row in proof.get('streams', [])) or
                any(row.get('codec_type') == 'video' for row in proof.get('streams', []))):
            raise ResourceError('驱动音轨身份或实际解码结果无效', 'avatar_audio_invalid')
        actual_ms = round(seconds * 1000)
        audio_duration(actual_ms, params)
        if actual_ms != request.duration_ms:
            raise ResourceError('任务时长须等于固定音轨实际时长，不自动裁剪或填充', 'avatar_audio_duration')
        return {'image_url': image_uri, 'mask_url': self._uri(mask, 'image/png'),
                'audio_url': self._uri(audio, audio_row['mime_type']), 'prompt': prompt, **params}

    @staticmethod
    def _file(row, modality):
        url = row.get('url') if isinstance(row, dict) else None
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or len(url) > 8192:
            raise ResourceError('主体处理结果缺少安全HTTPS文件地址', 'fal_output_invalid')
        if row.get('content_type') is not None and (not isinstance(row['content_type'], str) or not row['content_type'].startswith(modality + '/')):
            raise ResourceError('主体处理结果模态不符', 'fal_output_invalid')
        return {'url': url}

    def _output(self, value):
        if self.model == AVATAR_MODEL:
            if not bounded_number(value.get('duration'), .001, 60):
                raise ResourceError('数字人回执缺少原生duration', 'fal_output_invalid')
            return {'video': self._file(value.get('video'), 'video'), 'duration': value['duration']}
        masks = value.get('masks')
        if not isinstance(masks, list) or len(masks) > MAX_MASKS:
            raise ResourceError('主体识别没有可核对的mask列表', 'fal_output_invalid')
        result = {'masks': [self._file(row, 'image') for row in masks]}
        metadata = value.get('metadata', [])
        if not isinstance(metadata, list):
            raise ResourceError('主体候选索引元数据无效', 'fal_output_invalid')
        fixed = []; seen = set()
        for row in metadata:
            if not isinstance(row, dict) or type(row.get('index')) is not int or not 0 <= row['index'] < len(masks) or row['index'] in seen:
                raise ResourceError('主体候选索引超出原始mask集合', 'fal_output_invalid')
            item = {'index': row['index']}; seen.add(row['index'])
            if row.get('score') is not None:
                if not bounded_number(row['score'], 0, 1):
                    raise ResourceError('主体候选置信值无效', 'fal_output_invalid')
                item['score'] = row['score']
            if row.get('box') is not None:
                box = row['box']
                if not isinstance(box, list) or len(box) != 4 or not all(bounded_number(x, 0, 1) for x in box) or min(box[2:]) <= 0:
                    raise ResourceError('主体候选边界框无效', 'fal_output_invalid')
                item['box'] = box
            fixed.append(item)
        result['metadata'] = fixed
        return result

    def parse_result(self, raw):
        receipt = self._queue(raw, complete_urls=True)
        if receipt.get('status') != 'COMPLETED' or receipt.get('error') or receipt.get('error_type') or not isinstance(raw.get('result'), dict):
            raise ResourceError('主体处理尚无可核对成功回执', 'fal_output_invalid')
        value = self._output(raw['result'])
        metadata = {'fal_request_id': receipt['request_id'], 'fal_model': self.model}
        if self.model == AVATAR_MODEL:
            return [GeneratedAsset('video', temporary_uri=value['video']['url'], metadata={**metadata, 'provider_duration': value['duration']})]
        if not value['masks']:
            raise ResourceError('本次识别未找到人物；可手绘主体区域或明确发起新识别', 'subject_not_found')
        by_index = {row['index']: row for row in value['metadata']}
        return [GeneratedAsset('image', temporary_uri=row['url'], metadata={**metadata, 'subject_index': index,
                    'subject_metadata': by_index.get(index, {'index': index})}) for index, row in enumerate(value['masks'])]


def fal_avatar_factory(job, storage, *, client=None, read_key=None):
    provider = job['provider']; config = provider.get('configuration', {}); model = job['model']['model_key']
    expected = ('image', 'image_edit') if model == DETECTION_MODEL else ('video', 'digital_human')
    if (model not in {DETECTION_MODEL, AVATAR_MODEL} or (job['modality'], job['purpose']) != expected or
            (config.get('supplier'), config.get('product'), config.get('plan'), config.get('execution')) != ('fal', 'media', 'api', 'api') or
            provider['base_url'].rstrip('/') != BASE or provider['auth_ref'] != KEY_ENV or job['model'].get('default_params')):
        raise ResourceError('主体处理须使用独立FAL_KEY、原生模型与官方队列', 'invalid_provider_config')
    return FalAvatarProvider(model, job['provider_id'], job['input_media'], storage, client=client, read_key=read_key)
