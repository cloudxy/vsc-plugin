"""Shared role policy, immutable packet and return validation for all hosts.

Role cards are the only editable identity source. Dispatch instances bind an
executor label; that label is never an authentication or human approval grant.
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import uuid

MODES = {"work", "design", "fresh", "followup"}
KINDS = {"fact", "lesson", "check_method", "judgment", "recommendation", "preference", "decision", "session_brief"}


def delivery_errors(delivery):
    """An optional task requirement, never a result check or approval."""
    fields = {"format", "purpose", "artifact_type", "consumer", "validation", "preserve"}
    if not isinstance(delivery, dict) or delivery.get("format") != "vsc.role-delivery/v1":
        return ["delivery requires vsc.role-delivery/v1"]
    errors = []
    if set(delivery) - fields:
        errors.append("unknown delivery fields")
    for key in ("purpose", "artifact_type", "consumer", "validation"):
        if not isinstance(delivery.get(key), str) or not delivery[key].strip() or len(delivery[key]) > 2000:
            errors.append("delivery requires bounded nonempty " + key)
    if (not isinstance(delivery.get("preserve"), list) or len(delivery["preserve"]) > 50
            or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in delivery["preserve"])):
        errors.append("delivery preserve must be a text array")
    if not errors and len(json.dumps(delivery, ensure_ascii=False)) > 12000:
        errors.append("delivery exceeds 12000 character budget")
    return errors


def attach_delivery(packet, delivery=None, resumed=None):
    """Keep requirements when resuming; a changed requirement needs a new task."""
    previous = (resumed or {}).get("delivery")
    if previous is not None and delivery is not None and delivery != previous:
        raise ValueError("接续任务不能改写固定成果要求；用途变化请建立新任务")
    value = delivery if delivery is not None else previous
    if value is not None:
        errors = delivery_errors(value)
        if errors:
            raise ValueError("; ".join(errors))
        packet["delivery"] = value


def result_artifact_errors(packet, artifacts):
    """Check normalized, registered facts supplied by the owning authority."""
    delivery = packet.get("delivery")
    if delivery is None:
        return []
    inputs = {row["id"] for row in packet["inputs"]}
    errors = []
    for artifact in artifacts:
        if artifact["artifact_type"] != delivery["artifact_type"]:
            errors.append("返回产物类型与固定成果要求不符")
        if artifact["id"] in inputs:
            errors.append("不能把原输入作为本轮新成果返回")
        if not inputs <= set(artifact["input_ids"]):
            errors.append("返回产物没有关联全部固定任务输入版本")
        if not artifact["scope_matches"]:
            errors.append("返回产物范围与固定任务不符")
    return errors


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def policy_errors(card):
    p, e = card.get("memory_policy", {}), card.get("execution_policy", {})
    errors = []
    if not card.get("version"):
        errors.append("role version required")
    if not p.get("read") or set(p["read"]) - {"own_role", "approved_project"}:
        errors.append("invalid memory read policy")
    if not p.get("propose_kinds") or set(p["propose_kinds"]) - KINDS:
        errors.append("invalid memory proposal kinds")
    if p.get("write_targets") != ["own_role_draft", "dispatch_summary"]:
        errors.append("role may only propose own drafts and summaries")
    if not p.get("review_modes") or set(p["review_modes"]) - MODES:
        errors.append("invalid review modes")
    for key in ("default_budget_chars", "summary_ttl_hours"):
        if not isinstance(p.get(key), int) or isinstance(p.get(key), bool) or p[key] <= 0:
            errors.append("invalid " + key)
    if e.get("artifact_access") not in {"read_only", "declared_ownership"} or e.get("human_approval") is not False:
        errors.append("invalid execution authority")
    if not {"role_id", "dispatch_id", "context_sha256", "memory_proposals"} <= set(e.get("return_fields", [])):
        errors.append("incomplete return contract")
    return errors


def bind_packet(packet, *, host="unspecified", instance_id=None, actor="vsc-cli", review_mode=None, ownership=None):
    card = packet["role"]
    errors = policy_errors(card)
    if "delivery" in packet:
        errors.extend(delivery_errors(packet["delivery"]))
    if errors:
        raise ValueError("; ".join(errors))
    mode = review_mode or card["memory_policy"]["review_modes"][0]
    if mode not in card["memory_policy"]["review_modes"]:
        raise ValueError("review mode is not permitted for role")
    if mode == "fresh" and packet.get("parent_brief"):
        raise ValueError("fresh review cannot consume parent_brief")
    if (card["execution_policy"]["artifact_access"] == "read_only" or mode in {"fresh", "followup"}) and ownership:
        raise ValueError("read-only reviewer cannot own artifact edits")
    if not isinstance(ownership or [], list) or any(not isinstance(v, str) or not v.strip() for v in ownership or []):
        raise ValueError("edit ownership must be explicit paths")
    if any(Path(v).is_absolute() or ".." in Path(v).parts for v in ownership or []):
        raise ValueError("edit ownership paths must be project-relative without traversal")
    role_sha = digest(card)
    created = datetime.now(timezone.utc)
    packet["format"] = "vsc.role-context/v2"
    packet["dispatch"] = {"id": str(uuid.uuid4()), "role_id": card["id"], "role_version": card["version"],
        "role_sha256": role_sha, "host": host, "instance_id": instance_id or str(uuid.uuid4()),
        "actor": actor, "review_mode": mode, "edit_ownership": ownership or [],
        "artifact_access": "read_only" if mode in {"fresh", "followup"} else card["execution_policy"]["artifact_access"],
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(hours=card["memory_policy"]["summary_ttl_hours"])).isoformat()}
    packet["context_sha256"] = digest({k: v for k, v in packet.items() if k != "context_sha256"})
    return packet


def validate_packet(packet, expected_role=None, current_card=None):
    errors = []
    if not isinstance(packet, dict) or packet.get("format") not in {"vsc.role-context/v1", "vsc.role-context/v2"}:
        return ["invalid role context format"]
    for key in ("context_id", "project", "role", "task", "inputs", "approved_memories", "rules"):
        if key not in packet:
            errors.append("missing " + key)
    role = packet.get("role", {})
    if expected_role and role.get("id") != expected_role:
        errors.append("wrong role")
    if packet.get("format") == "vsc.role-context/v1":
        return errors  # Historical packets remain readable; never executable.
    errors.extend(policy_errors(role))
    if "delivery" in packet:
        errors.extend(delivery_errors(packet["delivery"]))
    if current_card is None:
        from vsc.kernel.catalog import role_cards
        current_card = role_cards().get(role.get("id"))
        if current_card is None:
            errors.append("unknown role")
    dispatch = packet.get("dispatch", {})
    if dispatch.get("role_id") != role.get("id") or dispatch.get("role_sha256") != digest(role):
        errors.append("role binding mismatch")
    if current_card is not None and digest(current_card) != dispatch.get("role_sha256"):
        errors.append("role policy changed; rebuild context")
    for key in ("id", "host", "instance_id", "actor", "role_version", "review_mode", "created_at", "expires_at"):
        if not isinstance(dispatch.get(key), str) or not dispatch[key]:
            errors.append("missing dispatch " + key)
    try:
        created, expiry = (datetime.fromisoformat(dispatch.get(key, "")) for key in ("created_at", "expires_at"))
        if (created.tzinfo is None or expiry.tzinfo is None or expiry <= created
                or expiry - created > timedelta(hours=role["memory_policy"]["summary_ttl_hours"])):
            errors.append("dispatch expiry violates role TTL policy")
    except (TypeError, ValueError, KeyError):
        errors.append("dispatch timestamps must be valid timezone datetimes")
    if packet.get("context_sha256") != digest({k: v for k, v in packet.items() if k != "context_sha256"}):
        errors.append("context hash mismatch")
    if dispatch.get("review_mode") == "fresh" and packet.get("parent_brief"):
        errors.append("fresh review parent brief forbidden")
    if dispatch.get("review_mode") not in role.get("memory_policy", {}).get("review_modes", []):
        errors.append("review mode violates role policy")
    if dispatch.get("review_mode") in {"fresh", "followup"} and (dispatch.get("artifact_access") != "read_only" or dispatch.get("edit_ownership")):
        errors.append("independent review must be read only")
    if not isinstance(packet.get("inputs"), list) or not isinstance(packet.get("approved_memories"), list):
        errors.append("inputs and memories must be arrays")
    if packet.get("approved_memories"):
        retrieval = packet.get("retrieval", {})
        size = sum(len(json.dumps(m, ensure_ascii=False, sort_keys=True)) for m in packet["approved_memories"])
        if (not isinstance(retrieval.get("budget_chars"), int) or size > retrieval["budget_chars"]
                or retrieval.get("used_chars") != size):
            errors.append("retrieval snapshot exceeds or disagrees with budget")
    return errors


def validate_return(packet, result, *, closed=True):
    if not isinstance(result, dict):
        return ["return must be an object"]
    expected = {"role_id": packet["role"]["id"], "role_sha256": packet["dispatch"]["role_sha256"],
        "context_id": packet["context_id"], "context_sha256": packet["context_sha256"],
        "dispatch_id": packet["dispatch"]["id"], "instance_id": packet["dispatch"]["instance_id"]}
    errors = ["return binding mismatch: " + k for k, v in expected.items() if result.get(k) != v]
    if not isinstance(result.get("result_refs"), list) or not isinstance(result.get("memory_proposals"), list):
        errors.append("return requires result_refs and memory_proposals arrays")
    elif any(not isinstance(r, dict) or r.get("kind") != "artifact"
            or not isinstance(r.get("id"), str) or not r["id"].strip()
            or not isinstance(r.get("sha256"), str) or len(r["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in r["sha256"]) for r in result["result_refs"]):
        errors.append("result references require typed artifact id and SHA")
    elif len({r["id"] for r in result["result_refs"]}) != len(result["result_refs"]):
        errors.append("result references must not repeat")
    elif packet.get("delivery") and not result["result_refs"]:
        if closed:
            errors.append("成果任务尚无固定产物；请保留任务并说明具体缺项")
        elif not isinstance(result.get("session_summary"), str) or not result["session_summary"].strip():
            errors.append("尚无成果时必须在接续摘要说明受阻原因和待完成项")
    return errors


def memory_allowed(item, role_id, *, mode="work", target_ids=(), target_keys=(), include_restricted=False):
    """Structural filtering shared by JSON and PostgreSQL consumers."""
    if item.get("status") != "approved":
        return False
    if item.get("kind") == "session_brief":
        return False
    from vsc.kernel.catalog import role_cards
    reads = role_cards().get(role_id, {}).get("memory_policy", {}).get("read", [])
    if (item.get("scope") == "project" and "approved_project" not in reads) or (item.get("scope") == "role" and "own_role" not in reads):
        return False
    if item.get("scope") != "project" and item.get("role", item.get("owner_role")) != role_id:
        return False
    if item.get("sensitivity") == "restricted" and not include_restricted:
        return False
    if mode == "fresh":
        return (item.get("role", item.get("owner_role")) == role_id
            and item.get("kind") in {"lesson", "check_method"}
            and item.get("association_complete") is True
            and not (set(item.get("target_object_ids", [])) & set(target_ids))
            and not (set(item.get("source_artifact_keys", [])) & set(target_keys))
            and not (set(item.get("source_object_ids", [])) & set(target_ids)))
    return True
