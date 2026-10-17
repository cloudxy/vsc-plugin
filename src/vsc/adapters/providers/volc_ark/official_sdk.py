"""Pinned official Ark Runtime SDK transport for the existing resource worker.

This is a transport, not another scheduler: VSC retains budget, submit intent,
unknown-result recovery and media storage. Only the image/video data plane is
exposed, with SDK retries and HTTP redirects disabled.
"""
from copy import deepcopy
import hashlib
import importlib.metadata as metadata
import json
import logging
import platform
from pathlib import Path
import re
import sys

from vsc.assets.resource_service import ResourceError
from vsc.adapters.providers import credentials

SDK_NAME = "arkruntime"
SDK_VERSION = "0.13.0"
ADAPTER_VERSION = "vsc.ark-sdk-transport/1"
SOURCE = "https://github.com/volcengine/ark-runtime-python"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_snapshot():
    """Fingerprint installed code and dependency versions; never install or read credentials."""
    seen, packages = set(), []
    pending = [SDK_NAME]
    while pending:
        name = pending.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            if name == SDK_NAME:
                raise ResourceError("未安装官方 arkruntime SDK；请显式安装 VSC 的 ark 可选依赖", "sdk_unavailable") from None
            continue  # conditional dependencies are checked by importing the SDK below
        code = []
        for item in sorted(dist.files or [], key=str):
            relative = str(item)
            # The omnibus distribution contains hundreds of unrelated cloud
            # services. Ark imports only these two namespaces; freeze exactly
            # the consumed code plus the distribution's complete RECORD below.
            if name == "volcengine-python-sdk" and not relative.startswith(("volcenginesdkark/", "volcenginesdkcore/")):
                continue
            if ".." in item.parts or "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"} or ".dist-info/" in relative:
                continue
            path = dist.locate_file(item)
            if path.is_symlink() or not path.is_file():
                raise ResourceError("SDK 依赖文件缺失或含外部链接，请修复固定运行环境", "sdk_runtime_changed")
            code.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        if not code:
            raise ResourceError("SDK 运行环境没有可核验代码清单", "sdk_runtime_unverifiable")
        packages.append({"name": name, "version": dist.version, "code_sha256": _digest(code),
            "distribution_manifest_sha256": hashlib.sha256((dist.read_text("RECORD") or "").encode()).hexdigest(),
            "scope": "volcenginesdkark,volcenginesdkcore" if name == "volcengine-python-sdk" else "distribution_code"})
        for requirement in dist.requires or []:
            # Extras are not used by the narrow data-plane transport.
            if re.search(r"\bextra\s*==", requirement):
                continue
            match = re.match(r"[A-Za-z0-9_.-]+", requirement)
            if match:
                pending.append(match.group())
    sdk = next((row for row in packages if row["name"] == SDK_NAME), None)
    if not sdk or sdk["version"] != SDK_VERSION:
        raise ResourceError("此适配器仅核验过 arkruntime==" + SDK_VERSION + "，请使用该固定版本", "sdk_version_mismatch")
    provider_dir = Path(__file__).parent
    adapter_files = {name: hashlib.sha256((provider_dir / name).read_bytes()).hexdigest()
        for name in ("official_sdk.py", "resource_factory.py", "provider.py", "api.py")}
    snapshot = {"format": "vsc.sdk-runtime/v1", "sdk": SDK_NAME, "version": SDK_VERSION,
        "publisher": "volcengine", "source": SOURCE, "adapter_version": ADAPTER_VERSION,
        "adapter_files": adapter_files, "python": platform.python_version(), "platform": sys.platform,
        "architecture": platform.machine(), "packages": sorted(packages, key=lambda row: row["name"])}
    snapshot["sha256"] = _digest(snapshot)
    return snapshot


def verify_runtime(expected):
    if not isinstance(expected, dict) or expected.get("format") != "vsc.sdk-runtime/v1":
        raise ResourceError("官方 SDK 配置缺服务端固定的运行环境，请重新保存配置", "sdk_runtime_missing")
    actual = runtime_snapshot()
    if expected != actual:
        raise ResourceError("当前 SDK 或依赖与任务固定环境不一致；请恢复原环境后续查，不能换版本重提", "sdk_runtime_changed")
    return actual


def _without_none(value):
    if isinstance(value, dict):
        return {key: _without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


class OfficialArkTransport:
    def __init__(self, expected_runtime, identity, http_client=None):
        self.runtime = verify_runtime(expected_runtime)
        self.identity = deepcopy(identity)
        self.http_client = http_client
        self.wire = None
        self.expected = None
        self.expected_path = None
        self.request_count = 0

    def preflight(self, request=None):
        # All checks occur before ResourceWorker records a billable submit intent.
        verify_runtime(self.runtime)
        problem = credentials.key_problem()
        if problem:
            raise ResourceError(problem, "credential_not_loaded")
        try:
            import arkruntime  # noqa: F401
            import httpx  # noqa: F401
        except ImportError:
            raise ResourceError("官方 SDK 运行依赖不完整，请修复 ark 可选依赖", "sdk_unavailable") from None

    def _capture(self, request):
        # Compare the real wire body before the SDK can send it. Credentials are
        # never included in this evidence or exception messages.
        if str(request.url).split("?", 1)[0] != credentials.PLAN_BASE + self.expected_path:
            raise ResourceError("SDK 尝试访问未授权的数据面地址", "sdk_request_changed")
        method = "POST" if self.expected is not None else "GET"
        if request.method != method:
            raise ResourceError("SDK 请求方法改变", "sdk_request_changed")
        if self.request_count:
            raise ResourceError("SDK 尝试重复提交；结果保持未知，不重发", "sdk_retry_forbidden")
        self.request_count += 1
        actual = _without_none(json.loads(request.content)) if self.expected is not None else None
        if actual != self.expected:
            raise ResourceError("SDK 请求与固定模型、提示词或输入不一致，已在发送前阻止", "sdk_request_changed")
        self.wire = {"method": method, "path": self.expected_path, "payload_sha256": _digest(actual), "requests": 1}

    def __call__(self, path, payload=None):
        if path not in {"/images/generations", "/contents/generations/tasks"} and not re.fullmatch(r"/contents/generations/tasks/[A-Za-z0-9_.-]{1,200}", path):
            raise ResourceError("官方 SDK 只允许已固定图像和视频任务接口", "sdk_endpoint_forbidden")
        if payload is not None and path not in {"/images/generations", "/contents/generations/tasks"}:
            raise ResourceError("任务查询不能携带创建请求", "sdk_endpoint_forbidden")
        self.preflight()
        from arkruntime import Ark
        import httpx
        # SDK debug output can contain request content; the worker emits only
        # structured, credential-free evidence and generic authentication errors.
        for name in ("arkruntime", "arkruntime._base_client", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        client = self.http_client or httpx.Client(follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(600, connect=30))
        hooks = client.event_hooks.setdefault("request", [])
        hooks.append(self._capture)
        self.expected, self.expected_path = _without_none(deepcopy(payload)), path
        self.request_count, self.wire = 0, None
        try:
            sdk = Ark(api_key=credentials.read_key(), base_url=credentials.PLAN_BASE,
                max_retries=0, timeout=600, http_client=client)
            if path == "/images/generations":
                response = sdk.images.generate(**payload)
            elif path == "/contents/generations/tasks":
                response = sdk.content_generation.tasks.create(**payload)
            else:
                response = sdk.content_generation.tasks.get(path.rsplit("/", 1)[1])
            raw = response.model_dump(mode="json", exclude_none=True)
            if not isinstance(raw, dict) or self.wire is None:
                raise ResourceError("SDK 未返回可核验的结构响应", "sdk_response_invalid")
            raw["vsc_execution"] = {"format": "vsc.provider-execution/v1", **self.identity,
                "tool": SDK_NAME, "tool_version": SDK_VERSION, "tool_publisher": "volcengine", "tool_source": SOURCE,
                "runtime_sha256": self.runtime["sha256"], "adapter_version": ADAPTER_VERSION,
                "max_retries": 0, "client_prompt_rewrite": False, "wire": self.wire,
                "model_returned": raw.get("model"), "usage": raw.get("usage")}
            return raw
        except ResourceError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            message = credentials.permission_denied(status, "官方 SDK 多模态接口")
            raise ResourceError(message or "官方 SDK 请求失败；已提交的未知结果不能自动重发", "sdk_auth_failed" if status in (401, 403) else "sdk_request_failed") from None
        finally:
            hooks.remove(self._capture)
            if self.http_client is None:
                client.close()
