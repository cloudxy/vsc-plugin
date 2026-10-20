"""Fixed subtitle intentions, leased execution and durable unapproved outputs."""
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from vsc.post import remotion_plan as RP
from vsc.post.edit_preview import OPERATIONS, RECIPE_VERSION, position_edit
from . import schema as S
from .values import CURRENT_REVISION, checked_id, clean, digest, new_id


def now():
    return datetime.now(timezone.utc)


class EditPreviewRepository:
    def __init__(self, store):
        self.store = store

    def _resolve(self, conn, p, *, render_id=None, media_id=None, artifact_id=None):
        if sum(bool(v) for v in (render_id, media_id, artifact_id)) != 1:
            raise ResourceError("请选择一个固定样片或渲染计划。", "edit_preview_target_required")
        query = select(S.render_versions).where(S.render_versions.c.project_id == p)
        if render_id:
            query = query.where(S.render_versions.c.id == checked_id(render_id))
        elif media_id:
            self.store._media(conn, p, media_id)
            query = query.where(S.render_versions.c.id.in_(select(S.render_outputs.c.render_id).where(
                S.render_outputs.c.project_id == p, S.render_outputs.c.media_id == checked_id(media_id))))
        else:
            self.store._one(conn, S.artifact_versions, p, artifact_id)
            query = query.where(S.render_versions.c.artifact_id == checked_id(artifact_id))
        render = conn.execute(query.order_by(S.render_versions.c.created_at.desc()).limit(1)).mappings().first()
        if render is None:
            raise ResourceError("当前对象还没有固定渲染样片，暂不能执行字幕位置预览。", "edit_preview_render_missing")
        return dict(render)

    def _baseline(self, conn, p, render, *, expected_draft=None):
        artifact = self.store._one(conn, S.artifact_versions, p, render["artifact_id"])
        newer = set(conn.execute(select(S.artifact_versions.c.id).where(S.artifact_versions.c.project_id == p,
            S.artifact_versions.c.artifact_key == artifact["artifact_key"], S.artifact_versions.c.version > artifact["version"])).scalars())
        preview_drafts = set(conn.execute(select(S.edit_preview_jobs.c.draft_artifact_id).where(
            S.edit_preview_jobs.c.project_id == p, S.edit_preview_jobs.c.source_artifact_id == artifact["id"],
            S.edit_preview_jobs.c.draft_artifact_id.is_not(None))).scalars())
        current = conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
            S.current_artifact_versions.c.project_id == p, S.current_artifact_versions.c.artifact_key == artifact["artifact_key"])).scalar_one_or_none()
        if newer - preview_drafts or current != artifact["id"]:
            raise Conflict("被审字幕计划已有新版本；原意见和旧基线预览保留，请重新定位。", "review_target_stale")
        if not self.store._artifact_approved(conn, p, artifact["id"]):
            raise Conflict("固定渲染计划的批准已失效。", "context_input_invalid")
        try:
            document = json.loads(artifact["document"])
            errors = RP.validate(document)
        except (ValueError, TypeError):
            errors = ["render plan unavailable"]
        if errors:
            raise ResourceError("当前渲染规格缺少可编辑的固定字幕计划。", "edit_preview_plan_missing")
        return artifact, document

    def _inputs(self, conn, p, render, document, outputs=None):
        if outputs is None:
            outputs = [dict(row) for row in conn.execute(select(S.render_caption_inputs).where(
                S.render_caption_inputs.c.project_id == p, S.render_caption_inputs.c.render_id == render["id"])).mappings()]
        inputs = []
        for role in ("clean_master", "subtitle_font"):
            found = [r for r in outputs if r["role"] == role]
            if len(found) != 1:
                raise ResourceError("固定渲染缺少唯一无字幕底片。" if role == "clean_master" else "固定渲染缺少原字幕字体。",
                                    "edit_preview_" + role + "_missing")
            media, gaps = self.store._usable(conn, p, found[0]["media_id"], "edit_preview")
            if gaps or not any(l["storage"] == "local" and l["available"] for l in media["locations"]):
                raise ResourceError("无字幕底片或字体的字节、权利或技术检查已失效。", "edit_preview_input_unavailable")
            inputs.append({**media, "role": role})
        master, font = inputs
        proof = render["parameters"].get("edit_preview_clean_master", {})
        composition = RP.render_plan(document)["composition"]
        if (proof.get("plan_sha256") != RP.document_sha256(document) or proof.get("sha256") != master["sha256"]
                or proof.get("font_sha256") != font["sha256"] or proof.get("subtitles_absent") is not True
                or proof.get("caption_count") != 0 or proof.get("composition") != composition
                or not proof.get("producer") or not proof.get("producer_version")
                or master["modality"] != "video" or master["width"] != composition["width"]
                or master["height"] != composition["height"] or not master["duration_ms"]
                or abs(master["duration_ms"] - composition["duration_in_frames"] * 1000 / RP.frame_rate(composition["fps"])) > 50):
            raise ResourceError("缺少与固定计划、字体及时间基准一致的无字幕底片生产回执。", "edit_preview_clean_master_unverified")
        package = RP.render_plan(document).get("subtitle_package")
        if package:
            from vsc.post import subtitles
            if (package.get("project_id") != p or package.get("timeline_id") != render["timeline_id"]
                    or package.get("package_sha256") != subtitles.content_digest({k:v for k,v in package.items() if k != "package_sha256"})
                    or package.get("status") != "verified" or package.get("gaps")):
                raise ResourceError("字幕包的固定项目、时间线或完整性证据失效。", "edit_preview_package_invalid")
            for snapshot in [package.get("timeline_artifact", {}), *package.get("scripts", []), *package.get("cue_artifacts", [])]:
                actual = self.store._one(conn, S.artifact_versions, p, snapshot.get("id"))
                decision = self.store._one(conn, S.artifact_decisions, p, snapshot.get("approval_decision_id"))
                if (actual["sha256"] != snapshot.get("sha256") or bytes(actual["document"]).decode() != snapshot.get("document_utf8")
                        or decision["artifact_id"] != actual["id"] or decision["outcome"] != "approve"
                        or not self.store._artifact_approved(conn, p, actual["id"])):
                    raise ResourceError("字幕包引用的原始批准快照已失效。", "edit_preview_package_invalid")
            seen_paths = {}
            for source in package.get("audio_sources", []):
                path = source.get("path", "")
                if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ":" in path
                        or any(part in {"..", ".", ""} for part in path.split("/"))
                        or (path in seen_paths and seen_paths[path] != source.get("sha256"))):
                    raise ResourceError("字幕包音频路径不安全或对应不同字节。", "edit_preview_package_path")
                seen_paths[path] = source.get("sha256")
                media, gaps = self.store._usable(conn, p, source.get("media_id"), "edit_preview")
                binding = conn.execute(select(S.timeline_item_media).join(S.timeline_items,
                    (S.timeline_items.c.project_id == S.timeline_item_media.c.project_id) &
                    (S.timeline_items.c.id == S.timeline_item_media.c.item_id)).where(
                        S.timeline_item_media.c.project_id == p, S.timeline_item_media.c.item_id == source.get("item_id"),
                        S.timeline_items.c.timeline_id == render["timeline_id"],
                        S.timeline_item_media.c.media_id == media["id"],
                        S.timeline_item_media.c.binding_decision_id == source.get("binding_decision_id"))).mappings().first()
                if gaps or not binding or media["sha256"] != source.get("sha256") or media["modality"] != "audio":
                    raise ResourceError("字幕包音频与原时间线采用、字节或权利不一致。", "edit_preview_package_audio_invalid")
                inputs.append({**media, "role": "subtitle_audio", "source_path": path,
                    "timeline_item_id": source["item_id"], "binding_decision_id": source["binding_decision_id"],
                    "source_in_frame": binding["source_in_frame"], "source_out_frame": binding["source_out_frame"]})
            if not package.get("audio_sources"):
                raise ResourceError("字幕包缺少固定音频用料。", "edit_preview_package_audio_invalid")
        return inputs

    def capability(self, project_id, **target):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            p = project["id"]
            result = {"revision": project["revision"], "available": False, "reason": None, "cues": [], "operations": list(OPERATIONS)}
            try:
                render = self._resolve(conn, p, **target)
                artifact, document = self._baseline(conn, p, render)
                plan = RP.render_plan(document)
                result.update(render_id=render["id"], artifact_id=artifact["id"], artifact_sha256=artifact["sha256"])
                output = conn.execute(select(S.render_outputs).where(S.render_outputs.c.project_id == p,
                    S.render_outputs.c.render_id == render["id"], ~S.render_outputs.c.role.in_(["clean_master", "subtitle_font"]))
                    .order_by(S.render_outputs.c.id).limit(1)).mappings().first()
                if output is None:
                    raise ResourceError("固定渲染没有可供审阅的带字幕样片。", "edit_preview_output_missing")
                media = self.store._media(conn, p, output["media_id"])
                result.update(render_output_id=output["id"], media_sha256=media["sha256"])
                result["target"] = {key: result[key] for key in ("render_id", "artifact_id", "artifact_sha256", "render_output_id", "media_sha256")}
                result["target"].update(category="subtitle", start_frame=0, end_frame=plan["composition"]["duration_in_frames"])
                result["cues"] = [{"id": s["id"], "text": s["text"], "start_frame": s["from_frame"],
                    "end_frame": s["from_frame"] + s["duration_in_frames"], "layout": s.get("subtitle_style", plan.get("subtitle_style", {}))}
                    for s in plan["segments"] if s["kind"] == "caption"]
                self._inputs(conn, p, render, document)
                result["available"] = bool(result["cues"])
                if not result["available"]:
                    result["reason"] = "该版本没有可定位的字幕 Cue。"
            except ResourceError as error:
                result.update(reason=error.message, code=error.code)
            return clean(result)

    def request(self, project_id, payload, tool, **kw):
        if not isinstance(payload, dict) or set(payload) - {"target", "body", "caption_id", "operation", "artifact_note_id"}:
            raise ResourceError("字幕预览请求包含未知字段。", "invalid_payload")
        def work(conn, project):
            from .review_store import ReviewRepository
            p = project["id"]
            if payload.get("artifact_note_id"):
                _, note = ReviewRepository(self.store).source(conn, p, payload, current=True)
                prior = conn.execute(select(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == p,
                    S.edit_preview_jobs.c.note_id == note["id"]).order_by(S.edit_preview_jobs.c.created_at.desc()).limit(1)).mappings().first()
                if prior:
                    return {"note_id": note["id"], "job_id": prior["id"], "status": prior["status"], "reused": True}
            else:
                target = required(payload, "target")
                allowed = {"artifact_id", "artifact_sha256", "category", "render_id", "render_output_id",
                           "media_sha256", "start_frame", "end_frame"}
                if not isinstance(target, dict) or set(target) != allowed or target.get("category") != "subtitle":
                    raise ResourceError("字幕意见必须固定当前样片、版本及字幕区间。", "invalid_payload")
                body = required(payload, "body")
                if not isinstance(body, str) or not 1 <= len(body.strip()) <= 4000:
                    raise ResourceError("原意见须为 1 至 4000 字。", "invalid_payload")
                note = dict(target, id=new_id(), body=body, author=kw["actor"])
                conn.execute(insert(S.artifact_review_notes).values(project_id=p, **note))
            if note["category"] != "subtitle":
                raise ResourceError("该意见不是字幕修改。", "review_action_mismatch")
            render = self.store._one(conn, S.render_versions, p, note["render_id"])
            artifact, document = self._baseline(conn, p, render)
            status, error, inputs = "queued", None, []
            edit = {"caption_id": payload.get("caption_id") or "", "operation": payload.get("operation") or "",
                    "layout": {}, "diff": {}}
            try:
                edit = position_edit(document, payload.get("caption_id"), payload.get("operation"), note["body"],
                    {"from_frame": note["start_frame"], "duration_in_frames": note["end_frame"]-note["start_frame"]})
                inputs = self._inputs(conn, p, render, document)
                if not tool["available"]:
                    raise ResourceError(tool["reason"] or "后台预览执行器未启动。", "edit_preview_worker_unavailable")
            except (ResourceError, ValueError) as failure:
                status, error = "blocked", getattr(failure, "message", str(failure))
            # A little surrounding footage gives the viewer a useful local cut.
            plan = RP.render_plan(document)
            pad = round(RP.frame_rate(plan["composition"]["fps"]))
            start = max(0, note["start_frame"] - pad)
            end = min(plan["composition"]["duration_in_frames"], note["end_frame"] + pad)
            fingerprint = digest({"source": artifact["sha256"], "edit": edit["diff"], "inputs": [
                {"media_id": i["id"], "sha256": i["sha256"], "role": i["role"], "path": i.get("source_path"),
                 "timeline_item_id": i.get("timeline_item_id"), "binding_decision_id": i.get("binding_decision_id")} for i in inputs],
                "range": [start, end], "recipe": RECIPE_VERSION, "tool": tool["tool_version"]})
            job_id = new_id()
            explanation = "仅调整所选字幕的位置；视频、声音和其他字幕沿用固定版本。修改预览尚未采用。"
            conn.execute(insert(S.edit_preview_jobs).values(project_id=p, id=job_id, note_id=note["id"],
                render_id=render["id"], source_artifact_id=artifact["id"], request_sha256=fingerprint,
                recipe_version=RECIPE_VERSION, tool_version=tool["tool_version"], caption_id=edit["caption_id"],
                operation=edit["operation"], layout=edit["layout"], diff=edit["diff"], start_frame=start, end_frame=end,
                status=status, error=error, explanation=explanation))
            for item in inputs:
                conn.execute(insert(S.edit_preview_inputs).values(project_id=p, id=new_id(), job_id=job_id,
                    media_id=item["id"], blob_id=item["blob_id"], blob_sha256=item["sha256"], role=item["role"],
                    start_frame=item.get("source_in_frame", 0), end_frame=item.get("source_out_frame", plan["composition"]["duration_in_frames"]),
                    source_path=item.get("source_path", ""), timeline_item_id=item.get("timeline_item_id"),
                    binding_decision_id=item.get("binding_decision_id")))
            return {"note_id": note["id"], "job_id": job_id, "status": status, "explanation": explanation, "error": error}
        return self.store._mutate(project_id, "request_edit_preview", payload, callback=work, **kw)

    def _job(self, conn, p, job_id, worker_id, attempt):
        job = self.store._one(conn, S.edit_preview_jobs, p, job_id)
        if (job["status"] != "running" or job["claim_owner"] != worker_id or job["attempt"] != attempt
                or not job["claim_until"] or job["claim_until"] <= now()):
            raise Conflict("字幕预览执行租约已失效。", "edit_preview_lease_lost")
        return job

    def claim(self, worker_id, project_id=None, lease_seconds=300):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ResourceError("字幕预览租约需要 1 至 3600 秒。", "invalid_lease")
        eligible = or_(S.edit_preview_jobs.c.status == "queued", and_(S.edit_preview_jobs.c.status == "running",
            S.edit_preview_jobs.c.claim_until <= now()))
        with self.store.engine.begin() as conn:
            query = select(S.projects).where(S.projects.c.id.in_(select(S.edit_preview_jobs.c.project_id).where(eligible)))
            pending = select(S.project_revisions.c.project_id).where(S.project_revisions.c.action == "migration_import",
                ~S.project_revisions.c.project_id.in_(select(S.project_revisions.c.project_id).where(S.project_revisions.c.action == "migration_activate")))
            query = query.where(~S.projects.c.id.in_(pending))
            if project_id:
                query = query.where(S.projects.c.id == checked_id(project_id))
            project = conn.execute(query.order_by(S.projects.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not project:
                return None
            row = dict(conn.execute(select(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == project["id"], eligible)
                .order_by(S.edit_preview_jobs.c.updated_at, S.edit_preview_jobs.c.id).with_for_update(skip_locked=True).limit(1)).mappings().one())
            if row["attempt"]:
                conn.execute(update(S.edit_preview_attempts).where(S.edit_preview_attempts.c.project_id == project["id"],
                    S.edit_preview_attempts.c.job_id == row["id"], S.edit_preview_attempts.c.attempt == row["attempt"],
                    S.edit_preview_attempts.c.status == "running").values(status="expired", finished_at=now()))
            row.update(status="running", attempt=row["attempt"]+1, claim_owner=worker_id,
                       claim_until=now()+timedelta(seconds=lease_seconds), updated_at=now(), error=None)
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == project["id"],
                S.edit_preview_jobs.c.id == row["id"]).values(**{key: row[key] for key in
                ("status", "attempt", "claim_owner", "claim_until", "updated_at", "error")}))
            attempt_id = new_id()
            conn.execute(insert(S.edit_preview_attempts).values(project_id=project["id"], id=attempt_id,
                job_id=row["id"], attempt=row["attempt"], worker_id=worker_id, status="running"))
            revision = project["revision"]+1
            conn.execute(update(S.projects).where(S.projects.c.id == project["id"]).values(revision=revision))
            conn.execute(insert(S.project_revisions).values(project_id=project["id"], revision=revision,
                actor=worker_id, action="claim_edit_preview", command_key="edit-lease:"+new_id()))
            return clean(dict(row, attempt_id=attempt_id))

    def heartbeat(self, project_id, job_id, worker_id, attempt, lease_seconds):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project_id, lock=True)
            self._job(conn, project_id, job_id, worker_id, attempt)
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == project_id,
                S.edit_preview_jobs.c.id == job_id).values(claim_until=now()+timedelta(seconds=lease_seconds)))

    def prepare(self, job, worker_id):
        from vsc.assets.resource_service import ResourceService
        p, job_id = job["project_id"], job["id"]
        with self.store.engine.connect() as conn:
            fixed = self._job(conn, p, job_id, worker_id, job["attempt"])
            render = self.store._one(conn, S.render_versions, p, fixed["render_id"])
            source, document = self._baseline(conn, p, render, expected_draft=fixed["draft_artifact_id"])
            self._inputs(conn, p, render, document)
        if not fixed["dispatch_id"]:
            service = ResourceService(self.store)
            for retry in range(5):
                try:
                    dispatch = service.process_review(p, {"artifact_note_id": job["note_id"]},
                        _execution={"job_id": job_id, "allowed_operations": ["edit_caption_position", "edit_preview"],
                                    "caption_id": job["caption_id"], "layout": job["layout"], "request_sha256": job["request_sha256"]},
                        actor=worker_id, expected_revision=self.store.get_project(p)["revision"], idempotency_key="edit-dispatch:"+job_id)
                    break
                except Conflict as error:
                    if error.code != "revision_conflict" or retry == 4:
                        raise
            def link(conn, project):
                self._job(conn, p, job_id, worker_id, job["attempt"])
                conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == p,
                    S.edit_preview_jobs.c.id == job_id).values(dispatch_id=dispatch["dispatch_id"]))
                return {"dispatch_id": dispatch["dispatch_id"]}
            self.store._mutate(p, "link_edit_dispatch", {"job_id": job_id, "dispatch_id": dispatch["dispatch_id"]},
                expected_revision=CURRENT_REVISION, idempotency_key="edit-dispatch-link:"+job_id, actor=worker_id, callback=link)
            fixed["dispatch_id"] = dispatch["dispatch_id"]
        dispatch = self.store.get_role_dispatch(p, fixed["dispatch_id"])
        packet = dispatch["packet"]
        expected = packet.get("execution", {})
        if (expected.get("job_id") != job_id or expected.get("request_sha256") != job["request_sha256"]
                or packet["dispatch"]["edit_ownership"] != ["edit-previews/"+job_id+"/draft.json"]):
            raise ResourceError("专业任务未获得该受限字幕编辑的固定归属。", "edit_preview_dispatch_scope")
        binding = {key: dispatch[key] for key in ("role_id", "instance_id", "context_sha256")}
        binding["dispatch_id"] = dispatch["id"]
        self.store.consume_role_dispatch(p, {**binding, "packet": packet}, actor=dispatch["actor"],
            expected_revision=CURRENT_REVISION, idempotency_key="edit-consume:"+job_id)
        def draft(conn, project):
            current = self._job(conn, p, job_id, worker_id, job["attempt"])
            if current["draft_artifact_id"]:
                result = self.store._one(conn, S.artifact_versions, p, current["draft_artifact_id"])
                return {"id": result["id"], "sha256": result["sha256"]}
            source, document = self._baseline(conn, p, render)
            note = self.store._one(conn, S.artifact_review_notes, p, job["note_id"])
            edit = RP.edit_caption_position(document, caption_id=job["caption_id"],
                expected_sha256=RP.document_sha256(document), layout=job["layout"],
                frame_range={"from_frame": note["start_frame"], "duration_in_frames": note["end_frame"]-note["start_frame"]})
            scopes = list(conn.execute(select(S.artifact_object_scopes.c.object_id).where(
                S.artifact_object_scopes.c.project_id == p, S.artifact_object_scopes.c.artifact_id == source["id"])).scalars())
            deps = list(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == source["id"])).scalars())
            result = self.store._create_artifact(conn, project, {"artifact_key": source["artifact_key"],
                "artifact_type": source["artifact_type"], "stage": source["stage"], "document": edit["document"],
                "object_ids": scopes, "project_wide": source["project_wide"], "supersedes_id": source["id"], "dependency_ids": deps,
                "registration_note": "原意见的受限字幕位置草稿，尚未采用"})
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == p,
                S.edit_preview_jobs.c.id == job_id).values(draft_artifact_id=result["id"]))
            return result
        result = self.store._mutate(p, "create_edit_preview_draft", {"job_id": job_id}, expected_revision=CURRENT_REVISION,
            idempotency_key="edit-draft:"+job_id, actor=dispatch["actor"], callback=draft)
        with self.store.engine.connect() as conn:
            artifact = self.store._one(conn, S.artifact_versions, p, result["id"])
            inputs = [dict(r) for r in conn.execute(select(S.edit_preview_inputs).where(
                S.edit_preview_inputs.c.project_id == p, S.edit_preview_inputs.c.job_id == job_id)).mappings()]
            output = self._output(conn, p, job_id)
        return dict(job, dispatch_id=dispatch["id"], draft_artifact_id=artifact["id"], document=json.loads(artifact["document"]),
            draft_sha256=artifact["sha256"], inputs=clean(inputs), output=clean(output),
            master_sha256=next(i["blob_sha256"] for i in inputs if i["role"] == "clean_master"),
            font_sha256=next(i["blob_sha256"] for i in inputs if i["role"] == "subtitle_font"))

    def _output(self, conn, p, job_id):
        row = conn.execute(select(S.edit_preview_outputs, S.media_blobs.c.mime_type, S.media_blobs.c.size_bytes).join(
            S.media_blobs, S.edit_preview_outputs.c.blob_id == S.media_blobs.c.id).join(S.edit_preview_attempts,
                (S.edit_preview_attempts.c.project_id == S.edit_preview_outputs.c.project_id) &
                (S.edit_preview_attempts.c.id == S.edit_preview_outputs.c.attempt_id)).where(
            S.edit_preview_outputs.c.project_id == p, S.edit_preview_outputs.c.job_id == job_id)
            .order_by(S.edit_preview_attempts.c.attempt.desc()).limit(1)).mappings().first()
        return dict(row) if row else None

    def record_output(self, job, worker_id, media, receipt):
        """Persist bytes even after a lease expires; publishing still requires it."""
        p = job["project_id"]
        def work(conn, project):
            attempt = self.store._one(conn, S.edit_preview_attempts, p, job["attempt_id"])
            if attempt["worker_id"] != worker_id or attempt["job_id"] != job["id"] or attempt["attempt"] != job["attempt"]:
                raise Conflict("字幕输出执行身份不符。", "edit_preview_attempt_mismatch")
            fixed = self.store._one(conn, S.edit_preview_jobs, p, job["id"])
            draft = self.store._one(conn, S.artifact_versions, p, fixed["draft_artifact_id"])
            composition = RP.render_plan(json.loads(draft["document"]))["composition"]
            fps = RP.frame_rate(composition["fps"])
            expected_ms = (fixed["end_frame"] - fixed["start_frame"]) / fps * 1000
            pins = {row["role"]: row["blob_sha256"] for row in conn.execute(select(S.edit_preview_inputs).where(
                S.edit_preview_inputs.c.project_id == p, S.edit_preview_inputs.c.job_id == job["id"])).mappings()}
            if (receipt.get("source_sha256") != pins["clean_master"] or receipt.get("font_sha256") != pins["subtitle_font"]
                    or receipt.get("draft_sha256") != draft["sha256"] or receipt.get("recipe_version") != fixed["recipe_version"]
                    or receipt.get("tool_version") != fixed["tool_version"] or receipt.get("full_decode") != "passed"
                    or receipt.get("start_frame") != fixed["start_frame"] or receipt.get("end_frame") != fixed["end_frame"]
                    or media.get("mime_type") != "video/mp4" or media.get("modality") != "video"
                    or (media.get("width"), media.get("height")) != (composition["width"], composition["height"])
                    or not isinstance(media.get("duration_ms"), (int, float))
                    or abs(media["duration_ms"] - expected_ms) > max(60, 1000 / fps)):
                raise ResourceError("字幕预览输出与固定用料或配方不一致。", "edit_preview_output_mismatch")
            key = required(media, "object_key")
            if media.get("storage") != "local" or key.startswith("/") or ".." in key.split("/") or "\\" in key:
                raise ResourceError("字幕预览只能保存至受控本地存储。", "unsafe_location")
            conn.execute(pg_insert(S.media_blobs).values(id=new_id(), sha256=media["sha256"], size_bytes=media["size_bytes"],
                mime_type=media["mime_type"], width=media["width"], height=media["height"], duration_ms=media["duration_ms"],
                sample_rate=media.get("sample_rate"), probe=media.get("probe", {})).on_conflict_do_nothing(index_elements=[S.media_blobs.c.sha256]))
            blob = conn.execute(select(S.media_blobs).where(S.media_blobs.c.sha256 == media["sha256"])).mappings().one()
            if blob["size_bytes"] != media["size_bytes"]:
                raise Conflict("预览字节摘要与大小冲突。", "blob_mismatch")
            conn.execute(pg_insert(S.blob_locations).values(id=new_id(), blob_id=blob["id"], storage="local", object_key=key)
                .on_conflict_do_nothing(index_elements=[S.blob_locations.c.blob_id, S.blob_locations.c.storage, S.blob_locations.c.object_key]))
            identifier = new_id()
            conn.execute(insert(S.edit_preview_outputs).values(project_id=p, id=identifier, job_id=job["id"],
                attempt_id=job["attempt_id"], blob_id=blob["id"], blob_sha256=blob["sha256"],
                start_frame=fixed["start_frame"], end_frame=fixed["end_frame"], duration_ms=media["duration_ms"], receipt=receipt))
            conn.execute(update(S.edit_preview_attempts).where(S.edit_preview_attempts.c.project_id == p,
                S.edit_preview_attempts.c.id == job["attempt_id"]).values(receipt=receipt))
            return {"output_id": identifier}
        return self.store._mutate(p, "record_edit_preview_output", {"job_id": job["id"], "attempt": job["attempt"],
            "sha256": media["sha256"], "receipt": receipt}, expected_revision=CURRENT_REVISION,
            idempotency_key="edit-output:"+job["attempt_id"], actor=worker_id, callback=work)

    def finish(self, job, worker_id):
        p = job["project_id"]
        with self.store.engine.connect() as conn:
            fixed = self._job(conn, p, job["id"], worker_id, job["attempt"])
            output = self._output(conn, p, job["id"])
            if not output:
                raise ResourceError("没有可回看的实际字幕预览。", "edit_preview_output_missing")
            render = self.store._one(conn, S.render_versions, p, fixed["render_id"])
            self._baseline(conn, p, render, expected_draft=fixed["draft_artifact_id"])
            self._inputs(conn, p, render, json.loads(self.store._one(conn, S.artifact_versions, p, fixed["source_artifact_id"])["document"]))
        dispatch = self.store.get_role_dispatch(p, fixed["dispatch_id"])
        packet = dispatch["packet"]
        result = {"role_id": dispatch["role_id"], "role_sha256": dispatch["role_sha256"],
            "context_id": dispatch["context_id"], "context_sha256": dispatch["context_sha256"],
            "dispatch_id": dispatch["id"], "instance_id": dispatch["instance_id"],
            "result_refs": [{"kind": "artifact", "id": fixed["draft_artifact_id"], "sha256": job["draft_sha256"]}],
            "memory_proposals": [], "session_summary": "已生成所选字幕位置草稿及可播放预览；请从原意见回看，尚未采用。"}
        binding = {key: dispatch[key] for key in ("role_id", "instance_id", "context_sha256")}
        def fence(conn, project):
            current = self._job(conn, p, job["id"], worker_id, job["attempt"])
            render = self.store._one(conn, S.render_versions, p, current["render_id"])
            _, document = self._baseline(conn, p, render, expected_draft=current["draft_artifact_id"])
            self._inputs(conn, p, render, document)
        self.store.return_role_dispatch(p, {**binding, "dispatch_id": dispatch["id"], "return_key": "edit-preview:"+job["id"],
            "result": result}, expected_revision=CURRENT_REVISION, idempotency_key="edit-return:"+job["id"],
            actor=dispatch["actor"], _fence=fence)
        return self._end(job, worker_id, "succeeded")

    def _end(self, job, worker_id, status, error=None):
        p = job["project_id"]
        def work(conn, project):
            self._job(conn, p, job["id"], worker_id, job["attempt"])
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == p,
                S.edit_preview_jobs.c.id == job["id"]).values(status=status, error=error, claim_until=None,
                    claim_owner=None, updated_at=now()))
            conn.execute(update(S.edit_preview_attempts).where(S.edit_preview_attempts.c.project_id == p,
                S.edit_preview_attempts.c.id == job["attempt_id"]).values(status=status, error=error, finished_at=now()))
            return {"id": job["id"], "note_id": job["note_id"], "status": status, "error": error}
        return self.store._mutate(p, "finish_edit_preview", {"job_id": job["id"], "attempt": job["attempt"], "status": status, "error": error},
            expected_revision=CURRENT_REVISION, idempotency_key="edit-finish:"+job["attempt_id"]+":"+status, actor=worker_id, callback=work)

    def fail(self, job, worker_id, error):
        code = getattr(error, "code", type(error).__name__)
        message = getattr(error, "message", "本地字幕预览执行失败。")
        if code == "edit_preview_lease_lost":
            return {"id": job["id"], "status": "lease_lost"}
        status = "stale" if code in {"review_target_stale", "context_input_invalid", "dispatch_expired", "dispatch_stale", "context_memory_invalid"} else "failed"
        try:
            return self._end(job, worker_id, status, code+": "+message)
        except Conflict as conflict:
            if conflict.code == "edit_preview_lease_lost":
                return {"id": job["id"], "status": "lease_lost"}
            raise

    def list(self, project_id, artifact_note_id=None):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            query = select(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id == project["id"])
            if artifact_note_id:
                self.store._one(conn, S.artifact_review_notes, project["id"], artifact_note_id)
                query = query.where(S.edit_preview_jobs.c.note_id == checked_id(artifact_note_id))
            rows = []
            for row in conn.execute(query.order_by(S.edit_preview_jobs.c.created_at.desc())).mappings():
                output = self._output(conn, project["id"], row["id"])
                if output:
                    output.pop("blob_id", None)
                    output["content_url"] = "/api/v1/projects/"+project["id"]+"/edit-previews/"+row["id"]+"/content"
                item = {key: value for key, value in row.items() if key not in {"claim_owner", "claim_until"}}
                rows.append(dict(item, output=output, adopted=False))
            return clean({"revision": project["revision"], "items": rows})

    def retry(self, project_id, job_id, **kw):
        def work(conn, project):
            p = project["id"]
            job = self.store._one(conn, S.edit_preview_jobs, p, job_id)
            if job["status"] != "failed":
                raise Conflict("仅可重试失败的原字幕任务；旧基线结果需要重新评估。", "edit_preview_not_failed")
            render = self.store._one(conn, S.render_versions, p, job["render_id"])
            _, document = self._baseline(conn, p, render)
            self._inputs(conn, p, render, document)
            if job["dispatch_id"]:
                dispatch = self.store._one(conn, S.role_dispatches, p, job["dispatch_id"])
                if dispatch["expires_at"] <= now():
                    raise Conflict("原专业任务已到期，请重新定位当前版本。", "dispatch_expired")
            conn.execute(update(S.edit_preview_jobs).where(S.edit_preview_jobs.c.project_id==p,
                S.edit_preview_jobs.c.id==job_id).values(status="queued", error=None, updated_at=now()))
            return {"id": job_id, "note_id": job["note_id"], "status": "queued"}
        return self.store._mutate(project_id,"retry_edit_preview",{"job_id":job_id},callback=work,**kw)

    def content(self, project_id, job_id):
        with self.store.engine.connect() as conn:
            self.store._project(conn, project_id)
            self.store._one(conn, S.edit_preview_jobs, project_id, job_id)
            output = self._output(conn, project_id, job_id)
            if not output:
                raise NotFound("该字幕修改尚未生成可播放预览。")
            locations = [dict(r) for r in conn.execute(select(S.blob_locations).where(
                S.blob_locations.c.blob_id == output["blob_id"], S.blob_locations.c.available.is_(True))).mappings()]
            return clean(dict(output, locations=locations))
