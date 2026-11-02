"""Native, synchronous OpenAI image edits; ResourceWorker owns intent/recovery.

Protocol verified 2026-11-02:
https://developers.openai.com/api/reference/python/resources/images/methods/edit
Only the independently configured API account is used. There is no POST retry
and no invented status endpoint for a response lost after submission.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os

from vsc.assets.resource_service import ResourceError
from vsc.production.providers import GeneratedAsset, JobHandle, JobStatus

BASE = 'https://api.openai.com/v1'
KEY_ENV = 'OPENAI_API_KEY'
MODELS = frozenset({'gpt-image-1.5'})
SIZES = frozenset({(1024, 1024), (1536, 1024), (1024, 1536)})


def validate_inpaint_bytes(source, mask):
    """Validate fixed inputs without turning an ordinary reference into a mask."""
    from PIL import Image, ImageOps
    if not source or len(source) >= 50 * 1024 * 1024 or not mask or len(mask) >= 4 * 1024 * 1024:
        raise ResourceError('原图需小于50MB，独立PNG遮罩需小于4MB', 'inpaint_input_size')
    try:
        image = Image.open(io.BytesIO(source))
        if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 16777216:
            raise ValueError('source format or dimensions')
        mime = Image.MIME[image.format]
        image.load()
        oriented = ImageOps.exif_transpose(image)
        overlay = Image.open(io.BytesIO(mask))
        if overlay.format != 'PNG' or 'A' not in overlay.getbands() or overlay.size != oriented.size:
            raise ValueError('mask format, alpha or dimensions')
        overlay.load()
        if overlay.getchannel('A').getextrema()[0] != 0:
            raise ValueError('mask has no editable pixels')
        # An oriented photograph is encoded losslessly at transport time. Its
        # immutable input hash still identifies the original registered file.
        if image.getexif().get(274, 1) != 1:
            stream = io.BytesIO(); oriented.save(stream, format='PNG')
            source, mime = stream.getvalue(), 'image/png'
            if len(source) >= 50 * 1024 * 1024:raise ValueError('oriented source too large')
        return source, mime
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ResourceError('遮罩必须是与原图同尺寸、含透明编辑区域的PNG；请从原图重新导出', 'inpaint_mask_invalid') from exc


class OpenAIImageProvider:
    def __init__(self, model, provider_id, fixed_inputs, storage, *, client=None, read_key=None):
        self.model, self.provider_id = model, provider_id
        self.fixed = {row['media_id']: row for row in fixed_inputs}
        self.storage, self.client = storage, client
        self.read_key = read_key or (lambda: os.environ.get(KEY_ENV, ''))

    def _key(self):
        key = self.read_key()
        if not isinstance(key, str) or not key:
            raise ResourceError('未加载 OPENAI_API_KEY；请检查 ~/.zshenv，在启动进程的 zsh 中 source ~/.zshenv 后重启；其他启动方式需显式传入环境', 'credential_not_loaded')
        return key

    def _bytes(self, media_id, digest, role):
        row = self.fixed.get(media_id)
        if not row or row.get('role') != role or row.get('blob_sha256') != digest:
            raise ResourceError('原图或遮罩不属于任务的固定输入', 'unfixed_reference')
        for location in row.get('locations', []):
            if location.get('storage') == 'local' and location.get('available'):
                content = self.storage.read(location['object_key'], digest)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ResourceError('原图或遮罩字节摘要已改变', 'inpaint_input_changed')
                return content
        raise ResourceError('固定原图或遮罩字节不可用', 'media_unavailable')

    def _inputs(self, request):
        source = self._bytes(request.source_media_id, request.source_sha256, 'operation_source')
        mask = self._bytes(request.mask_media_id, request.mask_sha256, 'operation_mask')
        content, mime = validate_inpaint_bytes(source, mask)
        return content, mime, mask

    def preflight(self, request=None):
        if self.model not in MODELS:
            raise ResourceError('请选择已核实的独立遮罩编辑模型', 'invalid_model_defaults')
        self._key()
        if request is None:return
        if request.purpose != 'image_edit' or getattr(request, 'operation', None) != 'inpaint':
            raise ResourceError('此路线仅执行明确的独立遮罩局部重绘', 'inpaint_operation_required')
        if not isinstance(request.prompt, str) or not request.prompt.strip() or len(request.prompt) > 32000:
            raise ResourceError('局部重绘需要1–32000字符的修改说明', 'inpaint_prompt_invalid')
        if (request.width, request.height) not in SIZES:
            raise ResourceError('此模型输出支持1024×1024、1536×1024、1024×1536', 'inpaint_output_size')
        if request.reference_media_ids or set(request.params) - {'quality'} or request.params.get('quality', 'auto') not in {'auto', 'low', 'medium', 'high'}:
            raise ResourceError('局部重绘仅接受固定原图、独立遮罩和质量参数', 'inpaint_params_unsupported')
        if not all(getattr(request, name, None) for name in ('source_media_id', 'source_sha256', 'mask_media_id', 'mask_sha256')):
            raise ResourceError('请先固定原图和编辑器导出的遮罩', 'inpaint_inputs_required')
        self._inputs(request)

    def submit(self, request):
        import httpx
        self.preflight(request)
        source, mime, mask = self._inputs(request)
        client = self.client or httpx.Client(timeout=180, follow_redirects=False)
        try:
            response = client.post(BASE + '/images/edits', headers={'Authorization': 'Bearer ' + self._key()},
                data={'model': self.model, 'prompt': request.prompt, 'n': '1', 'size': f'{request.width}x{request.height}',
                      'quality': request.params.get('quality', 'auto'), 'output_format': 'png'},
                files={'image': ('source.' + {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[mime], source, mime),
                       'mask': ('mask.png', mask, 'image/png')})
            if response.status_code in {401, 403}:
                raise ResourceError('OpenAI凭据或图像服务权限被拒绝；请核对OPENAI_API_KEY及账户权限', 'openai_authentication_failed')
            if not 200 <= response.status_code < 300:
                raise ResourceError('图像编辑未取得成功回执；保留原请求，不自动重发', 'image_edit_receipt_unknown')
            raw = response.json()
            self.parse_result(raw)
            # Only known response fields are retained; no transport headers or
            # arbitrary supplier text can enter the persisted job evidence.
            return JobHandle(self.provider_id, self.model, None,
                {'data': [{'b64_json': raw['data'][0]['b64_json']}], 'output_format': 'png'})
        except (httpx.HTTPError, ValueError) as exc:
            raise ResourceError('图像编辑回执未知；保留原请求，不自动重发', 'image_edit_receipt_unknown') from exc
        finally:
            if self.client is None:client.close()

    def poll(self, handle):
        if handle.provider != self.provider_id or handle.model != self.model or handle.external_task_id is not None:
            raise ResourceError('图像编辑回执不属于此固定配置', 'provider_handle_mismatch')
        self.parse_result(handle.raw)
        return JobStatus('succeeded', raw=handle.raw)

    def parse_result(self, raw):
        from PIL import Image
        rows = raw.get('data') if isinstance(raw, dict) else None
        encoded = rows[0].get('b64_json') if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None
        if not isinstance(encoded, str) or len(encoded) > 96 * 1024 * 1024:
            raise ResourceError('未取得单张图像的原始回执；不得重复提交', 'image_edit_receipt_unknown')
        try:
            content = base64.b64decode(encoded, validate=True)
            image = Image.open(io.BytesIO(content))
            if image.format != 'PNG' or image.width * image.height > 16777216:raise ValueError('output dimensions')
            image.load()
        except (OSError, ValueError, binascii.Error, Image.DecompressionBombError) as exc:
            raise ResourceError('图像编辑结果无法解码；保留回执供恢复', 'image_edit_output_invalid') from exc
        return [GeneratedAsset('image', inline_bytes=content, metadata={'mime_type': 'image/png', 'width': image.width, 'height': image.height})]


def openai_image_factory(job, storage, *, client=None, read_key=None):
    provider = job['provider']; config = provider.get('configuration', {})
    if (config.get('supplier'), config.get('product'), config.get('plan'), config.get('execution')) != ('openai', 'images', 'api', 'api') or provider['base_url'].rstrip('/') != BASE or provider['auth_ref'] != KEY_ENV or job['modality'] != 'image' or job['purpose'] != 'image_edit' or job['model'].get('default_params'):
        raise ResourceError('OpenAI局部重绘须使用官方端点与独立凭据引用', 'invalid_provider_config')
    return OpenAIImageProvider(job['model']['model_key'], job['provider_id'], job['input_media'], storage, client=client, read_key=read_key)
