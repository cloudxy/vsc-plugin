#!/usr/bin/env python3
"""Offline model registry and idempotent job planning for the series Profile.

No adapter is invoked here. The dispatcher consumes created jobs through
vsc_provider's modality contract after budget reservation and capability checks.
"""
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

from vsc.adapters.providers import credentials as credentials
from vsc.adapters.persistence.sqlite import series as db
from vsc.production.context import SeriesError, _artifact_document, build_shot_context, covered_script_units, series_state, stamp
from vsc.production.providers import AudioRequest, ImageRequest, VideoRequest
from vsc.project.state import project_lock

REQUEST_TYPES = {"image": ImageRequest, "video": VideoRequest, "audio": AudioRequest}


def audio_binding(project, context, logical):
    """Validate dialogue against approved script, shot coverage and voice identity."""
    line_ids = logical.script_line_ids
    if (logical.purpose != "dialogue_dry" or not isinstance(line_ids, (tuple, list))
            or len(line_ids) != 1 or not isinstance(line_ids[0], str) or not line_ids[0]):
        raise SeriesError("干声任务须绑定一条已批准剧本台词行")
    lines = [line for line in context["script_scene"].get("dialogue", [])
             if line.get("id") == line_ids[0]]
    if len(lines) != 1 or logical.prompt != lines[0].get("text"):
        raise SeriesError("音频文本须与已批准剧本台词逐字一致")
    coverage_ref, covered_units = covered_script_units(project, logical.shot_id)
    if line_ids[0] not in covered_units:
        raise SeriesError("已批准覆盖计划未把此台词行分配给当前镜头")
    speaker = lines[0].get("speaker")
    voice = context["audio_anchor"]["pack"]["entities"].get(speaker, {}).get("voice")
    if (not isinstance(voice, dict) or voice.get("rights") not in ("owned", "licensed")
            or not isinstance(voice.get("voice"), str) or not voice["voice"]):
        raise SeriesError("说话人物须有已批准且可用的音色绑定")
    return {"line_id": line_ids[0], "entity_id": speaker, "voice": voice,
            "audio_anchor_sha256": context["audio_anchor"]["sha256"]}, coverage_ref


def register_provider(project, name, modalities, auth_ref=None, base_url=None, rate_limit=None):
    series_state(project)
    if not name or not modalities or any(m not in REQUEST_TYPES for m in modalities):
        raise SeriesError("Provider 名称与模态必须明确")
    if auth_ref and not auth_ref.startswith("env:"):
        raise SeriesError(f"auth_ref 只能指向环境变量，例如 env:{credentials.KEY_ENV}")
    if name == "volc_ark":
        if auth_ref != f"env:{credentials.KEY_ENV}":
            raise SeriesError("火山方舟 Agent Plan Provider 须使用专属 key 的环境变量引用")
        if base_url and base_url.rstrip("/") != credentials.PLAN_BASE:
            raise SeriesError("火山方舟 Agent Plan Provider 须使用专属 Base URL")
        base_url = credentials.PLAN_BASE
    with project_lock(Path(project)), db.connect(project) as connection:
        connection.execute("INSERT INTO providers VALUES (?,?,?,?,?,?,?)",
            (name, db.canonical(sorted(set(modalities))), base_url, auth_ref, 1, rate_limit, stamp()))


def register_model(project, provider, model_id, model_key, modality, model_version, capabilities,
                   default_params=None, cost_rule=None):
    series_state(project)
    if modality not in REQUEST_TYPES or not model_version or not model_key:
        raise SeriesError("模型模态、标识和版本必须明确")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("purposes"), list):
        raise SeriesError("模型能力须包含 purposes 数组")
    if not all(isinstance(value, str) and value for value in capabilities["purposes"]):
        raise SeriesError("模型用途必须是非空字符串")
    if any(not isinstance(capabilities[key], int) or capabilities[key] < 1
           for key in ("max_duration_ms", "max_width", "max_height") if key in capabilities):
        raise SeriesError("模型能力上限须为正整数")
    with project_lock(Path(project)), db.connect(project) as connection:
        owner = connection.execute("SELECT modalities FROM providers WHERE name=? AND enabled=1", (provider,)).fetchone()
        if not owner or modality not in json.loads(owner["modalities"]):
            raise SeriesError("Provider 未启用此模态")
        connection.execute("INSERT INTO provider_models VALUES (?,?,?,?,?,?,?,?,?)",
            (model_id, provider, model_key, modality, model_version, db.canonical(capabilities),
             db.canonical(default_params or {}), db.canonical(cost_rule or {}), 1))


def set_route(project, modality, purpose, model_id):
    series_state(project)
    with project_lock(Path(project)), db.connect(project) as connection:
        model = connection.execute("SELECT provider FROM provider_models WHERE id=? AND modality=? AND enabled=1",
            (model_id, modality)).fetchone()
        if not model:
            raise SeriesError("路由模型不存在或模态不匹配")
        connection.execute("INSERT INTO provider_routes VALUES (?,?,?,?,1) ON CONFLICT(modality,purpose) DO UPDATE SET "
            "provider=excluded.provider,model_id=excluded.model_id,enabled=1",
            (modality, purpose, model["provider"], model_id))


def plan_job(project, run_id, request, candidate_no=1):
    """Persist one immutable logical request; repeat calls return the same job."""
    state = series_state(project)
    if not isinstance(request, dict) or request.get("format") != "vsc.generation-request/v1":
        raise SeriesError("请求必须是 vsc.generation-request/v1")
    modality = request.get("modality")
    purpose = request.get("purpose")
    shot_id = request.get("shot_id")
    if modality not in REQUEST_TYPES or not isinstance(purpose, str) or not purpose or not isinstance(shot_id, str):
        raise SeriesError("请求须有模态、用途和镜头 ID")
    if candidate_no < 1:
        raise SeriesError("候选编号须为正整数")
    context = build_shot_context(project, shot_id)
    boundary = context["cross_episode_boundary"]
    if boundary and boundary["status"] != "linked":
        raise SeriesError("相邻集末镜与本集首镜未形成有效衔接决定")
    if context["unresolved_reference_asset_ids"]:
        raise SeriesError("镜头缺少已批准参考素材绑定：" + ", ".join(context["unresolved_reference_asset_ids"]))
    if request.get("context_sha256") != context["sha256"]:
        raise SeriesError("镜头上下文已变化，先重新编译请求")
    fields = {key: value for key, value in request.items() if key not in ("format", "modality")}
    try:
        logical = REQUEST_TYPES[modality](**fields)
    except TypeError as exc:
        raise SeriesError("请求字段不符合统一接口：" + str(exc)) from None
    if not isinstance(logical.prompt, str) or not logical.prompt.strip() or not isinstance(logical.params, dict):
        raise SeriesError("请求须有非空提示词和参数对象")
    if any(key in logical.params for key in ("provider", "model", "external_task_id", "base_url", "auth_ref")):
        raise SeriesError("业务请求参数不能包含供应商、模型或外部任务字段")
    if not isinstance(logical.reference_media_ids, (list, tuple)) or not all(
            isinstance(value, str) and value for value in logical.reference_media_ids):
        raise SeriesError("参考媒体 ID 必须是字符串数组")
    if modality == "image" and (not isinstance(logical.width, int) or not isinstance(logical.height, int)
                                or logical.width < 1 or logical.height < 1):
        raise SeriesError("图片宽高须为正整数")
    if modality == "video" and (not isinstance(logical.duration_ms, int) or logical.duration_ms < 1):
        raise SeriesError("视频时长须为正整数")
    if getattr(logical, "reference_audio_media_ids", ()):
        raise SeriesError("独立视频音频参考目前须使用PostgreSQL固定用途与任务接口")
    voice_binding = None
    coverage_ref = None
    if modality == "audio":
        voice_binding, coverage_ref = audio_binding(project, context, logical)
    media_ids = {entry["media_id"] for entry in context["media_references"]}
    if set(logical.reference_media_ids) - media_ids:
        raise SeriesError("请求引用了未批准或不适用当前镜头的素材")
    needed_ref_modality = "audio" if modality == "audio" else "image"
    if any(entry["modality"] != needed_ref_modality for entry in context["media_references"]
           if entry["media_id"] in logical.reference_media_ids):
        raise SeriesError("参考媒体模态与生成请求不匹配")
    for extra in (getattr(logical, "first_frame_media_id", None), getattr(logical, "last_frame_media_id", None),
                  getattr(logical, "voice_media_id", None)):
        if extra and extra not in media_ids:
            raise SeriesError("首尾帧或声音参考未在当前镜头上下文中批准")
    for field, role in (("first_frame_media_id", "first_frame"), ("last_frame_media_id", "last_frame"),
                        ("voice_media_id", "voice_sample")):
        extra = getattr(logical, field, None)
        if extra and not any(entry["media_id"] == extra and entry["role"] == role for entry in context["media_references"]):
            raise SeriesError(f"{field} 未按 {role} 用途批准")
    run_item, run = _artifact_document(project, state, run_id)
    if run_item["type"] != "vsc.production_run" or run_item.get("scope") not in ("project", context["episode_id"]):
        raise SeriesError("任务须绑定本集有效 production_run")
    pinned = {(item["id"], item["sha256"]) for item in run.get("approved_inputs", [])}
    if not {(item["id"], item["sha256"]) for item in context["input_versions"]} <= pinned:
        raise SeriesError("production_run 未钉住镜头上下文的全部已批准版本")
    if coverage_ref and (coverage_ref["id"], coverage_ref["sha256"]) not in pinned:
        raise SeriesError("production_run 未钉住对白镜头的已批准覆盖计划")
    from vsc.production.series_run import operation as series_operation
    matches = [entry for entry in run.get("series_batch", {}).get("jobs", [])
               if entry.get("candidate_no") == candidate_no and entry.get("request") == request]
    if len(matches) != 1:
        raise SeriesError("请求与候选编号须原样列入已批准 series_batch")
    operation_key = series_operation(matches[0])
    with project_lock(Path(project)), db.connect(project) as connection:
        row = connection.execute("SELECT m.* FROM provider_routes r JOIN provider_models m ON m.id=r.model_id "
            "JOIN providers p ON p.name=r.provider WHERE r.modality=? AND r.purpose=? AND r.enabled=1 "
            "AND m.enabled=1 AND p.enabled=1", (modality, purpose)).fetchone()
        if not row:
            raise SeriesError("此用途没有已启用的模型路由")
        capabilities = json.loads(row["capabilities"])
        if purpose not in capabilities["purposes"]:
            raise SeriesError("路由模型未声明支持此用途")
        if logical.reference_media_ids and not capabilities.get("reference_media", False):
            raise SeriesError("路由模型不支持参考媒体")
        if modality == "video" and logical.last_frame_media_id and not capabilities.get("last_frame", False):
            raise SeriesError("路由模型不支持尾帧")
        if modality == "video" and logical.first_frame_media_id and not capabilities.get("first_frame", False):
            raise SeriesError("路由模型不支持首帧")
        if modality == "video" and logical.duration_ms > capabilities.get("max_duration_ms", logical.duration_ms):
            raise SeriesError("请求视频时长超过模型能力")
        if modality == "image" and (logical.width > capabilities.get("max_width", logical.width)
                                    or logical.height > capabilities.get("max_height", logical.height)):
            raise SeriesError("请求图片尺寸超过模型能力")
        if modality == "audio" and logical.voice_media_id and not capabilities.get("voice_reference", False):
            raise SeriesError("路由模型不支持声音参考")
        frozen = {"logical_request": request, "operation": operation_key, "context_sha256": context["sha256"],
                  "input_versions": context["input_versions"] + ([coverage_ref] if coverage_ref else []),
                  "reference_media": context["media_references"],
                  "provider": row["provider"], "model": row["model_key"], "model_version": row["model_version"],
                  "default_params": json.loads(row["default_params"]), "capabilities": capabilities}
        if voice_binding:
            frozen["voice_binding"] = voice_binding
        request_sha = db.digest(frozen)
        identity = db.digest({"run": run_id, "run_sha256": run_item["sha256"], "shot": shot_id,
            "purpose": purpose, "modality": modality, "candidate": candidate_no, "request_sha256": request_sha})
        existing = connection.execute("SELECT id,request_sha256,status FROM generation_jobs WHERE "
            "run_artifact_id=? AND target_id=? AND purpose=? AND candidate_no=?",
            (run_id, shot_id, purpose, candidate_no)).fetchone()
        if existing:
            if existing["request_sha256"] != request_sha:
                raise SeriesError("相同候选编号已绑定其他请求；须新建候选编号")
            return {"job_id": existing["id"], "status": existing["status"], "idempotency_key": identity}
        job_id = "J-" + uuid.uuid4().hex
        timestamp = stamp()
        connection.execute("INSERT INTO generation_jobs (id,run_artifact_id,target_id,purpose,modality,candidate_no,"
            "provider,model,model_version,context_sha256,request_sha256,idempotency_key,status,external_task_id,request,"
            "attempt,cost,latency_ms,raw_response,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, run_id, shot_id, purpose, modality, candidate_no, row["provider"], row["model_key"],
             row["model_version"], context["sha256"], request_sha, identity, "created", None,
             db.canonical(frozen), 0, None, None, None, timestamp, timestamp))
        connection.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
            ("E-" + uuid.uuid4().hex, job_id, "created", db.canonical({"request_sha256": request_sha}), timestamp))
        return {"job_id": job_id, "status": "created", "idempotency_key": identity}


TRANSITIONS = {
    "created": {"submission_unknown", "failed"},
    "submission_unknown": {"submitted", "running", "succeeded", "failed"},
    "submitted": {"submitted", "running", "succeeded", "failed"},
    "running": {"running", "succeeded", "failed"},
    "succeeded": set(), "failed": set(),
}


def record_status(project, job_id, status, external_task_id=None, details=None):
    """Durable reconciliation event; no hidden resubmission on uncertain outcome."""
    series_state(project)
    if status not in TRANSITIONS or not isinstance(details or {}, dict):
        raise SeriesError("任务状态或详情无效")
    with project_lock(Path(project)), db.connect(project) as connection:
        row = connection.execute("SELECT status,external_task_id,attempt FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or status not in TRANSITIONS[row["status"]]:
            raise SeriesError("任务状态不允许此转换")
        if row["external_task_id"] and external_task_id and row["external_task_id"] != external_task_id:
            raise SeriesError("外部任务 ID 已固定，不可改写")
        if status == "submission_unknown" and external_task_id:
            raise SeriesError("提交结果未知时不得伪造外部任务 ID")
        timestamp = stamp()
        connection.execute("UPDATE generation_jobs SET status=?,external_task_id=?,attempt=?,raw_response=?,updated_at=? WHERE id=?",
            (status, external_task_id or row["external_task_id"], row["attempt"] + (status == "submission_unknown"),
             db.canonical(details or {}), timestamp, job_id))
        connection.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
            ("E-" + uuid.uuid4().hex, job_id, status, db.canonical(details or {}), timestamp))


def mark_transferred(project, job_id, media_ids):
    """Durable marker that every output is stored locally; repeat calls are no-ops."""
    series_state(project)
    with project_lock(Path(project)), db.connect(project) as connection:
        row = connection.execute("SELECT status FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "succeeded":
            raise SeriesError("只有成功任务可以标记转存完成")
        if connection.execute("SELECT 1 FROM job_events WHERE job_id=? AND status='transferred'", (job_id,)).fetchone():
            return
        connection.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
            ("E-" + uuid.uuid4().hex, job_id, "transferred", db.canonical({"media_ids": media_ids}), stamp()))


def record_poll_error(project, job_id, error):
    """Audit a failed resume and move the job behind others in the polling queue."""
    with project_lock(Path(project)), db.connect(project) as connection:
        timestamp = stamp()
        connection.execute("UPDATE generation_jobs SET updated_at=? WHERE id=?", (timestamp, job_id))
        connection.execute("INSERT INTO job_events VALUES (?,?,?,?,?)",
            ("E-" + uuid.uuid4().hex, job_id, "poll_error", db.canonical({"error": str(error)[:500]}), timestamp))


def adapter_for_job(project, job_id, transport=None):
    """Resolve a frozen job to an adapter; does not submit or poll it."""
    series_state(project)
    with db.connect(project) as connection:
        job = connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise SeriesError("任务不存在")
        frozen = json.loads(job["request"])
    if db.digest(frozen) != job["request_sha256"] or frozen.get("model_version") != job["model_version"]:
        raise SeriesError("任务请求快照或模型版本已漂移")
    references = {entry["media_id"]: entry for entry in frozen["reference_media"]}

    def media_url(media_id):
        from vsc.adapters.providers.volc_ark import api as volc_ark
        from vsc.production.context import sha256
        item = references.get(media_id)
        if not item or item["rights"] not in ("owned", "licensed"):
            raise SeriesError("任务引用了未获权属批准的素材")
        root = Path(project).resolve()
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path) != item["sha256"]:
            raise SeriesError("任务参考媒体已漂移")
        return volc_ark.resolve(str(path), project, volc_ark.originals(project))[0]

    if job["provider"] != "volc_ark":
        raise SeriesError("此 Provider 尚无系列任务适配器")
    from vsc.adapters.providers.volc_ark.provider import VolcArkAudioProvider, VolcArkImageProvider, VolcArkVideoProvider
    defaults = frozen["default_params"]
    if job["modality"] == "image":
        sizes = defaults.get("size_map", {})
        if not isinstance(sizes, dict):
            raise SeriesError("图片模型须配置 size_map")
        return VolcArkImageProvider(job["model"], media_url,
            lambda width, height: sizes.get(f"{width}x{height}"), transport)
    if job["modality"] == "video":
        if not defaults.get("resolution") or not defaults.get("ratio"):
            raise SeriesError("视频模型须配置 resolution 与 ratio")
        return VolcArkVideoProvider(job["model"], media_url, defaults["resolution"], defaults["ratio"],
            bool(defaults.get("generate_audio", False)), transport)
    if job["modality"] == "audio":
        return VolcArkAudioProvider(job["model"], project, job_id, frozen.get("voice_binding"), defaults, transport)
    raise SeriesError("任务模态没有适配器")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("provider-add"); command.add_argument("project"); command.add_argument("--name", required=True)
    command.add_argument("--modality", action="append", required=True); command.add_argument("--auth-ref")
    command.add_argument("--base-url"); command.add_argument("--rate-limit", type=int)
    command = sub.add_parser("model-add"); command.add_argument("project"); command.add_argument("--provider", required=True)
    command.add_argument("--id", required=True); command.add_argument("--key", required=True)
    command.add_argument("--modality", choices=REQUEST_TYPES, required=True); command.add_argument("--version", required=True)
    command.add_argument("--capabilities", required=True); command.add_argument("--defaults"); command.add_argument("--cost-rule")
    command = sub.add_parser("route-set"); command.add_argument("project"); command.add_argument("--modality", choices=REQUEST_TYPES, required=True)
    command.add_argument("--purpose", required=True); command.add_argument("--model-id", required=True)
    command = sub.add_parser("plan"); command.add_argument("project"); command.add_argument("--run", required=True)
    command.add_argument("--request", required=True); command.add_argument("--candidate", type=int, default=1)
    command = sub.add_parser("jobs"); command.add_argument("project"); command.add_argument("--shot")
    command = sub.add_parser("record-status"); command.add_argument("project"); command.add_argument("--job", required=True)
    command.add_argument("--status", choices=TRANSITIONS, required=True); command.add_argument("--external-task-id")
    command.add_argument("--details")
    args = parser.parse_args(argv)
    try:
        if args.command == "provider-add":
            register_provider(args.project, args.name, args.modality, args.auth_ref, args.base_url, args.rate_limit)
        elif args.command == "model-add":
            register_model(args.project, args.provider, args.id, args.key, args.modality, args.version,
                json.loads(args.capabilities), json.loads(args.defaults) if args.defaults else None,
                json.loads(args.cost_rule) if args.cost_rule else None)
        elif args.command == "route-set":
            set_route(args.project, args.modality, args.purpose, args.model_id)
        elif args.command == "plan":
            request = json.loads(Path(args.request).read_text("utf-8"))
            print(json.dumps(plan_job(args.project, args.run, request, args.candidate), ensure_ascii=False))
        elif args.command == "record-status":
            record_status(args.project, args.job, args.status, args.external_task_id,
                          json.loads(args.details) if args.details else None)
        else:
            series_state(args.project)
            with db.connect(args.project) as connection:
                if args.shot:
                    rows = connection.execute("SELECT * FROM generation_jobs WHERE target_id=? ORDER BY created_at", (args.shot,)).fetchall()
                else:
                    rows = connection.execute("SELECT * FROM generation_jobs ORDER BY created_at").fetchall()
                print(json.dumps([{key: row[key] for key in row.keys() if key not in ("request", "raw_response")}
                    for row in rows], ensure_ascii=False, indent=2))
    except (SeriesError, db.SeriesStoreError, sqlite3.Error, ValueError, OSError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
