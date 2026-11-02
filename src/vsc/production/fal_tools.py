"""Fixed native media operations; actual decoded output is the acceptance input.

These are VSC contracts, not a claim about another product's projection semantics.
Model schemas: fal.ai/models/fal-ai/{hunyuan_world,clarity-upscaler,depth-anything-video}/api.
"""
from __future__ import annotations

import math
from vsc.assets.resource_service import ResourceError

ENDPOINTS = {
    'panorama': 'fal-ai/hunyuan_world',
    'upscale': 'fal-ai/clarity-upscaler',
    'depth': 'fal-ai/depth-anything-video',
}
DEPTH_PROMPT = '估计固定源视频的逐帧灰度深度，保持完整时长。'


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ResourceError('原生媒体处理参数超出支持范围', 'fal_parameters_invalid')
    return value


def normalize_params(operation, params):
    if not isinstance(params, dict):
        raise ResourceError('媒体处理需要明确参数', 'fal_parameters_invalid')
    defaults = {
        'panorama': {'projection': 'equirectangular'},
        'upscale': {'target': '4k', 'upscale_factor': 2, 'creativity': .35, 'resemblance': .6},
        'depth': {'depth_variant': 'VDA-Large', 'colormap': 'grayscale', 'resolution': 'auto'},
    }
    if operation not in defaults or set(params) - set(defaults[operation]):
        raise ResourceError('不支持的原生媒体操作或参数', 'fal_parameters_invalid')
    result = {**defaults[operation], **params}
    if operation == 'panorama' and result['projection'] != 'equirectangular':
        raise ResourceError('VSC全景预览只接受2:1等距柱状投影', 'panorama_projection_invalid')
    if operation == 'upscale':
        if result['target'] not in {'4k', '8k'}:
            raise ResourceError('超分目标为长边3840或7680像素', 'upscale_target_invalid')
        _number(result['upscale_factor'], 1, 4)
        for name in ('creativity', 'resemblance'):
            _number(result[name], 0, 1)
    if operation == 'depth' and (result['depth_variant'] not in {'VDA-Small', 'VDA-Base', 'VDA-Large'} or
            result['colormap'] != 'grayscale' or result['resolution'] not in {'auto', '360p', '480p', '720p', '1080p'}):
        raise ResourceError('深度中间视频须使用已登记模型、灰度和支持的分辨率', 'depth_parameters_invalid')
    return result


def image_operation_fields(operation, source, settings):
    """Compile from original probed media; callers persist these exact fields."""
    if operation not in {'panorama', 'upscale'} or source.get('modality') != 'image':
        raise ResourceError('原生图像处理需要固定原图', 'fal_source_invalid')
    width, height = source.get('width'), source.get('height')
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ResourceError('原图缺少已探测的实际尺寸', 'fal_source_invalid')
    settings = dict(settings)
    if operation == 'upscale':
        target = {'4k': 3840, '8k': 7680}.get(settings.get('target', '4k'))
        if not target:
            raise ResourceError('超分目标无效', 'upscale_target_invalid')
        factor = target / max(width, height)
        if not 1 < factor <= 4:
            raise ResourceError('原生AI超分仅支持大于1至4倍；4K源长边需至少960，8K至少1920，且小于目标尺寸', 'upscale_factor_unsupported')
        settings['upscale_factor'] = factor
        width, height = round(width * factor), round(height * factor)
    else:
        # The native panorama model chooses its output size. These dimensions
        # express the 2:1 layout only; validation never treats them as a size API.
        width, height = 1920, 960
    return {'operation': operation, 'source_media_id': source['id'], 'source_sha256': source['sha256'],
            'width': width, 'height': height, 'params': normalize_params(operation, settings)}


def depth_operation_fields(source, params=None):
    if source.get('modality') != 'video' or type(source.get('duration_ms')) is not int or source['duration_ms'] <= 0:
        raise ResourceError('深度估计需要已探测完整时长的原视频', 'fal_source_invalid')
    return {'operation': 'depth', 'source_media_id': source['id'], 'source_sha256': source['sha256'],
            'source_duration_ms': source['duration_ms'], 'duration_ms': source['duration_ms'],
            'prompt': DEPTH_PROMPT, 'params': normalize_params('depth', params or {})}


def validate_output(logical, media):
    """Call only with locally registered/probed media, never provider metadata.

    ResourceWorker remains responsible for fixed-byte identity and full decode.
    A failure leaves the original terminal receipt available for storage recovery.
    """
    operation = logical.get('operation')
    if operation not in ENDPOINTS:
        return
    params = normalize_params(operation, logical.get('params', {}))
    width, height = media.get('width'), media.get('height')
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ResourceError('媒体输出缺少实际解码尺寸', 'fal_output_invalid')
    if operation == 'panorama':
        if media.get('modality') != 'image' or width != height * 2:
            raise ResourceError('原生全景输出不符合2:1等距柱状预览合同', 'panorama_output_invalid')
    elif operation == 'upscale':
        target = {'4k': 3840, '8k': 7680}[params['target']]
        if media.get('modality') != 'image' or (width, height) != (logical.get('width'), logical.get('height')) or max(width, height) != target:
            raise ResourceError('AI超分实际尺寸未达到本次固定目标；保留原回执供恢复', 'upscale_output_invalid')
    else:
        duration, expected = media.get('duration_ms'), logical.get('source_duration_ms')
        if media.get('modality') != 'video' or type(duration) is not int or type(expected) is not int or abs(duration - expected) > 100:
            raise ResourceError('深度中间视频未保留完整源时长', 'depth_output_invalid')
        limit = 1080 if params['resolution'] == 'auto' else int(params['resolution'][:-1])
        if min(width, height) > limit:
            raise ResourceError('深度中间视频实际尺寸不符合分辨率合同', 'depth_output_invalid')
