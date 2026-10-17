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
    # Host contract: self.engine, self._mutate, self._one, self._create_artifact.

    @staticmethod
    def _scope_key(value):
        if not isinstance(value, str) or len(value) > 200:
            raise ResourceError("scope_key 必须是不超过 200 字符的文本", "invalid_payload")
        return value

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
            if base is not None and base != row["draft_revision"]:
                raise Conflict(f"剧本工作副本已被他人更新（当前 r{row['draft_revision']}）；请先加载最新内容再提交",
                               "draft_revision_conflict")
            document = row["content"]
            if not isinstance(document, dict):
                raise ResourceError("工作副本内容无效，不能提交", "invalid_payload")
            artifact_payload = {"document": dict(document, project_id=project["id"]),
                                "artifact_type": required(payload, "artifact_type"),
                                "artifact_key": payload.get("artifact_key") or ("screenplay:" + (scope_key or "project")),
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
                .values(submitted_artifact_id=result["id"], updated_at=func.now(), updated_by=actor or ""))
            return {"artifact": result, "scope_key": scope_key, "draft_revision": row["draft_revision"]}
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
