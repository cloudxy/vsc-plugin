"""Fixed speaking-subject contracts, independent of remote inference.

Detection creates candidate masks, never an adopted identity. The selected mask
must be tied to the original detection output or local editor export by the
application before a job is authorized. These helpers do not grant that authority.
"""
from __future__ import annotations

import io
import math
import re

from vsc.assets.resource_service import ResourceError

DETECTION_MODEL = 'fal-ai/sam-3/image'
AVATAR_MODEL = 'fal-ai/bytedance/omnihuman/v1.5'
DETECTION_PROMPT = 'person'
DEFAULT_PERFORMANCE = '让选中的人物按固定驱动音频讲话。'
MAX_MASKS = 8  # VSC local result bound, not an asserted provider maximum.


def normalize_selection(value):
    if value is None:
        return None
    common = {'origin', 'source_media_id', 'source_sha256', 'mask_media_id', 'mask_sha256'}
    expected = common | ({'job_id', 'output_index'} if isinstance(value, dict) and value.get('origin') == 'detected' else {'export_id'})
    if not isinstance(value, dict) or set(value) != expected or value.get('origin') not in {'detected', 'manual'}:
        raise ResourceError('主体选择必须固定检测任务输出或原手绘导出', 'subject_selection_invalid')
    for key in expected - {'origin', 'output_index'}:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 100:
            raise ResourceError('主体选择身份无效', 'subject_selection_invalid')
    if any(not re.fullmatch('[0-9a-f]{64}', value[key]) for key in ('source_sha256', 'mask_sha256')):
        raise ResourceError('主体选择缺少固定摘要', 'subject_selection_invalid')
    if value['origin'] == 'detected' and (type(value['output_index']) is not int or not 0 <= value['output_index'] < MAX_MASKS):
        raise ResourceError('主体选择索引无效', 'subject_selection_invalid')
    return dict(value)


def performance_prompt(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ResourceError('角色表演提示最多300字', 'avatar_performance_invalid')
    return value.strip()


def avatar_params(value):
    if not isinstance(value, dict) or set(value) - {'resolution', 'turbo_mode'}:
        raise ResourceError('数字人仅支持已核实的分辨率与加速参数', 'avatar_parameters_invalid')
    result = {'resolution': '1080p', 'turbo_mode': False, **value}
    if result['resolution'] not in {'720p', '1080p'} or type(result['turbo_mode']) is not bool:
        raise ResourceError('数字人分辨率须为720p或1080p，加速须为布尔值', 'avatar_parameters_invalid')
    return result


def detection_params(value):
    if not isinstance(value, dict) or set(value) - {'max_masks'}:
        raise ResourceError('主体识别只接受明确的候选数量', 'subject_parameters_invalid')
    result = {'max_masks': 6, **value}
    if type(result['max_masks']) is not int or not 1 <= result['max_masks'] <= MAX_MASKS:
        raise ResourceError('单次主体识别可返回1至8个候选', 'subject_parameters_invalid')
    return result


def _image_shape(media):
    if (media.get('modality') != 'image' or type(media.get('width')) is not int or
            type(media.get('height')) is not int or min(media['width'], media['height']) <= 0):
        raise ResourceError('主体图片需要实际解码尺寸', 'subject_image_invalid')
    return media['width'], media['height']


def audio_duration(duration_ms, params):
    limit = 30000 if avatar_params(params)['resolution'] == '1080p' else 60000
    if type(duration_ms) is not int or not 0 < duration_ms < limit:
        raise ResourceError('1080p驱动音频须短于30秒；720p须短于60秒，不自动裁剪', 'avatar_audio_duration')
    return duration_ms


def detection_request_fields(source, params=None):
    width, height = _image_shape(source)
    return {'operation': 'subject_detect', 'source_media_id': source['id'], 'source_sha256': source['sha256'],
            'prompt': DETECTION_PROMPT, 'width': width, 'height': height,
            'params': detection_params(params or {})}


def avatar_request_fields(source, audio, mask, performance='', params=None):
    if _image_shape(source) != _image_shape(mask) or source['id'] == mask['id']:
        raise ResourceError('主体遮罩须与固定原图同尺寸且单独登记', 'subject_mask_mismatch')
    if audio.get('modality') != 'audio':
        raise ResourceError('数字人需要唯一固定音轨', 'avatar_audio_invalid')
    params = avatar_params(params or {})
    return {'prompt': performance_prompt(performance) or DEFAULT_PERFORMANCE,
            'reference_media_ids': [source['id']], 'reference_audio_media_ids': [audio['id']],
            'subject_mask_media_id': mask['id'], 'subject_mask_sha256': mask['sha256'],
            'duration_ms': audio_duration(audio.get('duration_ms'), params), 'params': params}


def validate_mask_bytes(content, shape):
    """Validate actual opaque grayscale PNG; white selects the speaking subject.

    Gray antialiased boundaries are allowed. The threshold defines a nonempty
    selected region and nonempty background; alpha inpaint masks are rejected.
    """
    from PIL import Image, ImageChops
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format != 'PNG' or image.size != tuple(shape) or image.width * image.height > 67108864:
                raise ValueError('format or shape')
            image.load()
            rgba = image.convert('RGBA')
            red, green, blue, alpha = rgba.split()
            if alpha.getextrema() != (255, 255) or ImageChops.difference(red, green).getbbox() or ImageChops.difference(red, blue).getbbox():
                raise ValueError('mask is not opaque grayscale')
            selected = sum(red.histogram()[128:])
            if not 0 < selected < image.width * image.height:
                raise ValueError('mask must select a proper region')
            return {'width': image.width, 'height': image.height, 'selected_pixels': selected}
    except (ValueError, OSError, Image.DecompressionBombError) as error:
        raise ResourceError('主体mask须为原图同尺寸的黑底白区PNG，不能为空、全白或透明编辑mask', 'subject_mask_invalid') from error


def validate_output(logical, media, content=None):
    """Original worker calls only after storage identity and full decode checks."""
    if logical.get('operation') == 'subject_detect':
        if _image_shape(media) != (logical.get('width'), logical.get('height')) or content is None:
            raise ResourceError('识别mask实际尺寸必须与固定原图一致', 'subject_mask_mismatch')
        validate_mask_bytes(content, (logical['width'], logical['height']))
    elif logical.get('purpose') == 'digital_human' and logical.get('subject_mask_media_id'):
        params = avatar_params(logical.get('params', {}))
        expected = audio_duration(logical.get('duration_ms'), params)
        duration = media.get('duration_ms')
        streams = media.get('probe', {}).get('streams', [])
        if (media.get('modality') != 'video' or type(duration) is not int or abs(duration - expected) > 250 or
                not any(row.get('codec_type') == 'audio' for row in streams) or
                min(media.get('width') or 0, media.get('height') or 0) != int(params['resolution'][:-1])):
            raise ResourceError('数字人输出需实际音轨、固定音频时长及请求分辨率', 'avatar_output_invalid')


def bounded_number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
