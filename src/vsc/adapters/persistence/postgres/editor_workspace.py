"""Project-locked editorial drafts and leased, recoverable local exports."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, insert, update, and_, or_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.post.edit_workspace import FORMAT, RECIPE, validate_edit
from . import schema as S
from .values import CURRENT_REVISION, checked_id, new_id, clean, digest


class EditorWorkspaceRepository:
    def __init__(self, store):
        self.store = store

    def candidates(self, project_id, episode_id, *, offset=0, limit=48):
        """Page original video candidates by episode/shot, including unselected takes."""
        from sqlalchemy import union
        from .project_management import management_object_guard, hidden_object_ids
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
            raise ResourceError('候选分页需要非负起点及 1–100 条上限','invalid_page')
        with self.store.engine.connect() as conn:
            project=self.store._project(conn,project_id);p=project['id'];episode_id=checked_id(episode_id)
            self.store._one(conn,S.episodes,p,episode_id);management_object_guard(conn,p,episode_id)
            order=(S.scenes.c.ordinal,S.scenes.c.id,S.sequences.c.ordinal,S.sequences.c.id,S.shots.c.ordinal,S.shots.c.id)
            shots=select(S.shots.c.id.label('shot_id'),S.creative_objects.c.title.label('shot_title'),S.creative_objects.c.display_code.label('shot_code'),func.row_number().over(order_by=order).label('shot_number')).join(S.creative_objects,and_(S.creative_objects.c.project_id==p,S.creative_objects.c.id==S.shots.c.id)).join(S.sequences,and_(S.sequences.c.project_id==p,S.sequences.c.id==S.shots.c.parent_id)).join(S.scenes,and_(S.scenes.c.project_id==p,S.scenes.c.id==S.sequences.c.parent_id)).where(S.shots.c.project_id==p,S.scenes.c.parent_id==episode_id,S.shots.c.id.not_in(hidden_object_ids(conn,p))).subquery()
            bindings=select(S.binding_slots.c.target_object_id.label('shot_id'),S.binding_candidates.c.media_id).join(S.binding_candidates,and_(S.binding_candidates.c.project_id==p,S.binding_candidates.c.slot_id==S.binding_slots.c.id)).where(S.binding_slots.c.project_id==p,S.binding_slots.c.role=='video_take')
            outputs=select(S.generation_jobs.c.shot_id,S.job_outputs.c.media_id).join(S.job_outputs,and_(S.job_outputs.c.project_id==p,S.job_outputs.c.job_id==S.generation_jobs.c.id)).where(S.generation_jobs.c.project_id==p,S.generation_jobs.c.modality=='video',S.generation_jobs.c.status=='succeeded',S.generation_jobs.c.purpose!='depth')
            depth=select(S.job_outputs.c.media_id).join(S.generation_jobs,and_(S.generation_jobs.c.project_id==p,S.generation_jobs.c.id==S.job_outputs.c.job_id)).where(S.job_outputs.c.project_id==p,S.generation_jobs.c.purpose=='depth')
            sources=union(bindings,outputs).subquery()
            query=self.store._media_query(p).add_columns(shots).join(sources,sources.c.media_id==S.media_items.c.id).join(shots,shots.c.shot_id==sources.c.shot_id).where(S.media_items.c.modality=='video',S.media_items.c.id.not_in(depth))
            total=conn.scalar(select(func.count()).select_from(query.subquery()))
            rows=[dict(r) for r in conn.execute(query.order_by(shots.c.shot_number,S.media_items.c.created_at.desc(),S.media_items.c.id).offset(offset).limit(limit)).mappings()]
            items=[]
            for row in rows:
                selection=self.store._working_selection(conn,p,row['shot_id'],'video')
                selected_media=self.store._one(conn,S.binding_candidates,p,selection['candidate_id'])['media_id'] if selection and selection['candidate_id'] else None
                selected=selected_media==row['id'];duration=row.get('duration_ms')
                item={key:row.get(key) for key in ('id','name','modality','duration_ms','width','height','created_at','shot_id','shot_title','shot_code','shot_number')}
                item.update(media_id=row['id'],selected=selected,working_selection_version_id=selection['id'] if selected else None,
                    trim_in_ms=selection['trim_in_ms'] if selected else 0,trim_out_ms=selection['trim_out_ms'] if selected else duration,
                    content_url=f'/api/v1/projects/{p}/media/{row["id"]}/content',can_add=bool(duration and duration>0))
                if not item['can_add']:item['disabled_reason']='源视频尚无已验证时长，请先完成媒体检查'
                items.append(item)
            return clean(dict(items=items,total=total,next_offset=offset+len(items) if offset+len(items)<total else None,episode_id=episode_id,project_revision=project['revision']))

    def seed(self, project_id, episode_id):
        """Use working choices and trims in shot order, falling back to legacy adoption."""
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            p = project["id"]
            from .project_management import management_object_guard, hidden_object_ids
            management_object_guard(conn,p,episode_id)
            self.store._one(conn, S.episodes, p, episode_id)
            shots = conn.execute(select(S.shots).join(S.sequences, and_(S.sequences.c.project_id==p,
                S.sequences.c.id==S.shots.c.parent_id)).join(S.scenes, and_(S.scenes.c.project_id==p,
                S.scenes.c.id==S.sequences.c.parent_id)).where(S.shots.c.project_id==p, S.scenes.c.parent_id==episode_id)
                .order_by(S.scenes.c.ordinal, S.scenes.c.id, S.sequences.c.ordinal, S.sequences.c.id,
                          S.shots.c.ordinal, S.shots.c.id)).mappings().all()
            hidden=hidden_object_ids(conn,p)
            shots=[shot for shot in shots if shot['id'] not in hidden]
            document = {"format": FORMAT, "width": 720, "height": 1280, "fps": 24,
                        "clips": [], "audio": [], "captions": []}
            gaps, decisions = [], []
            for shot in shots:
                working = conn.execute(select(S.working_selection_versions,
                    S.binding_candidates.c.media_id).join(S.current_working_selections, and_(
                        S.current_working_selections.c.project_id == p,
                        S.current_working_selections.c.selection_version_id == S.working_selection_versions.c.id))
                    .outerjoin(S.binding_candidates, and_(S.binding_candidates.c.project_id == p,
                        S.binding_candidates.c.id == S.working_selection_versions.c.candidate_id))
                    .where(S.working_selection_versions.c.project_id == p,
                        S.working_selection_versions.c.shot_id == shot['id'],
                        S.working_selection_versions.c.output_kind == 'video')).mappings().first()
                if working:
                    if not working['candidate_id']:
                        gaps.append({'shot_id': shot['id'], 'reason': '当前镜头已清空视频选择'})
                        continue
                    from .workbench_generation import working_media
                    media, reasons = working_media(self.store, conn, p, working['media_id'], 'video_take')
                    if reasons:
                        gaps.append({'shot_id': shot['id'], 'reason': '当前所选视频不可用', 'details': reasons})
                        continue
                    start = round(working['trim_in_ms'] * document['fps'] / 1000)
                    end = round(working['trim_out_ms'] * document['fps'] / 1000)
                    if end <= start:
                        gaps.append({'shot_id': shot['id'], 'reason': '裁剪长度不足一帧'})
                        continue
                    document['clips'].append({'id': 'shot-' + shot['id'], 'shot_id': shot['id'],
                        'media_id': media['id'], 'in_frame': start, 'out_frame': end, 'volume': 1,
                        'muted': False, 'working_selection_version_id': working['id']})
                    decisions.append({'shot_id': shot['id'], 'working_selection_version_id': working['id'],
                        'sha256': media['sha256']})
                    continue
                rows = conn.execute(select(S.binding_candidates.c.media_id, S.current_bindings.c.decision_id)
                    .select_from(S.binding_slots.join(S.current_bindings, and_(S.current_bindings.c.project_id==p,
                        S.current_bindings.c.slot_id==S.binding_slots.c.id)).join(S.binding_candidates,
                        and_(S.binding_candidates.c.project_id==p, S.binding_candidates.c.id==S.current_bindings.c.candidate_id)))
                    .where(S.binding_slots.c.project_id==p, S.binding_slots.c.target_object_id==shot["id"],
                           S.binding_slots.c.role=="video_take")).mappings().all()
                if len(rows) != 1:
                    gaps.append({"shot_id": shot["id"], "reason": "缺少已采用的视频" if not rows else "存在多个已采用视频，请明确本次使用片段"})
                    continue
                media, reasons = self.store._usable(conn, p, rows[0]["media_id"], "video_take")
                if media["modality"] != "video" or reasons or not media.get("duration_ms"):
                    gaps.append({"shot_id": shot["id"], "reason": "已采用素材当前不可用", "details": reasons})
                    continue
                planned = shot.get("duration_ms") or media["duration_ms"]
                if media["duration_ms"] + 1000 / 24 < planned:
                    gaps.append({"shot_id": shot["id"], "reason": "已采用视频短于镜头时长，请先裁定本镜长度"})
                    continue
                frames = max(1, round(min(planned, media["duration_ms"]) * 24 / 1000))
                document["clips"].append({"id": "shot-"+shot["id"], "shot_id": shot["id"], "media_id": media["id"],
                                          "in_frame": 0, "out_frame": frames, "volume": 1, "muted": False})
                decisions.append({"shot_id": shot["id"], "decision_id": rows[0]["decision_id"], "sha256": media["sha256"]})
            validate_edit(document)
            return clean({"document": document, "gaps": gaps, "selection_refs": decisions,
                          "project_revision": project["revision"], "shot_count": len(shots),
                          "dynamic_frames": sum(c["out_frame"] - c['in_frame'] for c in document["clips"])})

    def get(self, project_id, episode_id):
        with self.store.engine.connect() as conn:
            p = self.store._project(conn, project_id)
            from .project_management import management_object_guard
            management_object_guard(conn,p['id'],episode_id)
            self.store._one(conn, S.episodes, p["id"], episode_id)
            row = conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id == p["id"],
                S.edit_workspaces.c.episode_id == checked_id(episode_id))).mappings().first()
            if not row:
                return {"project_id": p["id"], "project_revision": p["revision"], "episode_id": episode_id,
                        "workspace": None, "history": [], "renders": []}
            versions = conn.execute(select(S.edit_revisions).where(S.edit_revisions.c.project_id == p["id"],
                S.edit_revisions.c.workspace_id == row["id"]).order_by(S.edit_revisions.c.version.desc())).mappings().all()
            current = next(v for v in versions if v["id"] == row["current_version_id"])
            jobs = conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id == p["id"],
                S.edit_render_jobs.c.edit_version_id.in_([v["id"] for v in versions])).order_by(S.edit_render_jobs.c.created_at.desc())).mappings().all()
            result = clean({"project_id": p["id"], "project_revision": p["revision"], "episode_id": episode_id,
                "workspace": dict(row), "current": dict(current),
                "history": [{k:v[k] for k in ("id", "version", "sha256", "created_at")} for v in versions],
                "renders": [dict(j) for j in jobs]})
            for job in result["renders"]:
                if job["status"] == "succeeded":
                    job["content_url"] = f"/api/v1/projects/{project_id}/edit-exports/{job['id']}/content"
            return result

    def save(self, project_id, payload, **kw):
        def work(conn, project):
            p, episode_id = project["id"], checked_id(payload.get("episode_id"))
            self.store._one(conn, S.episodes, p, episode_id)
            current = conn.execute(select(S.edit_workspaces).where(S.edit_workspaces.c.project_id == p,
                S.edit_workspaces.c.episode_id == episode_id)).mappings().first()
            expected = payload.get("edit_revision")
            if type(expected) is not int or expected != (current["revision"] if current else 0):
                raise Conflict("剪辑稿已有新版本，请保留本地修改并重新载入。", "edit_revision_conflict")
            document = payload.get("document")
            if payload.get("restore_version_id"):
                if not current or document is not None:
                    raise ResourceError("恢复版本不能同时覆盖正文", "invalid_edit_restore")
                version = self.store._one(conn, S.edit_revisions, p, payload["restore_version_id"])
                if version["workspace_id"] != current["id"]:
                    raise ResourceError("不能恢复其他集的剪辑版本", "edit_scope_mismatch")
                document = version["document"]
            try:
                validate_edit(document)
            except ValueError as error:
                raise ResourceError(str(error), "invalid_edit_document") from error
            members, offset = [], 0
            scope = self.store._descendant_ids(conn, p, episode_id)
            for track in ("clips", "audio"):
                for ordinal, clip in enumerate(document.get(track, [])):
                    media = self.store._media(conn, p, clip["media_id"])
                    if media["modality"] not in ({"video", "image"} if track == "clips" else {"audio", "video"}):
                        raise ResourceError("素材类型与轨道不匹配", "edit_media_type")
                    shot = clip.get("shot_id")
                    if shot:
                        self.store._one(conn, S.shots, p, shot)
                        if shot not in scope:
                            raise ResourceError("镜头不属于当前集", "edit_scope_mismatch")
                    members.append({"project_id": p, "id": new_id(), "media_id": media["id"],
                        "blob_id": media["blob_id"], "blob_sha256": media["sha256"], "clip_key": clip["id"],
                        "shot_id": shot, "track": track, "ordinal": ordinal, "source_in_frame": clip["in_frame"],
                        "source_out_frame": clip["out_frame"], "offset_frame": offset if track == "clips" else clip.get("at_frame", 0),
                        "modality": media["modality"]})
                    if track == "clips":
                        offset += clip["out_frame"] - clip["in_frame"]
            workspace_id, version_id = current["id"] if current else new_id(), new_id()
            if not current:
                conn.execute(insert(S.edit_workspaces).values(project_id=p, id=workspace_id, episode_id=episode_id,
                    title="本集剪辑", revision=0))
            conn.execute(insert(S.edit_revisions).values(project_id=p, id=version_id, workspace_id=workspace_id,
                version=expected+1, document=document, sha256=digest(document), member_count=len(members), created_by=kw["actor"]))
            for member in members:
                conn.execute(insert(S.edit_revision_media).values(**member, edit_version_id=version_id))
            for clip in document['clips']:
                if clip.get('working_selection_version_id'):
                    conn.execute(insert(S.edit_revision_working_selections).values(project_id=p, id=new_id(),
                        edit_version_id=version_id, clip_key=clip['id'],
                        selection_version_id=checked_id(clip['working_selection_version_id'])))
            conn.execute(update(S.edit_workspaces).where(S.edit_workspaces.c.project_id==p, S.edit_workspaces.c.id==workspace_id)
                .values(revision=expected+1, current_version_id=version_id))
            return {"id": workspace_id, "edit_version_id": version_id, "edit_revision": expected+1, "sha256": digest(document)}
        return self.store._mutate(project_id, "save_edit_workspace", payload, callback=work, **kw)

    def _inputs(self, conn, p, version_id, usable=False):
        version = self.store._one(conn, S.edit_revisions, p, version_id)
        audio_purposes = {item["id"]: item.get("purpose", "music") for item in version["document"].get("audio", [])}
        rows = [dict(x) for x in conn.execute(select(S.edit_revision_media).where(S.edit_revision_media.c.project_id==p,
            S.edit_revision_media.c.edit_version_id==version_id).order_by(S.edit_revision_media.c.track, S.edit_revision_media.c.ordinal)).mappings()]
        for row in rows:
            purpose = "video_take" if row["modality"] == "video" and row["track"] == "clips" else "composition" if row["track"] == "clips" else audio_purposes[row["clip_key"]]
            from .workbench_generation import working_media
            media, gaps = working_media(self.store, conn, p, row["media_id"], purpose) if usable else (self.store._media(conn, p, row["media_id"]), [])
            # The local renderer performs a real decode; an absent earlier check
            # alone must not require a separate manual inspection round.
            gaps = [gap for gap in gaps if gap != "technical_check_missing"]
            if gaps:
                raise ResourceError("剪辑用料不可用：" + ", ".join(gaps), "edit_input_unusable")
            row["locations"] = media["locations"]
        return rows

    def request(self, project_id, payload, **kw):
        def work(conn, project):
            p = project["id"]
            version = self.store._one(conn, S.edit_revisions, p, payload.get("edit_version_id"))
            if not version["document"]["clips"]:
                raise ResourceError("先加入需要合成的片段", "edit_empty")
            self._inputs(conn, p, version["id"], usable=True)
            prior = conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==p,
                S.edit_render_jobs.c.edit_version_id==version["id"])).mappings().first()
            if prior:
                if prior["status"] in {"failed", "cancelled"}:
                    conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==p,
                        S.edit_render_jobs.c.id==prior["id"]).values(status="queued", error=None, cancel_requested=False, claim_owner=None, claim_until=None))
                return {"id": prior["id"], "edit_version_id": version["id"], "status": "queued" if prior["status"] in {"failed", "cancelled"} else prior["status"]}
            row_id = new_id()
            conn.execute(insert(S.edit_render_jobs).values(project_id=p, id=row_id, edit_version_id=version["id"],
                status="queued", attempt=0, receipt={}))
            return {"id": row_id, "edit_version_id": version["id"], "status": "queued"}
        return self.store._mutate(project_id, "request_edit_export", payload, callback=work, **kw)

    def cancel(self, project_id, payload, **kw):
        def work(conn, project):
            job = conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==project['id'],
                S.edit_render_jobs.c.id==checked_id(payload['job_id'])).with_for_update()).mappings().first()
            if not job:raise ResourceError('合成任务不属于当前项目','not_found',404)
            if job['status']=='succeeded':return {'id':job['id'],'status':'succeeded','cancel_requested':False,'already_completed':True}
            if job['status']=='cancelled':return {'id':job['id'],'status':'cancelled','cancel_requested':True}
            values={'cancel_requested':True}
            if job['status']!='running':values.update(status='cancelled',claim_owner=None,claim_until=None,error=None)
            conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==project['id'],S.edit_render_jobs.c.id==job['id']).values(**values))
            return {'id':job['id'],'status':values.get('status',job['status']),'cancel_requested':True}
        return self.store._mutate(project_id,'cancel_edit_export',payload,callback=work,**kw)

    def claim(self, owner, project_id=None, lease_seconds=120):
        now = datetime.now(timezone.utc)
        with self.store.engine.begin() as conn:
            eligible=or_(S.edit_render_jobs.c.status=='queued',and_(S.edit_render_jobs.c.status=='running',S.edit_render_jobs.c.claim_until<now))
            q=select(S.edit_render_jobs.c.project_id,S.edit_render_jobs.c.id).where(eligible)
            if project_id:q=q.where(S.edit_render_jobs.c.project_id==checked_id(project_id))
            for candidate in conn.execute(q.order_by(S.edit_render_jobs.c.created_at).limit(50)).mappings().all():
                # Same lock order as cancel/finish: project, then original job.
                project=conn.execute(select(S.projects).where(S.projects.c.id==candidate['project_id']).with_for_update(skip_locked=True)).mappings().first()
                if not project:continue
                job=conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==candidate['project_id'],S.edit_render_jobs.c.id==candidate['id'],eligible).with_for_update(skip_locked=True)).mappings().first()
                if not job:continue
                if job['cancel_requested']:
                    self._cancelled(conn,job);continue
                from .project_management import management_transaction_guard
                management_transaction_guard(conn,job['project_id'],'request_edit_export',{'edit_version_id':job['edit_version_id']})
                job=dict(job,status='running',attempt=job['attempt']+1,claim_owner=owner,claim_until=now+timedelta(seconds=lease_seconds))
                conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job['project_id'],S.edit_render_jobs.c.id==job['id']).values(status='running',attempt=job['attempt'],claim_owner=owner,claim_until=job['claim_until'],error=None))
                return job
        return None

    @staticmethod
    def _cancelled(conn, job):
        conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job['project_id'],S.edit_render_jobs.c.id==job['id']).values(status='cancelled',cancel_requested=True,error=None,claim_owner=None,claim_until=None))
        return {'id':job['id'],'status':'cancelled','cancel_requested':True}

    def _fenced(self, conn, job, owner):
        row = conn.execute(select(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job["project_id"],
            S.edit_render_jobs.c.id==job["id"]).with_for_update()).mappings().one()
        if row["status"] != "running" or row["claim_owner"] != owner or row["attempt"] != job["attempt"] or row["claim_until"] <= datetime.now(timezone.utc):
            raise Conflict("原合成租约已失效", "edit_lease_lost")
        return row

    def heartbeat(self, job, owner, seconds=120):
        with self.store.engine.begin() as conn:
            row=self._fenced(conn, job, owner)
            if row['cancel_requested']:return False
            conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job["project_id"],
                S.edit_render_jobs.c.id==job["id"]).values(claim_until=datetime.now(timezone.utc)+timedelta(seconds=seconds)))
            return True

    def prepare(self, job, owner):
        with self.store.engine.begin() as conn:
            row=self._fenced(conn, job, owner)
            if row['cancel_requested']:raise ResourceError('此合成已请求取消','edit_cancel_requested',409)
            version = self.store._one(conn, S.edit_revisions, job["project_id"], job["edit_version_id"])
            return dict(job, document=version["document"], edit_sha256=version["sha256"], inputs=self._inputs(conn, job["project_id"], version["id"], usable=True))

    def finish(self, job, owner, blob, receipt):
        def work(conn, project):
            row=self._fenced(conn, job, owner)
            if row['cancel_requested']:return self._cancelled(conn,row)
            self._inputs(conn, job["project_id"], job["edit_version_id"], usable=True)
            version = self.store._one(conn, S.edit_revisions, project["id"], job["edit_version_id"])
            document = version["document"]
            frames = validate_edit(document)
            tolerance = max(150, len(document["clips"]) * 1000 / document["fps"])
            if (receipt.get("full_decode") != "passed" or receipt.get("recipe") != RECIPE
                    or receipt.get("edit_sha256") != version["sha256"] or receipt.get("frames") != frames
                    or blob.get("mime_type") != "video/mp4" or blob.get("modality") != "video"
                    or (blob.get("width"), blob.get("height")) != (document["width"], document["height"])
                    or not isinstance(blob.get("duration_ms"), (float, int))
                    or abs(blob["duration_ms"] - frames * 1000 / document["fps"]) > tolerance):
                raise ResourceError("合成输出与固定剪辑稿不一致", "edit_output_mismatch")
            key = blob.get("object_key", "")
            if blob.get("storage") != "local" or not key or key.startswith("/") or ".." in key.split("/") or "\\" in key:
                raise ResourceError("合成只能写入受控本地存储", "unsafe_location")
            blob_id = conn.execute(select(S.media_blobs.c.id).where(S.media_blobs.c.sha256==blob["sha256"])).scalar_one_or_none()
            if not blob_id:
                blob_id = new_id()
                conn.execute(pg_insert(S.media_blobs).values(id=blob_id, sha256=blob["sha256"], size_bytes=blob["size_bytes"],
                    mime_type="video/mp4", width=blob.get("width"), height=blob.get("height"),
                    duration_ms=blob.get("duration_ms"), sample_rate=blob.get("sample_rate"), probe=blob.get("probe", {}))
                    .on_conflict_do_nothing(index_elements=[S.media_blobs.c.sha256]))
                blob_id = conn.execute(select(S.media_blobs.c.id).where(S.media_blobs.c.sha256==blob["sha256"])).scalar_one()
            stored_size = conn.execute(select(S.media_blobs.c.size_bytes).where(S.media_blobs.c.id==blob_id)).scalar_one()
            if stored_size != blob["size_bytes"]:
                raise Conflict("合成字节摘要与大小冲突", "blob_mismatch")
            conn.execute(pg_insert(S.blob_locations).values(id=new_id(), blob_id=blob_id, storage="local", object_key=blob["object_key"], available=True)
                .on_conflict_do_nothing())
            conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job["project_id"],
                S.edit_render_jobs.c.id==job["id"]).values(status="succeeded", output_blob_id=blob_id,
                    output_sha256=blob["sha256"], receipt=receipt, claim_owner=None, claim_until=None))
            return {"id": job["id"], "status": "succeeded", "sha256": blob["sha256"]}
        return self.store._mutate(job["project_id"], "finish_edit_export",
            {"job_id": job["id"], "attempt": job["attempt"], "sha256": blob["sha256"], "receipt": receipt},
            expected_revision=CURRENT_REVISION, idempotency_key=f"first-cut:{job['id']}:{job['attempt']}", actor=owner, callback=work)

    def fail(self, job, owner, error):
        with self.store.engine.begin() as conn:
            row=self._fenced(conn, job, owner)
            if row['cancel_requested']:return self._cancelled(conn,row)
            conn.execute(update(S.edit_render_jobs).where(S.edit_render_jobs.c.project_id==job["project_id"],
                S.edit_render_jobs.c.id==job["id"]).values(status="failed", error=str(error)[:1600], claim_owner=None, claim_until=None))
        return {"id": job["id"], "status": "failed"}

    def content(self, project_id, job_id):
        with self.store.engine.connect() as conn:
            self.store._project(conn, project_id)
            job = self.store._one(conn, S.edit_render_jobs, project_id, job_id)
            if job["status"] != "succeeded":
                raise ResourceError("合成尚未完成", "edit_export_not_ready", 409)
            self._inputs(conn, project_id, job["edit_version_id"], usable=True)
            locations = conn.execute(select(S.blob_locations).where(S.blob_locations.c.blob_id==job["output_blob_id"],
                S.blob_locations.c.available.is_(True))).mappings().all()
            return {"sha256": job["output_sha256"], "locations": [dict(l) for l in locations], "receipt": job["receipt"]}

    def export_inputs(self, project_id, version_id):
        with self.store.engine.connect() as conn:
            project = self.store._project(conn, project_id)
            version = self.store._one(conn, S.edit_revisions, project['id'], checked_id(version_id))
            workspace = self.store._one(conn, S.edit_workspaces, project['id'], version['workspace_id'])
            return clean(dict(version, episode_id=workspace['episode_id'],
                inputs=self._inputs(conn, project['id'], version['id'], usable=True)))
