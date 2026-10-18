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
from .budget_store import native_units, UNITS, operation_key
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
        key = operation_key(logical, candidate)
        if key in result:
            raise ResourceError("运行包存在重复逻辑候选", "invalid_production_run")
        result[key] = logical
    return result


def validate_guard(store, conn, project, run, context=None, job=None, model=None):
    data = run_document(run)
    phase = run_phase(run)
    p = project["id"]
    from .quality_relations import repeated_failures, environment_digest
    if model is None and job:
        model = conn.execute(select(S.provider_models).where(S.provider_models.c.id == job['model_id'])).mappings().one()
    shot = context.get('shot_id') if context else job.get('shot_id') if job else None
    purpose = context.get('purpose') if context else job.get('purpose') if job else None
    history = repeated_failures(store, conn, p, shot, purpose) if shot and purpose else {}
    stopped = {code: jobs for code, jobs in history.items() if len(jobs) >= 2}
    if stopped:
        change = data.get('route_change')
        if not isinstance(change, dict) or not isinstance(change.get('reason'), str) or not change['reason'].strip() or not set(stopped) <= set(change.get('defect_codes', [])):
            raise ResourceError('同镜头用途跨任务累计失败达到阈值，须固定换路线理由和试证；改名不能重置', 'repeated_failure_stop')
        # A new bounded experiment is permitted by its own human-approved run.
        # Formal production instead requires an approved verified evaluation.
        if phase != 'trial' and not change.get('evaluation_ref'):
            raise ResourceError('换路线正式生产需要固定方法评测', 'repeated_failure_stop')
        variables = change.get('changed_variables')
        if not isinstance(variables, list) or not variables or any(not isinstance(v, dict)
                or any(not isinstance(v.get(k), str) or not v[k].strip() for k in ('variable', 'before', 'after'))
                or v['before'].strip().casefold() == v['after'].strip().casefold()
                or v['variable'].strip().casefold() in {'name','label','id','version','method_name'} for v in variables):
            raise ResourceError('换路线须逐项明确实际变量及before/after，名称/编号变化不算新方法', 'repeated_failure_stop')
    pin_ids = {ref.get('id') for ref in data.get('approved_inputs', []) if isinstance(ref, dict)}
    professional = list(conn.execute(select(S.execution_instances).join(S.execution_shots,
        (S.execution_shots.c.project_id == S.execution_instances.c.project_id) & (S.execution_shots.c.execution_id == S.execution_instances.c.id)).where(
            S.execution_instances.c.project_id == p, S.execution_shots.c.shot_id == shot,
            S.execution_instances.c.artifact_id.in_(pin_ids), S.execution_instances.c.domain.in_(['voice'] if purpose in {'tts','dialogue_dry','dialogue'} else ['combat','dance','vfx']))).mappings()) if shot else []
    if phase != "trial" and not data.get("quality_plan") and not professional and not stopped:
        return
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
        for key in ("trial_id", "method_sha256", "hypothesis", "criteria", "stop_condition"):
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
        if not 1 <= len(allowed['allowed_shot_ids']) <= 8:
            raise ResourceError('一次试片限定1至8个相邻镜头', 'trial_scope_invalid')
        shots = [store._one(conn, S.shots, p, identifier) for identifier in allowed['allowed_shot_ids']]
        sequence = {row['parent_id'] for row in shots}
        if len(sequence) != 1:
            raise ResourceError('试片镜头须在同一连续段落', 'trial_scope_invalid')
        ordered = list(conn.execute(select(S.shots.c.id).where(S.shots.c.project_id == p,
            S.shots.c.parent_id == shots[0]['parent_id']).order_by(S.shots.c.ordinal)).scalars())
        indexes = sorted(ordered.index(row['id']) for row in shots)
        if indexes[-1] - indexes[0] + 1 != len(indexes):
            raise ResourceError('试片镜头必须相邻，不能跨过中间镜头', 'trial_scope_invalid')
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
        fixed_context = context['sha256'] if context else job['context_sha256']
        contexts = trial.get('shot_contexts')
        if contexts is None and len(shots) == 1:
            contexts = {shots[0]['id']: trial.get('context_sha256')}
        if not isinstance(contexts, dict) or set(contexts) != allowed['allowed_shot_ids'] or any(not isinstance(sha, str) or len(sha) != 64 or set(sha) - set('0123456789abcdef') for sha in contexts.values()):
            raise ResourceError('多镜试片必须逐镜固定 shot_contexts 摘要', 'trial_context_mismatch')
        if contexts.get(shot) != fixed_context:
            raise ResourceError("试片上下文摘要不匹配", "trial_context_mismatch")
        # Validate the whole bounded sequence before the first paid candidate,
        # so a later shot's missing input cannot be discovered only after spend.
        for identifier in allowed['allowed_shot_ids']:
            purposes = {request['purpose'] for request in requests.values() if request['shot_id'] == identifier}
            if len(purposes) != 1:
                raise ResourceError('每镜试片须固定一个上下文用途；不同用途分开运行', 'trial_scope_invalid')
            compiled = store._compile_context(conn, project, identifier, next(iter(purposes)))
            if not compiled['ready'] or compiled['sha256'] != contexts[identifier]:
                raise ResourceError('试片全范围的逐镜上下文缺失或漂移', 'trial_context_mismatch')
            if not {a['id'] for a in compiled['artifacts']} <= set(pinned):
                raise ResourceError('试片未固定全部相邻镜头输入', 'trial_inputs_missing')
            used = {ref['asset_id'] for ref in compiled.get('state_entity_refs', []) if ref['relation'] in {'in_frame','held','costume'}}
            if compiled.get('state', {}).get('location_id'):
                used.add(compiled['state']['location_id'])
            if not used <= allowed['allowed_asset_ids']:
                raise ResourceError('相邻镜头资产超出试片全范围授权', 'trial_scope_invalid')
        methods = [version for version in versions.values() if version["artifact_type"] == "trial-method"
                   and version["sha256"] == trial["method_sha256"]]
        if len(methods) != 1:
            raise ResourceError("试片方法必须是固定批准依赖", "trial_method_missing")
        method = run_document(methods[0])
        if not isinstance(method.get("method"), str) or not method["method"].strip():
            raise ResourceError("trial-method 必须写明可执行方法", "trial_method_missing")
        if stopped:
            prior_method_ids = set(conn.execute(select(S.quality_observations.c.method_artifact_id).where(
                S.quality_observations.c.project_id == p, S.quality_observations.c.job_id.in_([j for jobs in stopped.values() for j in jobs]))).scalars())
            prior_methods = [run_document(store._one(conn, S.artifact_versions, p, identifier)).get('method') for identifier in prior_method_ids if identifier]
            if ' '.join(method['method'].casefold().split()) in [' '.join(m.casefold().split()) for m in prior_methods if isinstance(m, str)]:
                raise ResourceError('换路线试片须改变实际方法和明确变量，不能仅换版本名', 'repeated_failure_stop')
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

    def evaluate_risk(risk, evaluation):
        ref = risk.get('evaluation_ref', {})
        row = conn.execute(select(S.method_evaluations).where(S.method_evaluations.c.project_id == p,
            S.method_evaluations.c.artifact_id == ref.get('artifact_id'))).mappings().first()
        if row is None or row['result'] != 'pass' or evaluation.get('format') != 'vsc.method-evaluation/v1':
            return ['PG capability evaluation 需要已登记并人工批准的方法实片评测，裸pass不能解锁']
        for key in ('method_artifact_id', 'trial_run_id', 'criteria_artifact_id'):
            if row[key] not in versions or not store._artifact_approved(conn, p, row[key]):
                return ['评测方法/试片/判据依赖缺失或批准失效']
        expected = risk.get('method_artifact_id')
        if expected != row['method_artifact_id']:
            return ['风险必须明确绑定当前使用的固定方法']
        if risk.get('criteria_artifact_id') != row['criteria_artifact_id']:
            return ['风险必须明确绑定本次适用的固定判据']
        criteria_sha = versions[row['criteria_artifact_id']]['sha256']
        for media_id in (row['baseline_media_id'], row['output_media_id']):
            _, gaps = store._usable(conn, p, media_id, purpose or 'video_clip')
            if gaps:
                return ['评测媒体已不可用：' + ','.join(gaps)]
            review = conn.execute(select(S.media_reviews).join(S.binding_candidates,
                (S.binding_candidates.c.project_id == S.media_reviews.c.project_id) & (S.binding_candidates.c.id == S.media_reviews.c.candidate_id)).where(
                    S.media_reviews.c.project_id == p, S.binding_candidates.c.media_id == media_id,
                    S.media_reviews.c.reviewer_type == 'human', S.media_reviews.c.criteria_version == criteria_sha)
                .order_by(S.media_reviews.c.project_revision.desc()).limit(1)).mappings().first()
            if not review or (media_id == row['output_media_id'] and review['outcome'] != 'pass'):
                return ['评测人工审查已失效或发生更晚的不通过决定']
        relevant = [request for request in requests.values() if not shot or (request.get('shot_id') == shot and request.get('purpose') == purpose)]
        if model is None or not relevant or any(environment_digest(model, request) != row['environment_sha256'] for request in relevant):
            return ['评测环境不适用于当前实际模型/版本/能力/控制参数']
        return []

    for execution in professional:
        from vsc.production.performance import prompt_fragment
        bindings = data.get('professional_bindings', [])
        bound = next((row for row in bindings if isinstance(row, dict) and row.get('execution_id') == execution['id']), None)
        relevant = {key: request for key, request in requests.items() if request.get('shot_id') == shot and request.get('purpose') == purpose}
        if execution['domain'] == 'voice':
            relevant = {key: request for key, request in relevant.items() if execution['line_id'] in request.get('script_line_ids', [])}
            if not relevant:
                continue
        if not bound or set(bound.get('job_ids', [])) != set(relevant):
            raise ResourceError('专业执行必须绑定实际全部逻辑任务', 'professional_binding_missing')
        if execution['method_artifact_id'] not in versions:
            raise ResourceError('专业执行方法必须固定到run批准输入', 'professional_input_missing')
        if execution['parameters'].get('route') != 'generation':
            raise ResourceError('本专业执行选择实拍/合成等路线，应使用对应制作操作；不能用生成prompt冒充', 'professional_route_mismatch')
        fragment = prompt_fragment(execution['domain'], execution['parameters'])
        for request in relevant.values():
            if execution['domain'] != 'voice' and fragment not in request['prompt']:
                raise ResourceError('专业规格未进入固定生成请求', 'professional_input_missing')
            materials = list(conn.execute(select(S.execution_materials).where(S.execution_materials.c.project_id == p,
                S.execution_materials.c.execution_id == execution['id'])).mappings())
            if any(m['role'] in {'mask', 'depth'} for m in materials):
                raise ResourceError('当前逻辑生成请求没有蒙版/深度控制通道，不能把普通参考当控制；使用已支持的合成操作或改设计', 'professional_control_unsupported')
            used_media = set(request.get('reference_media_ids', []) + request.get('reference_audio_media_ids', [])) | {request.get('first_frame_media_id'), request.get('last_frame_media_id'), request.get('voice_media_id')}
            if any(m['media_id'] not in used_media for m in materials if m['role'] in {'music', 'reference', 'voice', 'plate', 'mask', 'depth'}):
                raise ResourceError('专业执行的固定素材未进入实际请求；不支持时改设计/合成路线', 'professional_input_missing')
            if execution['domain'] == 'voice':
                # Audio prompt is the exact approved line, never an instruction
                # suffix that would be spoken aloud. Control binding is explicit.
                voices = context.get('voices', []) if context else [job['request_payload'].get('voice_binding', {})]
                from vsc.production.performance import voice_control_problems
                voice_problems = voice_control_problems(execution['parameters'], model, execution['voice_spec_id'], voices)
                if voice_problems:
                    raise ResourceError('; '.join(voice_problems), 'professional_control_unsupported')
    if stopped and phase != 'trial':
        ref = data['route_change'].get('evaluation_ref')
        evaluation = json.loads(read_ref(ref))
        problems = evaluate_risk(dict(data['route_change'], evaluation_ref=ref), evaluation)
        if problems:
            raise ResourceError('; '.join(problems), 'repeated_failure_stop')
        failed_jobs = [identifier for jobs in stopped.values() for identifier in jobs]
        prior = list(conn.execute(select(S.quality_observations).where(S.quality_observations.c.project_id == p,
            S.quality_observations.c.job_id.in_(failed_jobs))).mappings())
        changed_method = run_document(versions[evaluation['method_artifact_id']]).get('method')
        old_methods = [run_document(store._one(conn, S.artifact_versions, p, row['method_artifact_id'])).get('method')
                       for row in prior if row['method_artifact_id']]
        eval_version = versions[ref['artifact_id']]
        observation_times = [store._one(conn, S.artifact_versions, p, row['artifact_id'])['created_at'] for row in prior]
        same_method = isinstance(changed_method, str) and ' '.join(changed_method.casefold().split()) in [' '.join(m.casefold().split()) for m in old_methods if isinstance(m, str)]
        if same_method or any(t >= eval_version['created_at'] for t in observation_times):
            raise ResourceError('停止后的正式恢复须有不同方法及晚于失败观察的新试证，旧pass不能重置历史', 'repeated_failure_stop')

    from vsc.production.run_quality import quality_errors
    errors = quality_errors(data, ".", {"project_id": p}, {}, requests, read_ref=read_ref, evaluate_risk=evaluate_risk)
    if errors:
        raise ResourceError("质量检查阻止执行: " + "; ".join(errors), "quality_plan_blocked")


def validate_submission(store, conn, project, job):
    if job["status"] == "created":
        store.check_job_script_confirmation(conn, project, shot_id=job.get("shot_id"), asset_id=job.get("asset_id"), run_version_id=job["run_version_id"])
        request = job["request_payload"]
        if request.get("operation"):
            from vsc.production.video_operations import validate_source_metadata
            source, gaps = store._usable(conn, project["id"], request["source_media_id"], job["purpose"])
            if gaps:
                raise ResourceError("固定加工源片不再可用: " + ",".join(gaps), "operation_source_unusable")
            validate_source_metadata(request, source)
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
