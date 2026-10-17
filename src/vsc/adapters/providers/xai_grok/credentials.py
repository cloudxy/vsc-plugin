#!/usr/bin/env python3
"""xAI Grok 订阅凭证约定：图片与图生视频使用 grok CLI 登录态（订阅授权），不用独立 API Key。

订阅路线读取 ~/.grok/auth.json（在终端运行 grok 并按提示登录后生成）。文件按账号嵌套，
key 位于各账号条目内，是有时效的访问令牌，由 grok CLI 在使用中自动刷新。这里只读本地文件，
不联网、不刷新、不打印密钥值；过期或缺失时提示在终端运行 grok 登录或刷新。
按用量计费的 XAI_API_KEY 独立 API 路线与订阅分开建模，当前未接通，不混用凭证。
"""
import datetime
import json
from pathlib import Path

LOGIN_FILE = Path.home() / ".grok" / "auth.json"
API_BASE = "https://api.x.ai/v1"
# 官方接口在无浏览器 User-Agent 时经 Cloudflare 返回 403/1010；请求统一带此标头。
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
PERMISSION_STATUSES = (401, 403)


def _entries(data):
    """账号条目按嵌套结构展开；只保留带非空 key 的条目。"""
    if not isinstance(data, dict):
        return []
    found = []
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("key"), str) and value["key"].strip():
            found.append(value)
    return found


def _expiry(entry):
    value = entry.get("expires_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _login_entry():
    """Pick the unexpired account deterministically; returns (entry, problem)."""
    if not LOGIN_FILE.is_file():
        return None, None
    try:
        data = json.loads(LOGIN_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return None, "grok 登录态文件无法读取：" + str(LOGIN_FILE) + "；请重新登录"
    entries = _entries(data)
    if not entries:
        return None, "grok 登录态文件中没有可用 key：请在终端运行 grok 重新登录"
    fresh = [entry for entry in entries if (expiry := _expiry(entry)) is None or expiry > datetime.datetime.now(datetime.timezone.utc)]
    if not fresh:
        return None, "grok 登录态已过期：请在终端运行 grok 刷新登录后再使用 Grok 路线"
    chosen = max(fresh, key=lambda entry: _expiry(entry) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    if any(ord(char) < 32 for char in chosen["key"].strip()):
        return None, "grok 登录态凭证含非法控制字符：请重新登录"
    return chosen, None


def _login_key():
    entry, problem = _login_entry()
    if entry is None:
        return None, problem
    return entry["key"].strip(), None


def account_id():
    """登录账号的稳定身份（user_id，缺省退 email）；与可刷新 token 分开（F12）。

    任务归属与续查一致性以该身份为准：同账号刷新 token 后旧任务仍可续查；
    返回 None 表示当前登录态不可用或缺少稳定身份字段。
    """
    entry, problem = _login_entry()
    if entry is None:
        return None
    return str(entry.get("user_id") or entry.get("email") or "") or None


def key_problem():
    """User-facing reason the login state cannot supply a key, or None when it can."""
    if not LOGIN_FILE.is_file():
        return ("未找到 grok 订阅登录态：请在终端运行 grok，按提示完成登录，"
                "使 " + str(LOGIN_FILE) + " 生成后再使用 Grok 路线")
    _, problem = _login_key()
    return problem


def read_key(error=RuntimeError):
    problem = key_problem()
    if problem:
        raise error(problem)
    return _login_key()[0]


def login_present():
    """Local presence only; never probes the network or echoes the key."""
    return key_problem() is None


def permission_denied(status, service):
    """User-facing text when the provider rejects the login key; None for other statuses."""
    if status not in PERMISSION_STATUSES:
        return None
    return (f"HTTP {status}：grok 登录态没有{service}的权限，请自行核对订阅状态与登录账号"
            "（重新运行 grok 登录或核对订阅）；工作流不会自动换凭证或重试")
