"""Pure canvas-agent stream protocol: errors, questions, tickets and SSE frames.

No database and no host process. The same Chinese strings are the user-facing
contract shared with the browser module.
"""
import json
from datetime import datetime, timezone

REFERENCE_ONLY_PROMPT = "请理解所引用的素材。"
ACTIVE_TURN_STATUSES = ("queued", "running", "result_ready", "needs_input", "planned", "submission_unknown")
TOOL_CATEGORIES = ("read_canvas", "search_assets", "skill", "tool", "write_canvas")
CHAT_MODELS = ("grok", "grok-fast")
REASONING_EFFORTS = ("low", "medium", "high")

FAILURE_TEXT = {
    "rate_limited": "请求较多，请稍后重试",
    "quota_exhausted": "模型服务额度暂不可用，请稍后再试",
    "provider_unavailable": "模型服务暂不可用，请稍后重试",
    "content_rejected": "内容被模型拒绝，请调整后重试",
    "provider_timeout": "模型响应超时，请稍后重试",
    "provider_connection_error": "模型服务连接中断，请稍后重试",
    "turn_timeout": "本轮处理超时，已停止；发送新消息可以继续",
    "turn_failed": "回合执行失败",
}
FAILURE_ALIASES = {
    "canvas_agent_host_unavailable": "provider_unavailable",
    "canvas_agent_host_failed": "turn_failed",
    "canvas_agent_skill_changed": "turn_failed",
    "invalid_canvas_plan": "turn_failed",
    "canvas_agent_submission_unknown": "provider_timeout",
}
PAID_FIELDS = (
    ("operation", "操作与模型"),
    ("model", "操作与模型"),
    ("unit_price", "计费明细"),
    ("quantity", "计费明细"),
    ("total_credits", "金额"),
    ("canvas_version", "画布版本"),
    ("expires_at", "过期时间"),
)
DELETE_FIELDS = (
    ("canvas_version", "画布版本"),
    ("node_count", "节点数量"),
    ("node_list", "节点清单"),
    ("cascade_edge_count", "级联连线"),
    ("expires_at", "过期时间"),
)


def classify_agent_failure(value):
    """Map a host code or exception name to a readable Chinese reason."""
    raw = value
    if isinstance(value, dict):
        raw = value.get("reason") or value.get("code") or value.get("error") or ""
    code = str(raw or "").strip()
    mapped = FAILURE_ALIASES.get(code, code)
    if mapped not in FAILURE_TEXT:
        mapped = "turn_failed"
    return {"code": mapped, "message": FAILURE_TEXT[mapped]}


def reference_only_prompt(message, node_ids=None, attachment_ids=None):
    text = message.strip() if isinstance(message, str) else ""
    if text:
        return text
    if node_ids or attachment_ids:
        return REFERENCE_ONLY_PROMPT
    return ""


def validate_question_answers(batch, answers, skip=False):
    items = list((batch or {}).get("items") or [])
    if skip:
        return {"ok": True, "skipped": True, "answers": []}
    if not isinstance(answers, list):
        return {"ok": False, "code": "required_missing", "message": "请回答所有必答问题"}
    by_id = {row.get("question_id"): row for row in answers if isinstance(row, dict)}
    normalized = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            return {"ok": False, "code": "required_missing", "message": "请回答所有必答问题"}
        answer = by_id.get(item["id"]) or {}
        custom = answer.get("custom_text") if isinstance(answer.get("custom_text"), str) else ""
        selected = answer.get("selected_option_ids") if isinstance(answer.get("selected_option_ids"), list) else []
        limit = item.get("max_length")
        if isinstance(limit, int) and not isinstance(limit, bool) and len(custom) > limit:
            return {"ok": False, "code": "answer_too_long", "message": "自定义回答最多 %s 字" % limit}
        kind = item.get("kind") or "text"
        if kind == "single" and len(selected) > 1:
            return {"ok": False, "code": "required_missing", "message": "请回答所有必答问题"}
        if kind in {"single", "multi"} and selected:
            options = {opt.get("id") for opt in item.get("options") or [] if isinstance(opt, dict)}
            if any(option not in options for option in selected):
                return {"ok": False, "code": "required_missing", "message": "请回答所有必答问题"}
        filled = bool(custom.strip()) or bool(selected)
        if item.get("required") and not filled:
            return {"ok": False, "code": "required_missing", "message": "请回答所有必答问题"}
        normalized.append({"question_id": item["id"], "selected_option_ids": selected, "custom_text": custom})
    return {"ok": True, "skipped": False, "answers": normalized}


def _parse_expiry(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ticket_blockers(ticket, now=None):
    """Return why a ticket cannot be approved. Reject stays available."""
    ticket = ticket or {}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    kind = ticket.get("ticket_type") or ticket.get("kind") or "paid"
    fields = DELETE_FIELDS if kind == "delete" else PAID_FIELDS
    missing = []
    for key, label in fields:
        value = ticket.get(key)
        empty = value is None or value == "" or value == []
        if empty and label not in missing:
            missing.append(label)
    if kind == "delete" and ticket.get("node_count") is not None and isinstance(ticket.get("node_list"), list):
        if len(ticket["node_list"]) != ticket["node_count"]:
            return {"ok": False, "approve_disabled": True, "code": "missing_node_list_count_mismatch", "message": "节点清单与数量不一致"}
    if missing:
        return {
            "ok": False,
            "approve_disabled": True,
            "code": "missing_fields",
            "message": "授权票据缺少关键字段（%s），无法确认本次操作的影响范围，已禁用批准。请拒绝并让助手重新发起。" % "、".join(missing),
        }
    expires = _parse_expiry(ticket.get("expires_at"))
    if expires is None or expires <= now:
        return {"ok": False, "approve_disabled": True, "code": "ticket_expired", "message": "票据已过期，批准会被服务端拒绝，请让助手重新发起。"}
    return {"ok": True, "approve_disabled": False, "code": None, "message": ""}


def format_sse_frame(event):
    payload = dict(event.get("payload") or {})
    payload.setdefault("seq", event.get("seq"))
    payload.setdefault("kind", event.get("kind"))
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return "id: %s\nevent: %s\ndata: %s\n\n" % (event.get("seq"), event.get("kind") or "message", data)


def format_sse_heartbeat():
    return "event: heartbeat\ndata: {}\n\n"


def parse_event_cursor(last_event_id, after):
    """Invalid Last-Event-ID resumes from 0. Otherwise the later of the two cursors wins."""
    def one(value):
        if value is None or str(value).strip() == "":
            return None
        text = str(value).strip()
        if not text.isdigit():
            return 0
        return int(text)
    if last_event_id is not None and str(last_event_id).strip() and not str(last_event_id).strip().isdigit():
        return 0
    header, query = one(last_event_id), one(after)
    if header is None and query is None:
        return 0
    if header is None:
        return query
    if query is None:
        return header
    return max(header, query)
