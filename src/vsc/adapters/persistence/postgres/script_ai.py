"""Durable AI suggestion attempts and atomic, version-bound batch registration."""
from sqlalchemy import func, insert, select, update

from vsc.assets.resource_service import Conflict, ResourceError, required
from . import schema as S
from .values import checked_id, clean, digest, new_id, CURRENT_REVISION


class ScriptSuggestionRepository:
    def script_suggestion_receipt(self, project_id, payload, actor, key):
        with self.engine.connect() as conn:
            p = checked_id(project_id)
            self._project(conn, p)
            receipt = conn.execute(select(S.command_receipts).where(S.command_receipts.c.project_id == p,
                S.command_receipts.c.idempotency_key == key)).mappings().first()
            if receipt is None:
                if payload.get("new_attempt") is not True and payload.get("script_note_id"):
                    previous = conn.execute(select(S.script_suggestion_runs).join(S.review_script_runs,
                        (S.review_script_runs.c.project_id == S.script_suggestion_runs.c.project_id) &
                        (S.review_script_runs.c.run_id == S.script_suggestion_runs.c.id)).join(S.review_responses,
                            (S.review_responses.c.project_id == S.review_script_runs.c.project_id) &
                            (S.review_responses.c.id == S.review_script_runs.c.response_id)).where(
                                S.script_suggestion_runs.c.project_id == p,
                                S.review_responses.c.script_note_id == checked_id(payload["script_note_id"]),
                                S.script_suggestion_runs.c.base_draft_revision == payload.get("base_draft_revision"),
                                S.script_suggestion_runs.c.base_content_sha256 == payload.get("base_content_sha256"))
                        .order_by(S.script_suggestion_runs.c.created_at.desc()).limit(1)).mappings().first()
                    if previous:
                        draft = self._draft(conn, p, previous["scope_key"])
                        if (not draft or draft["draft_revision"] != previous["base_draft_revision"]
                                or digest(draft["content"]) != previous["base_content_sha256"]):
                            raise Conflict("原批注的稿次已变化；原结果仍可回看，请重新定位后处理", "review_target_stale")
                        return {"id": str(previous["id"]), "caller": None, "status": previous["status"]}
                if payload.get("new_attempt") is not True and not payload.get("script_note_id"):
                    previous = conn.execute(select(S.script_suggestion_runs).where(
                        S.script_suggestion_runs.c.project_id == p,
                        S.script_suggestion_runs.c.scope_key == payload.get("scope_key", ""),
                        S.script_suggestion_runs.c.base_draft_revision == payload.get("base_draft_revision"),
                        S.script_suggestion_runs.c.base_content_sha256 == payload.get("base_content_sha256"),
                        S.script_suggestion_runs.c.goal == payload.get("goal")).order_by(
                            S.script_suggestion_runs.c.created_at.desc()).limit(1)).mappings().first()
                    if previous:
                        return {"id": str(previous["id"]), "caller": None, "status": previous["status"]}
                return None
            if receipt["request_sha256"] != digest({"action": "start_script_suggestion_run", "payload": payload, "actor": actor}):
                raise Conflict("同一幂等键已用于不同操作", "idempotency_conflict")
            return clean(receipt["response"])

    def list_script_suggestion_runs(self, project_id, scope_key=""):
        with self.engine.connect() as conn:
            rows = conn.execute(select(S.script_suggestion_runs).where(
                S.script_suggestion_runs.c.project_id == checked_id(project_id),
                S.script_suggestion_runs.c.scope_key == scope_key).order_by(
                    S.script_suggestion_runs.c.created_at.desc()).limit(10)).mappings()
            return clean([{k: row[k] for k in ("id", "status", "goal", "base_draft_revision", "error_code", "created_at")}
                | {"result_available": row["result"] is not None} for row in rows])

    def persist_script_suggestion_result(self, project_id, run_id, suggestions, error):
        with self.engine.begin() as conn:
            p = checked_id(project_id)
            run = conn.execute(select(S.script_suggestion_runs).where(S.script_suggestion_runs.c.project_id == p,
                S.script_suggestion_runs.c.id == checked_id(run_id)).with_for_update()).mappings().one()
            if run["status"] == "running" and run["result"] is None:
                conn.execute(update(S.script_suggestion_runs).where(S.script_suggestion_runs.c.project_id == p,
                    S.script_suggestion_runs.c.id == run["id"]).values(result={"host_suggestions": suggestions, "error_code": error}))

    def get_script_suggestion_run(self, project_id, run_id):
        with self.engine.connect() as conn:
            return clean(self._one(conn, S.script_suggestion_runs, checked_id(project_id), run_id))

    def start_script_suggestion_run(self, project_id, payload, *, backend, caller, **kw):
        def work(conn, project):
            scope = self._scope_key(payload.get("scope_key", ""))
            row = self._draft(conn, project["id"], scope, lock=True)
            if row is None:
                raise ResourceError("先保存工作副本再生成建议", "draft_missing")
            if type(payload.get("base_draft_revision")) is not int or payload["base_draft_revision"] != row["draft_revision"]:
                raise Conflict("工作稿次已变化，请重新生成建议", "suggestion_stale")
            sha = digest(row["content"])
            if payload.get("base_content_sha256") != sha:
                raise Conflict("所见正文与服务器不同", "suggestion_stale")
            goal = required(payload, "goal")
            if not isinstance(goal, str) or len(goal) > 2000:
                raise ResourceError("建议目标须为不超过2000字符的文字", "invalid_payload")
            identifier = new_id()
            response_id = None
            if payload.get("script_note_id"):
                from .review_store import ReviewRepository
                reviews = ReviewRepository(self)
                _, note = reviews.source(conn, project["id"], payload, current=True)
                if (note["scope_key"] != scope or note["base_draft_revision"] != row["draft_revision"]
                        or not note["line_id"]):
                    raise ResourceError("仅支持准确行批注的局部建议；场级意见交编剧处理", "review_action_mismatch")
                if payload.get("new_attempt") is not True:
                    previous = conn.execute(select(S.script_suggestion_runs).join(S.review_script_runs,
                        (S.review_script_runs.c.project_id == S.script_suggestion_runs.c.project_id) &
                        (S.review_script_runs.c.run_id == S.script_suggestion_runs.c.id)).join(S.review_responses,
                            (S.review_responses.c.project_id == S.review_script_runs.c.project_id) &
                            (S.review_responses.c.id == S.review_script_runs.c.response_id)).where(
                                S.script_suggestion_runs.c.project_id == project["id"],
                                S.review_responses.c.script_note_id == note["id"]).order_by(
                                    S.script_suggestion_runs.c.created_at.desc()).limit(1)).mappings().first()
                    if previous:
                        return {"id": previous["id"], "caller": None, "status": previous["status"]}
                goal = note["body"] + "\n仅返回这行的一条局部建议，不列多个替代方案；保持其余行动、对白和事实。目标：" + str(note["scene_id"]) + "/" + str(note["line_id"])
                response_id = reviews.response(conn, project["id"], payload, "script_suggestions", kw["actor"],
                    limitations="生成建议不解决批注；请比较原文和差异后接受或拒绝。")
            conn.execute(insert(S.script_suggestion_runs).values(project_id=project["id"], id=identifier,
                draft_id=row["id"], scope_key=scope, base_draft_revision=row["draft_revision"],
                base_content_sha256=sha, input_document=row["content"], goal=goal,
                backend=backend, status="running"))
            if response_id:
                conn.execute(insert(S.review_script_runs).values(project_id=project["id"], response_id=response_id, run_id=identifier))
            return {"id": identifier, "caller": caller, "status": "running", "response_id": response_id}
        return self._mutate(project_id, "start_script_suggestion_run", payload, callback=work, **kw)

    def finish_script_suggestion_run(self, project_id, payload, **kw):
        def work(conn, project):
            run = self._one(conn, S.script_suggestion_runs, project["id"], required(payload, "run_id"))
            if run["status"] != "running":
                return {"id": run["id"], "status": run["status"], "result": run["result"]}
            row = self._draft(conn, project["id"], run["scope_key"], lock=True)
            persisted = run["result"]
            if persisted is None:
                raise ResourceError("没有可恢复的宿主结果，不得再次调用生成", "suggestion_result_missing")
            status, error = "completed", persisted.get("error_code")
            suggestions = persisted.get("host_suggestions")
            prepared = []
            if row is None or row["draft_revision"] != run["base_draft_revision"] or digest(row["content"]) != run["base_content_sha256"]:
                status, error = "stale", "suggestion_stale"
            elif error:
                status = "submission_unknown" if error == "suggestion_submission_unknown" else "failed"
            else:
                try:
                    if not isinstance(suggestions, list) or len(suggestions) > 12:
                        raise ResourceError("非法建议数组")
                    seen = set()
                    for suggestion in suggestions:
                        if not isinstance(suggestion, dict):
                            raise ResourceError("非法建议")
                        target = self._suggestion_target(row["content"], suggestion)
                        field = suggestion.get("field", "text")
                        identity = (suggestion["scene_id"], suggestion.get("line_id"), field)
                        review = conn.execute(select(S.review_responses).join(S.review_script_runs,
                            (S.review_script_runs.c.project_id == S.review_responses.c.project_id) &
                            (S.review_script_runs.c.response_id == S.review_responses.c.id)).where(
                                S.review_script_runs.c.project_id == project["id"], S.review_script_runs.c.run_id == run["id"])).mappings().first()
                        if review:
                            note = self._one(conn, S.script_notes, project["id"], review["script_note_id"])
                            anchor = conn.execute(select(S.script_note_anchors).where(S.script_note_anchors.c.project_id == project["id"],
                                S.script_note_anchors.c.note_id == note["id"])).mappings().one()
                            if identity != (note["scene_id"], note["line_id"], anchor["field"]) or suggestion["kind"] != anchor["kind"]:
                                raise ResourceError("建议越出原批注的固定行", "review_scope_mismatch")
                        if identity in seen:
                            raise ResourceError("同一字段不能有重复建议")
                        seen.add(identity)
                        after, reason = required(suggestion, "after_value"), required(suggestion, "reason")
                        before = target.get(field)
                        if (before is not None and not isinstance(before, str)) or not isinstance(after, str) or not isinstance(reason, str) or len(after) > 20000 or len(reason) > 4000:
                            raise ResourceError("建议文字无效")
                        prepared.append(dict(project_id=project["id"], id=new_id(), scope_key=run["scope_key"],
                            base_draft_revision=run["base_draft_revision"], scene_id=suggestion["scene_id"],
                            line_id=suggestion["line_id"], kind=suggestion["kind"], field=field,
                            before_value=before, after_value=after, reason=reason,
                            origin="ai", author=run["backend"]))
                except (ResourceError, KeyError, TypeError):
                    status, error, prepared = "failed", "invalid_suggestions", []
                for suggestion in prepared:
                    conn.execute(insert(S.script_suggestions).values(**suggestion))
                    conn.execute(insert(S.script_run_suggestions).values(project_id=project["id"], run_id=run["id"], suggestion_id=suggestion["id"]))
            result = {"suggestion_ids": [item["id"] for item in prepared], "error_code": error,
                      "host_suggestions": suggestions,
                      "base_draft_revision": run["base_draft_revision"], "base_content_sha256": run["base_content_sha256"]}
            conn.execute(update(S.script_suggestion_runs).where(S.script_suggestion_runs.c.project_id == project["id"],
                S.script_suggestion_runs.c.id == run["id"]).values(status=status, result=result, error_code=error, finished_at=func.now()))
            return {"id": run["id"], "status": status, "result": result}
        # This adds drafts only, never approvals. Check the exact frozen draft
        # under the project lock; unrelated project writes cannot lose a host result.
        kw["expected_revision"] = CURRENT_REVISION
        return self._mutate(project_id, "finish_script_suggestion_run", payload, callback=work, **kw)
