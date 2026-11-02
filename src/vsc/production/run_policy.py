"""Versioned production prerequisites and durable execution bounds.

Policies live in immutable run documents. Callers supply authoritative job
history while holding the project lock; this module owns no counters or clock.
"""
from datetime import datetime, timezone
import json
import re
import uuid

from vsc.assets.resource_service import ResourceError


def production_gate(profile, phase="production"):
    if phase in {"asset", "trial"}:
        return "script"
    return "design" if profile.get("production_policy") == "light-short-v1" else "animatic"


def production_input(profile, phase="production"):
    if phase in {"asset", "trial"}:
        return "vsc.asset_bible"
    return "vsc.shot_plan" if profile.get("production_policy") == "light-short-v1" else "vsc.animatic"


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def policy_errors(policy):
    if policy is None:
        return []
    if not isinstance(policy, dict) or policy.get("version") != "bounded-v1":
        return ["execution_policy.version 必须为 bounded-v1"]
    errors = []
    for key, maximum in (("max_attempts_per_purpose", 20), ("max_repair_rounds", 1)):
        value = policy.get(key)
        if type(value) is not int or not 0 <= value <= maximum or (key == "max_attempts_per_purpose" and value == 0):
            errors.append(key + " 必须是范围内的整数")
    try:
        first, stop = (_instant(policy.get(key)) for key in ("first_draft_due_at", "stop_submitting_at"))
        if first > stop:
            errors.append("首版目标不能晚于停止新增提交时间")
    except (ValueError, TypeError):
        errors.append("首版与停止时间必须是含时区的固定 ISO 时间")
    if "repair_round" in policy and (type(policy["repair_round"]) is not int or
            type(policy.get("max_repair_rounds")) is not int or
            not 0 <= policy["repair_round"] <= policy.get("max_repair_rounds", 0)):
        errors.append("repair_round 超过固定集中修补额度")
    authorization = policy.get("authorization")
    if authorization is not None:
        if not isinstance(authorization, dict):
            errors.append("制作授权范围必须为明确对象")
        elif authorization.get("mode") == "new_batch":
            if (set(authorization) != {"mode", "reason"} or not isinstance(authorization.get("reason"), str)
                    or not 1 <= len(authorization["reason"].strip()) <= 2000):
                errors.append("新的制作批次需要明确原因，随固定运行包一起批准")
        elif authorization.get("mode") == "continue":
            try:
                uuid.UUID(authorization.get("run_version_id"))
                if (set(authorization) != {"mode", "run_version_id", "sha256"}
                        or not re.fullmatch(r"[0-9a-f]{64}", authorization.get("sha256", ""))):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                errors.append("继续制作需要原授权运行版本与固定摘要")
        else:
            errors.append("制作授权只能选择新批次或继续固定批次")
    return errors


def logical_identity(job):
    """Run names, filenames and task keys cannot reset a creative attempt."""
    return (job.get("project_id"), job.get("shot_id"), job.get("asset_id"), job.get("purpose"))


def authorization_epoch(policy, run_id):
    """Derive identity only from the immutable, already authorized run record."""
    auth = (policy or {}).get("authorization") or {}
    return run_id if auth.get("mode") == "new_batch" else auth.get("run_version_id")


def authorization_policy(run, run_id, job, resolve):
    """Validate a continued authorization against its original approved version.

    The caller resolves under its existing project/approval boundary. This adds
    no second approval or mutable counter; each job already pins run_version_id.
    """
    policy = run.get("execution_policy")
    errors = policy_errors(policy)
    if errors:
        raise ResourceError("；".join(errors), "invalid_execution_policy")
    auth = (policy or {}).get("authorization") or {}
    if auth.get("mode") != "continue":
        return None
    if auth["run_version_id"] == run_id:
        raise ResourceError("继续制作必须引用原批次", "invalid_execution_authorization")
    original = resolve(auth["run_version_id"])
    if (not original.get("approved") or original.get("sha256") != auth["sha256"] or
            original.get("artifact_type") not in {"production-run", "vsc.production_run", "workbench-generation-run"}):
        raise ResourceError("原制作授权版本或批准已失效", "execution_authorization_invalid")
    doc = original["document"]
    doc = json.loads(doc) if isinstance(doc, (str, bytes)) else doc
    parent = doc.get("execution_policy")
    if policy_errors(parent) or ((parent or {}).get("authorization") or {}).get("mode") != "new_batch":
        raise ResourceError("继续制作必须直接引用明确批准的新批次", "invalid_execution_authorization")
    from vsc.production.bounded import tasks, request_for
    if not any(all(request_for(row).get(key) == job.get(key)
                   for key in ("shot_id", "asset_id", "purpose")) for row in tasks(doc)):
        raise ResourceError("当前对象与用途不在原制作授权内", "execution_authorization_scope")
    return parent


def enforce_execution_policy(run, job, history, now=None, *, inherited_policy=None):
    """Check before a paid submit under the existing project transaction lock.

History includes every earlier job for the project, plus each job's original
``execution_policy``. Unknown submissions count. Recovery does not call this.
    """
    policy = run.get("execution_policy")
    epoch = authorization_epoch(policy, job.get("run_version_id"))
    relevant = [row for row in history if logical_identity(row) == logical_identity(job)
                and row.get("id") != job.get("id")
                and (epoch is None or authorization_epoch(row.get("execution_policy"), row.get("run_version_id")) == epoch)]
    policies = [p for p in [policy, inherited_policy] + [row.get("execution_policy") for row in relevant] if p is not None]
    if not policies:
        return {"bounded": False}
    for value in policies:
        errors = policy_errors(value)
        if errors:
            raise ResourceError("；".join(errors), "invalid_execution_policy")
    # Only an explicitly approved new batch starts a new window. Renames and
    # continuations retain the original cap, including unknown submissions.
    deadline = min(_instant(p["stop_submitting_at"]) for p in policies)
    limit = min(p["max_attempts_per_purpose"] for p in policies)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now requires timezone")
    if current >= deadline:
        raise ResourceError("已到停止新增提交时间；继续追踪在途任务并保留已有结果", "production_deadline_reached")
    attempted = sum(max(int(row.get("attempt") or 0), int(row.get("status") in {
        "submitted", "running", "submission_unknown", "succeeded"})) for row in relevant)
    if attempted >= limit:
        raise ResourceError("同一对象与用途已达到跨运行创作尝试上限", "production_attempts_exhausted")
    return {"bounded": True, "attempts_used": attempted, "attempts_limit": limit,
            "stop_submitting_at": deadline.isoformat()}
