"""Consume approved trial/quality evidence before creating or submitting jobs.

PostgreSQL evidence is read from immutable artifact bytes via typed run
dependencies. No temporary files, JSON mirrors or provider calls are involved.
Runs without the opt-in fields retain their previous authorization behavior.
"""
import json
from sqlalchemy import select, text
from vsc.assets.resource_service import ResourceError, ResourceService, INHERITED_REFERENCE_ROLES
from vsc.production.run_authorization import normalize_request
from . import schema as S
from .budget_store import native_units, UNITS
from .values import digest, checked_id


REFERENCE_ROLES = INHERITED_REFERENCE_ROLES | {"composition", "first_frame", "last_frame", "reference_audio"}


def run_document(run):
    try:
        value = json.loads(run["document"])
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ResourceError("运行包必须是固定结构文档", "invalid_production_run") from exc
    if not isinstance(value, dict):
        raise ResourceError("运行包必须是对象", "invalid_production_run")
    return value


def run_phase(run):
    phase = run_document(run).get("phase", "production")
    if phase not in {"production", "asset", "trial"}:
        raise ResourceError("运行阶段必须为 production、asset 或 trial", "invalid_run_phase")
    return phase


def requests_for(run):
    batch = run.get("series_batch", {})
    if not isinstance(batch, dict):
        raise ResourceError("series_batch 必须为对象", "invalid_production_run")
    jobs = batch.get("jobs", run.get("jobs", []))
    if not isinstance(jobs, list) or not jobs:
        raise ResourceError("运行包缺少明确任务", "invalid_production_run")
    result = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ResourceError("运行任务格式不合法", "invalid_production_run")
        request = job.get("request", job.get("request_payload"))
        if not isinstance(request, dict):
            raise ResourceError("运行任务缺少固定请求", "invalid_production_run")
        shot = request.get("shot_id", job.get("shot_id"))
        asset = request.get("asset_id", job.get("asset_id"))
        purpose = request.get("purpose", job.get("purpose"))
        modality = request.get("modality", job.get("modality"))
        candidate = job.get("candidate_no", 0)
        if type(candidate) is not int or candidate < 0:
            raise ResourceError("候选编号必须是非负整数", "invalid_production_run")
        logical = normalize_request(request, shot, purpose, modality, asset_id=asset)
        key = "%s:%s:%s:%s" % ("asset" if asset else "series", asset or shot, purpose, candidate)
        if key in result:
            raise ResourceError("运行包存在重复逻辑候选", "invalid_production_run")
        result[key] = logical
    return result


def validate_guard(store, conn, project, run, context=None, job=None):
    data = run_document(run)
    phase = run_phase(run)
    if phase != "trial" and not data.get("quality_plan"):
        return
    p = project["id"]
    if not store._artifact_approved(conn, p, run["id"]):
        raise ResourceError("运行包批准已失效", "run_unapproved")
    if data.get("project_id") != p:
        raise ResourceError("质量运行包必须固定本项目身份", "quality_project_mismatch")
    requests = requests_for(data)
    if data.get("plan_sha256") != digest(requests):
        raise ResourceError("plan_sha256 必须匹配规范化的任务映射", "quality_plan_binding_mismatch")
    dependencies = set(conn.execute(select(S.artifact_dependencies.c.dependency_id).where(
        S.artifact_dependencies.c.project_id == p, S.artifact_dependencies.c.artifact_id == run["id"])).scalars())
    pinned = {ref.get("id"): ref.get("sha256") for ref in data.get("approved_inputs", []) if isinstance(ref, dict)}
    if set(pinned) != dependencies:
        raise ResourceError("运行包固定输入与关系依赖不符", "run_dependency_mismatch")
    versions = {}
    for identifier, sha in pinned.items():
        version = store._one(conn, S.artifact_versions, p, identifier)
        if version["sha256"] != sha or not store._artifact_approved(conn, p, identifier):
            raise ResourceError("运行包固定证据摘要或批准失效", "run_inputs_mismatch")
        versions[identifier] = version

    if phase == "trial":
        trial = data.get("trial")
        if not isinstance(trial, dict):
            raise ResourceError("试片须有固定 trial 规格", "trial_spec_required")
        for key in ("trial_id", "context_sha256", "method_sha256", "hypothesis", "criteria", "stop_condition"):
            if not isinstance(trial.get(key), str) or not trial[key].strip():
                raise ResourceError("试片缺少 " + key, "trial_spec_required")
        if trial.get("output_use", "preproduction_only") != "preproduction_only":
            raise ResourceError("试片产出须保留为前期候选", "trial_output_scope")
        if type(trial.get("max_remote_jobs")) is not int or not 1 <= len(requests) <= trial["max_remote_jobs"]:
            raise ResourceError("试片次数超过明确授权", "trial_job_limit")
        allowed = {}
        for key in ("allowed_shot_ids", "allowed_asset_ids"):
            values = trial.get(key)
            if not isinstance(values, list) or any(not isinstance(x, str) for x in values) or len(set(values)) != len(values):
                raise ResourceError("试片范围须为唯一ID数组", "trial_scope_invalid")
            allowed[key] = set(values)
        if len(allowed["allowed_shot_ids"]) != 1:
            raise ResourceError("本版PG试片须限定一个镜头及其固定上下文；不同镜头分别批准运行包", "trial_scope_invalid")
        for identifier in allowed["allowed_shot_ids"]:
            store._one(conn, S.shots, p, identifier)
        for identifier in allowed["allowed_asset_ids"]:
            store._one(conn, S.asset_identities, p, identifier)
        operations = data.get("operations")
        if not isinstance(operations, dict):
            raise ResourceError("试片必须明确每个候选的原生预算", "run_budget_unauthorized")
        for key, logical in requests.items():
            if logical.get("asset_id") or logical["shot_id"] not in allowed["allowed_shot_ids"] or logical["modality"] not in {"image", "video"}:
                raise ResourceError("试片请求超出镜头或模态范围", "trial_scope_invalid")
            bound = operations.get(key)
            requested = native_units(logical)
            if not isinstance(bound, dict) or set(bound) - UNITS or any(type(bound.get(unit)) is not int or bound[unit] < count for unit, count in requested.items()):
                raise ResourceError("每个试片候选必须有原生单位预算", "run_budget_unauthorized")
        fixed_context = context["sha256"] if context else job["context_sha256"]
        if trial["context_sha256"] != fixed_context:
            raise ResourceError("试片上下文摘要不匹配", "trial_context_mismatch")
        methods = [version for version in versions.values() if version["artifact_type"] == "trial-method"
                   and version["sha256"] == trial["method_sha256"]]
        if len(methods) != 1:
            raise ResourceError("试片方法必须是固定批准依赖", "trial_method_missing")
        method = run_document(methods[0])
        if not isinstance(method.get("method"), str) or not method["method"].strip():
            raise ResourceError("trial-method 必须写明可执行方法", "trial_method_missing")
        if context:
            # Scope and Profile requirements come from the existing gate; an
            # unrelated episode's approved screenplay is not sufficient.
            from vsc.project.pg_workflow import check_gate
            gate = check_gate(ResourceService(store), p, "script", scope=context["ancestors"][1])
            if not gate["passed"] or not {ref["id"] for ref in gate["artifacts"]} <= set(pinned):
                raise ResourceError("试片须固定当前镜头范围的script Gate输入", "trial_script_gate_failed")
            context_ids = {a["id"] for a in context["artifacts"]}
        else:
            context_ids = set(conn.execute(select(S.job_input_versions.c.artifact_id).where(
                S.job_input_versions.c.project_id == p, S.job_input_versions.c.job_id == job["id"])).scalars())
        kinds = {version["artifact_type"].replace("vsc.", "").replace("-", "_") for identifier, version in versions.items() if identifier in context_ids}
        if not {"screenplay", "asset_bible", "shot_plan"} <= kinds:
            raise ResourceError("试片需要固定批准剧本、资产规格与镜头规格", "trial_inputs_missing")
        if context:
            used = {ref["asset_id"] for ref in context.get("state_entity_refs", []) if ref["relation"] in {"in_frame", "held", "costume"}}
            if context.get("state", {}).get("location_id"):
                used.add(context["state"]["location_id"])
            if not used <= allowed["allowed_asset_ids"]:
                raise ResourceError("镜头状态资产超出试片授权范围", "trial_scope_invalid")
        if not data.get("quality_plan"):
            raise ResourceError("试片必须固定质量检查包", "quality_plan_required")

    def read_ref(ref):
        identifier = ref.get("artifact_id")
        if not identifier or identifier not in versions or versions[identifier]["sha256"] != ref.get("sha256"):
            raise ValueError("证据必须引用本项目 run 的固定批准依赖")
        return bytes(versions[identifier]["document"])

    from vsc.production.run_quality import quality_errors
    errors = quality_errors(data, ".", {"project_id": p}, {}, requests, read_ref=read_ref)
    if phase != "trial":
        try:
            package = json.loads(read_ref(data["quality_plan"]))
        except (ValueError, KeyError):
            package = None
        if isinstance(package, dict) and package.get("risks"):
            errors.insert(0, "PG capability evaluation 权威尚未接入，正式 run 的风险评测引用不能自动解锁。"
                          "保留原试片证据，将已确认结论落实到获批规格和实际请求的必要条件；未决风险不能删除或标记假通过。重复提交不能解决此限制。")
    if errors:
        raise ResourceError("质量检查阻止执行: " + "; ".join(errors), "quality_plan_blocked")


def validate_submission(store, conn, project, job):
    run = store._one(conn, S.artifact_versions, project["id"], job["run_version_id"])
    validate_guard(store, conn, project, run, job=job)


def trial_sources(conn, p, media_id):
    """Trace only registered operation derivation, never names or similarity."""
    return [dict(row) for row in conn.execute(text("""WITH RECURSIVE ancestry(id) AS (
        SELECT CAST(:media AS uuid) UNION
        SELECT i.media_id FROM ancestry a JOIN operation_outputs o ON o.project_id=:project AND o.media_id=a.id
        JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id)
        SELECT DISTINCT r.id, r.sha256 FROM ancestry a JOIN job_outputs o ON o.project_id=:project AND o.media_id=a.id
        JOIN generation_jobs j ON j.project_id=o.project_id AND j.id=o.job_id
        JOIN artifact_versions r ON r.project_id=j.project_id AND r.id=j.run_version_id
        WHERE r.artifact_type IN ('production-run','vsc.production_run')
        AND convert_from(r.document,'UTF8')::jsonb->>'phase'='trial'"""), {"project": p, "media": media_id}).mappings()]


def validate_adoption(store, conn, project, candidate, slot, payload):
    if slot["role"] in REFERENCE_ROLES:
        return []
    origins = trial_sources(conn, project["id"], candidate["media_id"])
    if not origins:
        return []
    adoption = payload.get("trial_adoption")
    if not isinstance(adoption, dict) or not isinstance(adoption.get("reason"), str) or not adoption["reason"].strip():
        raise ResourceError("试片正式采用须在本次选择明确 trial_adoption 理由", "trial_adoption_required")
    if payload.get("delegation_artifact_id"):
        raise ResourceError("试片转正式采用须由当前人工选择决定", "trial_adoption_human_required")
    p = project["id"]
    animatic = store._one(conn, S.artifact_versions, p, adoption.get("animatic_version_id"))
    if animatic["artifact_type"] not in {"vsc.animatic", "animatic"} or not store._artifact_approved(conn, p, animatic["id"]):
        raise ResourceError("试片正式采用需要已批准预演版本", "trial_animatic_required")
    from vsc.project.pg_workflow import check_gate
    target = store._one(conn, S.creative_objects, p, slot["target_object_id"])
    scope = None
    if target["kind"] == "episode":
        scope = target["id"]
    elif target["kind"] in {"scene", "sequence", "shot"}:
        table = {"scene": S.scenes, "sequence": S.sequences, "shot": S.shots}[target["kind"]]
        row = store._one(conn, table, p, target["id"])
        while table is not S.scenes:
            table = S.sequences if table is S.shots else S.scenes
            row = store._one(conn, table, p, row["parent_id"])
        scope = row["parent_id"]
    gate = check_gate(ResourceService(store), p, "animatic", scope=scope)
    if not gate["passed"] or animatic["id"] not in {ref["id"] for ref in gate["artifacts"]}:
        raise ResourceError("试片正式采用的预演Gate或范围未通过", "trial_animatic_required")
    decision = store._latest(conn, S.artifact_decisions, p, "artifact_id", animatic["id"])
    return [{"run_version_id": row["id"], "animatic_version_id": animatic["id"], "animatic_approval_id": decision["id"]} for row in origins]
