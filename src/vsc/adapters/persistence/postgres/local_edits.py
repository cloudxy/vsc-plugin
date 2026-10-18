"""Versioned local change proposals over existing instance/job/run facts."""
from copy import deepcopy
from dataclasses import fields
import json

from sqlalchemy import func, select, text
from vsc.assets.resource_service import Conflict, ResourceError, artifact_stage, required
from vsc.production.providers import AudioRequest, ImageRequest, VideoRequest
from vsc.production.run_authorization import normalize_request, validate_capabilities
from . import schema as S
from .budget_store import native_units, operation_key
from .values import checked_id, clean, digest

TYPES = {"image": ImageRequest, "video": VideoRequest, "audio": AudioRequest}


def _document(row):
    return json.loads(row["document"])


def _validate_contract(project, artifact):
    """Use the public registration contract again inside the locked proposal."""
    artifact["stage"] = artifact_stage(project["profile_snapshot"], artifact["artifact_type"], artifact["stage"])
    if artifact["artifact_type"].startswith("vsc."):
        from vsc.project.pg_workflow import validate_contract
        errors = validate_contract(artifact["document"], artifact["artifact_type"],
            project["profile_snapshot"].get("contract_policy", "production-v2"))
        if errors:
            raise ResourceError("产物违反固定契约: " + "; ".join(errors), "invalid_contract")


def _scopes(store, conn, p, artifact):
    return {"project_wide": True} if artifact["project_wide"] else {"object_ids": sorted(store._artifact_scopes(conn, p, artifact["id"]))}


def _line_keys(conn, p, values):
    """Historical physical row IDs resolve through their recorded stable key."""
    result = []
    for value in values:
        try:
            identifier = checked_id(value)
        except ResourceError:
            result.append(value)
            continue
        key = conn.execute(select(S.script_lines.c.line_key).where(S.script_lines.c.project_id == p,
            S.script_lines.c.id == identifier)).scalar_one_or_none()
        if key is None:
            raise ResourceError("原声音任务的固定台词不存在", "dialogue_coverage_mismatch")
        result.append(key)
    return result


def _preview(store, conn, project, payload):
    p, action = project["id"], required(payload, "action")
    allowed = {"replace_instance": {"instance_id", "replacement_spec_version_id"}, "resample": {"job_id", "params"},
               "redo_sound": {"shot_id", "purpose", "params"}}
    if action not in allowed or set(payload) - allowed[action] - {"action", "preview_sha256"}:
        raise ResourceError("局部操作包含未知字段或动作", "invalid_local_action")
    if action == "replace_instance":
        instance = store._one(conn, S.asset_use_instances, p, checked_id(required(payload, "instance_id")))
        source = store._one(conn, S.artifact_versions, p, instance["artifact_id"])
        spec = store._one(conn, S.asset_spec_versions, p, checked_id(required(payload, "replacement_spec_version_id")))
        if spec["asset_id"] != instance["asset_id"]:
            raise ResourceError("局部实例换版本须保持同一资产身份；跨身份替换需另行明确", "instance_identity_mismatch")
        if not store._artifact_approved(conn, p, source["id"]) or not store._artifact_approved(conn, p, spec["artifact_id"]):
            raise ResourceError("实例与替换规格须来自已批准固定版本", "local_source_unapproved")
        current = conn.execute(select(S.current_artifact_versions.c.artifact_id).where(
            S.current_artifact_versions.c.project_id == p, S.current_artifact_versions.c.artifact_key == source["artifact_key"])).scalar_one_or_none()
        if current != source["id"]:
            raise ResourceError("实例不属于当前关系版本；请刷新", "local_source_stale")
        document = deepcopy(_document(source))
        owned = dict(conn.execute(select(S.asset_use_instances.c.id, S.asset_use_instances.c.instance_key).where(
            S.asset_use_instances.c.project_id == p, S.asset_use_instances.c.artifact_id == source["id"])).all())
        for interaction in document.get("interactions", []):
            for field in ("subject", "object"):
                interaction[field] = owned.get(interaction.get(field), interaction.get(field))
        for execution in document.get("performances", []):
            for participant in execution.get("participants", []):
                participant["instance"] = owned.get(participant.get("instance"), participant.get("instance"))
        matches = [row for row in document.get("instances", []) if row.get("key") == instance["instance_key"]]
        if len(matches) != 1:
            raise ResourceError("实例key不能唯一定位原文", "local_source_invalid")
        matches[0]["spec_version_id"] = spec["id"]
        deps = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
            S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == source["id"])).scalars())
        deps.add(spec["artifact_id"])
        target = {"kind": "instance", "id": instance["id"], "key": instance["instance_key"], "label": instance["label"],
                  "shot_id": instance["shot_id"], "scene_id": instance["scene_id"], "asset_id": instance["asset_id"],
                  "before_spec_version_id": instance["spec_version_id"], "after_spec_version_id": spec["id"]}
        artifact = {"artifact_type": source["artifact_type"], "artifact_key": source["artifact_key"], "stage": source["stage"],
            "supersedes_id": source["id"], "document": document, "dependency_ids": sorted(deps), **_scopes(store, conn, p, source)}
        sources = [{"id": source["id"], "sha256": source["sha256"]}]
        jobs = []
        targets = [target]
    elif action in {"resample", "redo_sound"}:
        query = select(S.generation_jobs).where(S.generation_jobs.c.project_id == p)
        if action == "resample":
            query = query.where(S.generation_jobs.c.id == checked_id(required(payload, "job_id")))
        else:
            purpose = required(payload, "purpose")
            if purpose not in {"dialogue_dry", "dialogue", "tts", "ambience", "music", "sfx", "sound_effect"}:
                raise ResourceError("只重做声音须明确声音用途", "local_audio_purpose_required")
            shot = checked_id(required(payload, "shot_id"))
            store._one(conn, S.shots, p, shot)
            query = query.where(S.generation_jobs.c.shot_id == shot, S.generation_jobs.c.purpose == purpose,
                                S.generation_jobs.c.modality == "audio")
        rows = [dict(row) for row in conn.execute(query.order_by(S.generation_jobs.c.created_at.desc(), S.generation_jobs.c.id)).mappings()]
        if not rows:
            raise ResourceError("没有可用于此局部操作的固定任务", "local_source_missing")
        selected = {}
        for row in rows:
            logical = row["request_payload"]
            signature = tuple(_line_keys(conn, p, logical.get("script_line_ids", [])))
            selected.setdefault(signature, row)
        jobs, targets, sources, dependencies, approved_media = [], [], [], {}, []
        candidates = {}
        policies, run_contracts = [], set()
        for source_job in selected.values():
            if source_job["status"] not in {"succeeded", "failed", "cancelled"}:
                raise ResourceError("原任务仍在途或提交未知；先恢复/对账，不能将其重新POST", "local_recovery_required")
            run = store._one(conn, S.artifact_versions, p, source_job["run_version_id"])
            if run["artifact_type"] not in {"production-run", "vsc.production_run"}:
                raise ResourceError("原任务没有固定制作运行包", "invalid_production_run")
            run_contracts.add((run["artifact_type"], artifact_stage(project["profile_snapshot"], run["artifact_type"], run["stage"])))
            if len(run_contracts) != 1:
                raise ResourceError("选中任务运行包的类型或所属阶段不同，须分别提案", "local_policy_conflict")
            if not store._artifact_approved(conn, p, run["id"]):
                raise ResourceError("原任务运行包批准已失效", "local_source_unapproved")
            model = dict(conn.execute(
                select(S.provider_models).where(S.provider_models.c.id == source_job["model_id"])).mappings().one())
            context = (store._compile_asset_context(conn, project, source_job["asset_id"], source_job["purpose"]) if source_job["asset_id"] else
                       store._compile_context(conn, project, source_job["shot_id"], source_job["purpose"]))
            if not context["ready"]:
                raise ResourceError("当前固定上下文有缺口，须先补齐", "context_gaps")
            allowed = {field.name for field in fields(TYPES[source_job["modality"]])} | {"modality"}
            request = {key: value for key, value in source_job["request_payload"].items() if key in allowed}
            params = payload.get("params", {})
            if not isinstance(params, dict):
                raise ResourceError("局部参数变更须为对象", "invalid_payload")
            request["params"] = dict(request.get("params", {}), **params)
            if source_job["modality"] == "audio" and request.get("script_line_ids"):
                by_key = {line["line_key"]: line for line in context.get("script_lines", [])}
                keys = _line_keys(conn, p, request["script_line_ids"])
                if any(key not in by_key for key in keys):
                    raise ResourceError("原声音台词已不属于本镜当前固定覆盖", "dialogue_coverage_mismatch")
                request["script_line_ids"] = keys
                request["prompt"] = "\n".join(by_key[key]["spoken_text"] for key in keys)
            request["context_sha256"] = context["sha256"]
            request = normalize_request(request, source_job["shot_id"], source_job["purpose"], source_job["modality"], source_job["asset_id"])
            validate_capabilities(model, request, context)
            maximum = conn.execute(select(func.max(S.generation_jobs.c.candidate_no)).where(S.generation_jobs.c.project_id == p,
                S.generation_jobs.c.purpose == source_job["purpose"], S.generation_jobs.c.shot_id == source_job["shot_id"]
                if source_job["shot_id"] else S.generation_jobs.c.asset_id == source_job["asset_id"])).scalar_one()
            candidate_key = (source_job["shot_id"] or source_job["asset_id"], source_job["purpose"])
            candidate = max(source_job["candidate_no"], maximum or 0, candidates.get(candidate_key, 0)) + 1
            candidates[candidate_key] = candidate
            entry = {"candidate_no": candidate, "request": dict(request, context_sha256=context["sha256"]), "model_id": source_job["model_id"]}
            jobs.append(entry)
            targets.append({"kind": "job", "id": source_job["id"], "shot_id": source_job["shot_id"], "asset_id": source_job["asset_id"],
                "purpose": source_job["purpose"], "modality": source_job["modality"], "candidate_no": candidate,
                "before_params": source_job["request_payload"].get("params", {}), "after_params": request["params"],
                "before_prompt": source_job["request_payload"]["prompt"], "after_prompt": request["prompt"]})
            old_document = _document(run)
            policy = {key: value for key, value in old_document.items() if key not in {
                "approved_inputs", "approved_media_inputs", "jobs", "series_batch", "operations", "local_action"}}
            if old_document.get("series_batch"):
                policy["series_batch"] = {key: value for key, value in old_document["series_batch"].items() if key != "jobs"}
            if policies and policy != policies[0]:
                raise ResourceError("选中声音任务的固定质量/试片政策不同，须分别提案", "local_policy_conflict")
            policies.append(policy)
            for ref in old_document.get("approved_inputs", []) + [{"id": run["id"], "sha256": run["sha256"]}] + [
                    {"id": item["id"], "sha256": item["sha256"]} for item in context["artifacts"]]:
                dependencies[ref["id"]] = ref
            for ref in old_document.get("approved_media_inputs", []):
                if ref not in approved_media:
                    approved_media.append(ref)
            sources.append({"id": run["id"], "sha256": run["sha256"]})
        document = {**(policies[0] if policies else {}), "approved_inputs": list(dependencies.values()), "approved_media_inputs": approved_media,
            "jobs": jobs, "operations": {operation_key(item["request"], item["candidate_no"]): native_units(item["request"]) for item in jobs},
            "local_action": action}
        if "series_batch" in document:
            document["series_batch"] = dict(document["series_batch"], jobs=jobs)
        run_type, run_stage = next(iter(run_contracts))
        if run_type == "vsc.production_run":
            # This proposal is a typed PG job batch, not the source's legacy
            # file/audio request. Preserve its phase and quality policies.
            document.pop("batch", None)
            document.pop("audio_request", None)
            document["series_batch"] = dict(document.get("series_batch", {}), jobs=jobs)
            from .production_guard import requests_for
            document["plan_sha256"] = digest(requests_for(document))
        target_ids = sorted({item["shot_id"] or item["asset_id"] for item in targets})
        artifact = {"artifact_type": run_type, "artifact_key": "local-run:" + action + ":" + digest(targets),
            "stage": run_stage, "document": document, "dependency_ids": sorted(dependencies), "object_ids": target_ids}
    else:
        raise ResourceError("不支持的局部制作动作", "invalid_local_action")
    _validate_contract(project, artifact)
    result = {"project_id": p, "revision": project["revision"], "action": action, "sources": sources,
              "targets": targets, "artifact": artifact, "needs_approval": True, "read_only": True}
    result["preview_sha256"] = digest(result)
    return result


def preview(store, project_id, payload):
    with store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        return clean(_preview(store, conn, store._project(conn, checked_id(project_id)), payload))


def options(store, project_id, action, entity_id):
    with store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        conn.execute(text("SET TRANSACTION READ ONLY"))
        project = store._project(conn, checked_id(project_id))
        p, entity_id = project["id"], checked_id(entity_id)
        result = {"project_id": p, "revision": project["revision"], "action": action, "entity_id": entity_id, "read_only": True}
        if action == "replace_instance":
            instance = store._one(conn, S.asset_use_instances, p, entity_id)
            identity = store._one(conn, S.creative_objects, p, instance["asset_id"])
            rows = conn.execute(select(S.asset_spec_versions, S.artifact_versions.c.artifact_key,
                S.artifact_versions.c.version, S.artifact_versions.c.sha256).select_from(S.asset_spec_versions.join(S.artifact_versions,
                (S.artifact_versions.c.project_id == S.asset_spec_versions.c.project_id) &
                (S.artifact_versions.c.id == S.asset_spec_versions.c.artifact_id))).where(
                S.asset_spec_versions.c.project_id == p, S.asset_spec_versions.c.asset_id == instance["asset_id"])
                .order_by(S.artifact_versions.c.version.desc(), S.asset_spec_versions.c.id)).mappings()
            result["specs"] = [{"id": row["id"], "title": (identity["title"] or identity["display_code"]) + " · " + row["variant_key"],
                "artifact_id": row["artifact_id"], "artifact_version": row["version"], "sha256": row["sha256"],
                "current_for_instance": row["id"] == instance["spec_version_id"]} for row in rows if store._artifact_approved(conn, p, row["artifact_id"])]
        elif action == "redo_sound":
            store._one(conn, S.shots, p, entity_id)
            result["purposes"] = sorted(set(conn.execute(select(S.generation_jobs.c.purpose).where(
                S.generation_jobs.c.project_id == p, S.generation_jobs.c.shot_id == entity_id,
                S.generation_jobs.c.modality == "audio")).scalars()))
        elif action == "resample":
            job = store._one(conn, S.generation_jobs, p, entity_id)
            model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == job["model_id"])).mappings().one()
            provider = conn.execute(select(S.providers.c.id, S.providers.c.name).where(S.providers.c.id == job["provider_id"])).mappings().one()
            result["job"] = {"id": job["id"], "shot_id": job["shot_id"], "asset_id": job["asset_id"], "purpose": job["purpose"],
                "modality": job["modality"], "status": job["status"], "params": job["request_payload"].get("params", {}),
                "model": {"id": model["id"], "model_key": model["model_key"], "model_version": model["model_version"]}, "provider": dict(provider)}
        else:
            raise ResourceError("不支持的局部制作动作", "invalid_local_action")
        return clean(result)


def propose(store, project_id, payload, **kw):
    def work(conn, project):
        value = _preview(store, conn, project, payload)
        if required(payload, "preview_sha256") != value["preview_sha256"]:
            raise Conflict("局部操作固定输入已改变，请重看影响预览", "local_preview_changed")
        artifact = store._create_artifact(conn, project, dict(value["artifact"], registration_note="局部制作提案：" + value["action"]))
        return {"artifact": artifact, "action": value["action"], "targets": value["targets"], "phase": "pending", "needs_approval": True}
    return store._mutate(project_id, "propose_local_production", payload, callback=work, **kw)


def enqueue_payloads(store, conn, project, artifact_id):
    run = store._one(conn, S.artifact_versions, project["id"], checked_id(artifact_id))
    if not store._artifact_approved(conn, project["id"], run["id"]):
        raise ResourceError("局部运行提案须先批准所见版本", "run_unapproved")
    document = _document(run)
    if run["artifact_type"] not in {"production-run", "vsc.production_run"} or document.get("local_action") not in {"resample", "redo_sound"}:
        raise ResourceError("此产物不是可执行的局部制作提案", "invalid_local_action")
    _validate_contract(project, dict(run, document=document))
    return [{"run_version_id": run["id"], "shot_id": item["request"]["shot_id"], "asset_id": item["request"].get("asset_id"),
            "purpose": item["request"]["purpose"], "modality": item["request"]["modality"], "candidate_no": item["candidate_no"],
            "model_id": item["model_id"], "context_sha256": item["request"]["context_sha256"], "request_payload": item["request"]}
                for item in document["jobs"]]


def enqueue(store, project_id, payload, preflight, **kw):
    if set(payload) != {"artifact_id"}:
        raise ResourceError("执行只接受已批准提案artifact_id，不能另改candidate或请求", "invalid_local_action")
    def work(conn, project):
        jobs = enqueue_payloads(store, conn, project, required(payload, "artifact_id"))
        for item in jobs:
            preflight(project["id"], item)
        return {"artifact_id": payload["artifact_id"], "jobs": [store._create_generation_job(conn, project, item) for item in jobs]}
    return store._mutate(project_id, "enqueue_local_production", payload, callback=work, **kw)
