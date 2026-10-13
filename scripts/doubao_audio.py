#!/usr/bin/env python3
"""豆包 Seed-Audio 1.0 可选 MediaKit 适配器；默认 dry run，--execute 才付费提交。

凭证默认读取火山方舟 Agent 版本的 API Key（ARK_AGENT_PLAN_API_KEY）；找不到时提示配置该 key。
POST 不重试，保存任务编号后可继续 GET 查询。
仅生成完整音频候选，不承诺精确时长、不自动分轨、不进行人声分离。
"""
import argparse
import base64
import binascii
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

import consistency
import vsc_credentials as credentials
from doubao_speech import (NoRedirect, SAFE_ID, SpeechError, digest_json, generation_lock,
                           probe_audio, project_path, sha256, stamp, write_json)

BASE = "https://mediakit.cn-beijing.volces.com"
SUBMIT = "/api/v1/tools/call-maas-proxy"
PROVIDER = "doubao_audio"
MODEL = "seed-audio-1.0"
MAX_RESPONSE_BYTES = 192 * 1024 * 1024
MAX_AUDIO_BYTES = 128 * 1024 * 1024


class AudioError(SpeechError):
    pass


def api_key(env_name):
    return credentials.read_key(env_name, AudioError)


def call(path, key, payload=None):
    """每次只发一个请求，不跟随重定向、不自动重试 POST 或 GET。"""
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(BASE + path, data=data, method="GET" if payload is None else "POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=180) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AudioError("MediaKit 响应超过安全上限")
            result = json.loads(body)
    except urllib.error.HTTPError as exc:
        raise AudioError(f"MediaKit HTTP {exc.code}；不自动重试") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise AudioError(str(exc).replace(key, "[REDACTED]")) from None
    except (ValueError, UnicodeError):
        raise AudioError("MediaKit 返回无效 JSON") from None
    if not isinstance(result, dict):
        raise AudioError("MediaKit 响应必须是对象")
    return result


def plan(args):
    project = Path(args.project).resolve()
    try:
        project_id = json.loads(project_path(project, "vsc.json").read_text("utf-8"))["project_id"]
    except (OSError, ValueError, KeyError, TypeError):
        raise AudioError("无法读取作品 vsc.json 的 project_id") from None
    if not isinstance(project_id, str) or not project_id.strip():
        raise AudioError("project_id 必须是非空字符串")
    if not SAFE_ID.fullmatch(args.name):
        raise AudioError("--name 必须是安全 ID，最多128字，只含字母、数字、点、下划线或连字符")
    out = project_path(project, args.out)
    prompt = project_path(project, args.prompt_file).read_text("utf-8") if args.prompt_file else args.prompt
    if not prompt or not prompt.strip():
        raise AudioError("提示词不能为空")
    if args.max_chars <= 0 or len(prompt) > args.max_chars:
        raise AudioError(f"提示词字符预算超限：{len(prompt)} / {args.max_chars}")
    if args.max_polls <= 0 or args.max_polls > 10000:
        raise AudioError("--max-polls 范围为 1 到 10000")
    if not math.isfinite(args.poll_interval) or not 0 <= args.poll_interval <= 60:
        raise AudioError("--poll-interval 范围为 0 到 60 秒")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.key_env):
        raise AudioError("--key-env 只接受环境变量名")
    payload = {"api": "doubao.audio_generation", "maas_params": {"model": MODEL, "text_prompt": prompt,
        "audio_config": {"format": "mp3", "sample_rate": 48000, "pitch_rate": 0, "speech_rate": 0, "loudness_rate": 0}}}
    binding = {"project_id": project_id, "kind": "audio", "purpose": "asset", "asset_kind": args.asset_kind,
        "inputs": {"prompt": prompt, "references": [], "asset_kind": args.asset_kind}, "endpoint": BASE + SUBMIT,
        "payload": payload, "key_env": args.key_env, "max_chars": args.max_chars,
        "out": str(out.relative_to(project)), "name": args.name}
    return project, out, payload, binding


def new_record(binding):
    return {"format": consistency.RECORD_FORMAT, "project_id": binding["project_id"], "kind": "audio", "purpose": "asset",
        "shot_id": None, "inputs": binding["inputs"], "engine": {"provider": PROVIDER, "model": MODEL, "version": "mediakit-v1",
        "params": binding["payload"]["maas_params"], "request_sha256": digest_json(binding),
        "payload_sha256": digest_json(binding["payload"]), "responses": []},
        "budget": {"billable": True, "max_chars": binding["max_chars"], "prompt_chars": len(binding["inputs"]["prompt"]),
        "usage": {"note": "请求可能计费；平台尚未返回用量，金额未知；提示词字符数不等于账单用量"}},
        "submitted_at": stamp(), "finished_at": stamp(), "status": "failed", "outputs": [], "errors": [], "selection": None}


def response_path(project, out, name, label):
    return project_path(project, str((out / f"{name}-{label}.json").relative_to(project)))


def save_response(project, out, task, response, label, key):
    # 原始结果保留音频 Base64，便于下载/验证失败后本地恢复；绝不存凭证。
    clean = json.loads(json.dumps(response, ensure_ascii=False).replace(key, "[REDACTED]"))
    path = response_path(project, out, task["binding"]["name"], label)
    if path.exists():
        raise AudioError("响应快照已存在，拒绝覆盖")
    write_json(path, {"format": "vsc.mediakit-response/v1", "request_sha256": digest_json(task["binding"]),
        "received_at": stamp(), "response": clean})
    entry = {"path": str(path.relative_to(project)), "sha256": sha256(path)}
    task["record"]["engine"]["responses"].append(entry)
    result = clean.get("result", {})
    maas = result.get("maas_result", {}) if isinstance(result, dict) else {}
    usage = {}
    for source, value in (("mediakit", clean.get("usage")), ("result", result.get("usage") if isinstance(result, dict) else None),
                          ("maas", maas.get("usage") if isinstance(maas, dict) else None)):
        if isinstance(value, dict) and value:
            usage[source] = value
    if usage:
        task["record"]["budget"]["usage"] = usage
    return entry


def load_response(project, task, entry):
    if not isinstance(entry, dict):
        raise AudioError("任务缺少可核实响应快照")
    path = project_path(project, entry.get("path"))
    if not path.is_file() or sha256(path) != entry.get("sha256"):
        raise AudioError("响应快照缺失或 SHA-256 改变")
    wrapper = json.loads(path.read_text("utf-8"))
    if wrapper.get("format") != "vsc.mediakit-response/v1" or wrapper.get("request_sha256") != digest_json(task["binding"]):
        raise AudioError("响应快照不属于原请求")
    response = wrapper.get("response")
    if not isinstance(response, dict):
        raise AudioError("响应快照无效")
    return response


def valid_task_id(response):
    task_id = response.get("task_id")
    if response.get("success") is not True or not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
        raise AudioError("提交响应缺少有效 success/task_id；不确定是否计费，禁止自动重提")
    return task_id


def persist(task_file, record_file, task):
    write_json(task_file, task)
    write_json(record_file, task["record"])


def completed_response(response, task_id):
    if response.get("success") is not True or response.get("task_id") != task_id:
        raise AudioError("查询响应未成功或任务编号与请求不一致")
    if response.get("status") != "completed":
        raise AudioError("查询响应尚未完成")
    result = response.get("result")
    if not isinstance(result, dict) or result.get("api") != "doubao.audio_generation" or not isinstance(result.get("maas_result"), dict):
        raise AudioError("完成响应缺少原始音频生成结果")
    return result


def check_original(task):
    binding, record = task["binding"], task.get("record")
    if (not isinstance(record, dict) or consistency.record_errors(record)
            or record.get("project_id") != binding["project_id"] or record.get("inputs") != binding["inputs"]
            or record.get("kind") != "audio" or record.get("purpose") != "asset"):
        raise AudioError("任务原始记录与绑定不一致，不能安全续接")
    engine = record.get("engine", {})
    if (engine.get("request_sha256") != digest_json(binding) or engine.get("payload_sha256") != digest_json(binding["payload"])
            or engine.get("provider") != PROVIDER or engine.get("model") != MODEL
            or engine.get("params") != binding["payload"]["maas_params"]
            or record.get("budget", {}).get("max_chars") != binding["max_chars"]
            or record["budget"].get("prompt_chars") != len(binding["inputs"]["prompt"])
            or not isinstance(engine.get("responses"), list)):
        raise AudioError("任务原始参数或预算与绑定不一致，不能安全续接")
    if task.get("task_id") is not None and (not isinstance(task["task_id"], str) or not SAFE_ID.fullmatch(task["task_id"])
            or engine.get("task_id") != task["task_id"]):
        raise AudioError("任务编号与原始记录不一致")
    if type(task.get("polls")) is not int or task["polls"] < 0:
        raise AudioError("查询序号无效")


def publish(project, out, task, response):
    result = completed_response(response, task["task_id"])
    encoded = result["maas_result"].get("audio")
    if not isinstance(encoded, str) or not encoded:
        raise AudioError("完成响应缺少 Base64 音频；不猜测其他响应结构")
    if encoded.startswith(("https://", "http://")):
        raise AudioError("本版仅支持官方示例的 Base64 音频，不下载未知 URL 结构")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, binascii.Error):
        raise AudioError("完成响应的音频不是有效 Base64") from None
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise AudioError("完成响应的音频为空或超出安全上限")
    target = project_path(project, str((out / f"{task['binding']['name']}.mp3").relative_to(project)))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=out, prefix=".seed-audio-", suffix=".mp3", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        metadata = probe_audio(temporary, "mp3", 48000)
        digest = sha256(temporary)
        if target.exists():
            if sha256(target) != digest:
                raise AudioError("目标音频已存在且内容不同，拒绝覆盖")
        else:
            temporary.replace(target)
        record = task["record"]
        record.update(status="succeeded", finished_at=stamp(), errors=[], outputs=[{"id": task["binding"]["name"],
            "path": str(target.relative_to(project)), "sha256": digest, "asset_kind": task["binding"]["asset_kind"], **metadata}])
        if result.get("duration") is not None:
            record["engine"]["reported_duration_s"] = result["duration"]
        errors = consistency.record_errors(record)
        if errors:
            raise AudioError("生成记录无效：" + "；".join(errors))
        return record
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def checked_success(project, task):
    check_original(task)
    record, binding = task.get("record"), task["binding"]
    if (not isinstance(record, dict) or consistency.record_errors(record) or record.get("status") != "succeeded"
            or record.get("project_id") != binding["project_id"] or record.get("inputs") != binding["inputs"]
            or record.get("kind") != "audio" or record.get("purpose") != "asset"
            or record.get("engine", {}).get("request_sha256") != digest_json(binding)
            or record["engine"].get("provider") != PROVIDER or record["engine"].get("model") != MODEL
            or record["engine"].get("params") != binding["payload"]["maas_params"]
            or len(record.get("outputs", [])) != 1):
        raise AudioError("同名任务没有可核实的完整成功记录")
    output = record["outputs"][0]
    expected = str(Path(binding["out"]) / f"{binding['name']}.mp3")
    if output.get("path") != expected or output.get("id") != binding["name"] or output.get("asset_kind") != binding["asset_kind"]:
        raise AudioError("成功输出与绑定不一致")
    path = project_path(project, output["path"])
    if not path.is_file() or sha256(path) != output.get("sha256"):
        raise AudioError("成功音频缺失或 SHA-256 改变；不会重新提交")
    for entry in record["engine"].get("responses", []):
        load_response(project, task, entry)
    completed_response(load_response(project, task, task.get("completed_response")), task.get("task_id"))
    probe_audio(path, "mp3", 48000)
    return record


def generate(args):
    project, out, payload, binding = plan(args)
    if not args.execute:
        return {"format": "vsc.audio-request/v1", "dry_run": True, "billable": False,
                "binding": binding, "request_sha256": digest_json(binding), "prompt_chars": len(binding["inputs"]["prompt"])}
    out.mkdir(parents=True, exist_ok=True)
    task_file = response_path(project, out, args.name, "任务")
    record_file = response_path(project, out, args.name, "生成记录")
    target = project_path(project, str((out / f"{args.name}.mp3").relative_to(project)))
    with generation_lock(out / f".{args.name}-生成.lock"):
        if task_file.exists():
            task = json.loads(task_file.read_text("utf-8"))
            if not isinstance(task, dict) or task.get("format") != "vsc.mediakit-task/v1" or task.get("binding") != binding:
                raise AudioError("同名任务请求或预算已改变，需使用新的 --name")
            if task.get("status") == "succeeded":
                record = checked_success(project, task)
                if record_file.exists() and json.loads(record_file.read_text("utf-8")) != record:
                    raise AudioError("成功生成记录与任务快照不一致")
                if not record_file.exists():
                    write_json(record_file, record)
                return record
            check_original(task)
        else:
            if target.exists() or record_file.exists() or list(out.glob(f"{args.name}-响应-*.json")):
                raise AudioError("同名输出或响应已存在，请使用新的 --name")
            task = {"format": "vsc.mediakit-task/v1", "binding": binding, "status": "new", "record": new_record(binding), "polls": 0}
        for tool in ("ffprobe", "ffmpeg"):
            if not shutil.which(tool):
                raise AudioError(f"缺少 {tool}，不能验证音频，不发请求")
        errors = consistency.record_errors(task["record"])
        if errors:
            raise AudioError("生成记录预检失败：" + "；".join(errors))
        try:
            if task.get("completed_response"):
                response = load_response(project, task, task["completed_response"])
            else:
                if task["status"] == "remote_failed":
                    raise AudioError("远程任务已失败；不能自动重新提交")
                key = api_key(args.key_env)
                if task["status"] == "new":
                    from vsc_budget import check_authorization
                    check_authorization(project, getattr(args, 'budget_reservation', None),
                        f'audio:{out.relative_to(project)}/{args.name}', {'remote_jobs':1, 'audio_jobs':1}, request=binding)
                    task["status"] = "submitted"
                    persist(task_file, record_file, task)  # 付费请求前先落盘，不确定时禁止重提。
                    submitted = call(SUBMIT, key, payload)
                    entry = save_response(project, out, task, submitted, "响应-submit", key)
                    task["submit_response"] = entry
                    persist(task_file, record_file, task)
                    task["task_id"] = valid_task_id(submitted)
                    task["record"]["engine"]["task_id"] = task["task_id"]
                    task["status"] = "running"
                    persist(task_file, record_file, task)
                if not task.get("task_id"):
                    # 崩溃可能发生在提交响应落盘、保存任务ID之前；只能从该快照恢复，不能重POST。
                    submit_file = response_path(project, out, args.name, "响应-submit")
                    entry = task.get("submit_response")
                    if entry is None and submit_file.is_file():
                        entry = {"path": str(submit_file.relative_to(project)), "sha256": sha256(submit_file)}
                    if entry is None:
                        raise AudioError("提交结果不确定且无任务ID；禁止自动重新提交")
                    submitted = load_response(project, task, entry)
                    task["task_id"] = valid_task_id(submitted)
                    task["record"]["engine"]["task_id"] = task["task_id"]
                    task["status"] = "running"
                    if entry not in task["record"]["engine"]["responses"]:
                        task["record"]["engine"]["responses"].append(entry)
                    task["submit_response"] = entry
                    persist(task_file, record_file, task)
                if not isinstance(task["task_id"], str) or not SAFE_ID.fullmatch(task["task_id"]):
                    raise AudioError("远程任务编号无效")
                if task["status"] == "remote_failed":
                    raise AudioError("远程任务已失败；不能自动重新提交")
                for attempt in range(args.max_polls):
                    task["polls"] += 1
                    persist(task_file, record_file, task)  # 先预留序号，进程中断后不覆盖已存在响应。
                    response = call("/api/v1/tasks/" + task["task_id"], key)
                    entry = save_response(project, out, task, response, f"响应-poll-{task['polls']:06d}", key)
                    if response.get("success") is not True or response.get("task_id") != task["task_id"]:
                        persist(task_file, record_file, task)
                        raise AudioError("查询响应失败或任务编号不符；保留原任务供核验")
                    status = response.get("status")
                    task["record"]["engine"]["remote_status"] = status
                    if status == "completed":
                        task["completed_response"] = entry
                        task["status"] = "completed"
                        persist(task_file, record_file, task)
                        break
                    if status in ("failed", "cancelled", "canceled"):
                        task["status"] = "remote_failed"
                        persist(task_file, record_file, task)
                        raise AudioError("远程音频生成失败：" + str(response.get("error") or response.get("message") or status).replace(key, "[REDACTED]")[:500])
                    persist(task_file, record_file, task)
                    if status not in ("pending", "queued", "running", "processing"):
                        raise AudioError("未知任务状态；保留原任务，停止本轮查询")
                    if attempt + 1 < args.max_polls:
                        time.sleep(args.poll_interval)
                else:
                    raise AudioError("本轮达到 --max-polls 上限；重跑同名命令可继续查询原任务，不重新提交")
            record = publish(project, out, task, response)
            task["status"] = "succeeded"
            persist(task_file, record_file, task)
            return record
        except (SpeechError, OSError, ValueError, http.client.HTTPException) as exc:
            record = task["record"]
            message = str(exc)
            if "key" in locals():
                message = message.replace(key, "[REDACTED]")
            record.update(status="failed", finished_at=stamp(), errors=[message[:1000]], outputs=[])
            if task_file.exists():
                persist(task_file, record_file, task)
            raise AudioError(message) from None


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    command = sub.add_parser("generate")
    command.add_argument("--project", required=True)
    command.add_argument("--out", "--output", dest="out", default="06-素材/声音")
    command.add_argument("--name", required=True)
    text = command.add_mutually_exclusive_group(required=True)
    text.add_argument("--prompt")
    text.add_argument("--prompt-file", help="作品内UTF-8提示词相对路径")
    command.add_argument("--asset-kind", choices=("music", "ambience", "sfx"), default="music")
    command.add_argument("--max-chars", type=int, required=True, help="单次提示词字符上限，不等于计费金额预算")
    command.add_argument("--max-polls", type=int, default=30, help="本轮GET次数上限，可重跑续查同一任务")
    command.add_argument("--poll-interval", type=float, default=5, help="查询间隔秒数，0到60")
    command.add_argument("--key-env", default=credentials.KEY_ENV, help="鉴权环境变量名（默认火山方舟 Agent 版本的 API Key）；不自动fallback")
    command.add_argument('--budget-reservation')
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true", help="显式提交一次付费生成或续查原任务")
    return cli


def main(argv=None):
    try:
        print(json.dumps(generate(parser().parse_args(argv)), ensure_ascii=False, indent=2))
        return 0
    except (SpeechError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
