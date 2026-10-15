"""Durable preview work, fenced attempts and disposable rendition projections."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from . import schema as S
from .values import checked_id, clean, new_id, verify_sha


class PreviewRepository:
    def list_preview_jobs(self, project_id, media_id=None):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            query = select(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"])
            if media_id:
                self._one(conn, S.media_items, project["id"], media_id)
                query = query.where(S.preview_jobs.c.media_id == checked_id(media_id))
            return clean({"items": [dict(r) for r in conn.execute(query.order_by(S.preview_jobs.c.created_at, S.preview_jobs.c.id)).mappings()],
                          "revision": project["revision"]})

    def _renditions(self, conn, p, media_ids):
        rows = [dict(r) for r in conn.execute(select(S.media_renditions,
            S.media_blobs.c.sha256, S.media_blobs.c.mime_type, S.media_blobs.c.size_bytes, S.media_blobs.c.probe)
            .select_from(S.media_renditions.join(S.media_blobs, S.media_renditions.c.blob_id == S.media_blobs.c.id))
            .where(S.media_renditions.c.project_id == p, S.media_renditions.c.media_id.in_(media_ids))).mappings()]
        blob_ids = [r["blob_id"] for r in rows]
        locations = {}
        if blob_ids:
            for row in conn.execute(select(S.blob_locations).where(S.blob_locations.c.blob_id.in_(blob_ids))).mappings():
                locations.setdefault(row["blob_id"], []).append(dict(row))
        for row in rows:
            row["locations"] = locations.get(row["blob_id"], [])
        return rows

    def get_media_rendition(self, project_id, media_id, purpose=None):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            self._one(conn, S.media_items, project["id"], media_id)
            rows = self._renditions(conn, project["id"], [checked_id(media_id)])
            if purpose:
                rows = [r for r in rows if r["purpose"] == purpose]
            rows = [r for r in rows if any(l["available"] for l in r["locations"])]
            if not rows:
                raise NotFound("尚无可用的受控预览副本")
            rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return clean(rows[0])

    def claim_preview_job(self, project_id=None, retry_failed=False, stale_after_seconds=300):
        if not isinstance(stale_after_seconds, int) or not 1 <= stale_after_seconds <= 3600:
            raise ResourceError("预览租约需要1..3600秒")
        now = datetime.now(timezone.utc)
        eligible = or_(S.preview_jobs.c.status == "created", and_(S.preview_jobs.c.status == "running", S.preview_jobs.c.claim_until <= now))
        if retry_failed:
            eligible = or_(eligible, S.preview_jobs.c.status == "failed")
        with self.engine.begin() as conn:
            query = select(S.projects).where(S.projects.c.id.in_(select(S.preview_jobs.c.project_id).where(eligible)))
            pending = select(S.project_revisions.c.project_id).where(S.project_revisions.c.action == "migration_import",
                ~S.project_revisions.c.project_id.in_(select(S.project_revisions.c.project_id).where(S.project_revisions.c.action == "migration_activate")))
            query = query.where(~S.projects.c.id.in_(pending))
            if project_id:
                query = query.where(S.projects.c.id == checked_id(project_id))
            project = conn.execute(query.order_by(S.projects.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not project:
                return None
            project = dict(project)
            row = conn.execute(select(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"], eligible)
                .order_by(S.preview_jobs.c.created_at, S.preview_jobs.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not row:
                return None
            row = dict(row)
            row.update(status="running", attempt=row["attempt"] + 1, claim_until=now + timedelta(seconds=stale_after_seconds), error=None, updated_at=now)
            conn.execute(update(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"], S.preview_jobs.c.id == row["id"])
                .values(**{k: row[k] for k in ("status", "attempt", "claim_until", "error", "updated_at")}))
            project["revision"] += 1
            conn.execute(update(S.projects).where(S.projects.c.id == project["id"]).values(revision=project["revision"]))
            conn.execute(insert(S.project_revisions).values(project_id=project["id"], revision=project["revision"],
                actor="preview-worker", action="claim_preview_job", command_key="preview-lease:" + new_id()))
            media = self._media(conn, project["id"], row["media_id"])
            return clean(dict(row, media=media, source_media=media, revision=project["revision"]))

    def _preview_complete(self, project_id, job_id, attempt, result=None, error=None):
        payload = {"job_id": job_id, "attempt": attempt, "result": result, "error": error}
        status = "failed" if error is not None else "succeeded"
        def work(conn, project):
            job = self._one(conn, S.preview_jobs, project["id"], job_id)
            if (job["status"] != "running" or job["attempt"] != attempt or not job["claim_until"]
                    or job["claim_until"] <= datetime.now(timezone.utc)):
                raise Conflict("预览worker的attempt或租约已失效", "preview_attempt_conflict")
            rendition_id = None
            if result is not None:
                sha = verify_sha(required(result, "sha256"))
                proof = result.get("probe", {}).get("preview", {})
                source = self._media(conn, project["id"], job["media_id"])
                if (proof.get("source_sha256") != source["sha256"] or proof.get("recipe_version") != job["recipe_version"]
                        or proof.get("purpose") != job["purpose"] or not proof.get("tool") or not proof.get("tool_version")):
                    raise ResourceError("预览结果与固定来源、配方、工具不一致", "preview_evidence_mismatch")
                blob_id = new_id()
                blob_probe = {k: v for k, v in result.get("probe", {}).items() if k != "preview"}
                conn.execute(pg_insert(S.media_blobs).values(id=blob_id, sha256=sha,
                    size_bytes=required(result, "size_bytes"), mime_type=required(result, "mime_type"),
                    width=result.get("width"), height=result.get("height"), duration_ms=result.get("duration_ms"),
                    sample_rate=result.get("sample_rate"), probe=blob_probe).on_conflict_do_nothing(index_elements=[S.media_blobs.c.sha256]))
                blob = conn.execute(select(S.media_blobs).where(S.media_blobs.c.sha256 == sha)).mappings().one()
                if blob["size_bytes"] != result["size_bytes"]:
                    raise Conflict("预览字节摘要与大小冲突", "blob_mismatch")
                key = required(result, "object_key")
                if not isinstance(key, str) or key.startswith("/") or ".." in key.split("/") or "\\" in key:
                    raise ResourceError("预览位置越过受控存储", "unsafe_location")
                conn.execute(pg_insert(S.blob_locations).values(id=new_id(), blob_id=blob["id"], storage=required(result, "storage"), object_key=key)
                    .on_conflict_do_nothing(index_elements=[S.blob_locations.c.blob_id, S.blob_locations.c.storage, S.blob_locations.c.object_key]))
                rendition_id = new_id()
                rendition_id = conn.execute(pg_insert(S.media_renditions).values(project_id=project["id"], id=rendition_id,
                    media_id=job["media_id"], blob_id=blob["id"], purpose=job["purpose"], recipe_version=job["recipe_version"], request_sha256=job["request_sha256"],
                    tool=proof["tool"], tool_version=proof["tool_version"], parameters=proof.get("parameters", {}),
                    source_blob_id=source["blob_id"], source_sha256=source["sha256"])
                    .on_conflict_do_update(index_elements=[S.media_renditions.c.project_id, S.media_renditions.c.media_id,
                        S.media_renditions.c.purpose, S.media_renditions.c.request_sha256], set_={"blob_id": blob["id"]})
                    .returning(S.media_renditions.c.id)).scalar_one()
            conn.execute(update(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"], S.preview_jobs.c.id == job_id)
                .values(status=status, error=str(error)[:2000] if error is not None else None, claim_until=None, updated_at=datetime.now(timezone.utc)))
            return {"id": job_id, "status": status, "rendition_id": rendition_id, "attempt": attempt}
        for retry in range(4):
            revision = self.get_project(project_id)["revision"]
            try:
                return self._mutate(project_id, "finish_preview_job", payload, expected_revision=revision,
                    idempotency_key="preview:%s:%s:%s" % (job_id, attempt, status), actor="preview-worker", callback=work)
            except Conflict as conflict:
                if conflict.code != "revision_conflict" or retry == 3:
                    raise

    def finish_preview_job(self, project_id, job_id, attempt, result):
        return self._preview_complete(project_id, checked_id(job_id), attempt, result=result)

    def fail_preview_job(self, project_id, job_id, attempt, error):
        return self._preview_complete(project_id, checked_id(job_id), attempt, error=error)

    def retry_preview_job(self, project_id, payload, **kw):
        def work(conn, project):
            job = self._one(conn, S.preview_jobs, project["id"], required(payload, "job_id"))
            if job["status"] != "failed":
                raise Conflict("只能显式重试失败的预览任务", "preview_not_failed")
            conn.execute(update(S.preview_jobs).where(S.preview_jobs.c.project_id == project["id"], S.preview_jobs.c.id == job["id"])
                .values(status="created", error=None, claim_until=None, updated_at=datetime.now(timezone.utc)))
            return {"id": job["id"], "status": "created"}
        return self._mutate(project_id, "retry_preview_job", payload, callback=work, **kw)
