#!/usr/bin/env python3
"""快手可灵（Kling AI）图像与视频请求编译与本地规格预检（纯函数，零网络 IO）。

所有本地可判定的错误（模型模态、画幅、分辨率、5s/10s 时长、首尾帧与多图互斥、
参考图上限 ≤4、Data URI 前缀剥离与 Base64 校验）均在预算预留与网络提交前拒绝。
"""
from __future__ import annotations

import base64
import binascii
import math
import re
from typing import Any
from urllib.parse import urlsplit


class KlingSpecError(ValueError):
    """本地可判定的无效可灵请求；必须在预留预算与写提交意图前拒绝。"""


IMAGE_MODELS = ("kling-v2-1", "kling-v2", "kling-v1-5", "kolors")
VIDEO_MODELS = ("kling-v2-6", "kling-v2-5-turbo", "kling-v2-1-master", "kling-v1-6")
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9")
IMAGE_RESOLUTIONS = ("1k", "2k")
VIDEO_RESOLUTIONS = ("720p", "1080p")
VIDEO_DURATIONS_MS = (5000, 10000)
IMAGE_REFERENCES = ("subject", "face")
MAX_IMAGE_REFERENCES = 1
MAX_VIDEO_REFERENCES = 4
KLING_ROUTES = (
    "images/generations",
    "videos/text2video",
    "videos/image2video",
    "videos/multi-image2video",
)
_DATA_URI_RE = re.compile(r"^data:([a-zA-Z0-9.+/-]+);base64,([\s\S]+)$", re.I)


def is_image_model(model: str) -> bool:
    name = str(model or "").strip()
    if not name:
        return False
    if name in IMAGE_MODELS:
        return True
    if name in VIDEO_MODELS or "video" in name.lower() or name.endswith(("-turbo", "-master")):
        return False
    return name.startswith(("kling-v", "kling-image-"))


def is_video_model(model: str) -> bool:
    name = str(model or "").strip()
    if not name:
        return False
    if name in VIDEO_MODELS:
        return True
    if name in IMAGE_MODELS or "image" in name.lower():
        return False
    return name.startswith(("kling-v", "kling-video-"))


def strip_data_uri_prefix(value: str) -> str:
    """Strip `data:image/...;base64,` prefix and validate raw Base64 or `https://` URL."""
    if not isinstance(value, str) or not value.strip():
        raise KlingSpecError("可灵参考媒体输入不能为空")
    raw = value.strip()
    if raw.startswith("https://"):
        parsed = urlsplit(raw)
        if not parsed.hostname or parsed.username or parsed.password or any(ord(c) <= 32 for c in raw):
            raise KlingSpecError("可灵参考媒体 https:// 地址格式无效")
        return raw
    if raw.startswith("http://"):
        raise KlingSpecError("可灵参考媒体 URL 须为 https:// 或有效 Base64 字符串")
    match = _DATA_URI_RE.match(raw)
    if match:
        mime, encoded = match.groups()
        if not mime.lower().startswith("image/"):
            raise KlingSpecError(f"可灵参考媒体仅支持 image/* 类型，收到：{mime}")
        cleaned = re.sub(r"\s+", "", encoded)
    else:
        cleaned = re.sub(r"\s+", "", raw)
    if not cleaned:
        raise KlingSpecError("可灵参考图 Base64 内容为空")
    try:
        decoded = base64.b64decode(cleaned, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise KlingSpecError("可灵参考图须为有效 Base64 字符串或 https:// 地址") from exc
    if not decoded:
        raise KlingSpecError("可灵参考图解码字节为空")
    return cleaned


def _validate_fidelity(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise KlingSpecError(f"{field_name} 须为 0.0–1.0 之间的数值")
    num = float(value)
    if not 0.0 <= num <= 1.0:
        raise KlingSpecError(f"{field_name} 须落在 0.0–1.0 范围内")
    return num


def compile_image(
    model: str,
    prompt: str,
    references=(),
    aspect_ratio: str = "3:4",
    resolution: str = "2k",
    image_reference: str | None = None,
    negative_prompt: str = "",
    image_fidelity: float | None = None,
    human_fidelity: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """Compile `/v1/images/generations` payload with pure Base64 reference stripping."""
    if not is_image_model(model):
        raise KlingSpecError(f"不支持的可灵图像模型：{model}")
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise KlingSpecError("可灵图像请求需要非空提示词")
    refs = list(references or ())
    if len(refs) > MAX_IMAGE_REFERENCES:
        raise KlingSpecError(
            f"可灵生产生图单次最多支持 {MAX_IMAGE_REFERENCES} 张参考图（多图请先合成参考板）"
        )
    if aspect_ratio not in ASPECT_RATIOS:
        raise KlingSpecError(f"画幅 {aspect_ratio} 不在可灵图像支持列表")
    if resolution not in IMAGE_RESOLUTIONS:
        raise KlingSpecError("可灵图像分辨率须为 1k 或 2k")

    payload: dict[str, Any] = {
        "model_name": model,
        "prompt": clean_prompt,
        "n": 1,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    if refs:
        payload["image"] = strip_data_uri_prefix(refs[0])
        if image_reference is not None:
            if image_reference not in IMAGE_REFERENCES:
                raise KlingSpecError("image_reference 仅支持 subject 或 face")
            if model != "kling-v1-5":
                raise KlingSpecError("image_reference 细粒度参考仅支持 kling-v1-5 模型")
            payload["image_reference"] = image_reference
        if image_fidelity is not None:
            payload["image_fidelity"] = _validate_fidelity(image_fidelity, "image_fidelity")
        if human_fidelity is not None:
            payload["human_fidelity"] = _validate_fidelity(human_fidelity, "human_fidelity")
    else:
        if image_reference is not None or image_fidelity is not None or human_fidelity is not None:
            raise KlingSpecError("无参考图时不能指定 image_reference 或 fidelity 参数")

    if isinstance(negative_prompt, str) and negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()
    elif negative_prompt not in ("", None):
        raise KlingSpecError("negative_prompt 必须是字符串")

    return "/v1/images/generations", payload


def compile_video(
    model: str,
    prompt: str,
    duration_ms: int,
    first_frame: str | None = None,
    last_frame: str | None = None,
    references=(),
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = True,
    negative_prompt: str = "",
) -> tuple[str, str, dict[str, Any]]:
    """Compile Kling video payload and select `(submit_path, kling_route, payload)`."""
    if not is_video_model(model):
        raise KlingSpecError(f"不支持的可灵视频模型：{model}")
    if type(duration_ms) is not int or duration_ms not in VIDEO_DURATIONS_MS:
        raise KlingSpecError("可灵视频时长仅支持 5000ms（5 秒）或 10000ms（10 秒），禁止静默截断")
    if aspect_ratio not in ASPECT_RATIOS:
        raise KlingSpecError(f"视频画幅 {aspect_ratio} 不在可灵支持列表")
    if resolution not in VIDEO_RESOLUTIONS:
        raise KlingSpecError("可灵视频分辨率须为 720p 或 1080p")
    if not isinstance(generate_audio, bool):
        raise KlingSpecError("generate_audio 必须是布尔值")

    refs = list(references or ())
    if (first_frame or last_frame) and refs:
        raise KlingSpecError("可灵首尾帧图生视频与多图参考生视频互斥，不能同时传入")
    if last_frame and not first_frame:
        raise KlingSpecError("可灵尾帧控制必须同时提供首帧图像")
    if len(refs) > MAX_VIDEO_REFERENCES:
        raise KlingSpecError(
            f"可灵多图参考生视频最多支持 {MAX_VIDEO_REFERENCES} 张参考图（当前已选 {len(refs)} 张）"
        )

    clean_prompt = str(prompt or "").strip()
    duration_str = str(duration_ms // 1000)
    mode = "pro" if resolution == "1080p" else "std"

    if first_frame:
        kling_route = "videos/image2video"
        submit_path = "/v1/videos/image2video"
        payload: dict[str, Any] = {
            "model_name": model,
            "image": strip_data_uri_prefix(first_frame),
            "duration": duration_str,
            "aspect_ratio": aspect_ratio,
            "mode": mode,
        }
        if clean_prompt:
            payload["prompt"] = clean_prompt
        if last_frame:
            payload["image_tail"] = strip_data_uri_prefix(last_frame)
    elif refs:
        if not clean_prompt:
            raise KlingSpecError("可灵多图参考生视频需要非空提示词")
        kling_route = "videos/multi-image2video"
        submit_path = "/v1/videos/multi-image2video"
        payload = {
            "model_name": model,
            "prompt": clean_prompt,
            "image_list": [{"image": strip_data_uri_prefix(ref)} for ref in refs],
            "duration": duration_str,
            "aspect_ratio": aspect_ratio,
            "mode": mode,
        }
    else:
        if not clean_prompt:
            raise KlingSpecError("可灵文生视频需要非空提示词")
        kling_route = "videos/text2video"
        submit_path = "/v1/videos/text2video"
        payload = {
            "model_name": model,
            "prompt": clean_prompt,
            "duration": duration_str,
            "aspect_ratio": aspect_ratio,
            "mode": mode,
        }

    if str(model).startswith("kling-v2-6"):
        payload["sound"] = "on" if generate_audio else "off"

    if isinstance(negative_prompt, str) and negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()
    elif negative_prompt not in ("", None):
        raise KlingSpecError("negative_prompt 必须是字符串")

    return submit_path, kling_route, payload
