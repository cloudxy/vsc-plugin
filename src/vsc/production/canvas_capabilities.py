"""Canvas operation semantics shared by the catalogue and working-input compiler.

Provider model identities always come from the local registry. An operation in
this catalogue is not a promise that a provider implements it.
"""
from copy import deepcopy

from vsc.assets.resource_service import ResourceError

OPERATION_KEY = 'vsc_operation'


def field(key, label, kind='number', default=None, **limits):
    return dict(key=key, label=label, field_type=kind, default_value=default, **limits)


def port(handle, media_type, minimum=0, maximum=8):
    labels = {'prompt': '文本提示', 'reference': '参考图片', 'first_frame': '首帧',
              'last_frame': '尾帧', 'reference_image': '参考图片', 'reference_video': '参考视频',
              'reference_audio': '参考音频'}
    return dict(handle=handle, label=labels.get(handle, handle), media_type=media_type,
                accept=[media_type], min_count=minimum, max_count=maximum, required=minimum > 0)


# Explicit mappings, rather than remote model aliases or provider-name guesses.
IMAGE_OPERATIONS = {
    'image_three_view': 'three_view', 'image_character_dual_view': 'headshot',
    'image_panorama_generate': 'panorama', 'image_multi_angle': 'angle',
    'image_lighting_generate': 'lighting', 'image_portrait_texture_adjustment': 'texture',
    'image_portrait_emotion_adjustment': 'expression', 'image_face_three_view': 'face_views',
    'image_frame_predict_3s_after': 'frame_predict_3s_after',
    'image_frame_predict_5s_before': 'frame_predict_5s_before',
    'image_cinematic_lighting': 'cinematic_lighting', 'image_multi_camera_grid_2k': 'multi_camera_grid_2k',
    'image_multi_camera_grid_4k': 'multi_camera_grid_4k', 'image_outpaint': 'outpaint',
    'image_story_four_grid': 'story_four_grid', 'image_upscale': 'upscale',
    'image_dewatermark': 'watermark', 'image_matting': 'matting', 'image_inpaint': 'inpaint',
}

RATIO_DIMENSIONS = {
    '9:16': (1080, 1920),
    '16:9': (1920, 1080),
    '1:1': (1080, 1080),
    '21:9': (2520, 1080),
    '4:5': (1080, 1350),
    '5:4': (1350, 1080),
    '4:3': (1440, 1080),
    '3:4': (1080, 1440),
    '3:2': (1620, 1080),
    '2:3': (1080, 1620),
    '2:1': (2160, 1080),
    'adaptive': (1920, 1080),
}

ALL_IMAGE_RATIOS = ['16:9', '9:16', '21:9', '1:1', '4:5', '5:4', '4:3', '3:4', '3:2', '2:3', '2:1']
SEEDREAM_RATIOS = ['16:9', '9:16', '4:3', '3:4', '1:1', '3:2', '2:3', '2:1', '21:9']
GEMINI_RATIOS = ['16:9', '9:16', '4:3', '3:4', '1:1', '3:2', '2:3', '5:4', '4:5', '21:9']
HOST_AUTH_RATIOS = ['3:4', '1:1', '4:3', '9:16', '16:9']
SEEDANCE_RATIOS = ['adaptive', '16:9', '9:16', '1:1', '4:3', '3:4', '21:9']
GROK_VIDEO_RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9']

CAMERA_OPTIONS = {
    'cameras': [
        {'id': 'sony_venice', 'label': 'Sony Venice'},
        {'id': 'arri_alexa_35', 'label': 'ARRI Alexa 35'},
        {'id': 'arri_alexa_65', 'label': 'ARRI Alexa 65'},
        {'id': 'red_v_raptor', 'label': 'RED V-Raptor'},
        {'id': 'panavision_dxl2', 'label': 'Panavision DXL2'},
        {'id': 'arricam_lt', 'label': 'Arricam LT'},
        {'id': 'arriflex_435', 'label': 'Arriflex 435'},
        {'id': 'imax_keighley', 'label': 'IMAX Keighley'},
        {'id': 'imax_film_camera', 'label': 'IMAX Film Camera'},
    ],
    'lenses': [
        {'id': 'zeiss_ultra_prime', 'label': 'Zeiss Ultra Prime'},
        {'id': 'cooke_sf_18x', 'label': 'Cooke Anamorphic SF'},
        {'id': 'canon_k35', 'label': 'Canon K-35'},
        {'id': 'cooke_s4', 'label': 'Cooke S4'},
        {'id': 'cooke_speed_panchro', 'label': 'Cooke Speed Panchro'},
        {'id': 'arri_signature_prime', 'label': 'Arri Signature Prime'},
        {'id': 'helios', 'label': 'Helios 44-2'},
        {'id': 'panavision_c_series', 'label': 'Panavision C Series'},
        {'id': 'panavision_primo', 'label': 'Panavision Primo Anamorphic'},
        {'id': 'hawk_class_x', 'label': 'Hawk Class X Anamorphic'},
    ],
    'focal_lengths': [
        {'id': '8mm', 'label': '8mm', 'value': 8},
        {'id': '14mm', 'label': '14mm', 'value': 14},
        {'id': '24mm', 'label': '24mm', 'value': 24},
        {'id': '35mm', 'label': '35mm', 'value': 35},
        {'id': '50mm', 'label': '50mm', 'value': 50},
        {'id': '75mm', 'label': '75mm', 'value': 75},
        {'id': '125mm', 'label': '125mm', 'value': 125},
    ],
    'apertures': [
        {'id': 'f/1.4', 'label': 'f/1.4'},
        {'id': 'f/4', 'label': 'f/4'},
        {'id': 'f/11', 'label': 'f/11'},
    ],
}

FIVE_TIER_QUALITIES = [
    {'quality': 'max', 'show_quality': '最高品质', 'label': '最高'},
    {'quality': 'xhigh', 'show_quality': '超高品质', 'label': '超高'},
    {'quality': 'high', 'show_quality': '高品质', 'label': '高'},
    {'quality': 'medium', 'show_quality': '标准品质', 'label': '标准'},
    {'quality': 'low', 'show_quality': '低品质', 'label': '低'},
]
THREE_TIER_QUALITIES = [
    {'quality': 'high', 'show_quality': '高品质', 'label': '高'},
    {'quality': 'medium', 'show_quality': '标准品质', 'label': '标准'},
    {'quality': 'low', 'show_quality': '低品质', 'label': '低'},
]
TWO_TIER_QUALITIES = [
    {'quality': 'high', 'show_quality': '高品质', 'label': '高'},
    {'quality': 'medium', 'show_quality': '标准品质', 'label': '标准'},
]

STANDARD_IMAGE_FORMATS = [
    {'type': 'png', 'label': 'PNG', 'supports_reference_materials': True, 'supports_camera_params': True},
    {'type': 'jpeg', 'label': 'JPG', 'supports_reference_materials': True, 'supports_camera_params': True},
    {'type': 'webp', 'label': 'WEBP', 'supports_reference_materials': True, 'supports_camera_params': True},
]
GIF_OUTPUT_FORMAT = {
    'type': 'gif',
    'label': 'GIF',
    'supports_reference_materials': True,
    'supports_camera_params': False,
    'params': [
        {'key': 'size', 'value_type': 'string', 'default': '512x512', 'options': ['512x512', '512x768', '768x512']},
        {'key': 'frame_count', 'value_type': 'integer', 'default': 8, 'min': 4, 'max': 24},
        {'key': 'frame_duration_ms', 'value_type': 'integer', 'default': 120, 'min': 80, 'max': 500, 'unit': 'ms'},
    ],
}


def reference_show_name(model_key, *, name='', tool_id='', capabilities=None):
    key = str(model_key or '').strip()
    low = key.lower()
    caps = capabilities or {}
    channel_prefix = {
        'api-settings-agy_auth': 'AGY 授权',
        'api-settings-grok_auth': 'Grok 授权',
        'api-settings-codex_auth': 'Codex 订阅',
        'api-settings-grok_video_auth': 'Grok 订阅',
    }.get(str(tool_id or ''))
    base = ''
    if low.startswith('doubao-seedream-5-5'):
        base = 'Seedream 5.5'
    elif low.startswith('doubao-seedream-5-0-pro'):
        base = 'Seedream 5.0 Pro'
    elif low.startswith('doubao-seedream-5-0-lite'):
        base = 'Seedream 5.0 Lite'
    elif low.startswith('doubao-seedream-5-0'):
        base = 'Seedream 5.0'
    elif low.startswith('doubao-seedream-4-5'):
        base = 'Seedream 4.5'
    elif low.startswith('doubao-seedream-4-0'):
        base = 'Seedream 4.0'
    elif low.startswith('doubao-seededit-3-0'):
        base = 'SeedEdit 3.0'
    elif low.startswith('doubao-seedance-2-5'):
        if caps.get('video_draft') or 'draft' in low:
            base = 'Seedance 2.5 样片模式'
        elif 'flash' in low:
            base = 'Seedance 2.5 Flash'
        else:
            base = 'Seedance 2.5'
    elif low.startswith('doubao-seedance-2-0-fast'):
        base = 'Seedance 2.0 Fast'
    elif low.startswith('doubao-seedance-2-0-mini'):
        base = 'Seedance 2.0 Mini'
    elif low.startswith('doubao-seedance-2-0-pro'):
        base = 'Seedance 2.0 Pro'
    elif low.startswith('doubao-seedance-2-0'):
        base = 'Seedance 2.0'
    elif low.startswith('doubao-seedance-1-5'):
        base = 'Seedance 1.5 Pro'
    elif low.startswith('doubao-seedance-1-0'):
        base = 'Seedance 1.0 Lite'
    elif low in {'gpt-image-2.6-pro_sr', 'gpt-image-2.6-sunburst', 'gpt-image-2.6-pro'}:
        base = 'GImage 2.6 Pro'
    elif low in {'gpt-image-2.6-fast_sr', 'gpt-image-2.6-flare', 'gpt-image-2.6-fast'}:
        base = 'GImage 2.6 Fast'
    elif low in {'gpt-image-2.5-pro_sr', 'gpt-image-2.5-sunburst'}:
        base = 'GImage 2.5 Pro'
    elif low in {'gpt-image-2.5-fast_sr', 'gpt-image-2.5-flare'}:
        base = 'GImage 2.5 Fast'
    elif low == 'gpt-image-2.5':
        base = 'GImage 2.5'
    elif low == 'gpt-image-2':
        base = 'GImage 2'
    elif low == 'gpt-image-1.5':
        base = 'GImage 1.5'
    elif low == 'gpt-image-1':
        base = 'GImage 1'
    elif low in {'nano-banana-pro', 'gemini-3-pro-image-preview'}:
        base = 'NanoPro'
    elif low in {'nano-banana-2', 'gemini-3.1-flash-image-preview'}:
        base = 'Nano2'
    elif low.startswith('gemini-2.5-flash-image'):
        base = 'Gemini 2.5 Flash'
    elif low in {'wan2.7-image-pro', 'wan2.7_imagepro'}:
        base = 'Wan2.7_ImagePro'
    elif low in {'wan2.7-image', 'wan2.7_image'}:
        base = 'Wan2.7_Image'
    elif low.startswith('qwen-image-'):
        base = 'Qwen Image ' + key[len('qwen-image-'):]
    elif low.startswith('grok-imagine-image-2.0'):
        base = 'Grok Imagine 2.0'
    elif low == 'grok-imagine-image':
        base = 'Grok Imagine'
    elif low == 'grok-2-image-1212':
        base = 'Grok 2 Image'
    elif low == 'grok-imagine-video-1.5':
        base = 'Grok Video 1.5'
    elif low == 'grok-imagine-video-1.5-lite':
        base = 'Grok Video 1.5 Lite'
    elif low == 'grok-imagine-video':
        base = 'Grok Video'
    elif low == 'image-generator' and channel_prefix == 'AGY 授权':
        return 'AGY 授权 · image-generator'
    elif low == 'image-generation' and channel_prefix == 'Codex 订阅':
        return 'Codex 订阅 · GPT Image 2'
    elif low == 'image_edit' and channel_prefix == 'Grok 授权':
        return 'Grok 授权 · image_edit'
    elif low in {'seed-audio-1.0', 'doubao-seed-audio-1.0'}:
        base = 'Seed Audio 1.0'
    elif low == 'seed-tts-2.0':
        base = 'Seed TTS 2.0'
    elif low in {'mureka-9.5', 'mureka-v9.5'}:
        base = 'Mureka V9.5'
    elif low.startswith('veo-'):
        base = key.upper().replace('-GENERATE-PREVIEW', '').replace('-GENERATE-001', '')
    elif low.startswith('sora-'):
        base = key.replace('sora-', 'Sora ').title()
    elif low.startswith('wan'):
        base = key.replace('-', ' ')
    if channel_prefix and base:
        return f'{channel_prefix} · {base}'
    return base or name or key


def model_spec_for(model):
    """Return capabilities.json-aligned model_params for a registered or settings model."""
    modality = model.get('modality') or 'image'
    key = str(model.get('model_key') or model.get('id') or '').strip()
    low = key.lower()
    tool_id = str(model.get('tool_id') or '')
    caps = model.get('capabilities') or {}
    defaults = deepcopy(model.get('default_params') or {})
    purposes = set(caps.get('purposes') or [])
    image_ops = set(caps.get('image_operations') or [])
    show_name = reference_show_name(key, name=model.get('name', ''), tool_id=tool_id, capabilities=caps)

    if modality == 'audio':
        return {
            **defaults,
            'show_name': show_name,
            'model_key': key,
            'modality': 'audio',
            'aspect_ratios': None,
            'default_aspect_ratio': None,
            'resolutions': None,
            'default_resolution': None,
            'qualities': [],
            'default_quality': '',
            'backgrounds': [],
            'default_background': '',
            'output_formats': [],
            'default_output_format': '',
            'durations': None,
            'default_duration': 5,
            'counts': [1],
            'default_count': 1,
            'generate_audio': False,
            'supports_camera': False,
        }

    if modality == 'video':
        if low.startswith('doubao-seedance-2-5'):
            ratios = list(SEEDANCE_RATIOS)
            if caps.get('video_draft') or 'draft' in low:
                resolutions, default_res = ['480P'], '480P'
            elif 'flash' in low:
                resolutions, default_res = ['480P', '720P'], '720P'
            else:
                resolutions, default_res = ['480P', '720P', '1080P', '4K'], '720P'
            durations = list(range(4, 31))
            counts = [1, 2, 4]
            gen_audio = True
        elif low.startswith('doubao-seedance-2-0'):
            ratios = list(SEEDANCE_RATIOS)
            resolutions = ['480P', '720P'] if ('fast' in low or 'mini' in low) else ['480P', '720P', '1080P', '4K']
            default_res = '720P'
            durations = list(range(4, 16))
            counts = [1, 2, 4]
            gen_audio = True
        elif low.startswith('doubao-seedance-'):
            ratios = list(SEEDANCE_RATIOS)
            resolutions, default_res = ['480P', '720P', '1080P'], '720P'
            durations = list(range(4, 13))
            counts = [1, 2, 4]
            gen_audio = False
        elif low.startswith('grok-imagine-video-1.5'):
            ratios = list(GROK_VIDEO_RATIOS)
            resolutions = ['480P', '720P'] if 'lite' in low else ['480P', '720P', '1080P']
            default_res = str(defaults.get('resolution') or '720P').upper()
            if default_res not in resolutions:
                default_res = resolutions[0]
            durations = list(range(1, 16))
            counts = [1, 2, 4]
            gen_audio = bool(defaults.get('generate_audio', True))
        elif low.startswith('grok-imagine-video'):
            ratios = list(GROK_VIDEO_RATIOS)
            resolutions, default_res = ['480P', '720P'], '720P'
            durations = list(range(1, 11))
            counts = [1, 2]
            gen_audio = bool(defaults.get('generate_audio', True))
        elif low.startswith('wan'):
            ratios = ['16:9', '9:16', '1:1', '4:3', '3:4']
            resolutions, default_res = ['480P', '720P', '1080P'], '720P'
            durations = list(range(2, 16))
            counts = [1, 2, 4]
            gen_audio = True
        else:
            max_sec = max(1, min(60, int((caps.get('max_duration_ms') or 15000) // 1000)))
            min_sec = max(1, int((caps.get('min_duration_ms') or 1000) // 1000))
            ratios = list(GROK_VIDEO_RATIOS)
            res_raw = str(defaults.get('resolution') or '').upper()
            resolutions = [res_raw] if res_raw in {'480P', '720P', '1080P', '4K'} else ['480P', '720P', '1080P']
            default_res = resolutions[min(1, len(resolutions) - 1)]
            durations = list(range(min_sec, max_sec + 1))
            counts = [1] if 'digital_human' in purposes or caps.get('video_operations') else [1, 2, 4]
            gen_audio = bool(defaults.get('generate_audio', False))
        default_ratio = str(defaults.get('ratio') or ('16:9' if '16:9' in ratios else ratios[0]))
        if default_ratio not in ratios:
            default_ratio = ratios[0]
        return {
            **defaults,
            'show_name': show_name,
            'model_key': key,
            'modality': 'video',
            'aspect_ratios': ratios,
            'default_aspect_ratio': default_ratio,
            'resolutions': resolutions,
            'default_resolution': default_res,
            'qualities': [],
            'default_quality': '',
            'backgrounds': [],
            'default_background': '',
            'output_formats': [],
            'default_output_format': '',
            'durations': durations,
            'default_duration': 5 if 5 in durations else durations[0],
            'counts': counts,
            'default_count': 1,
            'generate_audio': gen_audio,
            'supports_camera': False,
        }

    # Image modality
    single_only = bool(image_ops & {'inpaint', 'panorama', 'upscale', 'subject_detect'}) and purposes <= {'image_edit'}
    if single_only:
        return {
            **defaults,
            'show_name': show_name,
            'model_key': key,
            'modality': 'image',
            'aspect_ratios': ['1:1', '9:16', '16:9'] if 'inpaint' in image_ops else None,
            'default_aspect_ratio': '9:16',
            'resolutions': ['1K', '2K'] if 'inpaint' in image_ops else (['4K'] if 'upscale' in image_ops else None),
            'default_resolution': '2K' if 'inpaint' in image_ops else ('4K' if 'upscale' in image_ops else None),
            'qualities': deepcopy(THREE_TIER_QUALITIES) if 'inpaint' in image_ops else [],
            'default_quality': 'medium' if 'inpaint' in image_ops else '',
            'backgrounds': ['auto', 'opaque', 'transparent'] if model.get('supplier') == 'openai' else [],
            'default_background': 'auto' if model.get('supplier') == 'openai' else '',
            'output_formats': [deepcopy(STANDARD_IMAGE_FORMATS[0])],
            'default_output_format': 'png',
            'durations': None,
            'default_duration': None,
            'counts': [1],
            'default_count': 1,
            'generate_audio': False,
            'supports_camera': False,
        }

    if low.startswith('doubao-seedream-5-5'):
        ratios = list(SEEDREAM_RATIOS)
        resolutions, default_res = ['1.5K', '2K'], '2K'
        qualities, default_qual = deepcopy(THREE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    elif low.startswith('doubao-seedream-5-0-pro') or low.startswith('doubao-seedream-5-0-lite'):
        ratios = list(SEEDREAM_RATIOS)
        resolutions, default_res = ['1K', '2K'], '2K'
        qualities, default_qual = deepcopy(THREE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    elif low.startswith('doubao-seedream-') or low.startswith('doubao-seededit-'):
        ratios = list(SEEDREAM_RATIOS)
        resolutions, default_res = ['1K', '2K', '4K'], '2K'
        qualities, default_qual = deepcopy(THREE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2] if low.startswith('doubao-seededit-') else [1, 2, 4]
    elif low.startswith('gpt-image-') or (tool_id == 'api-settings-codex_auth' or low == 'image-generation'):
        if tool_id == 'api-settings-codex_auth' or low == 'image-generation':
            ratios = list(HOST_AUTH_RATIOS)
            resolutions, default_res = ['2K'], '2K'
            qualities, default_qual = [{'quality': 'medium', 'show_quality': '标准品质', 'label': '标准'}], 'medium'
            backgrounds = ['auto', 'opaque', 'transparent']
            formats = [deepcopy(STANDARD_IMAGE_FORMATS[0])]
            counts = [1, 2, 4]
        else:
            ratios = list(ALL_IMAGE_RATIOS)
            resolutions, default_res = ['1K', '2K', '4K'], '2K'
            qualities, default_qual = deepcopy(FIVE_TIER_QUALITIES), 'medium'
            backgrounds = ['auto', 'opaque', 'transparent']
            formats = deepcopy(STANDARD_IMAGE_FORMATS) + [deepcopy(GIF_OUTPUT_FORMAT)]
            counts = [1, 2, 4]
    elif low in {'nano-banana-pro', 'gemini-3-pro-image-preview'}:
        ratios = list(GEMINI_RATIOS)
        resolutions, default_res = ['2K', '4K'], '2K'
        qualities, default_qual = deepcopy(TWO_TIER_QUALITIES), 'high'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    elif low.startswith('gemini-') or low.startswith('nano-banana'):
        ratios = list(GEMINI_RATIOS)
        resolutions, default_res = ['1K', '2K', '4K'], '2K'
        qualities, default_qual = deepcopy(THREE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    elif tool_id == 'api-settings-agy_auth' or low == 'image-generator':
        ratios = list(HOST_AUTH_RATIOS)
        resolutions, default_res = ['1K', '2K'], '2K'
        qualities, default_qual = deepcopy(TWO_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = [deepcopy(STANDARD_IMAGE_FORMATS[0])]
        counts = [1, 2, 4]
    elif low.startswith('grok-imagine-image'):
        ratio_map = defaults.get('ratio_map')
        ratios = list(dict.fromkeys(ratio_map.values())) if isinstance(ratio_map, dict) and ratio_map else list(SEEDREAM_RATIOS)
        resolutions, default_res = ['1K', '1.5K', '2K'], str(defaults.get('resolution') or '2K').upper()
        if default_res not in resolutions:
            default_res = '2K'
        qualities, default_qual = deepcopy(TWO_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    elif low == 'grok-2-image-1212':
        ratios = ['1:1', '4:3', '3:4', '16:9', '9:16']
        resolutions, default_res = ['1K'], '1K'
        qualities, default_qual = [], ''
        backgrounds = []
        formats = [deepcopy(STANDARD_IMAGE_FORMATS[0])]
        counts = [1, 2]
    elif tool_id == 'api-settings-grok_auth' or low == 'image_edit':
        ratios = ['3:4', '1:1', '4:3', '9:16', '16:9', '2:3', '3:2']
        resolutions, default_res = ['1K', '2K'], '2K'
        qualities, default_qual = [{'quality': 'medium', 'show_quality': '标准品质', 'label': '标准'}], 'medium'
        backgrounds = ['auto', 'opaque']
        formats = [deepcopy(STANDARD_IMAGE_FORMATS[0])]
        counts = [1, 2, 4]
    elif low.startswith('wan2.7-image') or low.startswith('qwen-image'):
        ratios = ['16:9', '9:16', '4:3', '3:4', '1:1', '3:2', '2:3', '21:9'] if low.startswith('wan') else ['3:4', '9:16', '1:1', '16:9']
        resolutions, default_res = ['1K', '2K'], '2K'
        qualities, default_qual = deepcopy(THREE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]
    else:
        ratio_map = defaults.get('ratio_map')
        ratios = list(dict.fromkeys(ratio_map.values())) if isinstance(ratio_map, dict) and ratio_map else list(ALL_IMAGE_RATIOS)
        resolutions, default_res = ['1K', '2K', '4K'], '2K'
        qualities, default_qual = deepcopy(FIVE_TIER_QUALITIES), 'medium'
        backgrounds = ['auto', 'opaque', 'transparent']
        formats = deepcopy(STANDARD_IMAGE_FORMATS)
        counts = [1, 2, 4]

    default_ratio = '9:16' if '9:16' in ratios else ratios[0]
    return {
        **defaults,
        'show_name': show_name,
        'model_key': key,
        'modality': 'image',
        'aspect_ratios': ratios,
        'default_aspect_ratio': default_ratio,
        'resolutions': resolutions,
        'default_resolution': default_res,
        'qualities': qualities,
        'default_quality': default_qual,
        'backgrounds': backgrounds,
        'default_background': 'auto' if 'auto' in backgrounds else (backgrounds[0] if backgrounds else ''),
        'output_formats': formats,
        'default_output_format': formats[0]['type'] if formats else 'png',
        'durations': None,
        'default_duration': None,
        'counts': counts,
        'default_count': 1,
        'generate_audio': False,
        'supports_camera': True,
    }


KNOWN_SETTINGS_MODELS = (
    {'id': 'image-generator', 'modality': 'image', 'model_key': 'image-generator', 'tool_id': 'api-settings-agy_auth'},
    {'id': 'image_edit', 'modality': 'image', 'model_key': 'image_edit', 'tool_id': 'api-settings-grok_auth'},
    {'id': 'image-generation', 'modality': 'image', 'model_key': 'image-generation', 'tool_id': 'api-settings-codex_auth'},
    {'id': 'grok-imagine-image-2.0', 'modality': 'image', 'model_key': 'grok-imagine-image-2.0'},
    {'id': 'grok-imagine-image', 'modality': 'image', 'model_key': 'grok-imagine-image'},
    {'id': 'grok-2-image-1212', 'modality': 'image', 'model_key': 'grok-2-image-1212'},
    {'id': 'gemini-3.1-flash-image-preview', 'modality': 'image', 'model_key': 'gemini-3.1-flash-image-preview'},
    {'id': 'gemini-3-pro-image-preview', 'modality': 'image', 'model_key': 'gemini-3-pro-image-preview'},
    {'id': 'gemini-2.5-flash-image', 'modality': 'image', 'model_key': 'gemini-2.5-flash-image'},
    {'id': 'gemini-2.5-flash-image-preview', 'modality': 'image', 'model_key': 'gemini-2.5-flash-image-preview'},
    {'id': 'gpt-image-2.5', 'modality': 'image', 'model_key': 'gpt-image-2.5'},
    {'id': 'gpt-image-2.5-sunburst', 'modality': 'image', 'model_key': 'gpt-image-2.5-sunburst'},
    {'id': 'gpt-image-2.5-flare', 'modality': 'image', 'model_key': 'gpt-image-2.5-flare'},
    {'id': 'gpt-image-2', 'modality': 'image', 'model_key': 'gpt-image-2'},
    {'id': 'gpt-image-1.5', 'modality': 'image', 'model_key': 'gpt-image-1.5'},
    {'id': 'gpt-image-1', 'modality': 'image', 'model_key': 'gpt-image-1'},
    {'id': 'qwen-image-3.0-pro', 'modality': 'image', 'model_key': 'qwen-image-3.0-pro'},
    {'id': 'qwen-image-2.1-pro', 'modality': 'image', 'model_key': 'qwen-image-2.1-pro'},
    {'id': 'qwen-image-2.1-turbo', 'modality': 'image', 'model_key': 'qwen-image-2.1-turbo'},
    {'id': 'qwen-image-2.0-pro', 'modality': 'image', 'model_key': 'qwen-image-2.0-pro'},
    {'id': 'qwen-image-edit-plus', 'modality': 'image', 'model_key': 'qwen-image-edit-plus'},
    {'id': 'doubao-seedream-5-5-261028', 'modality': 'image', 'model_key': 'doubao-seedream-5-5-261028'},
    {'id': 'doubao-seedream-5-0-pro', 'modality': 'image', 'model_key': 'doubao-seedream-5-0-pro'},
    {'id': 'doubao-seedream-5-0', 'modality': 'image', 'model_key': 'doubao-seedream-5-0'},
    {'id': 'doubao-seedream-5-0-lite', 'modality': 'image', 'model_key': 'doubao-seedream-5-0-lite'},
    {'id': 'doubao-seedream-4-5-251128', 'modality': 'image', 'model_key': 'doubao-seedream-4-5-251128'},
    {'id': 'doubao-seedream-4-0-250828', 'modality': 'image', 'model_key': 'doubao-seedream-4-0-250828'},
    {'id': 'doubao-seededit-3-0-i2i-250628', 'modality': 'image', 'model_key': 'doubao-seededit-3-0-i2i-250628'},
    {'id': 'grok-imagine-video-1.5', 'modality': 'video', 'model_key': 'grok-imagine-video-1.5'},
    {'id': 'grok-imagine-video-1.5-lite', 'modality': 'video', 'model_key': 'grok-imagine-video-1.5-lite'},
    {'id': 'grok-imagine-video', 'modality': 'video', 'model_key': 'grok-imagine-video'},
    {'id': 'doubao-seedance-2-5-260628', 'modality': 'video', 'model_key': 'doubao-seedance-2-5-260628'},
    {'id': 'doubao-seedance-2-0-pro', 'modality': 'video', 'model_key': 'doubao-seedance-2-0-pro'},
    {'id': 'doubao-seedance-1-5-pro', 'modality': 'video', 'model_key': 'doubao-seedance-1-5-pro'},
    {'id': 'doubao-seedance-1-0-lite-i2v', 'modality': 'video', 'model_key': 'doubao-seedance-1-0-lite-i2v'},
    {'id': 'veo-3.1-generate-preview', 'modality': 'video', 'model_key': 'veo-3.1-generate-preview'},
    {'id': 'veo-3.1-fast-generate-preview', 'modality': 'video', 'model_key': 'veo-3.1-fast-generate-preview'},
    {'id': 'veo-3.0-generate-001', 'modality': 'video', 'model_key': 'veo-3.0-generate-001'},
    {'id': 'veo-2.0-generate-001', 'modality': 'video', 'model_key': 'veo-2.0-generate-001'},
    {'id': 'wan2.6-i2v-plus', 'modality': 'video', 'model_key': 'wan2.6-i2v-plus'},
    {'id': 'wan2.6-t2v-plus', 'modality': 'video', 'model_key': 'wan2.6-t2v-plus'},
    {'id': 'wan2.5-i2v-turbo', 'modality': 'video', 'model_key': 'wan2.5-i2v-turbo'},
    {'id': 'wan2.2-kf2v-plus', 'modality': 'video', 'model_key': 'wan2.2-kf2v-plus'},
    {'id': 'sora-2', 'modality': 'video', 'model_key': 'sora-2'},
    {'id': 'sora-2-pro', 'modality': 'video', 'model_key': 'sora-2-pro'},
)


def _operations():
    from vsc.production.image_tools import TOOLS
    rows = []

    def add(key, name, kind, *, consumer='work_generation', ports=(), mode=None, reason=None, tool=None, action=None, camera_options=None):
        rows.append(dict(op_type=key, name=name, node_type=kind, category=kind,
            operation_role='source' if consumer == 'source' else 'generator',
            consumer=consumer, mode=mode, image_tool=tool, action=action,
            input_ports=list(ports), output_ports=[dict(handle='output', media_type=kind)],
            params_schema=dict(fields=[]), combination_rules={},
            result_ui_policy=dict(regeneratable=consumer == 'work_generation', preserve_original=True),
            camera_options=camera_options, unavailable_reason=reason))

    for kind, name in [('text', '文本'), ('audio', '音频'), ('image', '图片'), ('video', '视频')]:
        add('source_' + kind, name + '素材', kind, consumer='source')
    add('image_generate', '生图', 'image',
        ports=[port('prompt', 'text', maximum=200), port('reference', 'image')],
        mode='image', camera_options=deepcopy(CAMERA_OPTIONS))
    for key, tool in IMAGE_OPERATIONS.items():
        add(key, TOOLS[tool][0], 'image', ports=[port('reference', 'image', 1, 1)], mode='image_' + tool, tool=tool)
    for key, name, mode, inputs in [
        ('text_video', '文生视频', 'text', [port('prompt', 'text', maximum=200)]),
        ('single_image_video', '单图生视频', 'single', [port('prompt', 'text', maximum=200), port('first_frame', 'image', 1, 1)]),
        ('seedance_omni_video', '全能参考生视频', 'omni', [port('prompt', 'text', maximum=200), port('reference_image', 'image'), port('reference_video', 'video'), port('reference_audio', 'audio')]),
        ('head_tail_video', '首尾帧生视频', 'first_last', [port('prompt', 'text', maximum=200), port('first_frame', 'image', 1, 1), port('last_frame', 'image', 1, 1)]),
        ('multi_pic_video', '多图生视频', 'multi', [port('prompt', 'text', maximum=200), port('first_frame', 'image', maximum=1), port('reference_image', 'image', 1)]),
        ('audio_to_video', '音频生视频', 'audio_to_video', [port('prompt', 'text', maximum=200), port('reference_audio', 'audio', 1, 1)]),
        ('video_edit', '视频编辑', 'video_edit', [port('prompt', 'text', maximum=200), port('reference_video', 'video', 1, 1)]),
        ('audio_generate', '文本生成音频', 'audio', [port('prompt', 'text', maximum=200)]),
    ]:
        add(key, name, 'audio' if mode == 'audio' else 'video', mode=mode, ports=inputs)
    # These entries open existing editors; they never masquerade as generation.
    for key, name, kind, action in [
        ('lyrics_timeline_extract', '歌词时间线', 'text', 'lyrics'),
        ('shot_script_generate', 'MV 分镜脚本', 'text', 'script_generator'),
        ('smart_video_breakdown', '智能拉片', 'text', 'video_breakdown'),
        ('viral_reference_extract', '爆款复刻参考剧本提取', 'text', 'agent'),
        ('video_story_parse', '视频故事解析', 'text', 'video_story'),
        ('text_generate', '文本生成', 'text', 'agent'),
        ('image_reverse_prompt', '图片反推提示词', 'text', 'agent'),
        ('mv_director_brief', 'MV 导演 Brief', 'text', 'mv_brief'),
        ('audio_clip', '音频裁剪预览', 'audio', 'clip'),
        ('audio_speed', '音频变速预览', 'audio', 'speed'),
        ('video_clip', '视频裁剪预览', 'video', 'clip'),
        ('audio_video_separate', '音视频分离', 'video', 'separate_audio'),
        ('multi_video_edit', '多视频合成剪辑', 'video', 'edit'),
        ('video_soundtrack_compose', '视频配乐合成', 'video', 'music_mix'),
        ('audio_soundtrack', '图片/视频配乐', 'audio', 'music'),
        ('video_script_extract', '提取带时码剧本', 'text', 'video_script_extract'),
        ('video_dewatermark', '智能去字幕', 'video', 'video_dewatermark'),
        ('video_depth_map', '深度动作捕捉', 'video', 'video_depth'),
        ('video_segment_remake', '片段重拍', 'video', 'video_segment_remake'),
        ('video_upscale', '视频高清', 'video', 'video_upscale'),
        ('image_layer_separation', '图层分离', 'image', 'layer_separation'),
        ('image_layer_composition', '图层合成', 'image', 'layer_composition'),
    ]:
        add(key, name, kind, consumer='editor', action=action)
    for key, name, kind, reason in [
        ('seedance_long_video', '超长视频', 'video', '尚无分段生成与连续性拼接适配；可使用普通视频和剪辑工具。'),
    ]:
        add(key, name, kind, consumer='unavailable', reason=reason)
    return rows


def operation_for_node(node):
    """Resolve an explicit operation, while preserving old untagged canvases."""
    key = node.get('params', {}).get(OPERATION_KEY)
    if key is None:
        return None
    operation = next((row for row in _operations() if row['op_type'] == key), None)
    if operation is None or operation['node_type'] != node['type']:
        raise ResourceError('画布操作与节点类型不匹配', 'canvas_operation_mismatch')
    tool = node.get('params', {}).get('vsc_image_tool')
    if operation['image_tool'] != tool:
        raise ResourceError('画布操作与图像工具不匹配', 'canvas_operation_mismatch')
    return operation


def validate_work_operation(node, edges, nodes):
    operation = operation_for_node(node)
    if operation is None:
        return None
    if operation['consumer'] != 'work_generation':
        raise ResourceError(operation['unavailable_reason'] or '此操作须从对应编辑工具执行', 'canvas_operation_unavailable')
    ports = {p['handle']: p for p in operation['input_ports']}
    counts = {key: 0 for key in ports}
    for edge in edges:
        if edge['target'] != node['id'] or edge['port'] == 'derived_from':
            continue
        slot = ports.get(edge['port'])
        if slot is None or nodes[edge['source']]['type'] not in slot['accept']:
            raise ResourceError('所选操作不接受当前参考端口', 'canvas_operation_port')
        counts[edge['port']] += 1
    for key, slot in ports.items():
        if not slot['min_count'] <= counts[key] <= slot['max_count']:
            raise ResourceError(slot['label'] + '数量不符合所选操作要求', 'canvas_operation_port')
    if operation['mode'] == 'omni' and not any(counts.get(k, 0) for k in ('reference_image', 'reference_video', 'reference_audio')):
        raise ResourceError('全能参考生视频至少需要一份媒体参考', 'canvas_operation_port')
    return operation


def _model_overrides(models, operations, model_params):
    by_id = {m['id']: m for m in models if m.get('id')}
    overrides = []
    target_ops = {'image_generate', 'text_video', 'single_image_video', 'seedance_omni_video', 'head_tail_video', 'multi_pic_video'}
    for op in operations:
        if op['op_type'] not in target_ops:
            continue
        for model_id in op.get('supported_models') or []:
            model = by_id.get(model_id)
            if not model:
                continue
            caps = model.get('capabilities') or {}
            spec = model_params.get(model_id) or {}
            max_ref_img = int(caps.get('max_reference_images') or 8)
            in_ports = []
            for p in op['input_ports']:
                entry = deepcopy(p)
                entry['direction'] = 'input'
                if p['handle'] in {'reference', 'reference_image'} and max_ref_img > 0:
                    entry['max_count'] = max_ref_img
                in_ports.append(entry)
            out_ports = [{
                'handle': f"output_{op['node_type']}",
                'label': '生成图片' if op['node_type'] == 'image' else '生成视频',
                'media_type': op['node_type'],
                'accept': [op['node_type']],
                'required': False,
                'min_count': 0,
                'max_count': 999,
                'direction': 'output',
            }]
            overrides.append({
                'model_id': model_id,
                'model_name': spec.get('show_name') or model.get('name') or model.get('model_key') or model_id,
                'op_type': op['op_type'],
                'input_ports': in_ports,
                'output_ports': out_ports,
                'params_override': None,
                'combination_rules': {
                    'audio_only_allowed': False,
                    'prompt_required_when_no_image_and_no_video': op['op_type'] in {'text_video', 'seedance_omni_video'},
                },
            })
    return overrides


def input_validation_for(model):
    """Local input limits used by the canvas preflight. Numbers follow published family bounds, not a byte-for-byte port of the reference checker."""
    key = str((model or {}).get('model_key') or (model or {}).get('id') or '').strip().lower()
    caps = (model or {}).get('capabilities') or {}
    raw_max = caps.get('max_reference_images')
    max_images = raw_max if isinstance(raw_max, int) and not isinstance(raw_max, bool) and raw_max > 0 else None
    family, rules = None, {}
    if 'kling' in key:
        family = 'kling_4'
        rules = dict(image_aspect_min=0.4, image_aspect_max=2.5, image_short_edge_min=300, image_short_edge_max=4096,
                     max_reference_images=max_images or 4)
    elif 'seedance-2-5' in key or 'seedance-2.5' in key or key.startswith('doubao-seedance-2-5'):
        family = 'seedance_2_5'
        rules = dict(image_aspect_min=0.4, image_aspect_max=2.5, image_short_edge_min=300, image_short_edge_max=6000,
                     video_aspect_min=0.4, video_aspect_max=2.5, video_duration_min=4, video_duration_max=30,
                     max_reference_videos=3, max_reference_audios=3, max_reference_images=max_images or 9)
    elif 'seedance-2-0' in key or 'seedance-2.0' in key or key.startswith('doubao-seedance-2'):
        family = 'seedance_2_0'
        rules = dict(image_aspect_min=0.4, image_aspect_max=2.5, image_short_edge_min=300, image_short_edge_max=6000,
                     video_aspect_min=0.4, video_aspect_max=2.5, video_duration_min=4, video_duration_max=15,
                     max_reference_videos=3, max_reference_audios=3, max_reference_images=max_images or 9)
    elif key.startswith('wan'):
        family = 'wan_3_0'
        rules = dict(image_aspect_min=1 / 3, image_aspect_max=3, video_duration_min=2, video_duration_max=15,
                     max_reference_videos=3, max_reference_images=max_images or 4)
    elif max_images:
        family = 'reference_count'
        rules = dict(max_reference_images=max_images)
    if not rules:
        return None
    rules['family'] = family
    return rules


def with_input_validation(model):
    spec = model_spec_for(model)
    rules = input_validation_for(model)
    if not rules:
        return spec
    spec = dict(spec)
    spec['input_validation'] = rules
    return spec


def canvas_capabilities(models):
    """Build a fresh capability projection; never retain models across requests."""
    from vsc.assets.creative_canvas import NODE_TYPES
    rows = _operations()
    for row in rows:
        kind = row['node_type']
        applicable = []
        for model in models:
            if not model.get('enabled') or model.get('modality') != kind or model.get('adapter_available') is False:
                continue
            caps = model.get('capabilities') or {}
            if row['image_tool'] and 'image_edit' not in caps.get('purposes', []):
                continue
            native = {'panorama': 'panorama', 'upscale': 'upscale', 'inpaint': 'inpaint', 'watermark': 'inpaint'}.get(row['image_tool'])
            if native and native not in caps.get('image_operations', []):
                continue
            if row['mode'] in {'single', 'first_last'} and not caps.get('first_frame'):
                continue
            if row['mode'] == 'first_last' and not caps.get('last_frame'):
                continue
            if row['mode'] in {'multi', 'omni'} and not caps.get('reference_media'):
                continue
            applicable.append(model['id'])
        row['supported_models'] = applicable if row['consumer'] == 'work_generation' else []
        row['default_model_id'] = next(iter(row['supported_models']), None)
        row['available'] = row['consumer'] in {'source', 'editor'} or bool(row['supported_models'])
        if row['consumer'] == 'work_generation':
            row['params_schema']['fields'] = [
                field('count', '候选数量', default=1, min=1, max=8, step=1),
            ]
            if kind in {'image', 'video'}:
                row['params_schema']['fields'].append(field('dimensions', '画幅', 'select', '1080,1920', options=[
                    {'value': value, 'label': label} for value, label in [('1080,1920', '竖屏 9:16'), ('1920,1080', '横屏 16:9'),
                    ('1080,1080', '方形 1:1'), ('2520,1080', '宽银幕 21:9'), ('1080,1350', '竖版 4:5'),
                    ('1350,1080', '横版 5:4'), ('1440,1080', '经典横版 4:3'), ('1080,1440', '经典竖版 3:4'),
                    ('1620,1080', '胶片横版 3:2'), ('1080,1620', '胶片竖版 2:3'), ('2160,1080', '全景 2:1')]]))
            if kind in {'video', 'audio'}:
                row['params_schema']['fields'].append(field('duration_seconds', '时长（秒）', default=5, min=1, max=60, step=1))
            if kind == 'audio':
                row['params_schema']['fields'].append(field('purpose', '声音用途', 'select', 'sfx', options=[
                    {'value': v, 'label': label} for v, label in [('sfx', '音效'), ('music', '音乐'), ('ambience', '环境声')]]))
            if not row['available']:
                row['unavailable_reason'] = '没有支持此操作的已启用本地模型，请检查模型设置。'
    for row in rows:
        if row['op_type'] == 'video_upscale':
            row['available'] = True
            row['unavailable_reason'] = None
            row['params_schema'] = {'fields': [
                field('resolution', '分辨率', 'select', '1080p', options=[
                    {'value': '1080p', 'label': '1080p'}, {'value': '2k', 'label': '2K'}, {'value': '4k', 'label': '4K'}]),
                field('interpolate', '补帧', 'bool', False),
                field('slow', '慢放', 'bool', False),
                field('slow_factor', '慢放倍率', 'select', 2, options=[
                    {'value': 1, 'label': '1x'}, {'value': 2, 'label': '2x'}, {'value': 3, 'label': '3x'}, {'value': 5, 'label': '5x'}]),
            ]}
    params_by_model = {item['id']: with_input_validation(item) for item in KNOWN_SETTINGS_MODELS}
    for m in models:
        spec = with_input_validation(m)
        params_by_model[m['id']] = spec
        if m.get('model_key') and m['model_key'] not in params_by_model:
            params_by_model[m['model_key']] = deepcopy(spec)
    overrides = _model_overrides(models, rows, params_by_model)
    return deepcopy(dict(layout=dict(version=1, strategies=['explicit', 'grid'], profiles=[dict(id='grid', columns=4, horizontal_gap=280, vertical_gap=230)]),
        operations=rows, node_types=[dict(node_type=key, **value) for key, value in NODE_TYPES.items()],
        model_overrides=overrides, model_params=params_by_model,
        validation_rules=dict(max_nodes=200, max_edges=800, max_candidates=8, first_last_frame_max_count=1)))
