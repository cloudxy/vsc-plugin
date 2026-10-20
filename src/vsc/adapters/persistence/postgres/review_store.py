"""Original review history and typed links, sharing the resource transaction.

This repository never owns a second production state. Displayed progress comes
from the linked suggestion run, artifact decisions, jobs and role returns.
"""
import json
from sqlalchemy import func, insert, select

from vsc.assets.resource_service import Conflict, ResourceError, required
from . import schema as S
from .values import checked_id, clean, digest, new_id


SOURCES = {"script_note_id": S.script_notes, "media_review_id": S.media_reviews,
           "artifact_note_id": S.artifact_review_notes}
ROLES = {"subtitle": "remotion-composer", "edit": "editor", "director": "director", "asset": "asset-director"}


class ReviewRepository:
    def __init__(self, store):
        self.store = store

    def targets(self, project_id, *, artifact_id=None, media_id=None):
        with self.store.engine.connect() as conn:
            p = checked_id(project_id)
            self.store._project(conn, p)
            items = []
            if artifact_id:
                artifact = self.store._one(conn, S.artifact_versions, p, artifact_id)
                for table, field, category, label_field in ((S.shot_design_units, "design_unit_id", "director", "design_key"),
                        (S.asset_spec_versions, "spec_version_id", "asset", "variant_key"),
                        (S.asset_use_instances, "instance_id", "asset", "label")):
                    for row in conn.execute(select(table).where(table.c.project_id == p, table.c.artifact_id == artifact["id"])).mappings():
                        items.append({"label": row[label_field], "target": {"artifact_id": artifact["id"],
                            "artifact_sha256": artifact["sha256"], "category": category, field: row["id"]}})
            if media_id:
                media = self.store._media(conn, p, media_id)
                for output in conn.execute(select(S.render_outputs).where(S.render_outputs.c.project_id == p,
                        S.render_outputs.c.media_id == media["id"])).mappings():
                    render = self.store._one(conn, S.render_versions, p, output["render_id"])
                    timeline = self.store._one(conn, S.timeline_versions, p, render["timeline_id"])
                    artifact = self.store._one(conn, S.artifact_versions, p, render["artifact_id"])
                    duration = conn.execute(select(func.max(S.timeline_items.c.offset_frame + S.timeline_items.c.duration_frames)).where(
                        S.timeline_items.c.project_id == p, S.timeline_items.c.timeline_id == timeline["id"])).scalar_one()
                    if not duration:
                        continue
                    target = {"artifact_id": artifact["id"], "artifact_sha256": artifact["sha256"], "render_id": render["id"],
                        "render_output_id": output["id"], "media_sha256": media["sha256"], "start_frame": 0, "end_frame": duration}
                    items.append({"label": "成片节奏与声音衔接", "fps_num": timeline["fps_num"], "fps_den": timeline["fps_den"],
                        "duration_frames": duration, "target": dict(target, category="edit")})
                    items.append({"label": "字幕位置与排版", "fps_num": timeline["fps_num"], "fps_den": timeline["fps_den"],
                        "duration_frames": duration, "target": dict(target, category="subtitle")})
            return clean(items)

    def source(self, conn, p, payload, *, current=False):
        fields = [field for field in SOURCES if payload.get(field)]
        if len(fields) != 1:
            raise ResourceError("须绑定一条原批注、候选审查或文案意见", "review_source_required")
        field = fields[0]
        note = self.store._one(conn, SOURCES[field], p, payload[field])
        if field == "script_note_id":
            note["anchor"] = conn.execute(select(S.script_note_anchors).where(
                S.script_note_anchors.c.project_id == p, S.script_note_anchors.c.note_id == note["id"])).mappings().first()
            if note["anchor"]:
                note["anchor"] = dict(note["anchor"])
            if current:
                draft = self.store._draft(conn, p, note["scope_key"], lock=True)
                if (not draft or not note["anchor"] or draft["draft_revision"] != note["base_draft_revision"]
                        or digest(draft["content"]) != note["base_content_sha256"]):
                    raise Conflict("原批注的稿次或文字位置已变化；原话保留，请重新定位", "review_target_stale")
            note["body_text"] = note["body"]
        elif field == "media_review_id":
            candidate = self.store._one(conn, S.binding_candidates, p, note["candidate_id"])
            slot = self.store._one(conn, S.binding_slots, p, candidate["slot_id"])
            note["media"] = self.store._media(conn, p, candidate["media_id"])
            note["slot"] = slot
            note["body_text"] = note["reason"]
        else:
            if note.get("render_id"):
                render = self.store._one(conn, S.render_versions, p, note["render_id"])
                timeline = self.store._one(conn, S.timeline_versions, p, render["timeline_id"])
                note["range_seconds"] = {"start": note["start_frame"] * timeline["fps_den"] / timeline["fps_num"],
                                         "end": note["end_frame"] * timeline["fps_den"] / timeline["fps_num"]}
            if current:
                artifact = self.store._one(conn, S.artifact_versions, p, note["artifact_id"])
                latest = conn.execute(select(func.max(S.artifact_versions.c.version)).where(
                    S.artifact_versions.c.project_id == p,
                    S.artifact_versions.c.artifact_key == artifact["artifact_key"])).scalar_one()
                if latest != artifact["version"]:
                    if note["category"] == "subtitle" and note.get("render_id"):
                        from .edit_preview_store import EditPreviewRepository
                        render = self.store._one(conn, S.render_versions, p, note["render_id"])
                        EditPreviewRepository(self.store)._baseline(conn, p, render)
                    else:
                        raise Conflict("被审文案已有新版本；原时码与意见保留，请重新定位", "review_target_stale")
            note["body_text"] = note["body"]
        return field, note

    def response(self, conn, p, payload, action, actor, *, explanation=None, limitations=""):
        field, note = self.source(conn, p, payload, current=True)
        identifier = new_id()
        conn.execute(insert(S.review_responses).values(project_id=p, id=identifier, **{field: note["id"]},
            action=action, explanation=explanation or "按原意见提出局部修改：" + note["body_text"],
            preserve="保持原身份、范围、其他镜头与原批准；结果仍由使用者回看决定。",
            limitations=limitations, author=actor))
        return identifier

    def add_artifact_note(self, project_id, payload, **kw):
        allowed = {"artifact_id", "artifact_sha256", "category", "body", "design_unit_id", "spec_version_id",
                   "instance_id", "render_id", "render_output_id", "media_sha256", "start_frame", "end_frame"}
        if set(payload) - allowed:
            raise ResourceError("意见包含未知字段", "invalid_payload")
        body = required(payload, "body")
        if not isinstance(body, str) or not body.strip() or len(body) > 4000:
            raise ResourceError("原意见须为1至4000字的文字", "invalid_payload")
        def work(conn, project):
            identifier = new_id()
            conn.execute(insert(S.artifact_review_notes).values(project_id=project["id"], id=identifier,
                author=kw["actor"], **payload))
            return {"id": identifier}
        return self.store._mutate(project_id, "add_artifact_review_note", payload, callback=work, **kw)

    def read(self, project_id, *, script_note_id=None, media_review_id=None, artifact_note_id=None,
             artifact_id=None, media_id=None):
        if sum(value is not None for value in (script_note_id, media_review_id, artifact_note_id, artifact_id, media_id)) != 1:
            raise ResourceError("请选择一个原意见或固定对象回看", "review_source_required")
        with self.store.engine.connect() as conn:
            p = checked_id(project_id)
            project = self.store._project(conn, p)
            if artifact_id:
                self.store._one(conn, S.artifact_versions, p, artifact_id)
                notes = [("artifact_note_id", dict(row)) for row in conn.execute(select(S.artifact_review_notes).where(
                    S.artifact_review_notes.c.project_id == p, S.artifact_review_notes.c.artifact_id == checked_id(artifact_id))
                    .order_by(S.artifact_review_notes.c.created_at)).mappings()]
            elif media_id:
                self.store._media(conn, p, media_id)
                query = select(S.media_reviews).join(S.binding_candidates,
                    (S.binding_candidates.c.project_id == S.media_reviews.c.project_id) &
                    (S.binding_candidates.c.id == S.media_reviews.c.candidate_id)).where(
                        S.media_reviews.c.project_id == p, S.binding_candidates.c.media_id == checked_id(media_id))
                notes = [("media_review_id", dict(row)) for row in conn.execute(query.order_by(S.media_reviews.c.created_at)).mappings()]
                notes.extend(("artifact_note_id", dict(row)) for row in conn.execute(select(S.artifact_review_notes).join(
                    S.render_outputs, (S.render_outputs.c.project_id == S.artifact_review_notes.c.project_id) &
                    (S.render_outputs.c.id == S.artifact_review_notes.c.render_output_id)).where(
                        S.artifact_review_notes.c.project_id == p, S.render_outputs.c.media_id == checked_id(media_id))).mappings())
            else:
                field, note = self.source(conn, p, {"script_note_id": script_note_id, "media_review_id": media_review_id,
                                                    "artifact_note_id": artifact_note_id})
                notes = [(field, note)]
            items = []
            for field, note in notes:
                _, note = self.source(conn, p, {field: note["id"]})
                entry = {"source": {field: note["id"]}, "body": note.get("body", note.get("reason")), "note": note,
                         "responses": []}
                if field == "artifact_note_id":
                    from .edit_preview_store import EditPreviewRepository
                    entry["edit_previews"] = EditPreviewRepository(self.store).list(p, note["id"])["items"]
                if field == "media_review_id":
                    entry["source_jobs"] = [dict(row) for row in conn.execute(select(S.generation_jobs.c.id,
                        S.generation_jobs.c.shot_id, S.generation_jobs.c.purpose, S.generation_jobs.c.modality).join(S.job_outputs,
                            (S.job_outputs.c.project_id == S.generation_jobs.c.project_id) &
                            (S.job_outputs.c.job_id == S.generation_jobs.c.id)).where(S.generation_jobs.c.project_id == p,
                                S.job_outputs.c.media_id == note["media"]["id"])).mappings()]
                for response in conn.execute(select(S.review_responses).where(S.review_responses.c.project_id == p,
                        S.review_responses.c[field] == note["id"]).order_by(S.review_responses.c.created_at)).mappings():
                    value = dict(response, runs=[], proposals=[], dispatches=[])
                    run_ids = conn.execute(select(S.review_script_runs.c.run_id).where(S.review_script_runs.c.project_id == p,
                        S.review_script_runs.c.response_id == response["id"])).scalars()
                    for run_id in run_ids:
                        run = self.store._one(conn, S.script_suggestion_runs, p, run_id)
                        run.pop("input_document", None)
                        suggestions = []
                        for suggestion_id in conn.execute(select(S.script_run_suggestions.c.suggestion_id).where(
                                S.script_run_suggestions.c.project_id == p, S.script_run_suggestions.c.run_id == run_id)).scalars():
                            suggestion = self.store._one(conn, S.script_suggestions, p, suggestion_id)
                            suggestion["decisions"] = [dict(row) for row in conn.execute(select(S.script_suggestion_decisions).where(
                                S.script_suggestion_decisions.c.project_id == p,
                                S.script_suggestion_decisions.c.suggestion_id == suggestion_id).order_by(
                                    S.script_suggestion_decisions.c.created_at, S.script_suggestion_decisions.c.id)).mappings()]
                            suggestions.append(suggestion)
                        value["runs"].append(dict(run, suggestions=suggestions))
                    for artifact_id in conn.execute(select(S.review_proposals.c.artifact_id).where(
                            S.review_proposals.c.project_id == p, S.review_proposals.c.response_id == response["id"])).scalars():
                        artifact = self.store._one(conn, S.artifact_versions, p, artifact_id)
                        jobs = []
                        for job in conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id == p,
                                S.generation_jobs.c.run_version_id == artifact_id)).mappings():
                            outputs = [dict(row) for row in conn.execute(select(S.job_outputs).where(S.job_outputs.c.project_id == p,
                                S.job_outputs.c.job_id == job["id"])).mappings()]
                            jobs.append({"id": job["id"], "status": job["status"], "outputs": outputs})
                        value["proposals"].append({"id": artifact_id, "sha256": artifact["sha256"],
                            "artifact_type": artifact["artifact_type"], "jobs": jobs,
                            "approved": self.store._approval_map(conn, p).get(artifact_id, False)})
                    for dispatch_id in conn.execute(select(S.review_dispatches.c.dispatch_id).where(
                            S.review_dispatches.c.project_id == p, S.review_dispatches.c.response_id == response["id"])).scalars():
                        dispatch = self.store._one(conn, S.role_dispatches, p, dispatch_id)
                        returns = []
                        for returned in conn.execute(select(S.dispatch_returns).where(S.dispatch_returns.c.project_id == p,
                                S.dispatch_returns.c.dispatch_id == dispatch_id).order_by(S.dispatch_returns.c.created_at,
                                    S.dispatch_returns.c.id)).mappings():
                            artifacts = [dict(row) for row in conn.execute(select(S.artifact_versions.c.id, S.artifact_versions.c.sha256,
                                S.artifact_versions.c.artifact_type, S.artifact_versions.c.artifact_key).join(S.dispatch_result_artifacts,
                                    (S.dispatch_result_artifacts.c.project_id == S.artifact_versions.c.project_id) &
                                    (S.dispatch_result_artifacts.c.artifact_id == S.artifact_versions.c.id)).where(
                                        S.dispatch_result_artifacts.c.project_id == p,
                                        S.dispatch_result_artifacts.c.return_id == returned["id"])).mappings()]
                            for artifact in artifacts:
                                artifact["previews"] = [dict(row) for row in conn.execute(select(S.render_outputs.c.media_id,
                                    S.render_outputs.c.render_id, S.render_outputs.c.role, S.media_items.c.modality,
                                    S.media_blobs.c.sha256).select_from(S.render_versions.join(S.render_outputs,
                                        (S.render_outputs.c.project_id == S.render_versions.c.project_id) &
                                        (S.render_outputs.c.render_id == S.render_versions.c.id)).join(S.media_items,
                                            (S.media_items.c.project_id == S.render_outputs.c.project_id) &
                                            (S.media_items.c.id == S.render_outputs.c.media_id)).join(S.media_blobs,
                                                S.media_blobs.c.id == S.media_items.c.blob_id)).where(
                                                    S.render_versions.c.project_id == p,
                                                    S.render_versions.c.artifact_id == artifact["id"],
                                                    S.media_items.c.modality.in_(["video", "audio", "image"]))).mappings()]
                            returns.append({"id": returned["id"], "summary": returned["summary"], "artifacts": artifacts})
                        value["dispatches"].append({"id": dispatch_id, "role": dispatch["role_id"], "returns": returns,
                            "message": "已有专业返回，请回看实际产物" if any(r["artifacts"] for r in returns)
                                       else "已派给专业角色，尚无实际结果；意见保持待处理"})
                    entry["responses"].append(value)
                items.append(entry)
            return clean({"project_id": p, "revision": project["revision"], "items": items})

    def validate_local(self, conn, p, payload, value):
        """The reviewed audio must be an output of exactly the source being redone."""
        if not payload.get("media_review_id"):
            return
        _, note = self.source(conn, p, payload, current=True)
        if payload["action"] not in {"redo_sound", "resample"}:
            raise ResourceError("这条媒体意见不适用于实例规格替换", "review_action_mismatch")
        media = note["media"]
        outputs = set(conn.execute(select(S.job_outputs.c.job_id).where(S.job_outputs.c.project_id == p,
            S.job_outputs.c.media_id == media["id"])).scalars())
        targets = value["targets"]
        if not outputs or not any(target["id"] in outputs for target in targets):
            raise Conflict("所见候选已不是本次操作的固定来源，请重新定位", "review_target_stale")
        if payload["action"] == "redo_sound" and (media["modality"] != "audio" or
                any(target["shot_id"] != payload["shot_id"] or target["modality"] != "audio" for target in targets)):
            raise ResourceError("只重做本镜声音需要固定音频候选与同镜用途", "review_action_mismatch")
        value["review"] = {"media_review_id": note["id"], "media_id": media["id"], "sha256": media["sha256"],
                           "body": note["body_text"]}
