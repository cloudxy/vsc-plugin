#!/usr/bin/env python3
"""火山引擎凭证约定：图片、视频、语音与音效统一使用火山方舟 Agent 版本（Agent Plan）的 API Key。

只读 ARK_AGENT_PLAN_API_KEY（配置于 ~/.zshenv）；找不到时提示配置该 key。密钥值不打印、不保存。

方舟 Agent Plan 套餐规则：文本生成模型及向量化模型不可用于 API 调用；在非 AI 工具中使用套餐
Base URL 和 API Key 可能被识别为滥用，导致订阅停用或账号封禁。因此视觉检查、图生文等走
对话模型的直接调用一律拦截。
"""
import os
import re

KEY_ENV = "ARK_AGENT_PLAN_API_KEY"
PLAN_BASE = "https://ark.cn-beijing.volces.com/api/plan/v3"
RELOAD = "在启动工具的 zsh 中执行 source ~/.zshenv 后重启工具；其他启动方式须显式传入环境变量"
TEXT_MODELS_FORBIDDEN = ("方舟 Agent Plan 规则：文本生成模型及向量化模型不可用于 API 调用；"
                         f"{KEY_ENV} 只用于图片、视频与语音生成，视觉检查和图生文请改为人工审看")
# 平台以这些状态拒绝 key 本身；套餐档位与模型权限只认平台返回，不在本地预判。
PERMISSION_STATUSES = (401, 403)


def missing(env_name=KEY_ENV):
    if env_name == KEY_ENV:
        return (f"未找到火山方舟 API Key：请配置火山方舟 Agent 版本（Agent Plan）的 API Key，"
                f"在 ~/.zshenv 写入 export {KEY_ENV}=\"<API Key>\"；{RELOAD}")
    return f"未找到环境变量 {env_name}：请在 ~/.zshenv 配置，或改用火山方舟 Agent 版本的 API Key（{KEY_ENV}）；{RELOAD}"


def key_problem(env_name=KEY_ENV):
    """User-facing reason this variable cannot supply a key, or None when it can."""
    if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        return "--key-env 只接受环境变量名，不接受密钥字面值"
    value = os.environ.get(env_name, "").strip()
    if not value:
        return missing(env_name)
    return "凭证含非法控制字符" if any(ord(char) < 32 for char in value) else None


def read_key(env_name=KEY_ENV, error=RuntimeError):
    problem = key_problem(env_name)
    if problem:
        raise error(problem)
    return os.environ[env_name].strip()


def permission_denied(status, service, env_name=KEY_ENV):
    """User-facing text when the provider rejects the key; None for other HTTP statuses."""
    if status not in PERMISSION_STATUSES:
        return None
    holder = f"{env_name} 对应的 key" if env_name else "当前使用的 key"
    return (f"HTTP {status}：{holder}没有{service}的权限，请自行核对该 key 的服务开通、套餐与模型权限；"
            "工作流不会自动换 key 或重试")


def text_model_problem():
    """The only configured Volcano key is an Agent Plan key, so direct text-model calls are refused."""
    return TEXT_MODELS_FORBIDDEN
