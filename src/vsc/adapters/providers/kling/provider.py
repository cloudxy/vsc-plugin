#!/usr/bin/env python3
"""快手可灵（Kling AI）图像与视频生产适配器。

遵守 VSC 生产计费与归属安全不变量：
1. `preflight()` 在零网络调用下完成全部参数、画幅/时长、未知字段与环境变量核验；
2. `submit()` 对上游计费端点严格只发送 1 次 `POST`（零重试、零回退），异常交由
   `ResourceWorker` 保持 `submission_unknown`；
3. `poll()` 与 `parse_result()` 强制核验 `_vsc_kling_account_sha256` 稳定账号指纹；
4. `poll()` 在每一轮非终态（`submitted`/`running`）与终态（`succeeded`/`failed`）返回时，
   均原样结转 `kling_route`、`_vsc_kling_account_sha256` 与 `submission` 证据，确保跨多轮
   `ResourceWorker` 覆写 `raw_response` 后任务句柄恢复零丢参。
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlsplit

from vsc.adapters.providers.kling import credentials, spec
from vsc.production.provider_errors import safe_generation_detail
from vsc.production.providers import (
    GeneratedAsset,
    ImageRequest,
    JobHandle,
    JobStatus,
    VideoRequest,
)


class KlingAdapterError(ValueError):
    """快手可灵生产适配器错误（已脱敏，不含密钥或 JWT）。"""


ACCOUNT_FIELD = "_vsc_kling_account_sha256"
IMAGE_ALLOWED_ROUTES = frozenset({"images/generations"})
VIDEO_ALLOWED_ROUTES = frozenset(
    {"videos/text2video", "videos/image2video", "videos/multi-image2video"}
)
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s\"',;]+")

IMAGE_SUPPORTED_PARAMS = frozenset(
    {
        "resolution",
        "aspect_ratio",
        "image_reference",
        "negative_prompt",
        "image_fidelity",
        "human_fidelity",
    }
)
VIDEO_SUPPORTED_PARAMS = frozenset(
    {"resolution", "aspect_ratio", "generate_audio", "negative_prompt"}
)


def _redact_text(detail: Any, secrets: list[str]) -> str:
    text = str(detail or "")
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return safe_generation_detail(text)


def _sanitize_json(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item, secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
        text = _BEARER_RE.sub("Bearer [REDACTED]", text)
        text = _JWT_RE.sub("[REDACTED]", text)
        return text
    return value


def _validate_base_url(base_url: str) -> str:
    clean = str(base_url or "").strip().rstrip("/")
    if clean not in credentials.ALLOWED_BASES:
        raise KlingAdapterError(f"可灵生产端点不在官方允许列表：{clean or '<empty>'}")
    return clean


def _validate_https_output_url(url: Any, label: str) -> str:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise KlingAdapterError(f"可灵{label}结果缺有效 https:// 下载 URL")
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise KlingAdapterError(f"可灵{label}下载 URL 格式不安全")
    return url


def _verify_account(raw: Any, auth_ref: str) -> str:
    saved = raw.get(ACCOUNT_FIELD) if isinstance(raw, dict) else None
    if not isinstance(saved, str) or not saved:
        raise KlingAdapterError("可灵任务缺少稳定账号身份指纹，拒绝猜测归属")
    current = credentials.account_sha256(auth_ref, error=KlingAdapterError)
    if saved != current:
        raise KlingAdapterError("当前可灵凭证账号与原任务提交账号不一致，拒绝跨账号查询或下载")
    return saved


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    auth_ref: str,
    payload: dict[str, Any] | None = None,
    client=None,
    transport=None,
) -> tuple[dict[str, Any], str]:
    root = _validate_base_url(base_url)
    token, account_fp = credentials.resolve_auth(auth_ref, error=KlingAdapterError)
    secrets = [*credentials.secret_values(auth_ref), token]

    if transport is not None:
        try:
            raw = transport(method, path, payload)
        except KlingAdapterError:
            raise
        except Exception as exc:
            detail = _redact_text(f"{type(exc).__name__}: {exc}", secrets)
            raise KlingAdapterError(f"可灵请求异常（{detail}）；提交结果按未知保留") from exc
        if not isinstance(raw, dict):
            raise KlingAdapterError("可灵接口响应不是对象；提交结果须按未知处理并对账")
        return _sanitize_json(raw, secrets), account_fp

    import httpx

    url = f"{root}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"

    owned = client is None
    http = client if client is not None else httpx.Client(timeout=120.0, follow_redirects=False)
    try:
        if method == "POST":
            # Strictly 1 POST, zero retries (G-04 / SEC-03).
            response = http.post(url, json=payload, headers=headers)
        elif method == "GET":
            response = http.get(url, headers=headers)
        else:
            raise KlingAdapterError(f"不支持的 HTTP 方法：{method}")
    except httpx.HTTPError as exc:
        detail = _redact_text(f"{type(exc).__name__}: {exc}", secrets)
        raise KlingAdapterError(f"可灵网络请求未完成（{detail}）；为防重复扣费不自动重试") from exc
    finally:
        if owned:
            http.close()

    if not (200 <= response.status_code < 300):
        denied = credentials.permission_denied(response.status_code, "快手可灵生成服务", auth_ref)
        preview = _redact_text(response.text, secrets)
        if denied:
            raise KlingAdapterError(f"{denied}（上游响应：{preview}）" if preview else denied)
        raise KlingAdapterError(f"可灵接口返回 HTTP {response.status_code}：{preview or '无详情'}")

    try:
        parsed = response.json()
    except ValueError as exc:
        raise KlingAdapterError("可灵接口响应不是有效 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise KlingAdapterError("可灵接口响应不是 JSON 对象")
    return _sanitize_json(parsed, secrets), account_fp


def _extract_submitted_task_id(redacted_raw: dict[str, Any]) -> str:
    code = redacted_raw.get("code")
    if type(code) is not int or code != 0:
        msg = redacted_raw.get("message") or "上游返回非零状态码"
        raise KlingAdapterError(f"可灵提交被拒绝（code={code!r}）：{msg}")
    data = redacted_raw.get("data")
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id.strip()):
        raise KlingAdapterError("可灵提交响应缺有效 data.task_id；提交结果须按未知处理并对账")
    return task_id.strip()


def _poll_kling_task(
    handle: JobHandle,
    *,
    expected_model: str,
    allowed_routes: frozenset[str],
    base_url: str,
    auth_ref: str,
    client=None,
    transport=None,
) -> JobStatus:
    if (
        handle.provider != "kling"
        or handle.model != expected_model
        or not isinstance(handle.external_task_id, str)
        or not _TASK_ID_RE.fullmatch(handle.external_task_id.strip())
    ):
        raise KlingAdapterError("可灵任务句柄与当前适配器不匹配")
    if not isinstance(handle.raw, dict):
        raise KlingAdapterError("可灵任务句柄缺少原始元数据对象")
    kling_route = handle.raw.get("kling_route")
    if not isinstance(kling_route, str) or kling_route not in allowed_routes:
        raise KlingAdapterError("可灵任务句柄缺少合法 kling_route，拒绝猜测轮询路径")
    saved_account = _verify_account(handle.raw, auth_ref)

    task_id = handle.external_task_id.strip()
    redacted_poll_raw, _ = _request_json(
        "GET",
        base_url,
        f"/v1/{kling_route}/{task_id}",
        auth_ref=auth_ref,
        client=client,
        transport=transport,
    )
    code = redacted_poll_raw.get("code")
    if type(code) is not int or code != 0:
        msg = redacted_poll_raw.get("message") or "上游查询返回非零状态码"
        raise KlingAdapterError(f"可灵任务查询失败（code={code!r}）：{msg}")

    # F-002 invariant: ResourceWorker overwrites job["raw_response"] with status.raw on every
    # non-terminal and terminal poll; carry forward kling_route, ACCOUNT_FIELD, and submission.
    bound: dict[str, Any] = {
        **redacted_poll_raw,
        "kling_route": kling_route,
        ACCOUNT_FIELD: saved_account,
        "submission": handle.raw.get("submission"),
    }
    data = redacted_poll_raw.get("data")
    task_status = data.get("task_status") if isinstance(data, dict) else None
    if task_status == "submitted":
        return JobStatus("submitted", retryable=True, raw=bound)
    if task_status == "processing":
        return JobStatus("running", retryable=True, raw=bound)
    if task_status == "succeed":
        return JobStatus("succeeded", raw=bound)
    if task_status == "failed":
        return JobStatus("failed", error_code="kling_task_failed", raw=bound)
    raise KlingAdapterError(f"可灵任务返回未知状态：{task_status!r}")


class KlingImageProvider:
    """Asynchronous Kling `/v1/images/generations` production adapter."""

    def __init__(
        self,
        model: str,
        media_url: Callable[[str], str],
        ratio_for: Callable[[int, int], str | None],
        resolution: str = "2k",
        *,
        base_url: str = credentials.DEFAULT_BASE,
        auth_ref: str = credentials.DEFAULT_AUTH_REF,
        client=None,
        transport=None,
    ):
        self.model = model
        self.media_url = media_url
        self.ratio_for = ratio_for
        self.resolution = resolution
        self.base_url = base_url
        self.auth_ref = auth_ref
        self.client = client
        self.transport = transport

    def _compile(self, req: ImageRequest) -> tuple[str, dict[str, Any]]:
        if req.operation or req.source_media_id or req.mask_media_id:
            raise KlingAdapterError("当前可灵图像适配器不支持遮罩重绘或固定源操作")
        if req.width < 1 or req.height < 1:
            raise KlingAdapterError("图像规格缺有效宽高")
        params = req.params or {}
        unknown = set(params) - IMAGE_SUPPORTED_PARAMS
        if unknown:
            raise KlingAdapterError("可灵图像未支持参数：" + ",".join(sorted(unknown)))
        references = [self.media_url(media_id) for media_id in req.reference_media_ids]
        ratio = params["aspect_ratio"] if "aspect_ratio" in params else self.ratio_for(req.width, req.height)
        try:
            return spec.compile_image(
                self.model,
                req.prompt,
                references,
                ratio or "",
                params.get("resolution", self.resolution),
                image_reference=params.get("image_reference"),
                negative_prompt=params.get("negative_prompt", ""),
                image_fidelity=params.get("image_fidelity"),
                human_fidelity=params.get("human_fidelity"),
            )
        except spec.KlingSpecError as exc:
            raise KlingAdapterError(str(exc)) from None

    def preflight(self, req: ImageRequest | None = None) -> None:
        """All local checks (zero network) before budget reservation or submission intent."""
        _validate_base_url(self.base_url)
        if req is not None:
            self._compile(req)
        credentials.resolve_auth(self.auth_ref, error=KlingAdapterError)

    def submit(self, req: ImageRequest) -> JobHandle:
        self.preflight(req)
        submit_path, payload = self._compile(req)
        redacted_raw, account_fp = _request_json(
            "POST",
            self.base_url,
            submit_path,
            auth_ref=self.auth_ref,
            payload=payload,
            client=self.client,
            transport=self.transport,
        )
        task_id = _extract_submitted_task_id(redacted_raw)
        return JobHandle(
            "kling",
            self.model,
            task_id,
            {
                "kling_route": "images/generations",
                ACCOUNT_FIELD: account_fp,
                "submission": redacted_raw,
            },
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        return _poll_kling_task(
            handle,
            expected_model=self.model,
            allowed_routes=IMAGE_ALLOWED_ROUTES,
            base_url=self.base_url,
            auth_ref=self.auth_ref,
            client=self.client,
            transport=self.transport,
        )

    def parse_result(self, raw: dict[str, Any]) -> list[GeneratedAsset]:
        _verify_account(raw, self.auth_ref)
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, dict) or data.get("task_status") != "succeed":
            raise KlingAdapterError("可灵图像任务尚未成功完成")
        result = data.get("task_result")
        items = result.get("images") if isinstance(result, dict) else None
        if not isinstance(items, list) or not items:
            raise KlingAdapterError("可灵图像响应缺少候选素材")
        assets: list[GeneratedAsset] = []
        for item in items:
            if not isinstance(item, dict):
                raise KlingAdapterError("可灵图像候选条目格式无效")
            url = _validate_https_output_url(item.get("url"), "图像")
            meta = {k: v for k, v in item.items() if k != "url"}
            if isinstance(data.get("task_id"), str) and data["task_id"]:
                meta.setdefault("task_id", data["task_id"])
            assets.append(GeneratedAsset("image", temporary_uri=url, metadata=meta))
        return assets


class KlingVideoProvider:
    """Asynchronous Kling `text2video` / `image2video` / `multi-image2video` adapter."""

    def __init__(
        self,
        model: str,
        media_url: Callable[[str], str],
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: bool = True,
        *,
        base_url: str = credentials.DEFAULT_BASE,
        auth_ref: str = credentials.DEFAULT_AUTH_REF,
        client=None,
        transport=None,
    ):
        self.model = model
        self.media_url = media_url
        self.resolution = resolution
        self.ratio = ratio or "16:9"
        self.generate_audio = generate_audio
        self.base_url = base_url
        self.auth_ref = auth_ref
        self.client = client
        self.transport = transport

    def _compile(self, req: VideoRequest) -> tuple[str, str, dict[str, Any]]:
        if req.operation or req.source_media_id:
            raise KlingAdapterError("可灵视频适配器不支持固定源编辑或续接操作")
        if req.keyframes:
            raise KlingAdapterError("可灵视频适配器不支持中段关键帧时间戳钉定")
        if req.reference_audio_media_ids:
            raise KlingAdapterError("可灵视频适配器不支持外部参考音频素材文件")
        if req.reference_video_media_ids:
            raise KlingAdapterError("可灵视频适配器不支持参考视频文件输入")
        if req.subject_mask_media_id:
            raise KlingAdapterError("可灵视频适配器不支持主体遮罩输入")
        params = req.params or {}
        unknown = set(params) - VIDEO_SUPPORTED_PARAMS
        if unknown:
            raise KlingAdapterError("可灵视频未支持参数：" + ",".join(sorted(unknown)))
        first_frame = self.media_url(req.first_frame_media_id) if req.first_frame_media_id else None
        last_frame = self.media_url(req.last_frame_media_id) if req.last_frame_media_id else None
        references = [self.media_url(media_id) for media_id in req.reference_media_ids]
        try:
            return spec.compile_video(
                self.model,
                req.prompt,
                req.duration_ms,
                first_frame=first_frame,
                last_frame=last_frame,
                references=references,
                aspect_ratio=params.get("aspect_ratio", self.ratio),
                resolution=params.get("resolution", self.resolution),
                generate_audio=params.get("generate_audio", self.generate_audio),
                negative_prompt=params.get("negative_prompt", ""),
            )
        except spec.KlingSpecError as exc:
            raise KlingAdapterError(str(exc)) from None

    def preflight(self, req: VideoRequest | None = None) -> None:
        """All local checks (zero network) before budget reservation or submission intent."""
        _validate_base_url(self.base_url)
        if req is not None:
            self._compile(req)
        credentials.resolve_auth(self.auth_ref, error=KlingAdapterError)

    def submit(self, req: VideoRequest) -> JobHandle:
        self.preflight(req)
        submit_path, kling_route, payload = self._compile(req)
        redacted_raw, account_fp = _request_json(
            "POST",
            self.base_url,
            submit_path,
            auth_ref=self.auth_ref,
            payload=payload,
            client=self.client,
            transport=self.transport,
        )
        task_id = _extract_submitted_task_id(redacted_raw)
        return JobHandle(
            "kling",
            self.model,
            task_id,
            {
                "kling_route": kling_route,
                ACCOUNT_FIELD: account_fp,
                "submission": redacted_raw,
            },
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        return _poll_kling_task(
            handle,
            expected_model=self.model,
            allowed_routes=VIDEO_ALLOWED_ROUTES,
            base_url=self.base_url,
            auth_ref=self.auth_ref,
            client=self.client,
            transport=self.transport,
        )

    def parse_result(self, raw: dict[str, Any]) -> list[GeneratedAsset]:
        _verify_account(raw, self.auth_ref)
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, dict) or data.get("task_status") != "succeed":
            raise KlingAdapterError("可灵视频任务尚未成功完成")
        result = data.get("task_result")
        items = result.get("videos") if isinstance(result, dict) else None
        if not isinstance(items, list) or not items:
            raise KlingAdapterError("可灵视频响应缺少候选素材")
        assets: list[GeneratedAsset] = []
        for item in items:
            if not isinstance(item, dict):
                raise KlingAdapterError("可灵视频候选条目格式无效")
            url = _validate_https_output_url(item.get("url"), "视频")
            meta = {k: v for k, v in item.items() if k != "url"}
            if isinstance(data.get("task_id"), str) and data["task_id"]:
                meta.setdefault("task_id", data["task_id"])
            assets.append(GeneratedAsset("video", temporary_uri=url, metadata=meta))
        return assets
