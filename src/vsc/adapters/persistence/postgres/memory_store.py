"""Transactional role dispatch, memory proposals and immutable retrieval evidence.

All methods use the existing project lock/revision/receipt transaction. There
is deliberately no JSON fallback and no actor-label based approval shortcut.
"""
from datetime import datetime, timezone, timedelta
import hashlib

from sqlalchemy import insert, select, func

from vsc.assets.resource_service import ResourceError, Conflict, required
from vsc.project.role_runtime import digest, validate_packet, validate_return, memory_allowed
from . import schema as S
from .values import checked_id, clean, new_id


class RoleMemoryRepository:
    @staticmethod
    def _role(role_id):
        from vsc.kernel.catalog import role_cards
        cards = role_cards()
        if role_id not in cards:
            raise ResourceError("未知专业角色", "invalid_role")
        return {"id": role_id, **cards[role_id]}

    def _memory_rows(self, conn, p):
        rows = []
        approvals = self._approval_map(conn, p)
        entries = conn.execute(select(S.role_memories).where(S.role_memories.c.project_id == p)).mappings()
        for entry in entries:
            version = conn.execute(select(S.role_memory_versions).where(
                S.role_memory_versions.c.project_id == p, S.role_memory_versions.c.memory_id == entry["id"])
                .order_by(S.role_memory_versions.c.version.desc()).limit(1)).mappings().first()
            if not version:
                continue
            decisions = conn.execute(select(S.role_memory_decisions).where(
                S.role_memory_decisions.c.project_id == p, S.role_memory_decisions.c.memory_version_id == version["id"])
                .order_by(S.role_memory_decisions.c.decision_sequence.desc())).mappings().all()
            item = dict(entry, **{k: v for k, v in version.items() if k not in {"id", "project_id", "created_at"}})
            item.update(version_id=version["id"], role=entry["owner_role"],
                origin="agent_proposed" if version["producer_dispatch_id"] else "unverified_proposal",
                status=decisions[0]["outcome"] if decisions else "draft", decision_id=decisions[0]["id"] if decisions else None,
                source_artifact_keys=[], source_object_ids=[], target_object_ids=[], source_refs=[], invalid_reasons=[])
            for ref in conn.execute(select(S.role_memory_artifacts).where(
                    S.role_memory_artifacts.c.project_id == p, S.role_memory_artifacts.c.memory_version_id == version["id"])).mappings():
                root = self._one(conn, S.artifact_versions, p, ref["artifact_id"])
                for art in self._artifact_evidence_closure(conn, p, [root["id"]]):
                    newest = conn.execute(select(func.max(S.artifact_versions.c.version)).where(
                        S.artifact_versions.c.project_id == p, S.artifact_versions.c.artifact_key == art["artifact_key"])).scalar_one()
                    if not approvals.get(art["id"]) or art["version"] != newest:
                        item["invalid_reasons"].append("artifact_source_changed_or_unapproved")
                    item["source_artifact_keys"].append(art["artifact_key"])
                    item["source_object_ids"].extend(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                        S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == art["id"])).scalars())
                if root["sha256"] != ref["source_sha256"]:
                    item["invalid_reasons"].append("artifact_source_sha_changed")
                item["source_refs"].append({"kind": "artifact", "id": root["id"], "sha256": ref["source_sha256"]})
            for ref in conn.execute(select(S.role_memory_sources).where(
                    S.role_memory_sources.c.project_id == p, S.role_memory_sources.c.memory_version_id == version["id"])).mappings():
                source = self._one(conn, S.source_versions, p, ref["source_id"])
                newest = conn.execute(select(func.max(S.source_versions.c.version)).where(
                    S.source_versions.c.project_id == p, S.source_versions.c.source_key == source["source_key"])).scalar_one()
                if source["version"] != newest or source["sha256"] != ref["source_sha256"]:
                    item["invalid_reasons"].append("source_version_changed")
                item["source_refs"].append({"kind": "source", "id": source["id"], "sha256": ref["source_sha256"]})
            item["target_object_ids"] = list(conn.execute(select(S.role_memory_targets.c.object_id).where(
                S.role_memory_targets.c.project_id == p, S.role_memory_targets.c.memory_version_id == version["id"])).scalars())
            rows.append(item)
        return rows

    def _artifact_evidence_closure(self, conn, p, roots):
        pending, visited, rows = list(roots), set(), []
        while pending:
            identifier = pending.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            rows.append(self._one(conn, S.artifact_versions, p, identifier))
            pending.extend(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == identifier)).scalars())
        return rows

    def _validate_dispatch_evidence(self, conn, p, packet):
        approvals = self._approval_map(conn, p)
        if any(not approvals.get(a["id"]) for a in packet["inputs"]):
            raise ResourceError("固定任务输入已撤销批准", "context_input_invalid")
        for source in packet.get("source_refs", []):
            row = self._one(conn, S.source_versions, p, source["id"])
            newest = conn.execute(select(func.max(S.source_versions.c.version)).where(
                S.source_versions.c.project_id == p, S.source_versions.c.source_key == row["source_key"])).scalar_one()
            if row["sha256"] != source["sha256"] or row["version"] != newest:
                raise ResourceError("任务固定来源已有新版本或已失效", "context_source_invalid")
        for media in packet.get("resources", []):
            decision = self._one(conn, S.binding_decisions, p, media["binding_decision_id"])
            self._validate_fixed_decision(conn, p, decision, media["media_id"])
        active = {r["version_id"]: r for r in self._memory_rows(conn, p) if r["status"] == "approved" and not r["invalid_reasons"]}
        if any(m["version_id"] not in active or m["decision_id"] != active[m["version_id"]]["decision_id"] for m in packet["approved_memories"]):
            raise ResourceError("固定记忆批准或来源失效", "context_memory_invalid")

    def list_role_memories(self, project_id, role=None, scope=None):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            p = project["id"]
            return clean({"items": [r for r in self._memory_rows(conn, p)
                if (not role or r["owner_role"] == role) and (not scope or r["scope"] == scope)], "revision": project["revision"]})

    def retrieve_role_memories(self, project_id, role, task, budget_chars=2200, forced=(), scope_object_id=None,
                               mode="work", target_artifact_ids=(), include_restricted=False):
        from vsc.knowledge.learning import retrieve
        card = self._role(role)
        if mode not in card["memory_policy"]["review_modes"]:
            raise ResourceError("任务模式不属于角色策略", "invalid_review_mode")
        if not isinstance(budget_chars, int) or budget_chars < 1 or budget_chars > 20000:
            raise ResourceError("记忆读取预算须为1到20000字符", "context_budget")
        with self.engine.connect() as conn:
            p = self._project(conn, project_id)["id"]
            keys = [self._one(conn, S.artifact_versions, p, a)["artifact_key"] for a in target_artifact_ids]
            target_ids = set([scope_object_id] if scope_object_id else [])
            for a in target_artifact_ids:
                target_ids.update(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                    S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == a)).scalars())
            candidates, excluded = [], []
            for r in self._memory_rows(conn, p):
                permitted = memory_allowed(r, role, mode=mode, target_ids=target_ids, target_keys=keys,
                    include_restricted=include_restricted)
                if mode == "followup" and r["kind"] in {"judgment", "recommendation", "decision"} and r["id"] not in forced:
                    permitted = False
                in_scope = not r["scope_object_id"] or r["scope_object_id"] == scope_object_id
                if not permitted or not in_scope or r["invalid_reasons"]:
                    excluded.append({"id": r["id"], "reasons": r["invalid_reasons"] or ["role_scope_or_review_policy"]})
                    continue
                candidates.append({"category": "memory", "value": clean(r), "search": r["content"] + " " + " ".join(r["tags"])})
            try:
                selected, retrieval = retrieve(task, candidates, budget_chars, list(forced))
            except ValueError as exc:
                raise ResourceError(str(exc), "memory_retrieval_policy") from exc
            retrieval["excluded"] = excluded
            return {"items": [r["value"] for r in selected], "retrieval": retrieval}

    def _propose_memory(self, conn, project, payload, dispatch=None):
        p = project["id"]
        role = dispatch["role_id"] if dispatch else required(payload, "role")
        card = self._role(role)
        if payload.get("role", role) != role or payload.get("origin") or payload.get("status") or payload.get("decision"):
            raise ResourceError("提案不能冒用角色或声明批准来源", "memory_ownership")
        kind, content = required(payload, "kind"), required(payload, "content")
        if kind not in card["memory_policy"]["propose_kinds"] or not isinstance(content, str) or not 1 <= len(content.strip()) <= 6000:
            raise ResourceError("记忆种类或正文不符合角色策略", "memory_policy")
        sources = payload.get("sources", [])
        if not isinstance(sources, list) or not sources or any(not isinstance(r, dict) or r.get("kind") not in {"artifact", "source"} for r in sources):
            raise ResourceError("提案必须引用有类型的固定依据", "memory_source_required")
        tags = payload.get("tags", [])
        if (not isinstance(tags, list) or len(tags) > 50 or any(not isinstance(t, str) or len(t) > 100 for t in tags)
                or payload.get("confidence", "medium") not in {"high", "medium", "low"}):
            raise ResourceError("记忆标签或置信度不合法", "memory_policy")
        scope = payload.get("scope", "role")
        if scope not in {"role", "project"} or (dispatch and scope != "role"):
            raise ResourceError("代理只能提出角色私有记忆", "memory_ownership")
        if dispatch:
            fixed = {(r["id"], r["sha256"]) for r in dispatch["packet"].get("inputs", []) + dispatch["packet"].get("source_refs", [])}
            if any((r.get("id"), r.get("sha256")) not in fixed for r in sources):
                raise ResourceError("记忆依据必须在该任务固定输入中", "memory_source_outside_dispatch")
            brief = dispatch["packet"].get("parent_brief")
            if brief and content.strip() == brief.get("content", "").strip():
                raise ResourceError("父摘要不能自动永久化为记忆", "memory_parent_brief")
        scope_object = payload.get("scope_object_id", dispatch["scope_object_id"] if dispatch else None)
        if dispatch and scope_object != dispatch["scope_object_id"]:
            raise ResourceError("角色提案不能扩大任务范围", "memory_ownership")
        if scope_object:
            self._one(conn, S.creative_objects, p, scope_object)
        if dispatch and not payload.get("memory_id"):
            previous = conn.execute(select(S.role_memories).where(S.role_memories.c.project_id == p,
                S.role_memories.c.producer_dispatch_id == dispatch["id"],
                S.role_memories.c.proposal_key == required(payload, "proposal_key"))).mappings().first()
            if previous:
                if previous["request_sha256"] != digest(payload):
                    raise Conflict("同一提案键不能覆盖其他证据或正文", "idempotency_conflict")
                version = conn.execute(select(S.role_memory_versions).where(S.role_memory_versions.c.project_id == p,
                    S.role_memory_versions.c.memory_id == previous["id"]).order_by(S.role_memory_versions.c.version.desc()).limit(1)).mappings().one()
                return {"id": previous["id"], "version_id": version["id"], "version": version["version"], "status": "draft", "reused": True}
        memory_id, version_id = new_id(), new_id()
        prior_id = payload.get("memory_id")
        if prior_id:
            entry = self._one(conn, S.role_memories, p, prior_id)
            if entry["owner_role"] != role or entry["scope_object_id"] != scope_object or entry["kind"] != kind or entry["scope"] != scope:
                raise ResourceError("修订不能改变记忆归属、范围或种类", "memory_ownership")
            version = conn.execute(select(func.max(S.role_memory_versions.c.version)).where(
                S.role_memory_versions.c.project_id == p, S.role_memory_versions.c.memory_id == prior_id)).scalar_one()
            if payload.get("expected_memory_revision") != version:
                raise Conflict("记忆修订已改变，请基于原证据重新提案", "memory_revision_conflict")
            memory_id, number = prior_id, version + 1
        else:
            number = 1
            conn.execute(insert(S.role_memories).values(project_id=p, id=memory_id, owner_role=role, scope=scope,
                scope_object_id=scope_object, kind=kind, producer_dispatch_id=dispatch["id"] if dispatch else None,
                proposal_key=required(payload, "proposal_key"), request_sha256=digest(payload), origin="agent_proposed" if dispatch else "unverified_proposal"))
        conn.execute(insert(S.role_memory_versions).values(project_id=p, id=version_id, memory_id=memory_id,
            producer_dispatch_id=dispatch["id"] if dispatch else None,
            version=number, content=content.strip(), content_sha256=hashlib.sha256(content.strip().encode()).hexdigest(),
            confidence=payload.get("confidence", "medium"), sensitivity=payload.get("sensitivity", "project"),
            association_complete=payload.get("association_complete") is True, tags=payload.get("tags", [])))
        for ref in sources:
            table = S.artifact_versions if ref["kind"] == "artifact" else S.source_versions
            source = self._one(conn, table, p, ref["id"])
            if source["sha256"] != ref.get("sha256"):
                raise ResourceError("来源摘要不符", "memory_source_sha")
            if table is S.artifact_versions and not self._approval_map(conn, p).get(source["id"]):
                raise ResourceError("记忆依据产物未批准", "memory_source_unapproved")
            relation = S.role_memory_artifacts if table is S.artifact_versions else S.role_memory_sources
            field = "artifact_id" if table is S.artifact_versions else "source_id"
            conn.execute(insert(relation).values(project_id=p, memory_version_id=version_id, source_sha256=ref["sha256"], **{field: source["id"]}))
        targets = payload.get("target_object_ids", [])
        if dispatch and scope_object and set(targets) - {scope_object}:
            raise ResourceError("记忆对象越出任务范围", "memory_ownership")
        for target in targets:
            conn.execute(insert(S.role_memory_targets).values(project_id=p, memory_version_id=version_id, object_id=checked_id(target)))
        return {"id": memory_id, "version_id": version_id, "version": number, "status": "draft"}

    def propose_role_memory(self, project_id, payload, **kw):
        def work(conn, project):
            if payload.get("dispatch_id"):
                dispatch = self._dispatch(conn, project, payload, kw["actor"], require_consumed=True)
            else:
                dispatch = None
            return self._propose_memory(conn, project, payload, dispatch)
        return self._mutate(project_id, "propose_role_memory", payload, callback=work, **kw)

    def decide_role_memory(self, project_id, payload, confirmation_id, **kw):
        def work(conn, project):
            version = self._one(conn, S.role_memory_versions, project["id"], required(payload, "version_id"))
            if version["content_sha256"] != required(payload, "content_sha256"):
                raise ResourceError("人工确认必须绑定所见版本摘要", "memory_decision_version")
            latest = conn.execute(select(func.max(S.role_memory_versions.c.version)).where(
                S.role_memory_versions.c.project_id == project["id"], S.role_memory_versions.c.memory_id == version["memory_id"])).scalar_one()
            if version["version"] != latest:
                raise Conflict("旧记忆版本不能取得新的批准", "memory_decision_version")
            prior = conn.execute(select(S.role_memory_decisions).where(S.role_memory_decisions.c.project_id == project["id"],
                S.role_memory_decisions.c.memory_version_id == version["id"]).order_by(S.role_memory_decisions.c.decision_sequence.desc()).limit(1)).mappings().first()
            outcome = required(payload, "outcome")
            allowed = {"draft": {"approved", "rejected"}, "approved": {"retired"}}
            if outcome not in allowed.get(prior["outcome"] if prior else "draft", set()):
                raise ResourceError("记忆决定不能覆盖既有历史", "memory_transition")
            if outcome == "approved":
                entry = next(r for r in self._memory_rows(conn, project["id"]) if r["version_id"] == version["id"])
                if entry["invalid_reasons"]:
                    raise ResourceError("来源已失效，不能批准旧记忆提案", "memory_source_invalid")
            decision_id = new_id()
            values = self._decision(conn, project, kw["actor"], required(payload, "reason"))
            conn.execute(insert(S.role_memory_decisions).values(project_id=project["id"], id=decision_id,
                memory_version_id=version["id"], outcome=outcome, content_sha256=version["content_sha256"],
                confirmation_id=confirmation_id, **values))
            return {"id": version["memory_id"], "version_id": version["id"], "status": outcome, "decision_id": decision_id}
        return self._mutate(project_id, "decide_role_memory", payload, callback=work, **kw)

    def create_role_dispatch(self, project_id, payload, **kw):
        def work(conn, project):
            packet = required(payload, "packet")
            if not isinstance(packet, dict):
                raise ResourceError("角色任务包必须是对象", "invalid_role_context")
            errors = validate_packet(packet, current_card=self._role(packet.get("role", {}).get("id")))
            if packet.get("format") != "vsc.role-context/v2" or errors or packet.get("project", {}).get("project_id") != project["id"]:
                raise ResourceError("角色任务包绑定无效: " + "; ".join(errors), "invalid_role_context")
            if packet.get("revision") != project["revision"]:
                raise Conflict("任务包构建期间项目变化", "revision_conflict")
            d = packet["dispatch"]
            server_now = datetime.now(timezone.utc)
            created, expiry = datetime.fromisoformat(d["created_at"]), datetime.fromisoformat(d["expires_at"])
            if (created > server_now + timedelta(seconds=5) or expiry <= server_now
                    or expiry > server_now + timedelta(hours=packet["role"]["memory_policy"]["summary_ttl_hours"])):
                raise ResourceError("派单期限不能超出服务器角色策略或已到期", "dispatch_expiry_policy")
            self._validate_dispatch_evidence(conn, project["id"], packet)
            ownership = set(d.get("edit_ownership", []))
            if ownership:
                active = conn.execute(select(S.role_dispatches).where(S.role_dispatches.c.project_id == project["id"],
                    S.role_dispatches.c.expires_at > datetime.now(timezone.utc))).mappings()
                for other in active:
                    closed = conn.execute(select(S.dispatch_returns.c.id).where(S.dispatch_returns.c.project_id == project["id"],
                        S.dispatch_returns.c.dispatch_id == other["id"], S.dispatch_returns.c.closed.is_(True))).first()
                    if not closed and ownership & set(other["packet"]["dispatch"].get("edit_ownership", [])):
                        raise Conflict("文件已有未关闭的派单归属", "dispatch_ownership_conflict")
            conn.execute(insert(S.role_dispatches).values(project_id=project["id"], id=d["id"],
                context_id=packet["context_id"], role_id=d["role_id"], role_sha256=d["role_sha256"], context_sha256=packet["context_sha256"],
                host=d["host"], instance_id=d["instance_id"], actor=d["actor"], review_mode=d["review_mode"],
                scope_object_id=None if packet.get("scope", "project") == "project" else packet["scope"],
                packet=packet, expires_at=datetime.fromisoformat(d["expires_at"])))
            for a in packet["inputs"]:
                source = self._one(conn, S.artifact_versions, project["id"], a["id"])
                if a["sha256"] != source["sha256"] or not self._approval_map(conn, project["id"]).get(a["id"]):
                    raise ResourceError("任务输入不是有效批准版本", "context_input_invalid")
                conn.execute(insert(S.dispatch_inputs).values(project_id=project["id"], dispatch_id=d["id"], artifact_id=a["id"]))
            for source in packet.get("source_refs", []):
                row = self._one(conn, S.source_versions, project["id"], source["id"])
                if row["sha256"] != source["sha256"]:
                    raise ResourceError("任务来源摘要不符", "context_source_invalid")
                conn.execute(insert(S.dispatch_sources).values(project_id=project["id"], dispatch_id=d["id"], source_id=source["id"]))
            for media in packet.get("resources", []):
                item = self._media(conn, project["id"], media["media_id"])
                decision = self._one(conn, S.binding_decisions, project["id"], media["binding_decision_id"])
                self._validate_fixed_decision(conn, project["id"], decision, item["id"])
                slot = self._one(conn, S.binding_slots, project["id"], decision["slot_id"])
                if item["sha256"] != media["sha256"] or slot["role"] != media["role"]:
                    raise ResourceError("固定资源的摘要或用途不符", "context_media_invalid")
                conn.execute(insert(S.dispatch_media_refs).values(project_id=project["id"], dispatch_id=d["id"],
                    media_id=item["id"], binding_decision_id=decision["id"], role=slot["role"]))
            valid_memories = {m["version_id"]: m for m in self._memory_rows(conn, project["id"]) if m["status"] == "approved" and not m["invalid_reasons"]}
            keys = [self._one(conn, S.artifact_versions, project["id"], a["id"])["artifact_key"] for a in packet["inputs"]]
            target_ids = set([packet["scope"]] if packet.get("scope") not in {None, "project"} else [])
            for a in packet["inputs"]:
                target_ids.update(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                    S.artifact_object_scopes.c.project_id == project["id"], S.artifact_object_scopes.c.artifact_id == a["id"])).scalars())
            for m in packet["approved_memories"]:
                current = valid_memories.get(m.get("version_id"))
                if not current or current["decision_id"] != m.get("decision_id"):
                    raise ResourceError("记忆批准或来源已失效", "context_memory_invalid")
                if (not memory_allowed(current, d["role_id"], mode=d["review_mode"], target_ids=target_ids, target_keys=keys,
                        include_restricted=packet.get("include_restricted", False))
                        or (current["scope_object_id"] and current["scope_object_id"] != packet.get("scope"))
                        or clean(current) != m):
                    raise ResourceError("任务包记忆与角色策略或固定版本不符", "context_memory_policy")
                conn.execute(insert(S.dispatch_memory_refs).values(project_id=project["id"], dispatch_id=d["id"],
                    memory_version_id=m["version_id"], decision_id=m["decision_id"]))
            return {"dispatch_id": d["id"], "context_id": packet["context_id"], "packet": packet}
        return self._mutate(project_id, "create_role_dispatch", payload, callback=work, **kw)

    def get_role_dispatch(self, project_id, dispatch_id):
        with self.engine.connect() as conn:
            return clean(self._one(conn, S.role_dispatches, checked_id(project_id), dispatch_id))

    def resume_role_summary(self, project_id, dispatch_id, role):
        with self.engine.connect() as conn:
            p = self._project(conn, project_id)["id"]
            d = self._one(conn, S.role_dispatches, p, dispatch_id)
            returns = conn.execute(select(S.dispatch_returns).where(S.dispatch_returns.c.project_id == p,
                S.dispatch_returns.c.dispatch_id == d["id"]).order_by(S.dispatch_returns.c.created_at.desc())).mappings().all()
            if d["role_id"] != role or any(r["closed"] for r in returns) or not returns or not returns[0]["summary"]:
                raise ResourceError("接续任务已关闭、角色不同或缺摘要", "resume_unavailable")
            latest = returns[0]
            if latest["expires_at"] <= datetime.now(timezone.utc):
                raise ResourceError("接续摘要到期，请从权威输入重建", "summary_expired")
            self._validate_dispatch_evidence(conn, p, d["packet"])
            if validate_packet(d["packet"], current_card=self._role(role)):
                raise ResourceError("原任务角色或包已失效", "dispatch_stale")
            approvals = self._approval_map(conn, p)
            for a in d["packet"]["inputs"]:
                art = self._one(conn, S.artifact_versions, p, a["id"])
                newest = conn.execute(select(func.max(S.artifact_versions.c.version)).where(
                    S.artifact_versions.c.project_id == p, S.artifact_versions.c.artifact_key == art["artifact_key"])).scalar_one()
                if not approvals.get(a["id"]) or art["version"] != newest:
                    raise ResourceError("接续摘要来源失效", "resume_source_invalid")
            return clean({"content": latest["summary"], "dispatch_id": d["id"], "created_at": latest["created_at"],
                "expires_at": latest["expires_at"], "persistence": "temporary_resume_only"})

    def _dispatch(self, conn, project, payload, actor, require_consumed=False):
        d = self._one(conn, S.role_dispatches, project["id"], required(payload, "dispatch_id"))
        if (d["actor"] != actor or d["instance_id"] != payload.get("instance_id")
                or d["role_id"] != payload.get("role_id") or d["context_sha256"] != payload.get("context_sha256")):
            raise ResourceError("执行主体、角色或上下文与派单不一致", "dispatch_identity", 403)
        if d["expires_at"] <= datetime.now(timezone.utc):
            raise ResourceError("派单已到期；从权威输入重建任务", "dispatch_expired")
        if conn.execute(select(S.dispatch_returns.c.id).where(S.dispatch_returns.c.project_id == project["id"],
                S.dispatch_returns.c.dispatch_id == d["id"], S.dispatch_returns.c.closed.is_(True))).first():
            raise ResourceError("派单已关闭", "dispatch_closed")
        errors = validate_packet(d["packet"], current_card=self._role(d["role_id"]))
        if errors:
            raise ResourceError("角色策略或上下文失效", "dispatch_stale")
        self._validate_dispatch_evidence(conn, project["id"], d["packet"])
        if require_consumed and not conn.execute(select(S.dispatch_consumptions.c.id).where(
                S.dispatch_consumptions.c.project_id == project["id"], S.dispatch_consumptions.c.dispatch_id == d["id"])).first():
            raise ResourceError("先确认消费固定上下文，再回写", "context_not_consumed")
        return d

    def consume_role_dispatch(self, project_id, payload, **kw):
        def work(conn, project):
            d = self._dispatch(conn, project, payload, kw["actor"])
            if payload.get("packet") != d["packet"]:
                raise ResourceError("消费的任务包与冻结快照不同", "context_tampered")
            self._validate_dispatch_evidence(conn, project["id"], d["packet"])
            prior = conn.execute(select(S.dispatch_consumptions.c.id).where(S.dispatch_consumptions.c.project_id == project["id"],
                S.dispatch_consumptions.c.dispatch_id == d["id"])).scalar_one_or_none()
            if not prior:
                conn.execute(insert(S.dispatch_consumptions).values(project_id=project["id"], id=new_id(), dispatch_id=d["id"],
                    actor=kw["actor"], instance_id=d["instance_id"], context_sha256=d["context_sha256"]))
            return {"dispatch_id": d["id"], "context_id": d["context_id"], "role_id": d["role_id"],
                    "role_sha256": d["role_sha256"], "context_sha256": d["context_sha256"], "consumed": True}
        return self._mutate(project_id, "consume_role_dispatch", payload, callback=work, **kw)

    def return_role_dispatch(self, project_id, payload, **kw):
        def work(conn, project):
            stored = self._one(conn, S.role_dispatches, project["id"], required(payload, "dispatch_id"))
            result = required(payload, "result")
            errors = validate_return(stored["packet"], result)
            if errors:
                raise ResourceError("; ".join(errors), "invalid_dispatch_return")
            return_key = required(payload, "return_key")
            return_sha = digest({"result": result, "closed": payload.get("closed", True) is True})
            prior = conn.execute(select(S.dispatch_returns).where(S.dispatch_returns.c.project_id == project["id"],
                S.dispatch_returns.c.dispatch_id == stored["id"], S.dispatch_returns.c.return_key == return_key)).mappings().first()
            if prior:
                if (prior["result_sha256"] != return_sha or stored["actor"] != kw["actor"]
                        or stored["instance_id"] != payload.get("instance_id") or stored["role_id"] != payload.get("role_id")
                        or stored["context_sha256"] != payload.get("context_sha256")):
                    raise Conflict("同一返回键不能覆盖不同结果", "idempotency_conflict")
                return {"return_id": prior["id"], "memory_proposals": [], "reused": True}
            d = self._dispatch(conn, project, payload, kw["actor"], require_consumed=True)
            proposals = []
            for i, proposal in enumerate(result["memory_proposals"]):
                proposals.append(self._propose_memory(conn, project, dict(proposal, proposal_key=return_key + ":" + str(i)), d))
            summary = result.get("session_summary")
            if summary is not None and (not isinstance(summary, str) or len(summary) > 2200):
                raise ResourceError("接续摘要超过预算", "summary_budget")
            row_id = new_id()
            conn.execute(insert(S.dispatch_returns).values(project_id=project["id"], id=row_id, dispatch_id=d["id"],
                return_key=return_key, result_sha256=return_sha, result=result, summary=summary,
                expires_at=d["expires_at"] if summary else None, closed=payload.get("closed", True) is True))
            for ref in result["result_refs"]:
                artifact = self._one(conn, S.artifact_versions, project["id"], ref["id"])
                if artifact["sha256"] != ref["sha256"]:
                    raise ResourceError("返回产物固定摘要不符", "return_artifact_sha")
                conn.execute(insert(S.dispatch_result_artifacts).values(project_id=project["id"], return_id=row_id, artifact_id=ref["id"]))
            return {"return_id": row_id, "memory_proposals": proposals, "closed": payload.get("closed", True) is True}
        return self._mutate(project_id, "return_role_dispatch", payload, callback=work, **kw)
