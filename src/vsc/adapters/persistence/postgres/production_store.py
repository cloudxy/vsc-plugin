"""Provider registry and durable production job operations for PostgreSQL."""
from datetime import datetime, timedelta, timezone
import json
import re
import uuid
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from vsc.assets.resource_service import Conflict, NotFound, ResourceError, required
from . import schema as S
from .values import checked_id, clean, digest, new_id
from vsc.production.run_authorization import authorize_run, normalize_request, validate_capabilities


class ProductionRepository:
    def record_submission_result(self, project_id, payload, **kw):
        def work(conn, project):
            job = self._one(conn, S.generation_jobs, project["id"], required(payload, "job_id"))
            if (job["status"] != "submission_unknown" or job["claim_owner"] != required(payload, "worker_id")
                    or not job["claim_until"] or job["claim_until"] <= datetime.now(timezone.utc)):
                raise Conflict("提交响应不属于有效worker意图", "worker_lease_conflict")
            external = payload.get("external_task_id")
            provider_status = required(payload, "provider_status")
            if provider_status not in {"submitted", "running", "succeeded", "failed"}:
                raise ResourceError("Provider响应状态无效")
            values = {"raw_response": required(payload, "raw_response"), "external_task_id": external,
                      "status": "submitted" if external else "submission_unknown", "updated_at": datetime.now(timezone.utc)}
            if external and provider_status in {"submitted", "running"}:
                values.update(claim_owner=None, claim_until=None)
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id == project["id"], S.generation_jobs.c.id == job["id"]).values(**values))
            conn.execute(insert(S.job_events).values(project_id=project["id"], id=new_id(), job_id=job["id"], event_type="response_recorded",
                evidence={"provider_status": provider_status, "worker_id": payload["worker_id"], "external_task_id": external}))
            return {"id": job["id"], "status": values["status"]}
        return self._mutate(project_id, "record_submission_result", payload, callback=work, **kw)

    def register_provider(self, payload, actor):
        provider_id = required(payload, "id")
        auth_ref = required(payload, "auth_ref")
        if not isinstance(auth_ref, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", auth_ref):
            raise ResourceError("auth_ref 只能是凭证环境变量名称，不能保存密钥", "invalid_auth_ref")
        values = {"id": provider_id, "name": payload.get("name", provider_id),
                  "modality": payload.get("modality", "multimodal"), "base_url": required(payload, "base_url"),
                  "auth_ref": auth_ref, "enabled": bool(payload.get("enabled", True)), "rate_limit": payload.get("rate_limit", {})}
        with self.engine.begin() as conn:
            conn.execute(pg_insert(S.providers).values(**values).on_conflict_do_update(index_elements=[S.providers.c.id],
                set_={k: v for k, v in values.items() if k != "id"}))
            return clean(dict(conn.execute(select(S.providers).where(S.providers.c.id == provider_id)).mappings().one()))

    def register_model(self, payload, actor):
        provider_id, key, version = (required(payload, k) for k in ("provider_id", "model_key", "model_version"))
        model_id = checked_id(payload.get("id", str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc:model:" + provider_id + ":" + key + ":" + version))))
        values = {"id": model_id, "provider_id": provider_id, "model_key": key,
                  "model_version": version, "modality": required(payload, "modality"),
                  "capabilities": payload.get("capabilities", {}), "default_params": payload.get("default_params", {}),
                  "cost_rule": payload.get("cost_rule", {}), "enabled": bool(payload.get("enabled", True))}
        try:
            with self.engine.begin() as conn:
                existing = conn.execute(select(S.provider_models).where(S.provider_models.c.provider_id == provider_id,
                    S.provider_models.c.model_key == key, S.provider_models.c.model_version == version).with_for_update()).mappings().first()
                if existing:
                    if any(existing[k] != v for k, v in values.items() if k not in {"id", "enabled"}):
                        raise Conflict("已登记模型版本的能力与参数不可改写，请增加model_version", "model_version_conflict")
                    conn.execute(update(S.provider_models).where(S.provider_models.c.id == existing["id"]).values(enabled=values["enabled"]))
                    return clean(dict(existing, enabled=values["enabled"]))
                conn.execute(insert(S.provider_models).values(**values))
                return clean(values)
        except IntegrityError as exc:
            raise ResourceError("模型所属Provider或版本关系无效", "model_registration_failed") from exc

    def register_route(self, payload, actor):
        modality, purpose = required(payload, "modality"), required(payload, "purpose")
        priority = int(payload.get("priority", 0))
        row_id = checked_id(payload.get("id", str(uuid.uuid5(uuid.NAMESPACE_URL, "vsc:route:%s:%s:%s" % (modality, purpose, priority)))))
        values = {"id": row_id, "modality": modality, "purpose": purpose, "priority": priority,
                  "preferred_provider": required(payload, "preferred_provider"),
                  "fallback_provider": payload.get("fallback_provider"), "enabled": bool(payload.get("enabled", True))}
        try:
            with self.engine.begin() as conn:
                conn.execute(pg_insert(S.provider_routes).values(**values).on_conflict_do_update(index_elements=[S.provider_routes.c.id],
                    set_={k: v for k, v in values.items() if k != "id"}))
                return clean(values)
        except IntegrityError as exc:
            raise ResourceError("路由Provider未登记", "route_registration_failed") from exc

    def list_models(self, modality=None):
        with self.engine.connect() as conn:
            query = select(S.provider_models).order_by(S.provider_models.c.provider_id, S.provider_models.c.model_key, S.provider_models.c.model_version)
            if modality:
                query = query.where(S.provider_models.c.modality == modality)
            return clean([dict(r) for r in conn.execute(query).mappings()])

    def list_routes(self):
        with self.engine.connect() as conn:
            return clean([dict(r) for r in conn.execute(select(S.provider_routes).order_by(
                S.provider_routes.c.modality, S.provider_routes.c.purpose, S.provider_routes.c.priority, S.provider_routes.c.id)).mappings()])

    def get_generation_job(self, project_id, job_id):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            return clean(self._job_detail(conn, project, checked_id(job_id)))

    def _job_detail(self, conn, project, job_id):
        p = project["id"]
        job = self._one(conn, S.generation_jobs, p, job_id)
        job["input_media"] = [dict(r) for r in conn.execute(select(S.job_input_media).where(
            S.job_input_media.c.project_id == p, S.job_input_media.c.job_id == job_id).order_by(S.job_input_media.c.ordinal)).mappings()]
        for item in job["input_media"]:
            media = self._media(conn, p, item["media_id"])
            item["locations"] = media["locations"]
            item["mime_type"] = media["mime_type"]
        job["input_versions"] = [dict(r) for r in conn.execute(select(S.job_input_versions).where(
            S.job_input_versions.c.project_id == p, S.job_input_versions.c.job_id == job_id)).mappings()]
        job["outputs"] = [dict(r) for r in conn.execute(select(S.job_outputs).where(
            S.job_outputs.c.project_id == p, S.job_outputs.c.job_id == job_id)).mappings()]
        job["events"] = [dict(r) for r in conn.execute(select(S.job_events).where(
            S.job_events.c.project_id == p, S.job_events.c.job_id == job_id).order_by(S.job_events.c.created_at, S.job_events.c.id)).mappings()]
        job["provider"] = dict(conn.execute(select(S.providers).where(S.providers.c.id == job["provider_id"])).mappings().one())
        job["model"] = dict(conn.execute(select(S.provider_models).where(S.provider_models.c.id == job["model_id"])).mappings().one())
        job["revision"] = project["revision"]
        return job

    def list_generation_jobs(self, project_id, status=None, offset=0, limit=50):
        with self.engine.connect() as conn:
            project = self._project(conn, project_id)
            query = select(S.generation_jobs).where(S.generation_jobs.c.project_id == project["id"])
            if status:
                query = query.where(S.generation_jobs.c.status == status)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = [dict(r) for r in conn.execute(query.order_by(S.generation_jobs.c.created_at, S.generation_jobs.c.id).offset(offset).limit(limit)).mappings()]
            return clean({"items": rows, "total": total, "offset": offset, "limit": limit, "revision": project["revision"]})

    def claim_generation_job(self, worker_id, project_id=None, lease_seconds=300, statuses=("created",)):
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 3600:
            raise ResourceError("worker租约需要1..3600秒")
        statuses = tuple(statuses)
        if not statuses or any(status not in {"created", "submitted", "running"} for status in statuses):
            raise ResourceError("只能领取可提交或可轮询任务，unknown禁止自动重提", "job_not_claimable")
        now = datetime.now(timezone.utc)
        eligible = and_(S.generation_jobs.c.status.in_(statuses), or_(S.generation_jobs.c.claim_until.is_(None), S.generation_jobs.c.claim_until <= now))
        with self.engine.begin() as conn:
            # Lock order is always project then job, matching manual mutations.
            projects = select(S.projects).where(S.projects.c.id.in_(select(S.generation_jobs.c.project_id).where(eligible)))
            pending_imports = select(S.project_revisions.c.project_id).where(
                S.project_revisions.c.action == "migration_import", ~S.project_revisions.c.project_id.in_(
                    select(S.project_revisions.c.project_id).where(S.project_revisions.c.action == "migration_activate")))
            projects = projects.where(~S.projects.c.id.in_(pending_imports))
            if project_id:
                projects = projects.where(S.projects.c.id == checked_id(project_id))
            project = conn.execute(projects.order_by(S.projects.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not project:
                return None
            project = dict(project)
            job = conn.execute(select(S.generation_jobs).where(S.generation_jobs.c.project_id == project["id"], eligible)
                .order_by(S.generation_jobs.c.created_at, S.generation_jobs.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if not job:
                return None
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id == project["id"], S.generation_jobs.c.id == job["id"])
                .values(claim_owner=worker_id, claim_until=now + timedelta(seconds=lease_seconds), updated_at=now))
            conn.execute(insert(S.job_events).values(project_id=project["id"], id=new_id(), job_id=job["id"],
                event_type="lease_claimed", evidence={"worker_id": worker_id, "lease_seconds": lease_seconds}))
            project["revision"] += 1
            conn.execute(update(S.projects).where(S.projects.c.id == project["id"]).values(revision=project["revision"]))
            conn.execute(insert(S.project_revisions).values(project_id=project["id"], revision=project["revision"],
                actor=worker_id, action="claim_generation_job", command_key="lease:" + new_id()))
            return clean(self._job_detail(conn, project, job["id"]))

    def mark_submission_started(self, project_id, payload, **kw):
        def work(conn, project):
            job = self._one(conn, S.generation_jobs, project["id"], required(payload, "job_id"))
            worker = required(payload, "worker_id")
            if (job["status"] != "created" or job["claim_owner"] != worker or not job["claim_until"]
                    or job["claim_until"] <= datetime.now(timezone.utc)):
                raise Conflict("提交任务的worker租约无效", "worker_lease_conflict")
            self._reserve_budget(conn, project, job)
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id == project["id"], S.generation_jobs.c.id == job["id"])
                .values(status="submission_unknown", attempt=job["attempt"] + 1, updated_at=datetime.now(timezone.utc)))
            conn.execute(insert(S.job_events).values(project_id=project["id"], id=new_id(), job_id=job["id"],
                event_type="submission_started", evidence={"worker_id": worker}))
            return {"id": job["id"], "status": "submission_unknown"}
        return self._mutate(project_id, "mark_submission_started", payload, callback=work, **kw)

    def create_generation_job(self, project_id, payload, **kw):
        def work(conn, project):
            p = project["id"]
            shot_id = checked_id(payload["shot_id"]) if payload.get("shot_id") else None
            asset_id = checked_id(payload["asset_id"]) if payload.get("asset_id") else None
            if (shot_id is None) == (asset_id is None):
                raise ResourceError("任务须指定且仅指定镜头或资产身份", "job_target_required")
            if asset_id and (payload.get("modality") != "image" or payload.get("purpose") not in {"identity_ref", "location_master", "ref", "asset_ref", "prop_ref", "costume_ref", "style_ref"}):
                raise ResourceError("资产首参考只支持声明的图像用途", "asset_generation_unsupported")
            context = (self._compile_asset_context(conn, project, asset_id, payload.get("purpose")) if asset_id else
                self._compile_context(conn, project, shot_id, payload.get("purpose")))
            if not context["ready"]:
                raise ResourceError("镜头上下文存在缺口，不能提交生成", "context_gaps")
            if payload.get("context_sha256") != context["sha256"]:
                raise Conflict("镜头上下文已改变", "context_conflict")
            run = self._one(conn, S.artifact_versions, p, required(payload, "run_version_id"))
            if not self._artifact_approved(conn, p, run["id"]):
                raise ResourceError("运行版本未批准", "run_unapproved")
            model_id = checked_id(required(payload, "model_id"))
            model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == model_id)).mappings().first()
            if not model or not model["enabled"]:
                raise ResourceError("模型未注册或未启用", "model_unavailable")
            provider = conn.execute(select(S.providers).where(S.providers.c.id == model["provider_id"])).mappings().one()
            if not provider["enabled"] or model["modality"] != payload.get("modality"):
                raise ResourceError("Provider 或模型模态不可用", "model_unavailable")
            request = dict(required(payload, "request_payload"))
            if any(key in request for key in ("input_media", "input_versions", "voice_binding")):
                raise ResourceError("请求固定输入由服务端编译，客户端不能覆写", "untrusted_job_inputs")
            if request.get("context_sha256", context["sha256"]) != context["sha256"]:
                raise Conflict("逻辑请求上下文不匹配", "context_conflict")
            request = normalize_request(request, shot_id, payload["purpose"], payload["modality"], asset_id=asset_id)
            candidate_no = int(payload.get("candidate_no", 0))
            try:
                run_document = json.loads(run["document"])
            except (ValueError, UnicodeDecodeError):
                raise ResourceError("production-run必须是固定结构文档", "invalid_production_run")
            pinned = authorize_run(run_document, run["artifact_type"], context, request, candidate_no)
            dependencies = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
                S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == run["id"])).scalars())
            if {item[0] for item in pinned} != dependencies:
                raise ResourceError("run批准输入须与真实依赖关系完全一致", "run_dependency_mismatch")
            for artifact_id, sha in pinned:
                version = self._one(conn, S.artifact_versions, p, artifact_id)
                if version["sha256"] != sha or not self._artifact_approved(conn, p, artifact_id):
                    raise ResourceError("run固定上游版本摘要或批准失效", "run_inputs_mismatch")
            voice_binding = validate_capabilities(dict(model), request, context)
            if voice_binding:
                request["voice_binding"] = voice_binding
            request["context_sha256"] = context["sha256"]
            request["input_media"] = [{k: item[k] for k in ("media_id", "blob_id", "sha256", "role", "binding_decision_id")}
                                      for item in context["media"]]
            request["input_versions"] = [{k: artifact[k] for k in ("id", "sha256", "artifact_type")} for artifact in context["artifacts"]]
            request_sha = digest(request)
            key = digest({"run": run["id"], "shot": shot_id, "asset": asset_id, "purpose": required(payload, "purpose"),
                          "candidate": candidate_no, "provider": provider["id"], "model": model_id, "request": request_sha})
            row_id = new_id()
            conn.execute(insert(S.generation_jobs).values(project_id=p, id=row_id, run_version_id=run["id"], shot_id=shot_id, asset_id=asset_id,
                purpose=payload["purpose"], modality=payload["modality"], candidate_no=candidate_no, provider_id=provider["id"],
                model_id=model_id, model_version=model["model_version"], request_payload=request, request_sha256=request_sha,
                context_sha256=context["sha256"], idempotency_key=key, status="created", attempt=0))
            for ordinal, item in enumerate(context["media"]):
                conn.execute(insert(S.job_input_media).values(project_id=p, id=new_id(), job_id=row_id,
                    media_id=item["media_id"], blob_id=item["blob_id"], blob_sha256=item["sha256"],
                    binding_decision_id=item["binding_decision_id"], role=item["role"], ordinal=ordinal))
            for artifact in context["artifacts"]:
                conn.execute(insert(S.job_input_versions).values(project_id=p, id=new_id(), job_id=row_id,
                    artifact_id=artifact["id"], sha256=artifact["sha256"], role=artifact["artifact_type"]))
            conn.execute(insert(S.job_events).values(project_id=p, id=new_id(), job_id=row_id, event_type="intent_recorded", evidence={}))
            return {"id": row_id, "status": "created", "idempotency_key": key, "request_sha256": request_sha}
        return self._mutate(project_id, "create_generation_job", payload, callback=work, **kw)


    def update_generation_job(self, project_id, payload, **kw):
        allowed = {"created": {"submitted", "submission_unknown", "failed", "cancelled"},
                   "submitted": {"running", "succeeded", "failed"}, "running": {"running", "succeeded", "failed"},
                   "submission_unknown": {"submitted", "succeeded", "failed"}, "succeeded": set(), "failed": set(), "cancelled": set()}
        def work(conn, project):
            p = project["id"]
            job = self._one(conn, S.generation_jobs, p, required(payload, "job_id"))
            status = required(payload, "status")
            if payload.get("worker_id") and (job["claim_owner"] != payload["worker_id"] or not job["claim_until"]
                    or job["claim_until"] <= datetime.now(timezone.utc)):
                raise Conflict("任务worker租约已过期或归属不同", "worker_lease_conflict")
            if status not in allowed[job["status"]]:
                raise Conflict("生成任务状态转换不允许", "invalid_job_transition")
            if job["status"] == "created" and status in {"submitted", "submission_unknown"}:
                self._reserve_budget(conn, project, job)
            if job["status"] == "submission_unknown" and not payload.get("recovery_evidence"):
                raise ResourceError("未知提交结果必须提供恢复证据，禁止直接重提", "recovery_evidence_required")
            external = payload.get("external_task_id", job["external_task_id"])
            if job["external_task_id"] and external != job["external_task_id"]:
                raise Conflict("不能替换已有外部任务 ID", "external_task_conflict")
            if status in {"submitted", "running"} and not external:
                raise ResourceError("异步运行任务需要外部任务 ID")
            outputs = payload.get("outputs", [])
            if status == "succeeded" and not outputs:
                raise ResourceError("成功任务必须有已转存的输出素材", "job_output_required")
            for output in outputs:
                media = self._media(conn, p, required(output, "media_id"))
                if not any(location["available"] for location in media["locations"]):
                    raise ResourceError("任务输出字节未完成转存", "job_output_missing")
                conn.execute(insert(S.job_outputs).values(project_id=p, id=new_id(), job_id=job["id"],
                    media_id=media["id"], asset_type=output.get("asset_type", job["modality"]), original_uri=output.get("original_uri")))
            values = {"status": status, "external_task_id": external, "updated_at": datetime.now(timezone.utc),
                      "claim_owner": None, "claim_until": None}
            for field in ("cost", "latency_ms", "raw_response"):
                if field in payload:
                    values[field] = payload[field]
            if job["status"] == "created":
                values["attempt"] = job["attempt"] + 1
            conn.execute(update(S.generation_jobs).where(S.generation_jobs.c.project_id == p, S.generation_jobs.c.id == job["id"]).values(**values))
            if status in {"succeeded", "failed", "cancelled"}:
                self._settle_budget(conn, p, job, payload.get("actual_units"))
            conn.execute(insert(S.job_events).values(project_id=p, id=new_id(), job_id=job["id"], event_type=status,
                evidence=payload.get("recovery_evidence", {})))
            return {"id": job["id"], "status": status}
        return self._mutate(project_id, "update_generation_job", payload, callback=work, **kw)


