"""Bounded run task graphs over existing immutable runs and generation jobs.

No secondary queue: readiness is reconstructed from the run, selected media and
durable jobs. Each batch creates only ready jobs; the runtime advances successors.
"""
import copy
import hashlib
import json
import uuid

from vsc.assets.resource_service import Conflict, ResourceError
from vsc.production.run_authorization import normalize_request
from vsc.production.run_policy import enforce_execution_policy, policy_errors

OUTPUT_FIELDS = {"reference_media_ids", "reference_audio_media_ids", "first_frame_media_id",
                 "last_frame_media_id", "voice_media_id"}
LIST_FIELDS = {"reference_media_ids", "reference_audio_media_ids"}


def tasks(run):
    return run.get("series_batch", {}).get("jobs", run.get("jobs", []))


def request_for(task):
    return task.get("request", task.get("request_payload", {}))


def task_identity(task):
    request = request_for(task)
    return (request.get("shot_id", task.get("shot_id")), request.get("asset_id", task.get("asset_id")),
            request.get("purpose", task.get("purpose")), task.get("candidate_no", 0))


def matches_job(task, job):
    return task_identity(task) == (job.get("shot_id"), job.get("asset_id"), job.get("purpose"), job.get("candidate_no", 0))


def graph_errors(run):
    if not isinstance(run, dict) or ("series_batch" in run and not isinstance(run["series_batch"], dict)):
        return ["有界运行及 series_batch 必须为对象"]
    rows = tasks(run)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        return ["有界运行必须含非空任务数组"]
    errors = policy_errors(run.get("execution_policy"))
    if run.get("execution_policy") is None:
        errors.append("有界任务图必须固定 execution_policy")
    keys = [row.get("task_key") for row in rows]
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        return errors + ["task_key 必须非空且在运行内唯一"]
    if len(set(keys)) != len(keys):
        return errors + ["task_key 必须非空且在运行内唯一"]
    if any(not isinstance(request_for(row), dict) for row in rows):
        return errors + ["固定任务 request 必须为对象"]
    for row in rows:
        identity = task_identity(row)
        if any(value is not None and (not isinstance(value, str) or not value) for value in identity[:3]):
            return errors + ["任务对象和用途必须是非空文本"]
        if type(identity[3]) is not int or identity[3] < 0:
            return errors + ["候选序号必须为非负整数"]
    if len({task_identity(row) for row in rows}) != len(rows):
        errors.append("同一对象、用途与候选序号不能登记多个逻辑任务")
    by_key = dict(zip(keys, rows))
    for row in rows:
        request = request_for(row)
        if bool(request.get("shot_id", row.get("shot_id"))) == bool(request.get("asset_id", row.get("asset_id"))):
            errors.append("任务必须指定且仅指定镜头或资产")
        deps = row.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in by_key for dep in deps):
            errors.append("depends_on 必须仅引用本运行的 task_key")
            continue
        if len(set(deps)) != len(deps) or row["task_key"] in deps:
            errors.append("任务依赖重复或引用自身")
        if not isinstance(row.get("model_id"), str) or not row["model_id"]:
            errors.append("每个有界任务必须固定 model_id")
        candidate = row.get("candidate_no", 0)
        if type(candidate) is not int or candidate < 0:
            errors.append("候选序号必须为非负整数")
        try:
            normalize_request(request, request.get("shot_id", row.get("shot_id")),
                request.get("purpose", row.get("purpose")), request.get("modality", row.get("modality")),
                asset_id=request.get("asset_id", row.get("asset_id")))
        except (ResourceError, AttributeError, TypeError) as exc:
            errors.append("固定任务请求无效: " + str(exc))
        refs = row.get("output_inputs", [])
        if not isinstance(refs, list):
            errors.append("output_inputs 必须为数组")
            continue
        for ref in refs:
            if (not isinstance(ref, dict) or ref.get("task_key") not in deps or ref.get("field") not in OUTPUT_FIELDS
                    or not isinstance(ref.get("role"), str) or not ref.get("role")
                    or type(ref.get("output_index", 0)) is not int or ref.get("output_index", 0) < 0):
                errors.append("输出引用须固定直接上游任务、字段、用途和输出序号")
    visiting, visited = set(), set()
    def visit(key):
        if key in visiting:
            errors.append("任务依赖不得成环")
            return
        if key in visited:
            return
        visiting.add(key)
        deps = by_key[key].get("depends_on", [])
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, str) and dep in by_key:
                    visit(dep)
        visiting.remove(key)
        visited.add(key)
    for key in keys:
        visit(key)
    return errors


def resolve_request(task, context, task_outputs):
    """Resolve only approved upstream outputs that are selected in this context.

``task_outputs`` is compiled by the caller from same-run durable jobs and their
real stored output SHA. It must never come directly from an HTTP payload.
    """
    request = copy.deepcopy(request_for(task))
    for dependency in task.get("depends_on", []):
        result = task_outputs.get(dependency)
        if not result or result.get("status") != "succeeded":
            raise ResourceError("上游任务尚未成功，保留依赖等待", "task_dependency_waiting")
    for ref in task.get("output_inputs", []):
        result = task_outputs.get(ref["task_key"], {})
        outputs = result.get("outputs", [])
        index = ref.get("output_index", 0)
        # Worker output IDs encode the provider output ordinal. SQL row order
        # is not a stable ordering and must not select a different result.
        try:
            expected_id = str(uuid.uuid5(uuid.UUID(result["job_id"]), "output:" + str(index)))
        except (KeyError, ValueError, TypeError) as exc:
            raise ResourceError("上游任务身份无效", "task_output_missing") from exc
        output = next((item for item in outputs if item["media_id"] == expected_id), None)
        if output is None:
            raise ResourceError("上游输出序号不存在", "task_output_missing")
        selected = [media for media in context.get("media", []) if media["media_id"] == output["media_id"]
                    and media["sha256"] == output["sha256"] and media["role"] == ref["role"]
                    and media.get("binding_decision_id")]
        if not selected:
            raise ResourceError("上游输出尚未按指定用途有效选择，不能自动采用", "task_output_not_selected")
        field = ref["field"]
        if field in LIST_FIELDS:
            request.setdefault(field, [])
            if output["media_id"] not in request[field]:
                request[field].append(output["media_id"])
        else:
            if request.get(field) not in (None, output["media_id"]):
                raise ResourceError("固定输入与上游输出占用同一字段", "task_output_conflict")
            request[field] = output["media_id"]
    return request


def _all_jobs(service, project_id):
    result, offset = [], 0
    while True:
        page = service.list_generation_jobs(project_id, offset=offset, limit=200)
        result.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            return result


def _document(artifact):
    try:
        value = artifact["document"]
        document = json.loads(value) if isinstance(value, (str, bytes)) else value
        if not isinstance(document, dict):
            raise ValueError("run must be an object")
        return document
    except (ValueError, TypeError, KeyError) as exc:
        raise ResourceError("运行包必须为固定 JSON 文档", "invalid_production_run") from exc


def preview_batch(service, project_id, payload):
    run_id = payload.get("run_version_id")
    if not run_id:
        raise ResourceError("批量操作必须指定固定运行版本", "run_version_required")
    artifact = service.get_artifact_version(project_id, run_id)
    if payload.get("run_sha256") and payload["run_sha256"] != artifact["sha256"]:
        raise Conflict("运行包摘要与预览不符", "run_sha256_mismatch")
    if artifact.get("artifact_type") not in {"production-run", "vsc.production_run"} or not artifact.get("approved"):
        raise ResourceError("批量操作须使用已批准运行包", "run_unapproved")
    run = _document(artifact)
    errors = graph_errors(run)
    if errors:
        raise ResourceError("；".join(errors), "invalid_task_graph")
    rows = tasks(run)
    requested = payload.get("task_keys")
    if requested is not None and (not isinstance(requested, list) or
            any(key not in {row["task_key"] for row in rows} for key in requested)):
        raise ResourceError("任务选择超出固定运行包", "task_scope_mismatch")
    jobs = _all_jobs(service, project_id)
    same_run = [job for job in jobs if job["run_version_id"] == run_id]
    fixed, originals = {}, {run_id: run}
    for job in jobs:
        original_id = job["run_version_id"]
        if original_id not in originals:
            originals[original_id] = _document(service.get_artifact_version(project_id, original_id))
        job["execution_policy"] = originals[original_id].get("execution_policy")
    for row in rows:
        matches = [job for job in same_run if matches_job(row, job)]
        if len(matches) > 1:
            raise ResourceError("固定任务存在多个实际 job，须显式处理冲突", "task_job_conflict")
        if matches:
            detail = service.get_generation_job(project_id, matches[0]["id"])
            outputs = []
            for output in detail.get("outputs", []):
                media = service.get_media(project_id, output["media_id"])
                outputs.append({"media_id": media["id"], "sha256": media["sha256"]})
            fixed[row["task_key"]] = {"job_id": detail["id"], "status": detail["status"], "outputs": outputs}
    result = []
    for row in rows:
        key = row["task_key"]
        if requested is not None and key not in requested:
            continue
        shot, asset, purpose, candidate = task_identity(row)
        item = {"task_key": key, "target_id": shot or asset, "purpose": purpose, "gaps": []}
        if key in fixed:
            item.update(status="existing", job_id=fixed[key]["job_id"], job_status=fixed[key]["status"])
            result.append(item)
            continue
        blocked = [dep for dep in row.get("depends_on", []) if fixed.get(dep, {}).get("status") in {"failed", "cancelled"}]
        waiting = [dep for dep in row.get("depends_on", []) if fixed.get(dep, {}).get("status") != "succeeded"]
        if waiting:
            item.update(status="blocked" if blocked else "waiting", gaps=[{"code": "task_dependency_failed" if blocked
                else "task_dependency_waiting", "task_keys": blocked or waiting}])
            result.append(item)
            continue
        try:
            from vsc.production.run_policy import authorization_policy
            target = {"project_id": project_id, "run_version_id": run_id,
                      "shot_id": shot, "asset_id": asset, "purpose": purpose}
            inherited = authorization_policy(run, run_id, target,
                lambda identifier: service.get_artifact_version(project_id, identifier))
            enforce_execution_policy(run, target, jobs, inherited_policy=inherited)
            context = (service.compile_asset_context(project_id, asset, purpose,
                           spec_version_id=request_for(row).get("spec_version_id")) if asset else
                       service.compile_shot_context(project_id, shot, purpose))
            if not context["ready"]:
                item.update(status="blocked", gaps=context["gaps"])
            else:
                request = resolve_request(row, context, fixed)
                item.update(status="ready", payload={"shot_id": shot, "asset_id": asset, "purpose": purpose,
                    "modality": request.get("modality", row.get("modality")), "model_id": row["model_id"],
                    "run_version_id": run_id, "candidate_no": candidate,
                    "context_sha256": context["sha256"], "request_payload": request})
        except ResourceError as exc:
            item.update(status="waiting" if exc.code in {"task_dependency_waiting", "task_output_not_selected"} else "blocked",
                        gaps=[{"code": exc.code, "message": str(exc)}])
        result.append(item)
    return {"run_version_id": run_id, "run_sha256": artifact["sha256"], "tasks": result,
            **{status + "_count": sum(row["status"] == status for row in result)
               for status in ("ready", "waiting", "blocked", "existing")}}


def execute_batch(service, project_id, payload, actor):
    """Create ready jobs only; no provider calls and no implicit decisions."""
    preview = preview_batch(service, project_id, payload)
    for task in preview["tasks"]:
        if task["status"] != "ready":
            continue
        key = "bounded-run:" + hashlib.sha256((preview["run_version_id"] + ":" + task["task_key"]).encode()).hexdigest()
        for attempt in range(3):
            revision = service.get_project(project_id)["revision"]
            try:
                job = service.create_generation_job(project_id, task["payload"], expected_revision=revision,
                    idempotency_key=key, actor=actor)
                task.update(status="created", job_id=job["id"], job_status=job["status"])
                break
            except Conflict as exc:
                if exc.code == "revision_conflict" and attempt < 2:
                    continue
                task.update(status="blocked", gaps=[{"code": exc.code, "message": str(exc)}])
                break
            except ResourceError as exc:
                task.update(status="blocked", gaps=[{"code": exc.code, "message": str(exc)}])
                break
        task.pop("payload", None)
    return {**preview, **{status + "_count": sum(row["status"] == status for row in preview["tasks"])
                        for status in ("ready", "created", "waiting", "blocked", "existing")}}


def advance_batches(service, project_id=None, actor="generation-runtime"):
    """Continue only runs explicitly started by a prior durable job creation."""
    projects = [{"id": project_id}] if project_id else service.list_projects()
    if isinstance(projects, dict):
        projects = projects["items"]
    results = []
    for project in projects:
        p = project["id"]
        started = {job["run_version_id"] for job in _all_jobs(service, p)}
        for run_id in sorted(started):
            artifact = service.get_artifact_version(p, run_id)
            run = _document(artifact)
            if artifact.get("approved") and run.get("execution_policy"):
                try:
                    results.append(execute_batch(service, p, {"run_version_id": run_id}, actor))
                except ResourceError:
                    # A revoked or malformed run does not block other runs.
                    continue
    return results
