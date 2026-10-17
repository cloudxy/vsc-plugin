"""Mutable script working copy plus anchored, append-only review notes.

The working copy is the only mutable project table (migration 0006): autosave
updates content in place under its own optimistic draft_revision and never
creates artifact versions or project revisions. Submitting for human
confirmation freezes an immutable artifact version through the regular
``_create_artifact`` path inside one transaction.
"""
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from . import schema as S
from .values import checked_id, clean, new_id


class ScriptWorkspaceRepository:
    # Host contract: self.engine, self._mutate, self._one, self._create_artifact, self._approval_map.

    @staticmethod
    def _script_types(stages):
        """Profile 中剧本阶段声明的剧本类型（vsc.screenplay / screenplay 等兼容拼写）。"""
        for index, stage in enumerate(stages):
            if stage.get("id") == "script" or any(kind in stage.get("required", [])
                                                  for kind in ("vsc.screenplay", "screenplay")):
                return index, {kind for kind in stage.get("required", []) if "screenplay" in kind}
        return None, set()

    @staticmethod
    def _scope_key(value):
        if not isinstance(value, str) or len(value) > 200:
            raise ResourceError("scope_key 必须是不超过 200 字符的文本", "invalid_payload")
        return value

    def _object_parents(self, conn, project_id):
        parents = {}
        for table in (S.episodes, S.scenes, S.sequences, S.shots):
            for parent_id, row_id in conn.execute(select(table.c.parent_id, table.c.id)
                                                   .where(table.c.project_id == project_id)):
                parents[row_id] = parent_id
        return parents

    @staticmethod
    def _ancestor_chain(scope_id, parents):
        chain, cursor = set(), scope_id
        while cursor and cursor not in chain:
            chain.add(cursor)
            cursor = parents.get(cursor)
        return chain

    def _current_scripts(self, conn, project_id, script_types):
        """当前已批准的剧本候选及其对象范围（F05/F06 统一事实来源）。"""
        rows = conn.execute(select(S.artifact_versions.c.id, S.artifact_versions.c.artifact_key,
            S.artifact_versions.c.project_wide).where(S.artifact_versions.c.project_id == project_id,
            S.artifact_versions.c.artifact_type.in_(script_types))).mappings().all()
        current = set(conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
            S.current_artifact_versions.c.project_id == project_id)).scalars())
        approved = self._approval_map(conn, project_id)
        found = []
        for row in rows:
            if row["id"] not in current or not approved.get(row["id"], False):
                continue
            scopes = set() if row["project_wide"] else set(conn.execute(
                select(S.artifact_object_scopes.c.object_id).where(
                    S.artifact_object_scopes.c.project_id == project_id,
                    S.artifact_object_scopes.c.artifact_id == row["id"])).scalars())
            found.append({"id": row["id"], "artifact_key": row["artifact_key"],
                          "project_wide": row["project_wide"], "scopes": scopes})
        return found

    def check_script_confirmation(self, conn, project, payload):
        """F05/F06 硬停（在登记产物的事务内统一消费）：

        1. 产物类型→阶段归属只由固定 Profile 解析，调用方给的 stage 不参与判定；
        2. script 之后阶段的正式产物要求目标范围逐一被已批准且 current 的剧本覆盖
           （项目级产物须有项目级剧本；对象范围的每个对象都必须覆盖）；
        3. 覆盖范围内存在待人工确认的剧本修订时，相关新制作暂停（script_revision_pending）。
        """
        stages = project["profile_snapshot"].get("stages", [])
        script_index, script_types = self._script_types(stages)
        if script_index is None or not script_types:
            return
        artifact_type = payload.get("artifact_type")
        owners = [index for index, stage in enumerate(stages) if artifact_type in stage.get("required", [])]
        if not owners or max(owners) <= script_index:
            return
        project_id = project["id"]
        scope_ids = [checked_id(value) for value in payload.get("object_ids", [])]
        explicit_wide = payload.get("project_wide")
        if explicit_wide is not None and bool(explicit_wide) == bool(scope_ids):
            raise ResourceError("项目级范围与对象范围互斥且必须指定其一", "invalid_scope")
        wide = bool(explicit_wide) if explicit_wide is not None else not scope_ids  # 与登记语义一致：无对象范围即项目级
        candidates = self._current_scripts(conn, project_id, script_types)
        parents = self._object_parents(conn, project_id)
        if wide:
            confirmed = any(row["project_wide"] for row in candidates)
        else:
            confirmed = bool(scope_ids) and all(any(
                row["project_wide"] or (row["scopes"] & self._ancestor_chain(scope, parents))
                for row in candidates) for scope in scope_ids)
        if not confirmed:
            raise ResourceError("剧本尚未人工确认，不能登记后续阶段的正式产物；先在剧本工作区提交并批准该范围剧本",
                                "script_confirmation_required", 409)
        pending = conn.execute(select(S.script_drafts.c.scope_key, S.script_drafts.c.submitted_artifact_id)
            .where(S.script_drafts.c.project_id == project_id,
                   S.script_drafts.c.submitted_artifact_id != None)).all()  # noqa: E711
        decided = {row[0] for row in conn.execute(select(S.artifact_decisions.c.artifact_id)
            .where(S.artifact_decisions.c.project_id == project_id))}
        pending_scopes = {scope_key or "" for scope_key, artifact_id in pending if artifact_id not in decided}
        if pending_scopes:
            affected = wide or any(key == "" or key in self._ancestor_chain(scope, parents)
                                   for key in pending_scopes for scope in scope_ids)
            if affected:
                raise ResourceError("该范围存在待人工确认的剧本修订；相关新制作暂停，确认后再登记后续产物",
                                    "script_revision_pending", 409)

    @staticmethod
    def _draft(conn, project_id, scope_key, lock=False):
        query = select(S.script_drafts).where(S.script_drafts.c.project_id == project_id,
                                              S.script_drafts.c.scope_key == scope_key)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        return dict(row) if row else None

    def _artifact_state(self, conn, project_id, artifact_id):
        row = conn.execute(select(S.artifact_versions.c.id, S.artifact_versions.c.artifact_key,
            S.artifact_versions.c.version, S.artifact_versions.c.sha256, S.artifact_versions.c.created_at)
            .where(S.artifact_versions.c.project_id == project_id,
                   S.artifact_versions.c.id == checked_id(artifact_id))).mappings().first()
        if row is None:
            return {"id": artifact_id, "state": "missing"}
        outcome = conn.execute(select(S.artifact_decisions.c.outcome).where(
            S.artifact_decisions.c.project_id == project_id, S.artifact_decisions.c.artifact_id == row["id"])
            .order_by(S.artifact_decisions.c.decision_sequence.desc()).limit(1)).scalar()
        return clean(dict(row, state={"approve": "approved", "reject": "rejected",
                                      "revoke": "revoked"}.get(outcome, "pending")))

    def get_script_draft(self, project_id, scope_key=""):
        project_id = checked_id(project_id)
        scope_key = self._scope_key(scope_key)
        with self.engine.connect() as conn:
            row = self._draft(conn, project_id, scope_key)
            notes = list(conn.execute(select(S.script_notes).where(
                S.script_notes.c.project_id == project_id).order_by(S.script_notes.c.created_at, S.script_notes.c.id)).mappings())
            decisions = list(conn.execute(select(S.script_note_decisions).where(
                S.script_note_decisions.c.project_id == project_id)
                .order_by(S.script_note_decisions.c.created_at, S.script_note_decisions.c.id)).mappings())
            latest = {decision["note_id"]: dict(decision) for decision in decisions}
            note_rows = [{"id": note["id"], "scene_id": note["scene_id"], "line_id": note["line_id"],
                          "body": note["body"], "author": note["author"], "created_at": note["created_at"],
                          "status": {"resolve": "resolved", "dismiss": "dismissed"}.get(
                              latest.get(note["id"], {}).get("outcome"), "open"),
                          "decision": latest.get(note["id"])} for note in notes]
            if row is None:
                return {"exists": False, "scope_key": scope_key, "draft_revision": 0, "content": None,
                        "phase": "empty", "base": None, "submitted": None, "notes": note_rows}
            base = self._artifact_state(conn, project_id, row["base_artifact_id"]) if row["base_artifact_id"] else None
            submitted = self._artifact_state(conn, project_id, row["submitted_artifact_id"]) if row["submitted_artifact_id"] else None
            phase = {"approved": "approved", "rejected": "rejected"}.get(submitted["state"], "pending") if submitted else "editing"
            return {"exists": True, "scope_key": scope_key, "draft_revision": row["draft_revision"],
                    "content": row["content"], "updated_at": row["updated_at"], "updated_by": row["updated_by"],
                    "phase": phase, "base": base, "submitted": submitted, "notes": note_rows, "draft_id": row["id"]}

    def save_script_draft(self, project_id, payload, actor=None, **_):
        project_id = checked_id(project_id)
        scope_key = self._scope_key(payload.get("scope_key", ""))
        base = payload.get("base_draft_revision", 0)
        content = required(payload, "content")
        if not isinstance(content, dict):
            raise ResourceError("工作副本必须是结构化剧本文档", "invalid_payload")
        try:
            with self.engine.begin() as conn:
                row = self._draft(conn, project_id, scope_key, lock=True)
                if row is None:
                    if base not in (0, None):
                        raise Conflict("工作副本已被他人创建，请先加载最新内容", "draft_revision_conflict")
                    conn.execute(insert(S.script_drafts).values(project_id=project_id, id=new_id(),
                        scope_key=scope_key, content=content, draft_revision=1, updated_by=actor))
                    return {"scope_key": scope_key, "draft_revision": 1, "created": True}
                if base != row["draft_revision"]:
                    raise Conflict(f"剧本工作副本已被他人更新（当前 r{row['draft_revision']}）；请先加载最新内容",
                                   "draft_revision_conflict")
                revision = row["draft_revision"] + 1
                conn.execute(update(S.script_drafts).where(
                    S.script_drafts.c.project_id == project_id, S.script_drafts.c.scope_key == scope_key,
                    S.script_drafts.c.draft_revision == row["draft_revision"])
                    .values(content=content, draft_revision=revision, updated_at=func.now(), updated_by=actor))
                return {"scope_key": scope_key, "draft_revision": revision, "created": False}
        except IntegrityError as exc:
            raise Conflict("剧本工作副本并发写入冲突，请先加载最新内容", "draft_revision_conflict") from exc

    def submit_script_draft(self, project_id, payload, **kw):
        actor = kw.get("actor")

        def work(conn, project):
            scope_key = self._scope_key(payload.get("scope_key", ""))
            row = self._draft(conn, project["id"], scope_key, lock=True)
            if row is None:
                raise ResourceError("还没有可提交的剧本工作副本；先保存草稿", "draft_missing", 404)
            base = payload.get("base_draft_revision")
            if (not isinstance(base, int) or isinstance(base, bool) or base != row["draft_revision"]):
                raise Conflict(f"提交必须携带准确的 draft_revision（当前 r{row['draft_revision']}）；请先保存并加载最新内容",
                               "draft_revision_conflict")
            document = row["content"]
            if not isinstance(document, dict):
                raise ResourceError("工作副本内容无效，不能提交", "invalid_payload")
            stages = project["profile_snapshot"].get("stages", [])
            script_types = self._script_types(stages)[1]
            artifact_type = required(payload, "artifact_type")
            if script_types and artifact_type not in script_types:
                raise ResourceError("script-submit 只接受剧本类型产物；其他类型走正式登记入口", "invalid_artifact_type", 422)
            # F06：沿既有已批准剧本的固定 stream 提交，并记录当前基线，不另造可绕过的平行流。
            candidates = self._current_scripts(conn, project["id"], script_types)
            parents = self._object_parents(conn, project["id"])
            existing = None
            for candidate in candidates:
                if candidate["project_wide"]:
                    if not scope_key:
                        existing = candidate
                        break
                elif scope_key and scope_key in candidate["scopes"]:
                    existing = candidate
                    break
            artifact_payload = {"document": dict(document, project_id=project["id"]),
                                "artifact_type": artifact_type,
                                "artifact_key": payload.get("artifact_key") or (existing or {}).get("artifact_key")
                                    or ("screenplay:" + (scope_key or "project")),
                                "stage": payload.get("stage", "script"),
                                "registration_note": payload.get("registration_note", "剧本工作区提交人工确认")}
            if scope_key:
                artifact_payload["object_ids"] = [checked_id(scope_key)]
            else:
                artifact_payload["project_wide"] = True
            if payload.get("dependency_ids"):
                artifact_payload["dependency_ids"] = payload["dependency_ids"]
            result = self._create_artifact(conn, project, artifact_payload)
            conn.execute(update(S.script_drafts).where(
                S.script_drafts.c.project_id == project["id"], S.script_drafts.c.scope_key == scope_key)
                .values(submitted_artifact_id=result["id"],
                        base_artifact_id=(existing or {}).get("id") or row.get("base_artifact_id"),
                        updated_at=func.now(), updated_by=actor or ""))
            return {"artifact": result, "scope_key": scope_key, "draft_revision": row["draft_revision"],
                    "baseline_artifact_id": (existing or {}).get("id")}
        return self._mutate(project_id, "submit_script_draft", payload, callback=work, **kw)

    def add_script_note(self, project_id, payload, **kw):
        actor = kw.get("actor")

        def work(conn, project):
            note_id = new_id()
            conn.execute(insert(S.script_notes).values(project_id=project["id"], id=note_id,
                scene_id=required(payload, "scene_id"), line_id=payload.get("line_id"),
                body=required(payload, "body"), author=actor or ""))
            return {"id": note_id}
        return self._mutate(project_id, "add_script_note", payload, callback=work, **kw)

    def decide_script_note(self, project_id, payload, **kw):
        actor = kw.get("actor")

        def work(conn, project):
            note_id = checked_id(required(payload, "note_id"))
            outcome = required(payload, "outcome")
            if outcome not in ("resolve", "dismiss", "reopen"):
                raise ResourceError("批注处理只能是 resolve、dismiss 或 reopen", "invalid_payload")
            self._one(conn, S.script_notes, project["id"], note_id)
            decision_id = new_id()
            conn.execute(insert(S.script_note_decisions).values(project_id=project["id"], id=decision_id,
                note_id=note_id, outcome=outcome, actor=actor or "", reason=required(payload, "reason")))
            return {"id": decision_id, "note_id": note_id, "outcome": outcome}
        return self._mutate(project_id, "decide_script_note", payload, callback=work, **kw)
