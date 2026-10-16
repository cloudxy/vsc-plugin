"""Explicit, bounded authority for AI candidate selection; never human review."""
import json
import uuid
from datetime import datetime

from vsc.assets.resource_service import ROLE_MATRIX

TYPE = "vsc.review_delegation"
FORMAT = "vsc.review-delegation/v1"


def document(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def errors(value):
    try:
        value = document(value)
    except (TypeError, ValueError, UnicodeDecodeError):
        return ["委托必须是JSON文档"]
    if not isinstance(value, dict):
        return ["委托必须是object"]
    problems = []
    if value.get("format") != FORMAT:
        problems.append("委托format无效")
    try:
        uuid.UUID(value.get("project_id", ""))
    except (ValueError, TypeError, AttributeError):
        problems.append("project_id必须是UUID")
    for field in ("grantor_actor", "delegate_actor"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            problems.append(field + "必须是明确身份")
    if value.get("grantor_actor") == value.get("delegate_actor"):
        problems.append("委托人与受托人必须不同")
    roles = value.get("allowed_roles")
    if not isinstance(roles, list) or not roles or any(not isinstance(role, str) or role not in ROLE_MATRIX for role in roles):
        problems.append("allowed_roles必须是明确的已支持用途列表")
    elif len(roles) != len(set(roles)):
        problems.append("allowed_roles不能重复")
    try:
        expires = datetime.fromisoformat(value.get("expires_at", "").replace("Z", "+00:00"))
        if expires.tzinfo is None or expires.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        problems.append("expires_at必须是带时区ISO8601时间")
    if value.get("action") != "select_candidate" or value.get("final_release_authorized") is not False:
        problems.append("委托仅允许select_candidate，不能授权最终发布")
    return problems
