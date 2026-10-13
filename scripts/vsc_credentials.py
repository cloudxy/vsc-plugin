#!/usr/bin/env python3
"""火山引擎凭证约定：图片、视频、语音与音效统一使用一把方舟 Agent Plan 专属 key。

自 2026-10-13 起只读 ARK_AGENT_PLAN_API_KEY（配置于 ~/.zshenv）。旧变量名已停用：脚本遇到
它们时明确提示“API Key 已更换”，不静默读取。密钥值不打印、不保存。

方舟 Agent Plan 套餐规则：文本生成模型及向量化模型不可用于 API 调用；在非 AI 工具中使用套餐
Base URL 和 API Key 可能被识别为滥用，导致订阅停用或账号封禁。因此视觉检查、图生文等走
对话模型的直接调用一律拦截。
"""
import os
import re
import sys

KEY_ENV = "ARK_AGENT_PLAN_API_KEY"
RETIRED = ("HUO_SHAN_API_KEY", "ARK_API_KEY", "ARK_CODING_PLAN_API_KEY",
           "DOUBAO_SPEECH_API_KEY", "DOUBAO_MEDIAKIT_API_KEY")
CHANGED_ON = "2026-10-13"
RELOAD = "在启动工具的 zsh 中执行 source ~/.zshenv 后重启工具；其他启动方式须显式传入环境变量"
TEXT_MODELS_FORBIDDEN = ("方舟 Agent Plan 规则：文本生成模型及向量化模型不可用于 API 调用；"
                         f"{KEY_ENV} 只用于图片、视频与语音生成，视觉检查和图生文请改为人工审看")
_noticed = False


def changed(name):
    return f"火山方舟 API Key 已更换：{name} 已于 {CHANGED_ON} 停用，请改用 {KEY_ENV}（~/.zshenv）；{RELOAD}"


def stale_names():
    return [name for name in RETIRED if os.environ.get(name)]


def key_problem(env_name=KEY_ENV):
    """User-facing reason this variable cannot supply a key, or None when it can."""
    if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        return "--key-env 只接受环境变量名，不接受密钥字面值"
    if env_name in RETIRED:
        return changed(env_name)
    value = os.environ.get(env_name, "").strip()
    if value:
        return "凭证含非法控制字符" if any(ord(char) < 32 for char in value) else None
    stale = stale_names()
    if env_name == KEY_ENV and stale:
        return (f"火山方舟 API Key 已更换：当前进程仍是已停用的 {'、'.join(stale)}，"
                f"缺少新变量 {KEY_ENV}（~/.zshenv）；{RELOAD}")
    return f"缺少 {env_name}；请检查 ~/.zshenv 中的 export 配置，{RELOAD}"


def notify_stale(stream=None):
    """Once per process, tell an old session that its retired variables are ignored."""
    global _noticed
    stale = stale_names()
    if stale and not _noticed:
        _noticed = True
        print(f"提示：火山方舟 API Key 已更换，本次使用 {KEY_ENV}；"
              f"环境中的旧变量 {'、'.join(stale)} 已不再读取，重开终端即可清除。", file=stream or sys.stderr)


def read_key(env_name=KEY_ENV, error=RuntimeError):
    problem = key_problem(env_name)
    if problem:
        raise error(problem)
    notify_stale()
    return os.environ[env_name].strip()


def text_model_problem():
    """The only configured Volcano key is an Agent Plan key, so direct text-model calls are refused."""
    return TEXT_MODELS_FORBIDDEN
