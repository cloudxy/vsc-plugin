"""Native FAL queue media operations; the original worker owns all persistence.

No POST retry or fallback. Queue URLs are fixed from the submission receipt,
validated before sending credentials, and carried through every later response.
"""
from __future__ import annotations

import base64
import hashlib
import io
import math
import os
import re
from urllib.parse import urlsplit

from vsc.assets.resource_service import ResourceError
from vsc.production.fal_tools import DEPTH_PROMPT, ENDPOINTS, normalize_params
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus

BASE = 'https://queue.fal.run'
KEY_ENV = 'FAL_KEY'
MODELS = frozenset(ENDPOINTS.values())
_URL_FIELDS = {'response_url': '', 'status_url': '/status', 'cancel_url': '/cancel'}
MAX_INPUT_BYTES = 64 * 1024 * 1024


class FalMediaProvider:
    def __init__(self, model, provider_id, fixed_inputs, storage, *, client=None, read_key=None):
        self.model, self.provider_id = model, provider_id
        self.fixed = {row['media_id']: row for row in fixed_inputs}
        self.storage, self.client = storage, client
        self.read_key = read_key or (lambda: os.environ.get(KEY_ENV, ''))

    def _key(self):
        key = self.read_key()
        if not isinstance(key, str) or not key:
            raise ResourceError('未加载 FAL_KEY；请检查 ~/.zshenv，在启动进程的zsh中 source ~/.zshenv 后重启；其他启动方式需显式传入环境', 'credential_not_loaded')
        return key

    def _source(self, request):
        row = self.fixed.get(request.source_media_id)
        digest = request.source_sha256
        if not row or row.get('role') != 'operation_source' or row.get('blob_sha256') != digest or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ResourceError('媒体处理原件不属于任务的固定输入', 'unfixed_reference')
        location = next((loc for loc in row.get('locations', []) if loc.get('storage') == 'local' and loc.get('available')), None)
        if not location:
            raise ResourceError('固定媒体原件在本机不可用', 'media_unavailable')
        content = self.storage.read(location['object_key'], digest)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ResourceError('固定媒体原件摘要已改变', 'fal_source_changed')
        if not content or len(content) > MAX_INPUT_BYTES:
            raise ResourceError('当前原生媒体单次输入需为64MiB以内；请先裁剪源文件', 'fal_source_size')
        if request.operation != 'depth':
            from PIL import Image, ImageOps
            try:
                image = Image.open(io.BytesIO(content))
                if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 67108864:
                    raise ValueError('image format or size')
                image.load()
                oriented = ImageOps.exif_transpose(image)
                mime = Image.MIME[image.format]
                if image.getexif().get(274, 1) != 1:
                    stream = io.BytesIO(); oriented.save(stream, format='PNG')
                    content, mime = stream.getvalue(), 'image/png'
                shape = {'width': oriented.width, 'height': oriented.height}
            except (ValueError, OSError, Image.DecompressionBombError) as exc:
                raise ResourceError('固定原图无法完整解码', 'fal_source_invalid') from exc
        else:
            from vsc.adapters.media.qa import LocalProbeAdapter, ProbeFailure
            if row.get('mime_type') not in {'video/mp4', 'video/webm', 'video/quicktime'}:
                raise ResourceError('深度估计需要已登记的视频文件', 'fal_source_invalid')
            try:
                path = self.storage.verify(location['object_key'], digest)
                proof = (getattr(self.storage, 'probe', None) or LocalProbeAdapter()).probe(path)
            except (OSError, ProbeFailure) as exc:
                raise ResourceError('深度源视频未通过实际探测及完整解码', 'fal_source_invalid') from exc
            frames = proof.get('decode', {}).get('video_frames')
            if proof.get('sha256') != digest or proof.get('decode', {}).get('status') != 'passed' or type(frames) not in (int, float) or not 1 <= frames <= 2400 or int(frames) != frames:
                raise ResourceError('深度源视频须完整解码且不超过原生2400帧上限', 'depth_source_frames')
            duration = proof.get('duration_seconds')
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or abs(round(duration * 1000) - request.source_duration_ms) > 100:
                raise ResourceError('深度源视频实际时长与固定任务不符', 'depth_source_duration')
            mime, shape = row['mime_type'], {'frames': int(frames)}
        if len(content) > MAX_INPUT_BYTES:
            raise ResourceError('规范化图像超过单次输入上限', 'fal_source_size')
        return 'data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii'), shape

    def _body(self, request):
        operation = getattr(request, 'operation', None)
        if operation not in ENDPOINTS or self.model != ENDPOINTS[operation] or request.purpose != ('depth' if operation == 'depth' else 'image_edit'):
            raise ResourceError('原生模型与固定操作用途不符', 'fal_operation_mismatch')
        if not isinstance(request.prompt, str) or not request.prompt.strip() or len(request.prompt) > 20000:
            raise ResourceError('媒体处理需要明确、长度受限的说明', 'fal_parameters_invalid')
        if any(getattr(request, name, None) for name in ('reference_media_ids', 'mask_media_id', 'mask_sha256', 'reference_audio_media_ids', 'reference_video_media_ids', 'first_frame_media_id', 'last_frame_media_id', 'keyframes')):
            raise ResourceError('原生媒体处理只接受唯一固定源文件', 'fal_inputs_unsupported')
        params = normalize_params(operation, request.params)
        if operation == 'depth':
            if request.prompt != DEPTH_PROMPT or type(request.source_duration_ms) is not int or request.source_duration_ms <= 0 or request.duration_ms != request.source_duration_ms:
                raise ResourceError('深度估计使用固定处理说明及原片完整时长', 'depth_source_duration')
        uri, shape = self._source(request)
        if operation == 'panorama':
            return {'image_url': uri, 'prompt': request.prompt, 'enable_safety_checker': True}
        if operation == 'upscale':
            factor = params['upscale_factor']
            target = {'4k': 3840, '8k': 7680}[params['target']]
            expected = tuple(round(shape[key] * factor) for key in ('width', 'height'))
            if factor <= 1 or expected != (request.width, request.height) or max(expected) != target:
                raise ResourceError('超分倍率、原图尺寸与固定4K/8K目标不一致', 'upscale_target_invalid')
            return {'image_url': uri, 'prompt': request.prompt, **{key: params[key] for key in ('upscale_factor', 'creativity', 'resemblance')}, 'enable_safety_checker': True, 'sync_mode': False}
        return {'video_url': uri, 'model': params['depth_variant'], 'colormap': params['colormap'], 'resolution': params['resolution'],
                'max_frames': shape['frames'], 'side_by_side': False, 'include_raw_depths': False}

    def preflight(self, request=None):
        if self.model not in MODELS:
            raise ResourceError('请选择已核实的FAL原生媒体模型', 'invalid_model_defaults')
        self._key()
        if request is not None:
            self._body(request)

    def _request(self, method, url, payload=None):
        import httpx
        key = self._key()
        client = self.client or httpx.Client(timeout=120, follow_redirects=False)
        try:
            response = client.request(method, url, headers={'Authorization': 'Key ' + key}, follow_redirects=False,
                                      **({'json': payload} if payload is not None else {}))
            if not 200 <= response.status_code < 300:
                # HTTP authentication, expiry, capacity and temporary failures
                # say nothing about the original queue request's terminal state.
                raise ResourceError('FAL请求未取得可核对回执（HTTP ' + str(response.status_code) + '）；保留原任务，不重新提交', 'fal_receipt_unknown')
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError('response is not an object')
            return value
        except (httpx.HTTPError, ValueError) as exc:
            raise ResourceError('FAL回执暂不可核对；保留原任务，不重新提交', 'fal_receipt_unknown') from exc
        finally:
            if self.client is None:
                client.close()

    def _queue(self, value, request_id=None, *, complete_urls=False):
        identifier = value.get('request_id')
        if not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}', identifier) or request_id is not None and identifier != request_id:
            raise ResourceError('FAL回执缺失或属于其他任务', 'fal_receipt_unknown')
        result = {'request_id': identifier}
        # Full endpoint suffixes must not be appended to query routes.
        app = '/'.join(self.model.split('/')[:2])
        for field, suffix in _URL_FIELDS.items():
            url = value.get(field)
            if url is None and not complete_urls:
                continue
            expected = BASE + '/' + app + '/requests/' + identifier + suffix
            if url != expected:
                raise ResourceError('FAL队列地址不属于原模型、原任务及官方源', 'fal_queue_url_invalid')
            result[field] = url
        state = value.get('status')
        if state is not None:
            if state not in {'IN_QUEUE', 'IN_PROGRESS', 'COMPLETED'}:
                raise ResourceError('FAL队列状态未知；保留原回执', 'fal_receipt_unknown')
            result['status'] = state
        for name in ('error', 'error_type'):
            if value.get(name):
                text = value[name]
                if not isinstance(text, str):
                    raise ResourceError('FAL错误回执格式无法核对', 'fal_receipt_unknown')
                result[name] = text[:2000].replace(self._key(), '[REDACTED]')
        return result

    def submit(self, request):
        self.preflight()
        raw = self._request('POST', BASE + '/' + self.model, self._body(request))
        raw = self._queue(raw, complete_urls=True)
        return JobHandle(self.provider_id, self.model, raw['request_id'], raw)

    def _handle(self, handle):
        if handle.provider != self.provider_id or handle.model != self.model or not handle.external_task_id:
            raise ResourceError('FAL回执不属于此固定配置', 'provider_handle_mismatch')
        return self._queue(handle.raw, handle.external_task_id, complete_urls=True)

    def poll(self, handle):
        receipt = self._handle(handle)
        status = self._queue(self._request('GET', receipt['status_url']), receipt['request_id'])
        raw = {**receipt, **status}
        state = status.get('status')
        if state in {'IN_QUEUE', 'IN_PROGRESS'}:
            return JobStatus('running', raw=raw)
        if state != 'COMPLETED':
            raise ResourceError('FAL原任务尚无可识别状态', 'fal_receipt_unknown')
        if status.get('error') or status.get('error_type'):
            return JobStatus('failed', error_code='fal_request_failed', raw=raw)
        result = self._request('GET', receipt['response_url'])
        # The result endpoint returns the model output directly, not a second
        # queue envelope. An HTTP error here is still recoverable via original GET.
        raw['result'] = self._output(result)
        return JobStatus('succeeded', raw=raw)

    def cancel(self, handle):
        receipt = self._handle(handle)
        result = self._request('PUT', receipt['cancel_url'])
        if type(result.get('success')) is not bool:
            raise ResourceError('FAL取消尚未取得明确回执，请继续查询原任务', 'fal_receipt_unknown')
        return {'request_id': receipt['request_id'], 'cancel_requested': result['success']}

    def _output(self, value):
        field = 'video' if self.model == ENDPOINTS['depth'] else 'image'
        row = value.get(field)
        url = row.get('url') if isinstance(row, dict) else None
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or len(url) > 8192:
            raise ResourceError('原生媒体结果缺少单份HTTPS输出', 'fal_output_invalid')
        mime = row.get('content_type')
        if mime is not None and (not isinstance(mime, str) or not mime.startswith(field + '/')):
            raise ResourceError('原生媒体结果声明了错误模态', 'fal_output_invalid')
        result = {'url': url}
        if mime is not None:
            result['content_type'] = mime
        for key in ('width', 'height', 'file_size'):
            if row.get(key) is not None:
                if type(row[key]) is not int or row[key] <= 0:
                    raise ResourceError('原生媒体结果元数据无效', 'fal_output_invalid')
                result[key] = row[key]
        return {field: result}

    def parse_result(self, raw):
        receipt = self._queue(raw, complete_urls=True)
        if receipt.get('status') != 'COMPLETED' or receipt.get('error') or receipt.get('error_type') or not isinstance(raw.get('result'), dict):
            raise ResourceError('原生媒体任务没有固定的成功回执', 'fal_output_invalid')
        field = 'video' if self.model == ENDPOINTS['depth'] else 'image'
        row = self._output(raw['result'])[field]
        # Dimensions are deliberately NOT reported as verified output metadata.
        # ResourceWorker must download/decode/register then validate_output().
        return [GeneratedAsset(field, temporary_uri=row['url'], metadata={'fal_request_id': receipt['request_id'], 'fal_model': self.model})]


def fal_media_factory(job, storage, *, client=None, read_key=None):
    provider = job['provider']; config = provider.get('configuration', {})
    model = job['model']['model_key']
    modality, purpose = ('video', 'depth') if model == ENDPOINTS['depth'] else ('image', 'image_edit')
    if ((config.get('supplier'), config.get('product'), config.get('plan'), config.get('execution')) != ('fal', 'media', 'api', 'api') or
            provider['base_url'].rstrip('/') != BASE or provider['auth_ref'] != KEY_ENV or model not in MODELS or
            (job['modality'], job['purpose']) != (modality, purpose) or job['model'].get('default_params')):
        raise ResourceError('FAL媒体处理须使用官方队列及独立FAL_KEY配置', 'invalid_provider_config')
    return FalMediaProvider(model, job['provider_id'], job['input_media'], storage, client=client, read_key=read_key)
