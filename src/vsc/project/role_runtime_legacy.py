"""Role memory/dispatch operations on existing JSON and SQLite authorities.

The web adapter deliberately resolves the authoritative legacy reader first;
PostgreSQL failures never select this implementation.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from vsc.assets.resource_service import ResourceError, Conflict
from vsc.project.role_runtime import digest, validate_packet, validate_return


def content_sha(item):
    return hashlib.sha256(item["content"].encode()).hexdigest()


def source_problems(project, state, item):
    from vsc.project import state as ST
    from vsc.knowledge import learning
    source_id = item.get("source", "")
    if source_id.startswith("A-"):
        source = next((a for a in state["artifacts"] if a["id"] == source_id), None)
        if not source:
            return ["artifact source missing"]
        errors = ST.validate_artifact(project, state, source, require_approved=True)
        if item.get("source_version") != learning.artifact_snapshot(source):
            errors.append("artifact source version changed")
        if any(a.get("supersedes") == source_id for a in state["artifacts"]):
            errors.append("artifact source superseded")
        return errors
    if source_id.startswith("S-"):
        source = next((s for s in state["sources"] if s["id"] == source_id), None)
        if not source:
            return ["source missing"]
        errors = learning.source_problems(project, source, ST.sha16)
        path = Path(source["path"])
        path = path if path.is_absolute() else project / path
        if item.get("source_sha256") and learning.file_digest(path) != item["source_sha256"]:
            errors.append("source SHA changed")
        return errors
    return []


def list_memories(project, role=None, scope=None):
    from vsc.project import state as ST
    state = ST.project_state(project)
    return {"items": [dict(m, content_sha256=content_sha(m), invalid_reasons=source_problems(project, state, m))
        for m in state["memories"] if (not role or m.get("role") == role) and (not scope or m["scope"] == scope)], "revision": state["revision"]}


def mutate_memory(project, action, payload, *, actor, expected_revision, idempotency_key, human_decision=None):
    from vsc.project import state as ST
    from vsc.assets.role_memory import require_human_memory_decision
    from vsc.knowledge import learning
    if not isinstance(payload, dict) or "actor" in payload or "approved_by" in payload:
        raise ResourceError("身份必须来自已验证会话", "untrusted_actor")
    if not isinstance(expected_revision, int) or not isinstance(idempotency_key, str) or not idempotency_key:
        raise ResourceError("记忆写入需要revision及幂等键", "revision_required")
    if action == "decide":
        require_human_memory_decision(human_decision, actor)
    with ST.project_lock(project):
        state = ST.project_state(project)
        request_sha = digest({"action": action, "payload": payload, "actor": actor})
        receipts = state.setdefault("memory_receipts", {})
        if idempotency_key in receipts:
            receipt = receipts[idempotency_key]
            if receipt["request_sha256"] != request_sha:
                raise Conflict("同一幂等键不能覆盖其他记忆请求", "idempotency_conflict")
            return receipt["response"]
        if state["revision"] != expected_revision:
            raise Conflict()
        if action == "decide":
            item = next((m for m in state["memories"] if m["id"] == payload.get("version_id", payload.get("id"))), None)
            if item is None:
                raise ResourceError("该固定记忆版本不存在", "memory_not_found", 404)
            if payload.get("content_sha256") != content_sha(item):
                raise Conflict("决定与所见正文版本不符", "memory_decision_version")
            outcome = payload.get("outcome")
            if outcome not in {"draft": {"approved", "rejected"}, "approved": {"retired"}}.get(item["status"], set()):
                raise ResourceError("记忆决定不能覆盖历史", "memory_transition")
            if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
                raise ResourceError("记忆决定需要原因", "reason_required")
            if outcome == "approved" and source_problems(project, state, item):
                raise ResourceError("记忆来源已失效", "memory_source_invalid")
            decision = {"id": "MD-" + human_decision.confirmation_id, "by": actor,
                "confirmation_id": human_decision.confirmation_id, "at": ST.now(), "note": payload["reason"],
                "outcome": outcome, "content_sha256": content_sha(item), "based_on_revision": state["revision"]}
            item.setdefault("decisions", []).append(decision)
            item["decision"], item["status"] = decision, outcome
            result = {"id": item["id"], "status": outcome, "decision_id": decision["id"]}
        elif action == "propose":
            role = payload.get("role", "orchestrator")
            card = ST.role_card(role)
            kind, content = payload.get("kind"), payload.get("content")
            if kind not in card["memory_policy"]["propose_kinds"] or not isinstance(content, str) or not 1 <= len(content.strip()) <= 6000:
                raise ResourceError("提案种类或正文不符合角色策略", "memory_policy")
            sources = payload.get("sources", [])
            if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict) or sources[0].get("kind") not in {"artifact", "source"}:
                raise ResourceError("旧权威记忆提案需引用一个固定来源", "memory_source_required")
            ref = sources[0]
            item = {"id": ST.next_id(state["memories"], "M"), "scope": payload.get("scope", "role"), "role": role,
                "kind": kind, "content": content.strip(), "source": ref["id"], "confidence": payload.get("confidence", "medium"),
                "sensitivity": payload.get("sensitivity", "project"), "origin": "unverified_proposal", "status": "draft",
                "created_at": ST.now(), "decision": None, "version": 1, "tags": payload.get("tags", []),
                "association_complete": payload.get("association_complete") is True, "target_object_ids": payload.get("target_object_ids", [])}
            if ref["kind"] == "artifact":
                source = next((a for a in state["artifacts"] if a["id"] == ref["id"]), None)
                if source is None:
                    raise ResourceError("固定产物来源不存在", "memory_source_missing", 404)
                if ST.validate_artifact(project, state, source, require_approved=True):
                    raise ResourceError("来源不是已批准固定产物", "memory_source_invalid")
                item["source_version"] = learning.artifact_snapshot(source)
                item["source_artifact_keys"] = [source["id"]]
                sha = source.get("sha256") or learning.file_digest(project / source["path"])
            else:
                source = next((s for s in state["sources"] if s["id"] == ref["id"]), None)
                if source is None:
                    raise ResourceError("固定原始来源不存在", "memory_source_missing", 404)
                path = Path(source["path"])
                sha = learning.file_digest(path if path.is_absolute() else project / path)
                item["source_sha256"], item["source_sha256_16"] = sha, sha[:16]
            if sha != ref.get("sha256"):
                raise ResourceError("来源摘要不符", "memory_source_sha")
            state["memories"].append(item)
            result = {"id": item["id"], "status": "draft", "version_id": item["id"]}
        else:
            raise ResourceError("未知记忆写入操作", "invalid_memory_action")
        result["revision"] = state["revision"] + 1
        receipts[idempotency_key] = {"request_sha256": request_sha, "response": result}
        ST.append_event(state, "memory_" + action, memory_id=result["id"], actor=actor)
        ST.save(project, state)
        return result


def dispatch_command(args):
    from vsc.project import state as ST
    from vsc.knowledge import learning
    project = Path(args.project)
    state = ST.project_state(project)
    packet = ST.read_json(Path(args.file))
    errors = validate_packet(packet, expected_role=args.role, current_card=ST.role_card(args.role))
    if packet.get("format") != "vsc.role-context/v2" or errors:
        ST.die("任务包不可消费：" + "; ".join(errors))
    context = next((c for c in state["contexts"] if c["id"] == packet["context_id"]), None)
    d = packet["dispatch"]
    if (not context or packet.get("project", {}).get("project_id") != state["project_id"]
            or context.get("context_sha256") != packet["context_sha256"]
            or context.get("sha256") != learning.file_digest(Path(args.file))
            or args.actor != d["actor"] or args.instance_id != d["instance_id"]):
        ST.die("派单主体、固定任务包或项目不一致")
    if args.action == "return":
        result = ST.read_json(Path(args.result))
        errors = validate_return(packet, result)
        if errors:
            ST.die("; ".join(errors))
        previous = next((r for r in context.get("returns", []) if r["return_key"] == args.return_key), None)
        if previous:
            if previous["result_sha256"] != digest({"result": result, "closed": not args.keep_open}):
                ST.die("同一返回键不能覆盖不同结果")
            print("OK reused dispatch return")
            return
    if context.get("closed") or datetime.fromisoformat(d["expires_at"]) <= datetime.now(timezone.utc):
        ST.die("派单已关闭或到期；请从权威输入重建")
    for a in packet["inputs"]:
        current = ST.artifact_by_id(state, a["id"])
        if ST.validate_artifact(project, state, current, require_approved=True) or learning.artifact_snapshot(current) != {k: a[k] for k in learning.artifact_snapshot(current)}:
            ST.die("固定任务输入已失效")
    for m in packet["approved_memories"]:
        current = ST.memory_by_id(state, m["id"])
        if (current["status"] != "approved" or source_problems(project, state, current)
                or current.get("decision") != m.get("decision") or current["content"] != m["content"]):
            ST.die("固定记忆来源或决定已失效")
    if args.action == "consume":
        if any(c["instance_id"] == args.instance_id and c["context_sha256"] == packet["context_sha256"] for c in context.get("consumptions", [])):
            print("OK reused dispatch consumption")
            return
        context.setdefault("consumptions", []).append({"instance_id": args.instance_id, "actor": args.actor,
            "context_sha256": packet["context_sha256"], "at": ST.now()})
    else:
        if not context.get("consumptions"):
            ST.die("必须先确认消费固定上下文")
        for ref in result["result_refs"]:
            artifact = ST.artifact_by_id(state, ref["id"])
            if ref["sha256"] != artifact.get("sha256"):
                ST.die("返回产物固定摘要不符")
        for index, proposal in enumerate(result["memory_proposals"]):
            if proposal.get("role", args.role) != args.role or proposal.get("scope", "role") != "role":
                ST.die("代理只能提案自己的角色记忆")
            sources = proposal.get("sources", [])
            if len(sources) != 1 or sources[0]["id"] not in {a["id"] for a in packet["inputs"]}:
                ST.die("记忆来源必须属于固定任务输入")
            source = ST.artifact_by_id(state, sources[0]["id"])
            source_sha = source.get("sha256") or learning.file_digest(project / source["path"])
            if sources[0].get("sha256") != source_sha:
                ST.die("记忆来源摘要不符")
            content, kind = proposal.get("content"), proposal.get("kind")
            if kind not in packet["role"]["memory_policy"]["propose_kinds"] or not isinstance(content, str) or not 1 <= len(content.strip()) <= 6000:
                ST.die("记忆提案不符合角色策略")
            if packet.get("parent_brief") and content.strip() == packet["parent_brief"]["content"].strip():
                ST.die("父摘要不得自动永久化")
            state["memories"].append({"id": ST.next_id(state["memories"], "M"), "scope": "role", "role": args.role,
                "kind": kind, "content": content.strip(), "source": source["id"], "source_version": learning.artifact_snapshot(source),
                "confidence": proposal.get("confidence", "medium"), "sensitivity": proposal.get("sensitivity", "project"),
                "origin": "agent_proposed", "status": "draft", "version": 1, "decision": None, "created_at": ST.now(),
                "producer_dispatch_id": d["id"], "proposal_key": args.return_key + ":" + str(index),
                "association_complete": proposal.get("association_complete") is True,
                "source_artifact_keys": [source["id"]], "target_object_ids": proposal.get("target_object_ids", []), "tags": proposal.get("tags", [])})
        summary = result.get("session_summary")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 2200):
            ST.die("临时摘要超过2200字符预算")
        context.setdefault("returns", []).append({"return_key": args.return_key, "result_sha256": digest({"result": result, "closed": not args.keep_open}),
            "result": result, "summary": summary, "created_at": ST.now(), "expires_at": d["expires_at"], "dispatch_id": d["id"]})
        context["closed"] = not args.keep_open
    ST.save(project, state)
    print("OK dispatch " + args.action + " " + packet["context_id"])


def resume_summary(project, state, dispatch_id, role):
    from vsc.project import state as ST
    context = next((c for c in state["contexts"] if c.get("dispatch", {}).get("id") == dispatch_id), None)
    if not context or context.get("closed") or context.get("role") != role or not context.get("returns"):
        raise ResourceError("接续任务不存在、已关闭或角色不同", "resume_unavailable")
    result = context["returns"][-1]
    if not result.get("summary") or datetime.fromisoformat(result["expires_at"]) <= datetime.now(timezone.utc):
        raise ResourceError("接续摘要缺失或到期", "summary_expired")
    from vsc.knowledge import learning
    path = Path(context["path"])
    path = path if path.is_absolute() else project / path
    packet = ST.read_json(path)
    if (learning.file_digest(path) != context.get("sha256")
            or validate_packet(packet, expected_role=role, current_card=ST.role_card(role))):
        raise ResourceError("原任务包或角色策略失效", "resume_context_invalid")
    for m in packet["approved_memories"]:
        current = next((r for r in state["memories"] if r["id"] == m["id"]), None)
        if (not current or current["status"] != "approved" or source_problems(project, state, current)
                or current.get("decision") != m.get("decision") or current["content"] != m["content"]):
            raise ResourceError("原任务记忆来源或决定失效", "resume_memory_invalid")
    for a in context.get("input_versions", []):
        if ST.validate_artifact(project, state, ST.artifact_by_id(state, a["id"]), require_approved=True):
            raise ResourceError("接续依据失效，请从权威输入重建", "resume_source_invalid")
    return {"content": result["summary"], "created_at": result["created_at"], "expires_at": result["expires_at"],
            "dispatch_id": dispatch_id, "persistence": "temporary_resume_only"}
