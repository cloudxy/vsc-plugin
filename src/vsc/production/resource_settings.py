"""Global resource settings, credential presence and capability-aware defaults.

No credential value is returned or persisted here, and checks make no model call.
The PostgreSQL provider/model/route registry remains the production authority.
"""
from copy import deepcopy
import os
import re
from urllib.parse import urlsplit

from vsc.assets.resource_service import ResourceError
from vsc.adapters.providers.credentials import KEY_ENV, PLAN_BASE, RELOAD
from vsc.adapters.providers.xai_grok import credentials as grok_credentials

PURPOSES = [
    {"id": "identity_ref", "label": "参考图", "modality": "image"},
    {"id": "image_edit", "label": "图像编辑", "modality": "image"},
    {"id": "first_frame", "label": "首帧", "modality": "image"},
    {"id": "last_frame", "label": "尾帧", "modality": "image"},
    {"id": "image_to_video", "label": "图生视频", "modality": "video"},
    {"id": "text_to_video", "label": "文生视频", "modality": "video"},
    {"id": "reference_to_video", "label": "多模态参考视频", "modality": "video"},
    {"id": "digital_human", "label": "数字人声音驱动", "modality": "video"},
    {"id": "motion_transfer", "label": "动作模仿", "modality": "video"},
    {"id": "video_upgrade", "label": "样片升级1080p", "modality": "video"},
    {"id": "depth", "label": "灰度深度中间视频", "modality": "video"},
    {"id": "speech", "label": "独立朗读", "modality": "audio"},
    {"id": "dialogue_dry", "label": "配音", "modality": "audio"},
    {"id": "sfx", "label": "音效", "modality": "audio"},
    {"id": "bgm", "label": "音乐", "modality": "audio"},
    {"id": "music", "label": "音乐候选", "modality": "audio"},
    {"id": "song", "label": "歌词演唱歌曲", "modality": "audio"},
    {"id": "ambience", "label": "环境声", "modality": "audio"},
]
SUPPLIERS = {"volcengine", "alibaba", "xai", "openai", "mureka", "fal"}
EXECUTIONS = {"api", "official_sdk", "official_cli", "official_skill", "host_tool"}
SOURCES = {
    "volcengine": "https://docs.volcengine.com/docs/ark/agent-plan-personal-visual-models?lang=en",
    "alibaba": "https://help.aliyun.com/zh/model-studio/",
    "xai": "https://docs.x.ai/docs/guides/image-generation",
    "openai": "https://platform.openai.com/docs/guides/image-generation",
    "mureka": "https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html",
    "fal": "https://fal.ai/docs/documentation/model-apis/inference/queue",
}
PRESETS = [dict(id="volcengine-agent-plan", label="火山 Agent Plan", name="火山 Agent Plan",
    supplier="volcengine", product="ark", plan="agent-plan", region="cn-beijing", execution="api",
    modality="image", model_key="", model_version="", base_url=PLAN_BASE, auth_ref=KEY_ENV,
    capabilities={"purposes": ["identity_ref", "first_frame", "last_frame"], "reference_media": True},
    default_params={"size_map": {"1080x1920": "1440x2560"}}, enabled=False),
    dict(id="xai-grok-imagine-image", label="Grok Imagine 图像（订阅登录）", name="Grok Imagine 图像（订阅登录）",
    supplier="xai", product="grok-imagine", plan="subscription", region="global", execution="api",
    modality="image", model_key="grok-imagine-image-2.0", model_version="", base_url=grok_credentials.API_BASE, auth_ref="",
    capabilities={"purposes": ["identity_ref", "image_edit", "first_frame", "last_frame"], "reference_media": True,
                  "max_edit_sources": 5},
    default_params={"ratio_map": {"1080x1920": "9:16", "1920x1080": "16:9", "1080x1080": "1:1"}, "resolution": "2k"}, enabled=False),
    dict(id="xai-grok-imagine-video", label="Grok Imagine 图生视频（订阅登录）", name="Grok Imagine 图生视频（订阅登录）",
    supplier="xai", product="grok-imagine", plan="subscription", region="global", execution="api",
    modality="video", model_key="grok-imagine-video-1.5", model_version="", base_url=grok_credentials.API_BASE, auth_ref="",
    capabilities={"purposes": ["image_to_video", "text_to_video", "reference_to_video"], "reference_media": True, "first_frame": True, "last_frame": True,
                  "keyframes": True, "max_duration_ms": 15000, "max_reference_images": 14},
    default_params={"resolution": "480p", "reference_voice_ids": [], "generate_audio": True}, enabled=False),
    dict(id="xai-grok-imagine-video-lite", label="Grok Imagine 图生视频 lite（订阅登录）",
    name="Grok Imagine 图生视频 lite（订阅登录）",
    supplier="xai", product="grok-imagine", plan="subscription", region="global", execution="api",
    modality="video", model_key="grok-imagine-video-1.5-lite", model_version="", base_url=grok_credentials.API_BASE, auth_ref="",
    capabilities={"purposes": ["image_to_video", "text_to_video", "reference_to_video"], "reference_media": True, "first_frame": True, "last_frame": False,
                  "keyframes": False, "max_duration_ms": 15000, "max_reference_images": 14},
    default_params={"resolution": "720p", "reference_voice_ids": [], "generate_audio": True}, enabled=False),
    dict(id="xai-grok-video-operations", label="Grok 视频编辑／续接（订阅登录）", name="Grok 视频编辑／续接（订阅登录）",
    supplier="xai", product="grok-imagine", plan="subscription", region="global", execution="api",
    modality="video", model_key="grok-imagine-video", model_version="", base_url=grok_credentials.API_BASE, auth_ref="",
    capabilities={"purposes": ["video_edit", "video_extend"], "video_operations": ["edit", "extend"]},
    default_params={}, enabled=False),
    dict(id="volcengine-seed-audio", label="Seed-Audio 音乐/环境/音效（MediaKit 权限待验证）", name="Seed-Audio 音频候选",
    supplier="volcengine", product="mediakit", plan="agent-plan", region="cn-beijing", execution="api",
    modality="audio", model_key="seed-audio-1.0", model_version="mediakit-v1", base_url="https://mediakit.cn-beijing.volces.com", auth_ref=KEY_ENV,
    capabilities={"purposes": ["music", "bgm", "ambience", "sfx"]}, default_params={"max_prompt_chars": 2000}, enabled=False),
    dict(id="openai-image-inpaint", label="OpenAI 局部重绘（独立 API 权限待验证）", name="OpenAI 独立遮罩编辑",
    supplier="openai", product="images", plan="api", region="global", execution="api",
    modality="image", model_key="gpt-image-1.5", model_version="image-edit-2026-11-02", base_url="https://api.openai.com/v1", auth_ref="OPENAI_API_KEY",
    capabilities={"purposes":["image_edit"],"image_operations":["inpaint"],"max_width":1536,"max_height":1536},default_params={},enabled=False),
    dict(id="mureka-song", label="Mureka 歌词演唱（独立 API 权限待验证）", name="Mureka 歌词演唱",
    supplier="mureka", product="music", plan="api", region="global", execution="api",
    modality="audio", model_key="mureka-9.5", model_version="song-v1-2026-11-02", base_url="https://api.mureka.ai", auth_ref="MUREKA_API_KEY",
    capabilities={"purposes": ["song"], "lyrics": True}, default_params={}, enabled=False)] + [dict(id=supplier, label=label, name=label, supplier=supplier,
    product="", plan="", region="", execution="api", modality="image", model_key="", model_version="",
    base_url="", auth_ref=auth, capabilities={"purposes": []}, default_params={}, enabled=False)
    for supplier, label, auth in [("alibaba", "阿里（待接入）", "DASHSCOPE_API_KEY")]]
PRESETS.append(dict(id='volcengine-native-sample',label='Seedance 原生480p样片（账户权限待验证）',name='Seedance 原生样片',
    supplier='volcengine',product='ark',plan='agent-plan',region='cn-beijing',execution='api',modality='video',
    model_key='doubao-seedance-2-5-260628',model_version='native-draft-480p-2026-11-02',base_url=PLAN_BASE,auth_ref=KEY_ENV,
    capabilities={'purposes':['text_to_video','image_to_video','reference_to_video'],'video_draft':True,'first_frame':True,'reference_media':True,'max_duration_ms':15000},
    default_params={'resolution':'480p','ratio':'16:9','generate_audio':True},enabled=False))
SECRET_FIELDS = re.compile(r"(^|_)(api_?key|secret|password|token|authorization|credential)(_|$)", re.I)
from vsc.production.fal_tools import ENDPOINTS as FAL_ENDPOINTS
PRESETS.extend(dict(id='fal-'+operation,label=label+'（独立API权限待验证）',name=label,
    supplier='fal',product='media',plan='api',region='global',execution='api',modality='video' if operation=='depth' else 'image',
    model_key=endpoint,model_version='fal-native-2026-11-02',base_url='https://queue.fal.run',auth_ref='FAL_KEY',
    capabilities={'purposes':['depth' if operation=='depth' else 'image_edit'],
                  'video_operations' if operation=='depth' else 'image_operations':[operation]},default_params={},enabled=False)
    for operation,endpoint in FAL_ENDPOINTS.items()
    for label in [{'panorama':'Hunyuan 原生全景','upscale':'Clarity 原生AI超分','depth':'Depth Anything 深度中间视频'}[operation]])
from vsc.production.digital_human import AVATAR_MODEL, DETECTION_MODEL
PRESETS.extend([
    dict(id='fal-subject-detect',label='SAM3 主体识别（独立API权限待验证）',name='SAM3 主体识别',
        supplier='fal',product='media',plan='api',region='global',execution='api',modality='image',model_key=DETECTION_MODEL,
        model_version='subject-2026-11-02',base_url='https://queue.fal.run',auth_ref='FAL_KEY',
        capabilities={'purposes':['image_edit'],'image_operations':['subject_detect']},default_params={},enabled=False),
    dict(id='fal-digital-human',label='OmniHuman 主体讲话（独立API权限待验证）',name='OmniHuman 主体讲话',
        supplier='fal',product='media',plan='api',region='global',execution='api',modality='video',model_key=AVATAR_MODEL,
        model_version='1.5',base_url='https://queue.fal.run',auth_ref='FAL_KEY',
        capabilities={'purposes':['digital_human'],'reference_media':True,'reference_audio':True,'subject_mask':True,'max_duration_ms':59999},
        default_params={},enabled=False),
])


def safe_parameters(value):
    """Only JSON parameters, never embedded authentication or executable settings."""
    if isinstance(value, dict):
        if any(not isinstance(k, str) or SECRET_FIELDS.search(k) for k in value):
            raise ResourceError("参数中不能保存凭证；请使用环境变量引用", "credential_literal_forbidden")
        return {k: safe_parameters(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_parameters(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ResourceError("参数必须是 JSON 值")


def adapter_available(row):
    if row.get('supplier') == 'fal':
        from vsc.adapters.providers.fal_media import BASE, KEY_ENV as FAL_KEY
        from vsc.production.digital_human import DETECTION_MODEL, AVATAR_MODEL
        if row.get('model_key') in {DETECTION_MODEL, AVATAR_MODEL}:
            detecting = row['model_key'] == DETECTION_MODEL
            caps = row.get('capabilities', {})
            return (row.get('product') == 'media' and row.get('plan') == 'api' and row.get('execution') == 'api'
                and row.get('base_url', '').rstrip('/') == BASE and row.get('auth_ref') == FAL_KEY
                and row.get('modality') == ('image' if detecting else 'video') and not row.get('default_params')
                and caps.get('purposes') == (['image_edit'] if detecting else ['digital_human'])
                and (caps.get('image_operations') == ['subject_detect'] if detecting else
                     caps.get('subject_mask') is True and caps.get('reference_media') is True and caps.get('reference_audio') is True))
        operation=next((op for op,endpoint in FAL_ENDPOINTS.items() if endpoint==row.get('model_key')),None)
        return (operation is not None and row.get('product')=='media' and row.get('plan')=='api' and row.get('execution')=='api'
            and row.get('modality')==('video' if operation=='depth' else 'image')
            and row.get('base_url','').rstrip('/')==BASE and row.get('auth_ref')==FAL_KEY
            and row.get('capabilities',{}).get('purposes')==['depth' if operation=='depth' else 'image_edit']
            and row.get('capabilities',{}).get('video_operations' if operation=='depth' else 'image_operations')==[operation])
    if row.get('supplier') == 'openai':
        from vsc.adapters.providers.openai_image import BASE, KEY_ENV as OPENAI_KEY, MODELS
        return (row.get('product')=='images' and row.get('plan')=='api' and row.get('execution')=='api'
            and row.get('modality')=='image' and row.get('model_key') in MODELS
            and row.get('base_url','').rstrip('/')==BASE and row.get('auth_ref')==OPENAI_KEY
            and row.get('capabilities',{}).get('purposes')==['image_edit']
            and row.get('capabilities',{}).get('image_operations')==['inpaint'])
    if row.get('supplier') == 'mureka':
        from vsc.adapters.providers.mureka import BASE, KEY_ENV as MUREKA_KEY, MODELS
        return (row.get('product')=='music' and row.get('plan')=='api' and row.get('execution')=='api'
            and row.get('modality')=='audio' and row.get('model_key') in MODELS
            and row.get('base_url','').rstrip('/')==BASE and row.get('auth_ref')==MUREKA_KEY
            and row.get('capabilities',{}).get('purposes')==['song'] and row.get('capabilities',{}).get('lyrics') is True)
    if row.get("supplier") == "volcengine" and row.get("product") == "mediakit":
        return (row.get("plan") == "agent-plan" and row.get("execution") == "api" and row.get("modality") == "audio"
            and row.get("model_key") == "seed-audio-1.0" and row.get("base_url", "").rstrip("/") == "https://mediakit.cn-beijing.volces.com"
            and row.get("auth_ref") == KEY_ENV
            and set(row.get("capabilities", {}).get("purposes", [])) <= {"music", "bgm", "ambience", "sfx"})
    if row.get("supplier") == "xai":
        model = row.get("model_key", "")
        family_matches = ((row.get("modality") == "image" and model.startswith("grok-imagine-image-"))
            or (row.get("modality") == "video" and (model == "grok-imagine-video" or model.startswith("grok-imagine-video-"))))
        return (row.get("product") == "grok-imagine" and row.get("plan") == "subscription"
            and row.get("execution") == "api" and row.get("modality") in {"image", "video"}
            and row.get("base_url", "").rstrip("/") == grok_credentials.API_BASE
            and not row.get("auth_ref") and family_matches)
    model = row.get("model_key", "")
    family_matches = ((row.get("modality") == "image" and model.startswith("doubao-seedream-"))
        or (row.get("modality") == "video" and model.startswith("doubao-seedance-"))
        or (row.get("modality") == "audio" and model == "seed-tts-2.0"))
    return (row.get("supplier") == "volcengine" and row.get("product") == "ark"
        and row.get("plan") == "agent-plan" and row.get("execution") in {"api", "official_sdk"}
        and not (row.get("execution") == "official_sdk" and row.get("modality") == "audio")
        and row.get("base_url", "").rstrip("/") == PLAN_BASE and row.get("auth_ref") == KEY_ENV and family_matches
        and (row.get("modality") in {"image", "video"} or (row.get("modality") == "audio"
            and row.get("model_key") == "seed-tts-2.0"
            and set(row.get("capabilities", {}).get("purposes", [])) <= {"dialogue_dry", "speech"})))


def validate_configuration(payload):
    allowed = {"id", "name", "supplier", "product", "plan", "region", "execution", "modality", "model_key",
               "model_version", "base_url", "auth_ref", "capabilities", "default_params", "enabled", "tool_id", "reuse_model_id"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ResourceError("配置含未知字段；不接受密钥或身份字段", "invalid_configuration")
    value = deepcopy(payload)
    value["tool_id"] = value.get("tool_id") or None
    for key in ("name", "supplier", "product", "plan", "region", "execution", "modality", "model_key", "model_version"):
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 240:
            raise ResourceError("配置需要有效字段：" + key, "invalid_configuration")
        value[key] = value[key].strip()
    if value["supplier"] not in SUPPLIERS or value["execution"] not in EXECUTIONS or value["modality"] not in {"image", "video", "audio"}:
        raise ResourceError("供应商、执行方式或模态不支持", "invalid_configuration")
    if type(value.get("enabled")) is not bool:
        raise ResourceError("enabled 必须是布尔值")
    auth = value.get("auth_ref", "")
    if not isinstance(auth, str) or (auth and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", auth)):
        raise ResourceError("auth_ref 只接受环境变量名", "invalid_auth_ref")
    login_authorized = value["supplier"] == "xai" and value["plan"] == "subscription"
    if value["execution"] != "host_tool" and not login_authorized and not auth:
        raise ResourceError("需要凭证环境变量引用", "invalid_auth_ref")
    base = value.get("base_url", "")
    if not isinstance(base, str):
        raise ResourceError("base_url 必须是 URL")
    parsed = urlsplit(base)
    if base and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ResourceError("端点须为不含凭证、查询或片段的 HTTPS 地址", "invalid_endpoint")
    value["base_url"] = base.rstrip("/")
    for key in ("capabilities", "default_params"):
        if not isinstance(value.get(key, {}), dict):
            raise ResourceError(key + " 必须是对象")
        value[key] = safe_parameters(value.get(key, {}))
    purposes = value["capabilities"].get("purposes", [])
    if not isinstance(purposes, list) or any(not isinstance(p, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", p) for p in purposes):
        raise ResourceError("能力用途必须是用途 ID 数组")
    if value.get("tool_id") is not None and (not isinstance(value["tool_id"], str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value["tool_id"])):
        raise ResourceError("工具 ID 格式无效")
    mediakit = value["supplier"] == "volcengine" and value["product"] == "mediakit"
    if value['supplier']=='fal':
        if not adapter_available(value):raise ResourceError('FAL模型必须精确声明对应原生操作、官方队列和独立FAL_KEY','invalid_provider_config')
        if value['default_params']:raise ResourceError('原生媒体参数须由固定任务明确保存，不接受额外默认参数','invalid_model_defaults')
    if value['supplier']=='openai':
        if not adapter_available(value):
            raise ResourceError('OpenAI局部重绘须用官方端点、独立OPENAI_API_KEY和独立遮罩能力','invalid_provider_config')
        if value['default_params']:
            raise ResourceError('局部重绘每任务一张，不接受未映射默认参数','invalid_model_defaults')
    if value['supplier']=='mureka':
        if not adapter_available(value):
            raise ResourceError('Mureka 歌曲须用独立 MUREKA_API_KEY、官方端点和歌词演唱用途','invalid_provider_config')
        if value['default_params']:
            raise ResourceError('歌曲每任务固定一首；不接受未映射的默认参数','invalid_model_defaults')
    if mediakit and not adapter_available(value):
        raise ResourceError("MediaKit 音频限定 Seed-Audio、固定端点与原 Agent Plan 凭证引用，服务权限仍需验证", "invalid_provider_config")
    if mediakit:
        maximum = value["default_params"].get("max_prompt_chars", 2000)
        if type(maximum) is not int or not 1 <= maximum <= 20000 or set(value["default_params"]) - {"max_prompt_chars"}:
            raise ResourceError("Seed-Audio 默认参数仅支持 1–20000 的 max_prompt_chars", "invalid_model_defaults")
    if value["supplier"] == "volcengine" and not mediakit and (value["plan"] != "agent-plan" or value["product"] != "ark"
            or value["auth_ref"] != KEY_ENV or value["base_url"] != PLAN_BASE):
        raise ResourceError("火山资源必须使用 Ark Agent Plan、ARK_AGENT_PLAN_API_KEY 与套餐端点", "invalid_provider_config")
    if value["supplier"] == "volcengine" and not mediakit:
        family = {"image": "doubao-seedream-", "video": "doubao-seedance-", "audio": "seed-tts-"}[value["modality"]]
        if not value["model_key"].startswith(family):
            raise ResourceError("模型与多模态用途不匹配；不能用套餐凭证测试文本或向量模型", "invalid_model_family")
    if value["supplier"] == "xai":
        family = {"image": "grok-imagine-image-", "video": "grok-imagine-video-"}.get(value["modality"])
        if (value["product"] != "grok-imagine" or value["plan"] != "subscription" or value["execution"] != "api"
                or value["base_url"] != grok_credentials.API_BASE or value.get("auth_ref")):
            raise ResourceError("Grok 订阅路线须为 grok-imagine/subscription/api 与官方端点，凭证走 grok 登录态（不使用环境变量）", "invalid_provider_config")
        classic_video = value["modality"] == "video" and value["model_key"] == "grok-imagine-video"
        if not family or not (classic_video or value["model_key"].startswith(family)):
            raise ResourceError("模型与多模态用途不匹配；Grok 订阅路线只接 Imagine 图像／视频模型", "invalid_model_family")
        operations = value["capabilities"].get("video_operations", [])
        if operations and (not classic_video or not isinstance(operations, list) or set(operations) - {"edit", "extend"}):
            raise ResourceError("视频加工须声明经典Grok模型的edit/extend能力", "model_capability_mismatch")
    if value['capabilities'].get('video_draft'):
        from vsc.production.video_samples import SAMPLE_MODELS
        if value['capabilities']['video_draft'] is not True or value['model_key'] not in SAMPLE_MODELS or value['modality']!='video' or value['supplier']!='volcengine' or value['default_params'].get('resolution') not in {'480p','1080p'}:
            raise ResourceError('原生样片能力需要已支持的实际模型及固定分辨率','sample_capability_missing')
        upgrade='video_upgrade' in purposes
        if upgrade != (value['default_params']['resolution']=='1080p') or (upgrade and value['capabilities'].get('video_operations')!=['draft_upgrade']):
            raise ResourceError('1080p配置须明确样片升级用途和原生升级能力','sample_resolution_mismatch')
    if value["enabled"] and not adapter_available(value):
        raise ResourceError("此执行路线尚未接通，可停用保存为待配置", "adapter_unavailable")
    if value["enabled"] and not purposes:
        raise ResourceError("启用前需要声明适用用途", "model_capability_mismatch")
    known = {purpose["id"]: purpose["modality"] for purpose in PURPOSES}
    if value["enabled"] and any(purpose in known and known[purpose] != value["modality"] for purpose in purposes):
        raise ResourceError("所选用途与模型模态不匹配", "model_capability_mismatch")
    if value["enabled"] and value["execution"] == "official_sdk":
        defaults = value["default_params"]
        if value["modality"] == "image":
            sizes = defaults.get("size_map")
            if not isinstance(sizes, dict) or not sizes or any(not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", key)
                    or not isinstance(size, str) or not size.strip() for key, size in sizes.items()):
                raise ResourceError("官方 SDK 图像需要尺寸到模型规格的 size_map 映射", "invalid_model_defaults")
        if value["modality"] == "video" and (not isinstance(defaults.get("resolution"), str) or not defaults["resolution"].strip()
                or not isinstance(defaults.get("ratio"), str) or not defaults["ratio"].strip()
                or type(defaults.get("generate_audio", False)) is not bool):
            raise ResourceError("官方 SDK 视频需要 resolution、ratio 与布尔 generate_audio 映射", "invalid_model_defaults")
        from vsc.adapters.providers.volc_ark.official_sdk import verify_runtime
        verify_runtime(value["default_params"].get("sdk_runtime"))
    if value["enabled"] and value["supplier"] == "xai":
        from vsc.adapters.providers.xai_grok import spec as grok_spec
        defaults = value["default_params"]
        if value["modality"] == "image":
            ratios = defaults.get("ratio_map")
            if (not isinstance(ratios, dict) or not ratios
                    or any(not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", key) or not isinstance(ratio, str) or not ratio.strip()
                           for key, ratio in ratios.items()) or defaults.get("resolution") not in grok_spec.IMAGE_RESOLUTIONS):
                raise ResourceError("Grok 图像需要尺寸到画幅的 ratio_map 与 1k/1.5k/2k resolution 映射", "invalid_model_defaults")
        if value["modality"] == "video" and any(purpose not in {"video_edit", "video_extend"} for purpose in purposes):
            if defaults.get("resolution") not in ("480p", "720p", "1080p"):
                raise ResourceError("Grok 视频需要 480p/720p/1080p resolution 映射", "invalid_model_defaults")
            voices = defaults.get("reference_voice_ids", [])
            if (not isinstance(voices, list) or len(voices) > 3
                    or any(not isinstance(voice, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", voice) for voice in voices)):
                raise ResourceError("reference_voice_ids 必须是最多 3 个平台预置 voice_id（平台资源 id）", "invalid_model_defaults")
            if defaults.get("generate_audio", True) is not None and not isinstance(defaults.get("generate_audio", True), bool):
                raise ResourceError("generate_audio 必须是布尔", "invalid_model_defaults")
    return value


def credential_present(row):
    """Env reference first; the Grok subscription route reads the grok CLI login state instead."""
    auth = row.get("auth_ref")
    if auth:
        return bool(os.environ.get(auth))
    return grok_credentials.login_present()


def public_configuration(row):
    row = deepcopy(row)
    row["adapter_available"] = adapter_available(row)
    row["supported_purposes"] = row.get("capabilities", {}).get("purposes", [])
    row["official_source"] = SOURCES.get(row.get("supplier"))
    if row.get("execution") == "host_tool":
        status = "host_managed"
    elif not row["adapter_available"]:
        status = "not_connected"
    elif not credential_present(row):
        status = "not_loaded"
    else:
        status = "loaded_unverified"
    row["connection_status"] = status
    if row.get("execution") == "official_sdk" and row.get("supplier") == "volcengine":
        import importlib.metadata
        from vsc.adapters.providers.volc_ark.official_sdk import SDK_NAME, SDK_VERSION
        try:
            installed = importlib.metadata.version(SDK_NAME)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        row["runtime_status"] = "installed_unverified" if installed == SDK_VERSION else "not_installed" if installed is None else "version_mismatch"
        row["runtime_version"] = installed
        if installed != SDK_VERSION:
            row["adapter_available"] = False
            row["connection_status"] = "runtime_unavailable"
    # Registry defaults are not allowed to smuggle credential literals to HTTP.
    for key in ("capabilities", "default_params"):
        try:
            row[key] = safe_parameters(row.get(key, {}))
        except ResourceError:
            row[key] = {}
            row["connection_status"] = "invalid_configuration"
    return row


class ResourceSettings:
    def __init__(self, store=None):
        self.repository = None
        if store is not None and hasattr(store, "engine"):
            from vsc.adapters.persistence.postgres.resource_settings_store import ResourceSettingsRepository
            self.repository = ResourceSettingsRepository(store.engine)

    def _repository(self):
        if self.repository is None:
            raise ResourceError("资源配置需要已连接并迁移的 PostgreSQL 权威", "settings_unavailable", 503)
        return self.repository

    def list(self):
        result = {"available": self.repository is not None, "configurations": [], "defaults": {},
                  "purposes": PURPOSES, "presets": deepcopy(PRESETS),
                  "default_scope": "新建 PostgreSQL 生成任务未指定 model_id 时生效；旧任务保持固定版本"}
        if self.repository is None:
            result["message"] = "尚未配置 PostgreSQL，预设只读，未保存任何配置"
            return result
        rows, defaults = self.repository.list()
        result.update(configurations=[public_configuration(row) for row in rows], defaults=defaults)
        return result

    def save(self, payload, actor):
        if isinstance(payload, dict) and payload.get("execution") == "official_sdk":
            payload = deepcopy(payload)
            from vsc.adapters.providers.volc_ark.official_sdk import runtime_snapshot
            if not isinstance(payload.get("default_params", {}), dict):
                raise ResourceError("默认参数必须是对象")
            payload.setdefault("default_params", {}).pop("sdk_runtime", None)
            if adapter_available(payload):
                try:
                    payload["default_params"]["sdk_runtime"] = runtime_snapshot()
                except ResourceError:
                    if payload.get("enabled"):
                        raise
        return public_configuration(self._repository().save(validate_configuration(payload), actor))

    def enabled(self, model_id, enabled, actor):
        if type(enabled) is not bool:
            raise ResourceError("enabled 必须是布尔值")
        row = self._repository().get(model_id)
        if enabled:
            fields = {key: value for key, value in row.items() if key not in {"provider_id", "previous_model_id"}}
            validate_configuration(dict(fields, enabled=True))
        return public_configuration(self.repository.enabled(model_id, enabled))

    def bind_default(self, purpose, configuration_id, actor):
        spec = next((p for p in PURPOSES if p["id"] == purpose), None)
        if spec is None:
            raise ResourceError("未知默认用途")
        if configuration_id is None:
            return {"defaults": self._repository().clear_default(purpose)}
        row = self._repository().get(configuration_id)
        if not adapter_available(row) or not row["enabled"] or row["modality"] != spec["modality"] or purpose not in row["capabilities"].get("purposes", []):
            raise ResourceError("默认用途只能绑定已启用且支持该用途的配置", "model_capability_mismatch")
        if row.get("execution") == "official_sdk" and adapter_available(row):
            from vsc.adapters.providers.volc_ark.official_sdk import verify_runtime
            verify_runtime(row["default_params"].get("sdk_runtime"))
        return {"defaults": self.repository.bind_default(purpose, configuration_id)}

    def check(self, model_id):
        row = public_configuration(self._repository().get(model_id))
        runtime_message = ""
        if row.get("execution") == "official_sdk" and adapter_available(row):
            from vsc.adapters.providers.volc_ark.official_sdk import verify_runtime
            try:
                verify_runtime(row["default_params"].get("sdk_runtime"))
                runtime_message = "官方 SDK 及依赖字节与固定环境一致。"
            except ResourceError as exc:
                row["connection_status"] = "runtime_unavailable"
                runtime_message = str(exc) + "。"
        return {"id": model_id, "status": row["connection_status"], "scope": "local_configuration_and_environment_presence",
            "credential_loaded": credential_present(row),
            "generation_verified": False, "quota": "unknown", "message":
            runtime_message + ("仅检查配置与登录态文件是否存在；未调用模型，未验证生成权限。Grok 订阅路线凭证来自 grok CLI 登录态（"
                               + str(grok_credentials.LOGIN_FILE) + "），缺失时在终端运行 grok 按提示登录。"
                               if row.get("supplier") == "xai" and not row.get("auth_ref")
                               else "仅检查配置与当前进程环境变量是否加载；未调用模型，未验证生成权限。配置位置 ~/.zshenv；" + RELOAD)}

    def models(self, model_id):
        row = self._repository().get(model_id)
        rows, _ = self.repository.list()
        return {"models": [{"model_key": r["model_key"], "model_version": r["model_version"], "modality": r["modality"]}
                for r in rows if r["supplier"] == row["supplier"] and r["product"] == row["product"] and r["plan"] == row["plan"]],
            "scope": "registered_models", "remote_discovery": False,
            "message": "显示本机已登记的同套餐模型；此路线尚未接入独立鉴权模型发现，不以文本 hello 或生成请求代替。"}
