#!/usr/bin/env python3
"""快手可灵（Kling AI）生产凭证约定：标准库动态签发 HS256 JWT（AK+SK）或兼容单 API Key。

生产注册表 `providers.auth_ref` 仅保存单一环境变量名标识符（配置于 `~/.zshenv`）：
- 当 `auth_ref` 形如 `<PREFIX>_ACCESS_KEY`（默认 `KLING_ACCESS_KEY`）时，自动配对同前缀
  `<PREFIX>_SECRET_KEY`（如 `KLING_SECRET_KEY`），在内存中动态签发短期 HS256 JWT，不落盘；
- 当 `auth_ref` 为其他合法变量名（如 `KLING_API_KEY`）时，作为单 Bearer 令牌读取。
绝不打印、保存或回显任何密钥值与 JWT。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

from vsc.adapters.providers.credentials import RELOAD

DEFAULT_BASE = "https://api-beijing.klingai.com"
ALLOWED_BASES = (
    "https://api-beijing.klingai.com",
    "https://api.klingai.com",
    "https://api-singapore.klingai.com",
)
DEFAULT_AUTH_REF = "KLING_ACCESS_KEY"
SINGLE_KEY_AUTH_REF = "KLING_API_KEY"
PERMISSION_STATUSES = (401, 403)
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ACCESS_KEY_SUFFIX = "_ACCESS_KEY"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def paired_secret_env(auth_ref: str) -> str | None:
    """Derive `<PREFIX>_SECRET_KEY` when `auth_ref` is `<PREFIX>_ACCESS_KEY`; else None."""
    if not isinstance(auth_ref, str):
        return None
    name = auth_ref.strip()
    if not name or not _ENV_NAME_RE.fullmatch(name) or not name.endswith(_ACCESS_KEY_SUFFIX):
        return None
    prefix = name[: -len(_ACCESS_KEY_SUFFIX)]
    if not prefix:
        return None
    candidate = f"{prefix}_SECRET_KEY"
    return candidate if _ENV_NAME_RE.fullmatch(candidate) else None


def missing_env_vars(auth_ref: str) -> list[str]:
    """Return concrete environment variable names missing from `os.environ`."""
    if not isinstance(auth_ref, str) or not auth_ref.strip():
        return [DEFAULT_AUTH_REF, "KLING_SECRET_KEY"]
    name = auth_ref.strip()
    paired = paired_secret_env(name)
    required = (name, paired) if paired else (name,)
    return [var for var in required if not os.environ.get(var, "").strip()]


def encode_kling_jwt(access_key: str, secret_key: str, now_sec: int | None = None) -> str:
    """Sign an official Kling HS256 JWT in memory using only Python stdlib."""
    ak = str(access_key or "").strip()
    sk = str(secret_key or "").strip()
    if not ak or not sk:
        raise ValueError("官方 AK/SK 鉴权需同时提供非空 Access Key 与 Secret Key")
    if any(ord(ch) < 32 for ch in ak) or any(ord(ch) < 32 for ch in sk):
        raise ValueError("可灵 AK/SK 凭证含非法控制字符，请核对 ~/.zshenv 配置")
    now = int(time.time()) if now_sec is None else int(now_sec)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": ak, "exp": now + 1800, "nbf": now - 5}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(sk.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def resolve_auth(
    auth_ref: str = DEFAULT_AUTH_REF,
    *,
    now_sec: int | None = None,
    error=ValueError,
) -> tuple[str, str]:
    """Resolve `(bearer_token, account_sha256)` without network calls or secret echoing."""
    if not isinstance(auth_ref, str) or not _ENV_NAME_RE.fullmatch(auth_ref.strip()):
        raise error("auth_ref 只接受环境变量名，严禁填入密钥明文")
    name = auth_ref.strip()
    paired = paired_secret_env(name)
    missing = missing_env_vars(name)
    if missing:
        joined = " / ".join(missing)
        if paired:
            raise error(
                f"未读取到环境变量 {joined}（配置位置 ~/.zshenv）："
                f"快手可灵官方 AK/SK 模式需在 ~/.zshenv 同时配置 {name} 与 {paired}"
                f"（或改用单密钥 {SINGLE_KEY_AUTH_REF}）；{RELOAD}"
            )
        raise error(
            f"未读取到环境变量 {joined}（配置位置 ~/.zshenv）："
            f"请在 ~/.zshenv 配置 export {name}=\"<API Key>\"；{RELOAD}"
        )
    if paired:
        ak = os.environ[name].strip()
        sk = os.environ[paired].strip()
        if any(ord(ch) < 32 for ch in ak) or any(ord(ch) < 32 for ch in sk):
            raise error("可灵环境变量凭证含非法控制字符，请核对 ~/.zshenv 配置")
        token = encode_kling_jwt(ak, sk, now_sec=now_sec)
        fingerprint = hashlib.sha256(f"ak:{ak}".encode("utf-8")).hexdigest()
        return token, fingerprint

    token = os.environ[name].strip()
    if any(ord(ch) < 32 for ch in token):
        raise error("可灵环境变量凭证含非法控制字符，请核对 ~/.zshenv 配置")
    fingerprint = hashlib.sha256(f"key:{token}".encode("utf-8")).hexdigest()
    return token, fingerprint


def account_sha256(auth_ref: str = DEFAULT_AUTH_REF, *, error=ValueError) -> str:
    """Return deterministic account fingerprint (`sha256('ak:'+ak)` or `sha256('key:'+key)`)."""
    return resolve_auth(auth_ref, error=error)[1]


def secret_values(auth_ref: str = DEFAULT_AUTH_REF) -> list[str]:
    """Internal helper for redacting loaded credentials from upstream failure messages."""
    if not isinstance(auth_ref, str) or not _ENV_NAME_RE.fullmatch(auth_ref.strip()):
        return []
    name = auth_ref.strip()
    paired = paired_secret_env(name)
    names = (name, paired) if paired else (name,)
    return [val for var in names if (val := os.environ.get(var, "").strip())]


def permission_denied(status: int, service: str, auth_ref: str = DEFAULT_AUTH_REF) -> str | None:
    """User-facing text when Kling rejects the credential; None for other HTTP statuses."""
    if status not in PERMISSION_STATUSES:
        return None
    paired = paired_secret_env(auth_ref)
    holder = f"{auth_ref} / {paired}" if paired else (auth_ref or "当前凭证")
    return (
        f"HTTP {status}：{holder} 没有{service}的权限或签名校验未通过，"
        "请核对可灵开放平台凭证、时钟同步与账户余量；工作流不会自动换密钥或重试"
    )
