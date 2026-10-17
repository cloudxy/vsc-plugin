"""Mutable script working copy plus anchored, append-only review notes.

The working copy is the only mutable project table (migration 0006): autosave
updates content in place under its own optimistic draft_revision and never
creates artifact versions or project revisions. Submitting for human
confirmation freezes an immutable artifact version through the regular
``_create_artifact`` path inside one transaction.
"""
import json
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
            project = self._project(conn, project_id)
            row = self._draft(conn, project_id, scope_key)
            notes = list(conn.execute(select(S.script_notes).where(
                S.script_notes.c.project_id == project_id).order_by(S.script_notes.c.created_at, S.script_notes.c.id)).mappings())
            decisions = list(conn.execute(select(S.script_note_decisions).where(
                S.script_note_decisions.c.project_id == project_id)
                .order_by(S.script_note_decisions.c.created_at, S.script_note_decisions.c.id)).mappings())
            latest = {decision["note_id"]: dict(decision) for decision in decisions}
            note_rows = [{"id": note["id"], "scene_id": note["scene_id"], "line_id": note["line_id"],
                          "scope_key": note["scope_key"], "scoped": note["scope_key"] == scope_key,
                          "body": note["body"], "author": note["author"], "created_at": note["created_at"],
                          "status": {"resolve": "resolved", "dismiss": "dismissed"}.get(
                              latest.get(note["id"], {}).get("outcome"), "open"),
                          "decision": latest.get(note["id"])} for note in notes
                         if note["scope_key"] == scope_key or note["scope_key"] is None]
            suggestions, suggestion_decisions = self._suggestion_rows(conn, project_id, scope_key)
            if row is None:
                return {"exists": False, "scope_key": scope_key, "draft_revision": 0, "content": None,
                        "phase": "empty", "base": None, "submitted": None, "notes": note_rows,
                        "suggestions": suggestions}
            base = self._artifact_state(conn, project_id, row["base_artifact_id"]) if row["base_artifact_id"] else None
            if base is None:
                # 未提交修订时也显示当前覆盖范围的已批准基线（只读派生，不写事实）。
                _, script_types = self._script_types(project["profile_snapshot"].get("stages", []))
                if script_types:
                    for candidate in self._current_scripts(conn, project_id, script_types):
                        if candidate["project_wide"] or (scope_key and scope_key in candidate["scopes"]):
                            base = self._artifact_state(conn, project_id, candidate["id"])
                            break
            submitted = self._artifact_state(conn, project_id, row["submitted_artifact_id"]) if row["submitted_artifact_id"] else None
            phase = {"approved": "approved", "rejected": "rejected"}.get(submitted["state"], "pending") if submitted else "editing"
            return {"exists": True, "scope_key": scope_key, "draft_revision": row["draft_revision"],
                    "content": row["content"], "updated_at": row["updated_at"], "updated_by": row["updated_by"],
                    "phase": phase, "base": base, "submitted": submitted, "notes": note_rows,
                    "suggestions": suggestions, "draft_id": row["id"]}

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
                scope_key=self._scope_key(payload.get("scope_key", "")),
                scene_id=required(payload, "scene_id"), line_id=payload.get("line_id"),
                body=required(payload, "body"), author=actor or ""))
            return {"id": note_id}
        return self._mutate(project_id, "add_script_note", payload, callback=work, **kw)

    @staticmethod
    def _suggestion_rows(conn, project_id, scope_key):
        from datetime import datetime, timezone

        def created(row):
            value = row.get("created_at")
            return value.timestamp() if hasattr(value, "timestamp") else float(value or 0)
        suggestions = [dict(row) for row in conn.execute(select(S.script_suggestions).where(
            S.script_suggestions.c.project_id == project_id,
            S.script_suggestions.c.scope_key == scope_key)).mappings()]
        identifiers = [row["id"] for row in suggestions]
        decisions = {}
        if identifiers:
            for row in conn.execute(select(S.script_suggestion_decisions).where(
                    S.script_suggestion_decisions.c.project_id == project_id,
                    S.script_suggestion_decisions.c.suggestion_id.in_(identifiers))).mappings():
                current = decisions.get(row["suggestion_id"])
                if current is None or created(row) > created(current):
                    decisions[row["suggestion_id"]] = dict(row)
        for row in suggestions:
            decision = decisions.get(row["id"])
            row["status"] = {"accept": "accepted", "reject": "rejected", "undo_accept": "pending"}.get(
                (decision or {}).get("outcome"), "pending")
            row["decision"] = decision
        return suggestions, list(decisions.values())

    def add_script_suggestion(self, project_id, payload, **kw):
        actor = kw.get("actor")

        def work(conn, project):
            scope_key = self._scope_key(payload.get("scope_key", ""))
            row = self._draft(conn, project["id"], scope_key)
            if row is None:
                raise ResourceError("当前范围没有工作副本；建议需要绑定工作副本修订", "draft_missing", 404)
            suggestion_id = new_id()
            conn.execute(insert(S.script_suggestions).values(project_id=project["id"], id=suggestion_id,
                scope_key=scope_key, base_draft_revision=row["draft_revision"],
                scene_id=required(payload, "scene_id"), line_id=payload.get("line_id"),
                kind=required(payload, "kind"), field=payload.get("field", "text"),
                before_value=payload.get("before_value"), after_value=required(payload, "after_value"),
                reason=required(payload, "reason"), origin=payload.get("origin", "manual"), author=actor or ""))
            return {"id": suggestion_id, "base_draft_revision": row["draft_revision"]}
        return self._mutate(project_id, "add_script_suggestion", payload, callback=work, **kw)

    @staticmethod
    def _apply_suggestion(content, suggestion, value):
        """按稳定场／行身份写入一个字段；找不到目标行时明确报错，不做名称猜测。"""
        scene = next((row for row in content.get("scenes", []) if row.get("id") == suggestion["scene_id"]), None)
        if scene is None:
            raise ResourceError("建议指向的场次在当前稿中不存在：" + suggestion["scene_id"], "suggestion_stale")
        field_name = {"action": "actions", "dialogue": "dialogue", "silence": "silence"}[suggestion["kind"]]
        line = next((row for row in scene.get(field_name, []) if row.get("id") == suggestion["line_id"]), None) \
            if suggestion["line_id"] else None
        if line is None:
            raise ResourceError("建议指向的行在当前稿中不存在：" + str(suggestion["line_id"]), "suggestion_stale")
        line[suggestion["field"]] = value

    def decide_script_suggestion(self, project_id, payload, **kw):
        actor = kw.get("actor")
        outcome = required(payload, "outcome")

        def work(conn, project):
            if outcome not in ("accept", "reject", "undo_accept"):
                raise ResourceError("建议处理只能是 accept、reject 或 undo_accept", "invalid_payload")
            scope_key = self._scope_key(payload.get("scope_key", ""))
            suggestion = self._one(conn, S.script_suggestions, project["id"], checked_id(required(payload, "suggestion_id")))
            if suggestion["scope_key"] != scope_key:
                raise ResourceError("建议不属于当前范围", "invalid_payload")
            suggestions, _ = self._suggestion_rows(conn, project["id"], scope_key)
            status = next(row["status"] for row in suggestions if row["id"] == suggestion["id"])
            row = self._draft(conn, project["id"], scope_key, lock=True)
            if row is None:
                raise ResourceError("当前范围没有工作副本", "draft_missing", 404)
            applied_revision = None
            if outcome == "accept":
                if status != "pending":
                    raise ResourceError("只有待处理建议可以接受", "invalid_payload")
                if row["draft_revision"] != suggestion["base_draft_revision"]:
                    raise Conflict("建议基于的稿次已过期（当前 r%d，建议基于 r%d）；请先加载最新内容再重新提出建议"
                                   % (row["draft_revision"], suggestion["base_draft_revision"]), "suggestion_stale")
                content = dict(row["content"])
                self._apply_suggestion(content, suggestion, suggestion["after_value"])
                conn.execute(update(S.script_drafts).where(
                    S.script_drafts.c.project_id == project["id"], S.script_drafts.c.scope_key == scope_key)
                    .values(content=content, draft_revision=row["draft_revision"] + 1,
                            updated_at=func.now(), updated_by=actor or ""))
                applied_revision = row["draft_revision"] + 1
            elif outcome == "undo_accept":
                decision = next((item["decision"] for item in suggestions
                                 if item["id"] == suggestion["id"] and item["status"] == "accepted"), None)
                if decision is None or status != "accepted":
                    raise ResourceError("只有已接受且未撤销的建议可以撤销", "invalid_payload")
                if decision.get("applied_revision") is None or row["draft_revision"] != decision["applied_revision"]:
                    raise Conflict("接受后工作副本已有新编辑（当前 r%d，接受时 r%s）；不能自动撤销，请人工改回"
                                   % (row["draft_revision"], decision.get("applied_revision")), "suggestion_stale")
                content = dict(row["content"])
                self._apply_suggestion(content, suggestion,
                                       suggestion["before_value"] if suggestion["before_value"] is not None else "")
                conn.execute(update(S.script_drafts).where(
                    S.script_drafts.c.project_id == project["id"], S.script_drafts.c.scope_key == scope_key)
                    .values(content=content, draft_revision=row["draft_revision"] + 1,
                            updated_at=func.now(), updated_by=actor or ""))
                applied_revision = row["draft_revision"] + 1
            decision_id = new_id()
            conn.execute(insert(S.script_suggestion_decisions).values(project_id=project["id"], id=decision_id,
                suggestion_id=suggestion["id"], outcome=outcome, actor=actor or "",
                reason=required(payload, "reason"), applied_revision=applied_revision))
            return {"id": decision_id, "suggestion_id": suggestion["id"], "outcome": outcome,
                    "draft_revision": applied_revision or row["draft_revision"]}
        return self._mutate(project_id, "decide_script_suggestion", payload, callback=work, **kw)

    def script_revision_impact(self, project_id, scope_key=""):
        """B1-06：待审／草稿修订相对已批准基线的真实下游影响（覆盖镜头、声音Cue、时间线用料）。"""
        from vsc.assets.script_diff import compare_documents
        project_id = checked_id(project_id)
        scope_key = self._scope_key(scope_key)
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            _, script_types = self._script_types(project["profile_snapshot"].get("stages", []))
            if not script_types:
                return {"scope_key": scope_key, "baseline_artifact_id": None, "changed_lines": [], "shots": [], "cues": [], "unresolved": []}
            parents = self._object_parents(conn, project_id)
            candidates = self._current_scripts(conn, project_id, script_types)
            baseline = next((row for row in candidates if row["project_wide"] or (scope_key and scope_key in row["scopes"])), None)
            draft = self._draft(conn, project_id, scope_key)
            revised = None
            if draft is not None and draft.get("submitted_artifact_id"):
                revised = self._artifact_state(conn, project_id, draft["submitted_artifact_id"])
                if revised.get("state") == "approved":
                    revised = None
            if baseline is None or (draft is None and revised is None):
                return {"scope_key": scope_key, "baseline_artifact_id": (baseline or {}).get("id"),
                        "changed_lines": [], "shots": [], "cues": [], "unresolved": []}
            baseline_doc = json.loads(conn.execute(select(S.artifact_versions.c.document).where(
                S.artifact_versions.c.project_id == project_id,
                S.artifact_versions.c.id == baseline["id"])).scalar_one())
            if revised is not None:
                revised_doc = json.loads(conn.execute(select(S.artifact_versions.c.document).where(
                    S.artifact_versions.c.project_id == project_id,
                    S.artifact_versions.c.id == revised["id"])).scalar_one())
            else:
                revised_doc = draft["content"]
            changes = compare_documents(baseline_doc, revised_doc).get("lines", [])
            line_keys = sorted({str(row.get("line_id")) for row in changes if row.get("line_id")})
            unresolved = [row for row in changes if not row.get("line_id")]
            shots, cues = [], []
            if line_keys:
                lines = conn.execute(select(S.script_lines.c.id, S.script_lines.c.line_key).where(
                    S.script_lines.c.project_id == project_id,
                    S.script_lines.c.script_version_id == baseline["id"],
                    S.script_lines.c.line_key.in_(line_keys))).mappings().all()
                found = {row["line_key"]: row["id"] for row in lines}
                unresolved.extend({"line_id": key, "reason": "baseline_missing_line"}
                                   for key in line_keys if key not in found)
                ids = list(found.values())
                if ids:
                    shots = [dict(row) for row in conn.execute(select(
                        S.creative_objects.c.id, S.creative_objects.c.title, S.creative_objects.c.display_code)
                        .distinct().where(S.creative_objects.c.project_id == project_id, S.creative_objects.c.id.in_(
                            select(S.shot_line_coverage.c.shot_id).where(
                                S.shot_line_coverage.c.project_id == project_id,
                                S.shot_line_coverage.c.line_id.in_(ids))))).mappings()]
                    cue_rows = conn.execute(select(S.sound_cues.c.id, S.sound_cues.c.cue_key,
                        S.sound_cues.c.label, S.sound_cues.c.subtitle_version_id).where(
                        S.sound_cues.c.project_id == project_id, S.sound_cues.c.line_id.in_(ids))).mappings().all()
                    for cue in cue_rows:
                        row = dict(cue)
                        row["timeline_items"] = conn.execute(select(func.count()).select_from(
                            S.cue_timeline_items).where(S.cue_timeline_items.c.project_id == project_id,
                            S.cue_timeline_items.c.cue_id == cue["id"])).scalar_one()
                        cues.append(row)
            return {"scope_key": scope_key, "baseline_artifact_id": baseline["id"] if baseline else None,
                    "changed_lines": changes, "shots": shots, "cues": cues, "unresolved": unresolved}

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
