"""Character studio routes: reference galleries, CLI/OAuth auth bridges and HTTPS provider proxy.

Browser-configured API keys stay in browser localStorage and only traverse `/api/proxy`
to allow-listed HTTPS origins.  Local CLI/OAuth modes (`grok_auth` and `agy_auth`) run
on the server using the user's local `~/.grok/auth.json` or `agy` CLI state without
ever returning or logging raw credentials.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from vsc.adapters.providers.xai_grok import credentials as grok_credentials
from vsc.adapters.providers.xai_grok import spec as grok_spec
from vsc.assets import pose_gallery
from vsc.bootstrap import repository_root

DEFAULT_ALLOWED_ORIGINS = (
    "https://dashscope.aliyuncs.com",
    "https://*.aliyuncs.com",
    "https://ark.cn-beijing.volces.com",
    "https://*.volces.com",
    "https://generativelanguage.googleapis.com",
    "https://api.openai.com",
    "https://api.x.ai",
    "https://*.x.ai",
)
MAX_PROXY_BYTES = 15 * 1024 * 1024
MAX_GENERATE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024
FORWARD_HEADERS = ("content-type", "authorization", "x-goog-api-key", "x-dashscope-async", "accept")
MEDIA_URL_PREFIX = "/api/v1/asset-center/pose-gallery/media/"
AGY_STATE_REL = Path(".gemini") / "antigravity-cli" / "jetski_state.pbtxt"
AGY_BRAIN_REL = Path(".gemini") / "antigravity-cli" / "brain"
AGY_IMAGE_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "saved_path": {"type": "string"},
            "error": {"type": "string"},
        },
        "required": ["saved_path", "error"],
    },
    separators=(",", ":"),
)
_WILDCARD = re.compile(r"^(?:(https?)://)?\*\.([a-z0-9.-]+)(?::(\d+))?(?:/.*)?$", re.I)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_MODEL_ID_RE = re.compile(r"\b(?:gemini|claude|gpt)-[a-z0-9][a-z0-9.-]{2,60}\b", re.I)
_SAFE_CONV_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{3,127}$")
_ABS_IMAGE_PATH_RE = re.compile(r"(/[^\s`'\"<>()]+?\.(?:png|jpe?g|webp|gif))", re.I)
_QUOTA_RESET_RE = re.compile(r"reset after\s+([0-9hms.]+)", re.I)
_FALLBACK_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def _rule_matches(target, rule: str) -> bool:
    rule = rule.strip()
    if not rule:
        return False
    if rule == "*":
        return True
    wildcard = _WILDCARD.match(rule)
    if wildcard:
        proto, base, port = wildcard.groups()
        if proto and proto.lower() != target.scheme:
            return False
        if (port or "") != (str(target.port) if target.port else ""):
            return False
        host = (target.hostname or "").lower()
        suffix = "." + base.lower().strip(".")
        return host.endswith(suffix) and len(host) > len(suffix)
    parsed = urlsplit(rule if "://" in rule else "https://" + rule)
    return (parsed.scheme, (parsed.hostname or "").lower(), parsed.port) == (
        target.scheme,
        (target.hostname or "").lower(),
        target.port,
    )


def _safe_https_target(url: str):
    try:
        target = urlsplit(url)
        target.port  # noqa: B018 - validates port syntax
    except ValueError:
        return None
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        return None
    try:
        address = ipaddress.ip_address(target.hostname.strip("[]"))
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return None
    host = (target.hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return None
    return target


def proxy_target_allowed(url: str, extra: str = "") -> bool:
    target = _safe_https_target(url)
    if target is None:
        return False
    rules = list(DEFAULT_ALLOWED_ORIGINS) + [r for r in re.split(r"[\s,;]+", extra or "") if r]
    return any(_rule_matches(target, rule) for rule in rules)


def _detect_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    return None


def _mask_identity(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "@" in text:
        local, _, domain = text.partition("@")
        head = local[:2] if len(local) > 2 else local[:1]
        return f"{head}***@{domain}"
    if len(text) <= 8:
        return text[:2] + "***"
    return f"{text[:4]}…{text[-4:]}"


def _agy_state_file() -> Path:
    return Path.home() / AGY_STATE_REL


def _agy_brain_dir() -> Path:
    return Path.home() / AGY_BRAIN_REL


def _resolve_cli_bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if getattr(shutil.which, "__module__", "") != "shutil":
        return None
    for folder in (*_FALLBACK_BIN_DIRS, str(Path.home() / ".local" / "bin")):
        cand = Path(folder) / name
        try:
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        except OSError:
            continue
    return None


def _grok_auth_status() -> dict:
    cli_installed = bool(_resolve_cli_bin("grok"))
    problem = grok_credentials.key_problem()
    ready = problem is None
    has_file = grok_credentials.LOGIN_FILE.is_file()
    account = _mask_identity(grok_credentials.account_id()) if ready else None
    if ready:
        status = "authorized"
        message = f"Grok 订阅登录已就绪（账号：{account}）" if account else "Grok 订阅登录已就绪"
    elif has_file:
        status = "expired"
        message = problem or "Grok 登录态不可用，请重新授权登录"
    elif not cli_installed:
        status = "cli_missing"
        message = "未检测到本机 grok CLI，请先安装 grok CLI 后运行 grok login --oauth"
    else:
        status = "unauthorized"
        message = "尚未登录 Grok 订阅账号，可点击「调起浏览器授权登录」或在终端执行 grok login --oauth"
    return {
        "provider": "grok_auth",
        "cli_installed": cli_installed,
        "ready": ready,
        "status": status,
        "account": account,
        "message": message,
        "login_command": "grok login --oauth",
    }


def _agy_auth_status() -> dict:
    cli_installed = bool(_resolve_cli_bin("agy"))
    state_file = _agy_state_file()
    try:
        has_state = state_file.is_file() and state_file.stat().st_size > 0
    except OSError:
        has_state = False
    ready = cli_installed and has_state
    if ready:
        status = "authorized"
        message = "本机 AGY (Google Antigravity) 授权已就绪，可通过内置 image-generator 生成图像"
    elif not cli_installed:
        status = "cli_missing"
        message = "未检测到本机 agy CLI，请先安装 Antigravity CLI 后运行 agy 完成登录"
    else:
        status = "unauthorized"
        message = "已安装 agy CLI，尚未检测到授权状态；请点击「打开终端完成 AGY 授权」或在终端运行 agy"
    return {
        "provider": "agy_auth",
        "cli_installed": cli_installed,
        "ready": ready,
        "status": status,
        "account": None,
        "message": message,
        "login_command": "agy",
    }


def _verify_agy_online() -> dict:
    info = _agy_auth_status()
    agy_bin = _resolve_cli_bin("agy")
    if not agy_bin:
        return {**info, "verified": False}
    try:
        proc = subprocess.run(
            [agy_bin, "models"],
            capture_output=True,
            text=True,
            timeout=45,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **info,
            "verified": False,
            "message": f"AGY 在线验证未完成（{type(exc).__name__}），请确认网络或在终端执行 agy models",
        }
    cleaned = _ANSI_RE.sub("", (proc.stdout or "") + "\n" + (proc.stderr or ""))
    models = sorted(set(_MODEL_ID_RE.findall(cleaned)))
    if proc.returncode == 0 and models:
        return {
            **info,
            "ready": True,
            "verified": True,
            "status": "authorized",
            "model_count": len(models),
            "message": f"AGY 在线验证通过（可用模型 {len(models)} 个，内置 image-generator 已就绪）",
        }
    return {
        **info,
        "ready": False,
        "verified": False,
        "status": "unauthorized",
        "message": "AGY 尚未完成在线授权或登录已过期，请在终端执行 agy 完成 Google 登录",
    }


def _open_macos_terminal(command: str) -> bool:
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Terminal"\nactivate\ndo script "{escaped}"\nend tell'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=8,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _trigger_auth_login(provider: str) -> dict:
    if provider in ("grok", "grok_auth", "grok_video_auth"):
        grok_bin = _resolve_cli_bin("grok")
        if not grok_bin:
            return {
                "started": False,
                "command": "grok login --oauth",
                "message": "本机未找到 grok 命令，请先安装 grok CLI 后在终端运行 grok login --oauth",
            }
        if _open_macos_terminal(f"{grok_bin} login --oauth"):
            return {
                "started": True,
                "command": "grok login --oauth",
                "message": "已打开终端并调起浏览器 Grok OAuth 授权，请在浏览器中点击确认；完成后本页会自动更新状态。",
            }
        try:
            subprocess.Popen(
                [grok_bin, "login", "--oauth"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "started": True,
                "command": "grok login --oauth",
                "message": "已启动 Grok 浏览器 OAuth 登录流程，请在弹出的浏览器页面完成授权；也可在终端运行 grok login --oauth。",
            }
        except OSError:
            return {
                "started": False,
                "command": "grok login --oauth",
                "message": "无法自动启动登录进程，请复制命令 grok login --oauth 在终端执行。",
            }
    if provider in ("agy", "agy_auth"):
        agy_bin = _resolve_cli_bin("agy")
        if not agy_bin:
            return {
                "started": False,
                "command": "agy",
                "message": "本机未找到 agy 命令，请先安装 Antigravity CLI 后在终端运行 agy 完成登录。",
            }
        if _open_macos_terminal(agy_bin):
            return {
                "started": True,
                "command": "agy",
                "message": "已打开终端启动 AGY 登录向导，请按提示完成 Google 账号授权；完成后本页会自动刷新状态。",
            }
        return {
            "started": False,
            "command": "agy",
            "message": "未能自动唤起系统终端，请复制命令 agy 在终端中运行并完成 Google 授权。",
        }
    raise HTTPException(422, "不支持的授权登录类型")


def _resolve_reference_bytes(repo_root: Path, ref: str) -> tuple[bytes, str]:
    value = str(ref or "").strip()
    if not value:
        raise HTTPException(422, "参考图地址不能为空")
    if value.startswith("data:image/"):
        _, sep, payload = value.partition(",")
        if not sep or not payload:
            raise HTTPException(422, "参考图 Base64 格式无效")
        try:
            raw = base64.b64decode(payload, validate=False)
        except ValueError as exc:
            raise HTTPException(422, "参考图 Base64 解码失败") from exc
        if len(raw) > MAX_REFERENCE_IMAGE_BYTES:
            raise HTTPException(413, "单张参考图超过大小限制")
        mime = _detect_image_mime(raw)
        if not mime:
            raise HTTPException(422, "参考图不是受支持的图片格式")
        return raw, mime
    subpath = None
    if value.startswith(MEDIA_URL_PREFIX):
        subpath = value[len(MEDIA_URL_PREFIX) :]
    elif value.lstrip("/").startswith(("img/", "thumbs/")):
        subpath = value.lstrip("/")
    if subpath is not None:
        path = pose_gallery.media_file(repo_root, subpath)
        if path is None:
            raise HTTPException(422, "参考图文件不存在")
        raw = path.read_bytes()
        mime = _detect_image_mime(raw)
        if not mime:
            raise HTTPException(422, "参考图文件格式不受支持")
        return raw, mime
    if value.startswith("https://") and _safe_https_target(value) is not None:
        import httpx

        try:
            with httpx.Client(timeout=30.0, follow_redirects=False) as client:
                res = client.get(value, headers={"User-Agent": grok_credentials.USER_AGENT})
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"下载远程参考图失败：{type(exc).__name__}") from exc
        if res.status_code != 200 or len(res.content) > MAX_REFERENCE_IMAGE_BYTES:
            raise HTTPException(422, f"远程参考图不可用 (HTTP {res.status_code})")
        mime = _detect_image_mime(res.content)
        if not mime:
            raise HTTPException(422, "远程参考图不是有效图片")
        return res.content, mime
    raise HTTPException(422, "不支持的参考图来源地址")


def _download_https_image(url: str) -> tuple[bytes, str]:
    if _safe_https_target(url) is None:
        raise HTTPException(502, "平台返回的图片地址不符合安全要求")
    import httpx

    try:
        with httpx.Client(timeout=120.0, follow_redirects=False) as client:
            res = client.get(url, headers={"User-Agent": grok_credentials.USER_AGENT})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"下载生成结果图片失败：{type(exc).__name__}") from exc
    if res.status_code != 200:
        raise HTTPException(502, f"下载生成结果图片失败 (HTTP {res.status_code})")
    mime = _detect_image_mime(res.content)
    if not mime:
        raise HTTPException(502, "平台返回的生成结果不是有效图片")
    return res.content, mime


def _generate_with_grok_auth(repo_root: Path, body: dict) -> dict:
    try:
        key = grok_credentials.read_key(error=ValueError)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    prompt = str(body.get("prompt") or "").strip()
    model = str(body.get("model") or "grok-imagine-image-2.0").strip() or "grok-imagine-image-2.0"
    aspect_ratio = str(body.get("aspect_ratio") or "3:4").strip()
    resolution = str(body.get("resolution") or "2k").strip().lower()
    raw_refs = body.get("references") or []
    if not isinstance(raw_refs, list) or not raw_refs:
        raise HTTPException(422, "请先选择或上传至少 1 张参考图")
    if len(raw_refs) > grok_spec.EDIT_SOURCE_LIMIT:
        raise HTTPException(
            422,
            f"[Grok 授权] Grok 图像编辑一次最多支持 {grok_spec.EDIT_SOURCE_LIMIT} 张参考图（当前 {len(raw_refs)} 张），请减少附加参考图或关闭附带合成拼图",
        )
    data_uris = []
    for ref in raw_refs:
        raw, mime = _resolve_reference_bytes(repo_root, str(ref))
        data_uris.append(f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}")
    try:
        path, payload = grok_spec.compile_image(model, prompt, data_uris, aspect_ratio, resolution, 1)
    except grok_spec.GrokSpecError as exc:
        raise HTTPException(422, f"[Grok 授权] {exc}") from exc

    import httpx

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": grok_credentials.USER_AGENT,
        "Authorization": f"Bearer {key}",
    }
    try:
        with httpx.Client(timeout=180.0, follow_redirects=False) as client:
            upstream = client.post(f"{grok_credentials.API_BASE}{path}", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        safe_msg = str(exc).replace(key, "[REDACTED]")
        raise HTTPException(502, f"[Grok 授权] 网络请求失败：{type(exc).__name__} ({safe_msg[:160]})") from None

    denied = grok_credentials.permission_denied(upstream.status_code, "xAI Grok Imagine 接口")
    if denied:
        raise HTTPException(upstream.status_code, denied)
    try:
        result = upstream.json()
    except ValueError:
        result = {}
    if upstream.status_code >= 400:
        err_obj = result.get("error") if isinstance(result, dict) else None
        err_msg = (
            (err_obj.get("message") if isinstance(err_obj, dict) else err_obj)
            or (result.get("message") if isinstance(result, dict) else None)
            or upstream.text[:240]
        )
        safe_err = str(err_msg).replace(key, "[REDACTED]")
        raise HTTPException(502 if upstream.status_code >= 500 else upstream.status_code, f"[Grok 授权] {safe_err}")

    items = result.get("data") if isinstance(result, dict) else None
    first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    if isinstance(first.get("b64_json"), str) and first["b64_json"]:
        raw = base64.b64decode(first["b64_json"])
        mime = _detect_image_mime(raw) or "image/png"
        return {"image_url": f"data:{mime};base64,{first['b64_json']}", "model": model, "provider": "grok_auth"}
    if isinstance(first.get("url"), str) and first["url"]:
        raw, mime = _download_https_image(first["url"])
        return {
            "image_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
            "model": model,
            "provider": "grok_auth",
        }
    raise HTTPException(502, "[Grok 授权] 平台已响应但未返回有效图片")


def _probe_agy_image_file(
    candidate: str | Path,
    tmp_dir: Path,
    brain_root: Path | None,
    ref_names: set[str],
) -> Path | None:
    if isinstance(candidate, Path):
        cand = candidate
    else:
        text = str(candidate or "").strip().strip("`'\"")
        if text.startswith("file://"):
            text = text[7:]
        if not text:
            return None
        cand = Path(text).expanduser()
        if not cand.is_absolute():
            cand = tmp_dir / cand
    try:
        resolved = cand.resolve()
        if not resolved.is_file():
            return None
        in_tmp = resolved.is_relative_to(tmp_dir)
        in_brain = brain_root is not None and resolved.is_relative_to(brain_root)
        if not (in_tmp or in_brain):
            return None
        if in_tmp and resolved.parent == tmp_dir and resolved.name in ref_names:
            return None
        with resolved.open("rb") as fh:
            head = fh.read(16)
        if _detect_image_mime(head):
            return resolved
    except OSError:
        return None
    return None


def _parse_agy_json_output(stdout: str) -> dict | None:
    cleaned = _ANSI_RE.sub("", stdout or "").strip()
    if not cleaned:
        return None
    candidates = [cleaned]
    candidates.extend(
        line.strip()
        for line in reversed(cleaned.splitlines())
        if line.strip().startswith("{") and line.strip() != cleaned
    )
    for candidate_text in candidates:
        try:
            obj = json.loads(candidate_text)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _extract_agy_result(
    stdout: str,
    stderr: str,
    tmp_dir: Path,
    out_path: Path,
    ref_names: set[str],
) -> tuple[Path | None, str]:
    try:
        brain_root = _agy_brain_dir().resolve()
    except OSError:
        brain_root = None

    direct = _probe_agy_image_file(out_path, tmp_dir, brain_root, ref_names)
    if direct is not None:
        return direct, ""

    parsed = _parse_agy_json_output(stdout)
    structured: dict = {}
    conv_id = ""
    response_text = ""
    if isinstance(parsed, dict):
        raw_struct = parsed.get("structured_output")
        if isinstance(raw_struct, str) and raw_struct.strip().startswith("{"):
            try:
                raw_struct = json.loads(raw_struct)
            except ValueError:
                raw_struct = None
        structured = raw_struct if isinstance(raw_struct, dict) else parsed
        conv_id = str(parsed.get("conversation_id") or "").strip()
        response_text = str(parsed.get("response") or "").strip()

        saved = str(structured.get("saved_path") or "").strip()
        if saved:
            found = _probe_agy_image_file(saved, tmp_dir, brain_root, ref_names)
            if found is not None:
                return found, ""

        for match in _ABS_IMAGE_PATH_RE.findall(response_text):
            found = _probe_agy_image_file(match, tmp_dir, brain_root, ref_names)
            if found is not None:
                return found, ""

    try:
        tmp_children = sorted(tmp_dir.iterdir())
    except OSError:
        tmp_children = []
    for child in tmp_children:
        found = _probe_agy_image_file(child, tmp_dir, brain_root, ref_names)
        if found is not None:
            return found, ""

    if brain_root is not None and conv_id and _SAFE_CONV_ID_RE.match(conv_id):
        try:
            conv_dir = (brain_root / conv_id).resolve()
            if conv_dir.is_relative_to(brain_root) and conv_dir.is_dir():
                candidates = [p for p in conv_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
                candidates.sort(
                    key=lambda p: (
                        0 if p.name.startswith("vsc_studio_result") else 1,
                        -p.stat().st_mtime,
                        p.name,
                    )
                )
                for child in candidates:
                    found = _probe_agy_image_file(child, tmp_dir, brain_root, ref_names)
                    if found is not None:
                        return found, ""
        except OSError:
            pass

    for err_candidate in (
        structured.get("error") if isinstance(structured, dict) else None,
        parsed.get("error") if isinstance(parsed, dict) else None,
    ):
        text = str(err_candidate or "").strip()
        if text:
            return None, text

    if response_text and response_text not in ("正在等待生图结果", "正在等待生图结果。"):
        return None, response_text

    cleaned_err = _ANSI_RE.sub("", stderr or "").strip()
    err_lines = [ln.strip() for ln in cleaned_err.splitlines() if ln.strip()]
    non_warning_err = [ln for ln in err_lines if not ln.lower().startswith("warning:")]
    if non_warning_err:
        return None, " ".join(non_warning_err)

    cleaned_out = _ANSI_RE.sub("", stdout or "").strip()
    if cleaned_out and parsed is None:
        return None, cleaned_out
    if err_lines:
        return None, " ".join(err_lines)
    return None, ""


def _raise_agy_generation_error(returncode: int, detail: str) -> None:
    compact = re.sub(r"\s+", " ", detail or "").strip()
    lower = compact.lower()
    if (
        "429" in lower
        or "resource_exhausted" in lower
        or "quota_exhausted" in lower
        or "exhausted your capacity" in lower
        or "rate_limit" in lower
        or "too many requests" in lower
    ):
        reset_match = _QUOTA_RESET_RE.search(compact)
        reset_hint = f"（预计 {reset_match.group(1)} 后重置）" if reset_match else ""
        raise HTTPException(
            429,
            f"[AGY 授权] 当前账号的 AGY 生图模型配额已用尽{reset_hint}。"
            "请等待配额重置后再试，或在「API 接口配置」中切换为 Gemini API 接口 / Grok 生图通道。",
        )
    if (
        "no image generated in response" in lower
        or "image_safety" in lower
        or "safety" in lower
        or "content policy" in lower
        or "prohibited" in lower
        or ("安全" in compact and ("拦截" in compact or "过滤" in compact or "拒绝" in compact))
    ):
        raise HTTPException(
            422,
            "[AGY 授权] 生图请求触发模型安全策略拦截（未返回图像）。请尝试更换较温和的参考图或调整提示词描述后重试。",
        )
    if (
        "unauthenticated" in lower
        or "not logged in" in lower
        or "login required" in lower
        or "invalid_grant" in lower
        or "token expired" in lower
        or "authentication failed" in lower
    ):
        raise HTTPException(
            401,
            "[AGY 授权] 本机 AGY 登录态已过期或未授权，请在终端执行 agy 重新完成 Google 登录。",
        )
    short = compact[:280]
    raise HTTPException(
        502,
        f"[AGY 授权] 未获取到有效生成图片（exit={returncode}）{('：' + short) if short else ''}",
    )


def _generate_with_agy_auth(repo_root: Path, body: dict) -> dict:
    agy_bin = _resolve_cli_bin("agy")
    if not agy_bin:
        raise HTTPException(422, "未检测到本机 agy CLI，请先安装 Antigravity CLI")
    if not _agy_auth_status()["ready"]:
        raise HTTPException(401, "AGY 尚未完成授权登录，请先在「API 接口配置」中完成 AGY 登录")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(422, "提示词不能为空")
    model = str(body.get("model") or "image-generator").strip() or "image-generator"
    aspect_ratio = str(body.get("aspect_ratio") or "3:4").strip()
    raw_refs = body.get("references") or []
    if not isinstance(raw_refs, list) or not raw_refs:
        raise HTTPException(422, "请先选择或上传至少 1 张参考图")
    if len(raw_refs) > 8:
        raise HTTPException(422, "[AGY 授权] 单次最多支持 8 张参考图")

    resolved_refs = [_resolve_reference_bytes(repo_root, str(ref)) for ref in raw_refs]
    with tempfile.TemporaryDirectory(prefix="vsc-agy-studio-") as tmp:
        tmp_dir = Path(tmp).resolve()
        ref_paths = []
        ref_names = set()
        for idx, (raw, mime) in enumerate(resolved_refs, 1):
            name = f"ref_{idx}.{_IMAGE_EXT.get(mime, 'png')}"
            target = tmp_dir / name
            target.write_bytes(raw)
            ref_paths.append(target)
            ref_names.add(name)
        out_path = tmp_dir / "result.png"
        ref_list = ", ".join(str(p) for p in ref_paths)
        ref_lines = "\n".join(f"- 图{i}: {p}" for i, p in enumerate(ref_paths, 1))
        agy_prompt = (
            "你是 VSC 角色合成台的生图协调器。严禁读取或修改任何工作区文件，严禁执行终端命令，严禁轮询 manage_subagents 或读取 transcript。\n"
            "请立即通过 `invoke_subagent` 调用 `image-generator` 子智能体执行一次生图：\n"
            '- ImageName: "vsc_studio_result"\n'
            f'- AspectRatio: "{aspect_ratio}"\n'
            f"- ImagePaths（按顺序对应提示词中的图1..图{len(ref_paths)}）: [{ref_list}]\n"
            f"参考图对应关系：\n{ref_lines}\n"
            "要求 `image-generator` 直接调用一次 `generate_image`（若遇到 429 配额耗尽或安全拦截，不要重试，立即原样汇报错误信息；生图成功后直接回复生成的 brain 文件绝对路径，无需移动或转换文件）。\n"
            '你在发出 `invoke_subagent` 后直接简短输出一句“正在等待生图结果”并结束当前回合等待系统唤醒；收到子智能体回复后，立即调用 `finish` 工具填入 `saved_path`（生成图片的绝对路径，失败则填 ""）与 `error`（失败原因原文，成功则填 ""）；调用 `finish` 后若系统提示总结，仅回复 OK。\n\n'
            f"生图提示词：\n{prompt}"
        )
        cmd = [
            agy_bin,
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
            "--effort",
            "low",
            "--add-dir",
            str(tmp_dir),
            "--output-format",
            "json",
            "--json-schema",
            AGY_IMAGE_SCHEMA,
        ]
        if model and model != "image-generator":
            cmd.extend(["--model", model])
        cmd.extend(["-p", agy_prompt])
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
                timeout=240,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "[AGY 授权] 调用 AGY 生图超时，请稍后重试") from None
        except OSError as exc:
            raise HTTPException(502, f"[AGY 授权] 无法启动 agy CLI：{type(exc).__name__}") from exc

        found, error_detail = _extract_agy_result(proc.stdout, proc.stderr, tmp_dir, out_path, ref_names)
        if found is not None:
            raw = found.read_bytes()
            mime = _detect_image_mime(raw)
            if mime:
                return {
                    "image_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
                    "model": model,
                    "provider": "agy_auth",
                }
        _raise_agy_generation_error(proc.returncode, error_detail)


def install_character_studio_routes(app, etag, read_actor, origin):
    def repo():
        return repository_root()

    def page(request, build):
        read_actor(request)
        try:
            return etag(request, build())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/v1/asset-center/pose-gallery/costumes")
    def costumes(
        request: Request,
        top: str = "",
        source: str = "",
        category: str = "",
        tag: str = "",
        q: str = "",
        safe: bool = True,
        offset: int = 0,
        limit: int = pose_gallery.PAGE_SIZE,
    ):
        return page(
            request,
            lambda: pose_gallery.costume_page(
                repo(), top=top, source=source, category=category, tag=tag, q=q, safe=safe, offset=offset, limit=limit
            ),
        )

    @app.get("/api/v1/asset-center/pose-gallery/poses")
    def poses(
        request: Request,
        view: str = "group",
        system: str = "",
        category: str = "",
        angle: str = "",
        q: str = "",
        safe: bool = True,
        offset: int = 0,
        limit: int = pose_gallery.PAGE_SIZE,
    ):
        return page(
            request,
            lambda: pose_gallery.pose_page(
                repo(), view=view, system=system, category=category, angle=angle, q=q, safe=safe, offset=offset, limit=limit
            ),
        )

    @app.get("/api/v1/asset-center/pose-gallery/portraits")
    def portraits(
        request: Request,
        section: str = "",
        hair: str = "",
        style: str = "",
        hot: bool = False,
        q: str = "",
        offset: int = 0,
        limit: int = pose_gallery.PAGE_SIZE,
    ):
        return page(
            request,
            lambda: pose_gallery.portrait_page(
                repo(), section=section, hair=hair, style=style, hot=hot, q=q, offset=offset, limit=limit
            ),
        )

    @app.post("/api/v1/asset-center/pose-gallery/random")
    def random_pick(request: Request, body: dict):
        read_actor(request)
        slot, safe = body.get("slot"), body.get("safe", True) is not False
        try:
            if slot == "recipe":
                return pose_gallery.random_recipe(repo(), safe=safe)
            item = pose_gallery.random_reference(
                repo(), slot, scope=body.get("scope", "similar"), current_id=str(body.get("current_id") or ""), safe=safe
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"item": item}

    @app.get("/api/v1/asset-center/pose-gallery/media/{subpath:path}")
    def media(subpath: str):
        # Image tags send the session cookie but cannot attach the CSRF header.
        path = pose_gallery.media_file(repo(), subpath)
        if path is None:
            raise HTTPException(404, "参考图不存在")
        return FileResponse(
            path,
            media_type=pose_gallery.media_type(path),
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.get("/api/v1/character-studio/auth/status")
    def auth_status(request: Request):
        read_actor(request)
        return {"grok": _grok_auth_status(), "agy": _agy_auth_status()}

    @app.post("/api/v1/character-studio/auth/verify")
    async def auth_verify(request: Request, body: dict):
        origin(request)
        read_actor(request)
        provider = str(body.get("provider") or "").strip()
        if provider in ("grok", "grok_auth", "grok_video_auth"):
            info = _grok_auth_status()
            return {**info, "verified": info["ready"]}
        if provider in ("agy", "agy_auth"):
            return await asyncio.to_thread(_verify_agy_online)
        raise HTTPException(422, "不支持的授权验证类型")

    @app.post("/api/v1/character-studio/auth/login")
    async def auth_login(request: Request, body: dict):
        origin(request)
        read_actor(request)
        provider = str(body.get("provider") or "").strip()
        return await asyncio.to_thread(_trigger_auth_login, provider)

    @app.post("/api/v1/character-studio/generate")
    async def studio_generate(request: Request):
        origin(request)
        read_actor(request)
        raw_body = bytearray()
        async for chunk in request.stream():
            raw_body.extend(chunk)
            if len(raw_body) > MAX_GENERATE_BYTES:
                raise HTTPException(413, "生成请求体超过大小限制")
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(400, "请求 JSON 格式无效") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "请求体必须是 JSON 对象")
        provider = str(body.get("provider") or "").strip()
        if provider == "grok_auth":
            return await asyncio.to_thread(_generate_with_grok_auth, repo(), body)
        if provider == "agy_auth":
            return await asyncio.to_thread(_generate_with_agy_auth, repo(), body)
        raise HTTPException(422, "不支持的服务端授权生图通道")

    @app.post("/api/proxy")
    async def provider_proxy(request: Request):
        origin(request)
        read_actor(request)
        target = request.headers.get("x-target-url", "")
        if not target:
            return JSONResponse({"error": {"message": "Missing x-target-url header"}}, status_code=400)
        method = request.headers.get("x-target-method", "POST").strip().upper()
        if method not in ("POST", "GET"):
            return JSONResponse({"error": {"message": "Unsupported x-target-method"}}, status_code=400)
        if not proxy_target_allowed(target, os.environ.get("PROXY_ALLOWED_ORIGINS", "")):
            return JSONResponse({"error": {"message": "Target origin not allowed"}}, status_code=403)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_PROXY_BYTES:
            return JSONResponse({"error": {"message": f"Request body exceeds {MAX_PROXY_BYTES} bytes"}}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_PROXY_BYTES:
                return JSONResponse({"error": {"message": f"Request body exceeds {MAX_PROXY_BYTES} bytes"}}, status_code=413)
        headers = {k: request.headers[k] for k in FORWARD_HEADERS if request.headers.get(k)}
        headers.setdefault("user-agent", grok_credentials.USER_AGENT)
        import httpx

        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=False) as client:
                if method == "GET":
                    upstream = await client.get(target, headers=headers)
                else:
                    upstream = await client.post(target, content=bytes(body), headers=headers)
        except httpx.HTTPError as error:
            return JSONResponse({"error": {"message": f"Upstream proxy error: {type(error).__name__}"}}, status_code=502)
        return Response(
            upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type") or "application/json; charset=utf-8",
        )
