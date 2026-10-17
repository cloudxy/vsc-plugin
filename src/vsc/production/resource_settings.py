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

PURPOSES = [
    {"id": "identity_ref", "label": "参考图", "modality": "image"},
    {"id": "image_edit", "label": "图像编辑", "modality": "image"},
    {"id": "first_frame", "label": "首帧", "modality": "image"},
    {"id": "last_frame", "label": "尾帧", "modality": "image"},
    {"id": "image_to_video", "label": "图生视频", "modality": "video"},
    {"id": "dialogue_dry", "label": "配音", "modality": "audio"},
    {"id": "sfx", "label": "音效", "modality": "audio"},
    {"id": "bgm", "label": "音乐", "modality": "audio"},
]
SUPPLIERS = {"volcengine", "alibaba", "xai", "openai"}
EXECUTIONS = {"api", "official_sdk", "official_cli", "official_skill", "host_tool"}
SOURCES = {
    "volcengine": "https://docs.volcengine.com/docs/ark/agent-plan-personal-visual-models?lang=en",
    "alibaba": "https://help.aliyun.com/zh/model-studio/",
    "xai": "https://docs.x.ai/docs/guides/image-generation",
    "openai": "https://platform.openai.com/docs/guides/image-generation",
}
PRESETS = [dict(id="volcengine-agent-plan", label="火山 Agent Plan", name="火山 Agent Plan",
    supplier="volcengine", product="ark", plan="agent-plan", region="cn-beijing", execution="api",
    modality="image", model_key="", model_version="", base_url=PLAN_BASE, auth_ref=KEY_ENV,
    capabilities={"purposes": ["identity_ref", "first_frame", "last_frame"], "reference_media": True},
    default_params={"size_map": {"1080x1920": "1440x2560"}}, enabled=False)] + [dict(id=supplier, label=label, name=label, supplier=supplier,
    product="", plan="", region="", execution="api", modality="image", model_key="", model_version="",
    base_url="", auth_ref=auth, capabilities={"purposes": []}, default_params={}, enabled=False)
    for supplier, label, auth in [("alibaba", "阿里（待接入）", "DASHSCOPE_API_KEY"),
        ("xai", "xAI（待接入）", "XAI_API_KEY"), ("openai", "OpenAI API（待接入）", "OPENAI_API_KEY")]]
SECRET_FIELDS = re.compile(r"(^|_)(api_?key|secret|password|token|authorization|credential)(_|$)", re.I)


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
            and set(row.get("capabilities", {}).get("purposes", [])) <= {"dialogue_dry"})))


def validate_configuration(payload):
    allowed = {"id", "name", "supplier", "product", "plan", "region", "execution", "modality", "model_key",
               "model_version", "base_url", "auth_ref", "capabilities", "default_params", "enabled", "tool_id"}
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
    if value["execution"] != "host_tool" and not auth:
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
    if value["supplier"] == "volcengine" and (value["plan"] != "agent-plan" or value["product"] != "ark"
            or value["auth_ref"] != KEY_ENV or value["base_url"] != PLAN_BASE):
        raise ResourceError("火山资源必须使用 Ark Agent Plan、ARK_AGENT_PLAN_API_KEY 与套餐端点", "invalid_provider_config")
    if value["supplier"] == "volcengine":
        family = {"image": "doubao-seedream-", "video": "doubao-seedance-", "audio": "seed-tts-"}[value["modality"]]
        if not value["model_key"].startswith(family):
            raise ResourceError("模型与多模态用途不匹配；不能用套餐凭证测试文本或向量模型", "invalid_model_family")
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
    return value


def public_configuration(row):
    row = deepcopy(row)
    row["adapter_available"] = adapter_available(row)
    row["supported_purposes"] = row.get("capabilities", {}).get("purposes", [])
    row["official_source"] = SOURCES.get(row.get("supplier"))
    if row.get("execution") == "host_tool":
        status = "host_managed"
    elif not row["adapter_available"]:
        status = "not_connected"
    elif not row.get("auth_ref") or not os.environ.get(row["auth_ref"]):
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
            "credential_loaded": bool(row.get("auth_ref") and os.environ.get(row["auth_ref"])),
            "generation_verified": False, "quota": "unknown", "message":
            runtime_message + "仅检查配置与当前进程环境变量是否加载；未调用模型，未验证生成权限。配置位置 ~/.zshenv；" + RELOAD}

    def models(self, model_id):
        row = self._repository().get(model_id)
        rows, _ = self.repository.list()
        return {"models": [{"model_key": r["model_key"], "model_version": r["model_version"], "modality": r["modality"]}
                for r in rows if r["supplier"] == row["supplier"] and r["product"] == row["product"] and r["plan"] == row["plan"]],
            "scope": "registered_models", "remote_discovery": False,
            "message": "显示本机已登记的同套餐模型；此路线尚未接入独立鉴权模型发现，不以文本 hello 或生成请求代替。"}
