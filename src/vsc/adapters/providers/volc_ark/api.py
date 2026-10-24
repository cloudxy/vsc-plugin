#!/usr/bin/env python3
"""火山方舟（豆包）生成适配器：Seedream 图像、Seedance 视频与豆包视觉检查。只用标准库。

  image   --project P --out DIR --name N (--prompt T | --prompt-file F) [--ref X ...] [--base-frame X --base-use edit|reference]
          [--purpose asset|candidate] [--shot S --moment entry|exit --bible B --state S] [--model M] [--size 2K]
  video   --project P --out DIR --name N --shot S (--prompt T | --prompt-file F)
          [--first-frame X [--last-frame X] | --first-frame-ref X] [--ref-image X ...] [--ref-video X ...] [--ref-audio X ...]
          [--bible B --state S] [--model M] [--resolution 480p] [--ratio adaptive] [--duration 5] [--no-audio] [--draft] [--dry-run]
  inspect --project P --media FILE --bible B (--shot S --state S [--moment entry|exit] | --entity E ...) [--check 文字 ...] [--model M]

X 是本地文件、https 链接或 asset://<素材 ID>。本地文件若正是某份生成记录里的方舟原始产物，且原始链接未过期，就改传原始链接：
方舟只信任未经改动的原始产物（见 TRUST），转成 Base64 可能失去信任。每次生成写一份 vsc.generation-record/v1，
inspect 写 vsc.visual-check/v1；两者都放在输出旁边。视觉检查只作提醒，不能代替人工批准。

密钥只从 ARK_AGENT_PLAN_API_KEY（火山方舟 Agent 版本的 API Key）读取，不打印、不落盘；找不到时提示配置该 key。
默认走套餐专属地址，ARK_BASE_URL 只能设为 https://ark.cn-beijing.volces.com/api/plan/v3。套餐规则禁止用该 key
直接调用文本生成模型，因此 inspect 只能预检和读取已有报告，不再发起新提交。提交生成任务不自动重试，避免重复计费；
视频任务的编号先写入 <名称>-任务.json，中断后重跑同一命令会续接查询，不会重新提交。
"""
import argparse
import base64
import contextlib
import contextvars
import datetime
import fcntl
import hashlib
import http.client
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from vsc.story import consistency as consistency
from vsc.adapters.providers import credentials as credentials

PLAN_BASE = credentials.PLAN_BASE
TEXT_PATHS = ("/chat/completions", "/responses", "/completions", "/embeddings", "/embeddings/multimodal")
IMAGE_MODEL = "doubao-seedream-5-0-flash-260915"
VIDEO_MODEL = "doubao-seedance-2-5-260628"
VISION_MODEL = "doubao-seed-2-1-pro-260915"
PROVIDER = "volcengine_ark"
URL_TTL = datetime.timedelta(hours=24)
# 平台规则（2026-10-08 版文档“便利创作含肖像视频”）：Seedance 2.x 不接受直接上传的写实人脸，但信任同账号下
# 这些模型的原始产物，自生成起 30 天内可再作输入；Seedream 5.0 只限纯文生图。改动、转码或跨账号即失去信任。
TRUST_WINDOW = datetime.timedelta(days=30)
TRUSTED = {
    "doubao-seedream-5-0-260128": "text_only",
    "doubao-seedream-5-0-pro-260628": "text_only",
    "doubao-seedream-5-0-flash-260915": "text_only",
    "doubao-seedance-2-5-260628": "any",
    "doubao-seedance-2-0-260128": "any",
    "doubao-seedance-2-0-fast-260128": "any",
    "doubao-seedance-2-0-mini-260615": "any",
}
SEQUENTIAL = ("doubao-seedream-5-0-260128", "doubao-seedream-4-5-251128", "doubao-seedream-4-0-250828")
QUERY_DEADLINE = contextvars.ContextVar("ark_query_deadline", default=None)


class ArkError(RuntimeError):
    """请求无效、平台拒绝或运行环境未就绪。"""


class ArkHTTPError(ArkError):
    """HTTP 错误保留状态码；计费分类不依赖异常文本。"""
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class ArkPending(ArkError):
    """本轮查询有界退出；远程任务仍可用同一编号续查。"""


def now():
    return datetime.datetime.now().astimezone()


def stamp(moment):
    return moment.isoformat(timespec="seconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def api_key():
    return credentials.read_key(error=ArkError)


def base_url():
    """Keep the Agent Plan key on its documented OpenAI-compatible data plane."""
    value = os.environ.get("ARK_BASE_URL", PLAN_BASE).strip().rstrip("/")
    if value != PLAN_BASE:
        raise ArkError("Agent Plan 专属 key 只能使用 ARK_BASE_URL=" + PLAN_BASE)
    return value


def call(path, payload=None, attempts=None):
    """调用方舟接口。提交（有 payload）只发一次，查询失败时重试。"""
    problem = credentials.text_model_problem() if path.split("?", 1)[0].rstrip("/") in TEXT_PATHS else None
    if problem:
        raise ArkError(problem)
    key = api_key()
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(base_url() + path, data=data, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    attempts = 1 if payload is not None else (attempts or 6)
    deadline = QUERY_DEADLINE.get() if payload is None else None
    if deadline is not None:
        attempts = 1
    for attempt in range(attempts):
        timeout = 300 if deadline is None else min(300, deadline - time.monotonic())
        if timeout <= 0:
            raise ArkPending("本轮查询已达到 deadline；相同命令可续查原任务")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace").replace(key, "[REDACTED]")
            denied = credentials.permission_denied(exc.code, "方舟图像／视频接口")
            message = f"{denied}。平台返回：{body[:800]}" if denied else f"HTTP {exc.code}: {body[:800]}"
            raise ArkHTTPError(exc.code, message) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt == attempts - 1:
                raise ArkError(f"网络错误：{str(exc).replace(key, '[REDACTED]')}") from None
            time.sleep(10)


def download(url, target):
    """完整下载后原子落盘；网络中断不会留下看似完整的产物。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
                temporary = Path(handle.name)
                with urllib.request.urlopen(url, timeout=180) as response:
                    while chunk := response.read(1 << 20):
                        handle.write(chunk)
            temporary.replace(target)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt == 3:
                raise ArkError(f"下载失败：{exc}") from None
            time.sleep(5)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


# ---------- 输入素材 ----------

def records(project):
    """项目内全部生成记录（文件名以“生成记录.json”结尾）。"""
    found = []
    for path in sorted(Path(project).rglob("*生成记录.json")):
        try:
            record = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("format") == consistency.RECORD_FORMAT:
            found.append((path, record))
    return found


def originals(project):
    """{SHA-256: 输出项}：记录了方舟原始链接的输出。"""
    index = {}
    for _, record in records(project):
        if not isinstance(record.get("engine"), dict) or record["engine"].get("provider") != PROVIDER:
            continue
        for output in record.get("outputs", []):
            if isinstance(output, dict) and output.get("source_url") and output.get("sha256"):
                index[output["sha256"]] = output
    # 素材库复用保留供应商原始产物来源；只有同供应商、字节未变的文件才可沿用原链接。
    for path in sorted((Path(project) / "06-素材/素材库").glob("*/来源.json")):
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict) or manifest.get("format") != "vsc.library-use/v1" or manifest.get("provider") != PROVIDER:
            continue
        if not isinstance(manifest.get("files"), list):
            continue
        for item in manifest["files"]:
            if not isinstance(item, dict) or item.get("provider", PROVIDER) != PROVIDER:
                continue
            if not item.get("source_url") or not isinstance(item.get("sha256"), str) or not consistency.SHA256.fullmatch(item["sha256"]):
                continue
            try:
                source = project_path(project, item.get("path"))
                if source.is_file() and sha256(source) == item["sha256"]:
                    index[item["sha256"]] = item
            except (ArkError, OSError):
                continue
    return index


def resolve(value, project, sources, at=None):
    """把命令行给出的素材转成方舟可接受的地址；本地文件同时返回 {path, sha256} 供生成记录使用。"""
    if value.startswith(("asset://", "https://", "http://")):
        return value, None
    path = Path(value)
    if not path.is_file():
        raise ArkError(f"素材不存在：{value}")
    digest = sha256(path)
    try:
        shown = str(path.resolve().relative_to(Path(project).resolve()))
    except ValueError:
        shown = str(path.resolve())
    item = {"path": shown, "sha256": digest}
    original = sources.get(digest)
    expires = original and original.get("source_url_expires_at")
    if expires:
        try:
            expiry = datetime.datetime.fromisoformat(expires)
            if expiry.tzinfo is not None and expiry > (at or now()):
                return original["source_url"], item
        except (TypeError, ValueError):
            pass
    return f"data:{media_type(path)};base64,{base64.b64encode(path.read_bytes()).decode()}", item


def media_type(path):
    """按文件头判断媒体类型；扩展名可能与内容不符（例如 JPEG 内容存成 .png）。"""
    with Path(path).open("rb") as handle:
        head = handle.read(16)
    for magic, kind in ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"), (b"GIF8", "image/gif"), (b"BM", "image/bmp"),
                        (b"ID3", "audio/mp3"), (b"\xff\xfb", "audio/mp3"), (b"\xff\xf3", "audio/mp3")):
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF":
        return {b"WEBP": "image/webp", b"WAVE": "audio/wav"}.get(head[8:12], "application/octet-stream")
    if head[4:8] == b"ftyp":
        return "video/quicktime" if head[8:10] == b"qt" else "video/mp4"
    return mimetypes.guess_type(Path(path).name)[0] or "application/octet-stream"


def trust_until(model, created, text_only):
    rule = TRUSTED.get(model)
    if rule == "any" or (rule == "text_only" and text_only):
        return stamp(created + TRUST_WINDOW)
    return None


def prompt_of(args):
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text("utf-8").strip()
        if prompt:
            return prompt
    if args.prompt:
        if args.prompt.strip():
            return args.prompt.strip()
    raise ArkError("需要 --prompt 或 --prompt-file")


def anchors(args, shot):
    if not (args.bible or args.state):
        return None
    if not (args.bible and args.state and shot):
        raise ArkError("绑定锚点包需要同时给出 --shot、--bible、--state")
    bible = consistency.load(args.bible, consistency.BIBLE_FORMAT)
    state = consistency.load(args.state, consistency.STATE_FORMAT)
    errors = consistency.bible_errors(bible) + consistency.state_errors(state, bible)
    if bible.get("project_id") != project_id(args.project) or state.get("project_id") != project_id(args.project):
        errors.append("资产库、场景状态与当前项目编号必须一致")
    if errors:
        raise ArkError("锚点输入无效：" + "；".join(errors))
    return consistency.pack_sha256(consistency.anchor_pack(bible, state, shot))


def audio_anchors(args, shot):
    if not (args.bible and args.state and shot):
        return None
    return consistency.pack_sha256(consistency.audio_pack(consistency.load(args.bible, consistency.BIBLE_FORMAT),
                                                         consistency.load(args.state, consistency.STATE_FORMAT), shot))


def typed_references(values, media, args):
    """适配器保留真正的媒体角色与用途；资产库能确定实体时一并绑定。"""
    bible = consistency.load(args.bible, consistency.BIBLE_FORMAT) if args.bible else {}
    result = []
    for url, item in values:
        if not item:
            result.append({"source_uri": url, "sha256": None, "media_type": media, "role": "reference_" + media,
                           "purpose": {"image": "identity", "video": "action", "audio": "sound"}[media], "entity_id": None})
            continue  # 不能伪造远程不透明输入的内容 SHA；下游会明确报告无法核对。
        matches = []
        for entity in bible.get("entities", []):
            for ref in entity.get("references", []):
                info = consistency.reference_info(ref)
                if info["sha256"] == item["sha256"] and info["media_type"] == media:
                    matches.append((entity["id"], info))
            if media == "audio" and entity.get("sound", {}).get("sha256") == item["sha256"]:
                matches.append((entity["id"], {"purpose": "sound"}))
        purpose = matches[0][1]["purpose"] if matches and len({ref[1]["purpose"] for ref in matches}) == 1 else {
            "image": "identity", "video": "action", "audio": "sound"}[media]
        bound = {**item, "media_type": media, "role": "reference_" + media, "purpose": purpose,
                 "entity_id": matches[0][0] if len({ref[0] for ref in matches}) == 1 else None}
        result.append(bound)
    return result


def project_id(project):
    try:
        return json.loads((Path(project) / "vsc.json").read_text("utf-8"))["project_id"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ArkError(f"无法读取项目编号：{exc}") from None


def write_record(out, name, record):
    errors = consistency.record_errors(record)
    if errors:
        raise ArkError("生成记录无效：" + "；".join(errors))
    path = out / f"{name}-生成记录.json"
    write_json(path, record)
    return path


def base_record(args, kind, purpose, shot, inputs, engine, started):
    return {"format": consistency.RECORD_FORMAT, "project_id": project_id(args.project), "kind": kind, "purpose": purpose,
            "shot_id": shot, "inputs": inputs, "engine": {"provider": PROVIDER, **engine}, "budget": {"billable": False, "usage": None},
            "submitted_at": stamp(started), "finished_at": None, "status": "failed", "outputs": [], "errors": [], "selection": None}


def output_dir(args):
    if not isinstance(args.name, str) or not consistency.SAFE_ID.fullmatch(args.name):
        raise ArkError("--name 必须是安全文件名：以字母或数字开头，只含字母、数字、点、下划线或连字符")
    out = project_path(args.project, args.out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def project_path(project, relative):
    """拒绝绝对路径、父目录、反斜杠与跨项目的符号链接。"""
    if not isinstance(relative, str) or not relative or "\\" in relative or any(ord(char) < 32 for char in relative):
        raise ArkError("输出与来源路径必须是项目内的相对路径")
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ArkError("输出与来源路径必须是项目内的相对路径")
    root = Path(project).resolve()
    target = root / value
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise ArkError("输出与来源路径不能通过符号链接离开项目") from None
    return target


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@contextlib.contextmanager
def generation_lock(out, name):
    """同名候选串行化，避免两个进程同时通过检查后重复付费。"""
    lock = out / f".{name}-生成.lock"
    if lock.is_symlink():
        raise ArkError("生成锁不能是符号链接")
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ArkError(f"同名生成正在运行：{name}") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def semantic_payload(payload, media_inputs):
    """运输地址可过期；本地输入的语义固定为内容 SHA，媒体角色仍由原 content 保留。"""
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    media_inputs = iter(media_inputs)
    if "content" in normalized:
        for entry in normalized["content"]:
            for key in ("image_url", "video_url", "audio_url"):
                if key in entry:
                    _, item = next(media_inputs)
                    if item:
                        entry[key]["url"] = "sha256:" + item["sha256"]
    elif normalized.get("image"):
        normalized["image"] = ["sha256:" + item["sha256"] if item else url for url, item in media_inputs]
    return normalized


def request_binding(record, payload, semantic=None):
    binding = {"project_id": record["project_id"], "kind": record["kind"], "purpose": record["purpose"],
            "shot_id": record["shot_id"], "inputs": record["inputs"], "model": record["engine"]["model"],
            "params": record["engine"]["params"], "payload_sha256": digest_json(payload)}
    if semantic is not None:
        binding["semantic_payload_sha256"] = digest_json(semantic)
    return json.loads(json.dumps(binding, ensure_ascii=False))


def preflight_record(record):
    checked = {**record, "finished_at": stamp(now())}
    errors = consistency.record_errors(checked)
    if errors:
        raise ArkError("生成输入无效：" + "；".join(errors))


def checked_outputs(record, project):
    """只允许已登记且字节完全一致的本地产物作为续接结果。"""
    for item in record.get("outputs", []):
        path = project_path(project, item["path"])
        if not path.is_file() or sha256(path) != item.get("sha256"):
            return False
    return bool(record.get("outputs"))


def generation_task(out, args, record, payload, targets, semantic=None):
    task_file, record_file = out / f"{args.name}-任务.json", out / f"{args.name}-生成记录.json"
    for path in [task_file, record_file, *targets]:
        if path.is_symlink():
            raise ArkError(f"生成输出不能是符号链接：{path.name}")
    binding = request_binding(record, payload, semantic)
    if task_file.exists():
        task = json.loads(task_file.read_text("utf-8"))
        if not isinstance(task, dict):
            raise ArkError("任务文件无效，不能安全续接")
        saved_binding = task.get("binding")
        same_semantics = (isinstance(saved_binding, dict) and saved_binding.get("semantic_payload_sha256")
                          and {key: value for key, value in saved_binding.items() if key != "payload_sha256"}
                          == {key: value for key, value in binding.items() if key != "payload_sha256"})
        if saved_binding != binding and not same_semantics:
            # 老任务未保存请求，只有纯文生视频的完整记录可逐项反证其原始请求。
            legacy = task.get("binding") is None and record["kind"] == "video"
            old = json.loads(record_file.read_text("utf-8")) if legacy and record_file.is_file() else None
            if (isinstance(old, dict) and len(payload["content"]) == 1 and not consistency.record_errors(old)
                    and old.get("status") == "succeeded" and old.get("project_id") == record["project_id"]
                    and old.get("kind") == record["kind"] and old.get("purpose") == record["purpose"]
                    and old.get("shot_id") == record["shot_id"] and old.get("inputs") == record["inputs"]
                    and old.get("submitted_at") == task.get("submitted_at")
                    and old.get("engine", {}).get("provider") == PROVIDER
                    and old["engine"].get("task_id") == task.get("id") and old["engine"].get("model") == record["engine"]["model"]
                    and {k: v for k, v in old["engine"].get("params", {}).items() if k != "actual"} == record["engine"]["params"]
                    and checked_outputs(old, args.project)):
                return task_file, {"completed_record": old}
            reason = "旧任务没有可核实的完整原始请求记录" if legacy else "同名任务的输入或请求参数已改变"
            raise ArkError(reason + "；请使用新的 --name，不能把新输入记到旧任务")
        saved = task.get("record")
        if not isinstance(saved, dict) or any(saved.get(key) != record.get(key) for key in ("project_id", "kind", "purpose", "shot_id", "inputs")):
            raise ArkError("任务文件缺少原始生成记录，不能安全续接")
        engine = saved.get("engine", {})
        if (not isinstance(engine, dict) or engine.get("provider") != PROVIDER or engine.get("model") != record["engine"]["model"]
                or not isinstance(engine.get("params"), dict)
                or {key: value for key, value in engine["params"].items() if key != "actual"} != record["engine"]["params"]):
            raise ArkError("任务文件的原始模型或参数与绑定不符，不能安全续接")
        if record["kind"] == "video" and (not isinstance(task.get("id"), str) or not consistency.SAFE_ID.fullmatch(task["id"])):
            reason = "平台已明确拒绝该提交" if task.get("submission_state") == "rejected" else "提交状态未知，任务文件缺少有效远程编号"
            raise ArkError(reason + "；不能自动重提，请先人工核查平台任务与账单")
        if task.get("credential_sha256") and task["credential_sha256"] != hashlib.sha256(api_key().encode()).hexdigest():
            raise ArkError("当前凭证与原任务提交凭证不一致；请恢复原凭证后续查或下载，不能自动重提")
        return task_file, task
    if any(path.exists() for path in [record_file, *targets]):
        raise ArkError(f"同名输出或生成记录已存在：{args.name}；请使用新的 --name")
    return task_file, {"format": "vsc.ark-task/v1", "binding": binding, "record": record}


def submit_once(task_file, task, path, payload, out, args):
    """提交意图先持久化；进程退出或响应丢失时不能靠重跑再次扣费。"""
    if task_file.exists():
        reason = "平台已明确拒绝该提交" if task.get("submission_state") == "rejected" else "提交结果未知"
        raise ArkError(reason + "；不能自动重提，请先人工核查平台任务与账单")
    base_url()
    key = api_key()  # 本地缺密钥不留下可能已提交的凭证。
    check_budget_authorization(args, task["record"]["kind"])
    record = task["record"]
    record.update(finished_at=stamp(now()), errors=[],
                  budget={"billable": True, "usage": {"note": "提交意图已记录；结果未知，可能计费，须核对平台账单"}})
    task.update(submission_state="intent", submitted_at=stamp(now()), credential_sha256=hashlib.sha256(key.encode()).hexdigest())
    write_json(task_file, task)
    write_record(out, args.name, record)
    try:
        result = call(path, payload)
    except BaseException as exc:
        rejected = isinstance(exc, ArkHTTPError) and 400 <= exc.status_code < 500
        task["submission_state"] = "rejected" if rejected else "unknown"
        record.update(finished_at=stamp(now()), errors=[{"error": str(exc) or type(exc).__name__, "stage": "submission"}],
                      budget={"billable": False} if rejected else
                      {"billable": True, "usage": {"note": "提交结果未知，可能计费；不能自动重提，须核对平台任务和账单"}})
        write_json(task_file, task)
        write_record(out, args.name, record)
        raise
    task.update(submission_state="responded", submission=result)
    if isinstance(result, dict):
        if record["kind"] == "image":
            task.update(result=result, generated_at=stamp(generated_at(result, now())))
        else:
            identifier = result.get("id")
            if isinstance(identifier, str) and consistency.SAFE_ID.fullmatch(identifier):
                task["id"] = identifier
                record["engine"]["task_id"] = identifier
    # 原始响应先落盘，后续解析异常也不能丢失提交证据。
    write_json(task_file, task)
    return result


def check_budget_authorization(args, operation):
    """正式运行在付费 POST 前核对共享预算；查询／下载不重新预留。"""
    try:
        from vsc.production import budget as vsc_budget
    except ImportError:
        state = json.loads((Path(args.project) / "vsc.json").read_text("utf-8"))
        if state.get("profile_snapshot", {}).get("contract_policy") == "production-v2":
            raise ArkError("正式运行缺少预算授权模块，不能提交付费请求") from None
        return
    try:
        required = {"remote_jobs": 1, "images": 1} if operation == "image" else {"remote_jobs": 1, "video_seconds": args.duration}
        vsc_budget.check_authorization(args.project, getattr(args, "budget_reservation", None),
                                       f"{operation}:{args.out}/{args.name}", required, request=vars(args))
    except (ValueError, RuntimeError) as exc:
        raise ArkError(f"预算授权无效：{exc}") from None


def remote_success(record, result):
    record.update(finished_at=stamp(now()), status="failed", errors=[],
                  budget={"billable": True, "usage": result.get("usage") or {"note": "平台未返回用量"}})


def generated_at(result, fallback):
    """信任期限从供应商生成时间起算；缺省才用首次成功查询时间。"""
    for key in ("generated_at", "finished_at", "created", "created_at"):
        value = result.get(key)
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
            if isinstance(value, str):
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return parsed
        except (ValueError, OverflowError, OSError):
            continue
    return fallback


def download_output(url, target, record, args, metadata):
    expected = next((item for item in record["outputs"] if item.get("id") == metadata["id"]), None)
    if target.exists():
        if expected and target.is_file() and sha256(target) == expected.get("sha256"):
            return
        raise ArkError(f"本地产物已存在但无法核实，拒绝覆盖：{target.name}")
    download(url, target)
    record["outputs"].append({**metadata, "path": str(target.relative_to(Path(args.project).resolve())), "sha256": sha256(target)})


def persist_download_failure(out, args, record, exc):
    record.update(status="partial" if record["outputs"] else "failed", errors=[{"error": str(exc), "stage": "download"}])
    write_record(out, args.name, record)


# ---------- 图像 ----------

def image_payload(model, prompt, size, images):
    payload = {"model": model, "prompt": prompt, "size": size, "response_format": "url", "watermark": False}
    if model.startswith("doubao-seedream-5"):
        payload["output_format"] = "png"
    if model in SEQUENTIAL:
        payload["sequential_image_generation"] = "disabled"
    if images:
        payload["image"] = images
    return payload


def generate_image(args):
    if args.purpose == "candidate" and not (args.shot and args.moment and args.bible and args.state):
        raise ArkError("候选关键帧需要 --shot、--moment、--bible、--state；资产图请用 --purpose asset")
    out, prompt, sources = output_dir(args), prompt_of(args), originals(args.project)
    refs = [resolve(value, args.project, sources) for value in args.ref]
    base = resolve(args.base_frame, args.project, sources) if args.base_frame else None
    images = ([base[0]] if base else []) + [url for url, _ in refs]
    inputs = {"anchors_sha256": anchors(args, args.shot), "references": typed_references(refs, "image", args), "prompt": prompt}
    if args.moment:
        inputs["moment"] = args.moment
    if base:
        inputs["base_frame"] = {**base[1], "use": args.base_use} if base[1] else None
    started = now()
    record = base_record(args, "image", args.purpose, args.shot, inputs, {"model": args.model, "params": {"size": args.size}}, started)
    preflight_record(record)
    payload = image_payload(args.model, prompt, args.size, images)
    target = out / f"{args.name}.{'png' if args.model.startswith('doubao-seedream-5') else 'jpeg'}"
    with generation_lock(out, args.name):
        task_file, task = generation_task(out, args, record, payload, [target], semantic_payload(payload, ([base] if base else []) + refs))
        if "result" not in task:
            result = submit_once(task_file, task, "/images/generations", payload, out, args)
            if not isinstance(result, dict):
                raise ArkError("平台图像响应不是对象；提交已有响应，不能安全重提")
            task.update(result=result, generated_at=stamp(generated_at(result, now())))
            write_json(task_file, task)  # 响应与用量先落盘，下载失败不会导致再次生成。
        else:
            record = task["record"]
        result = task["result"]
        remote_success(record, result)
        record["engine"]["request_sha256"] = digest_json(task["binding"])
        record["engine"]["payload_sha256"] = task["binding"]["payload_sha256"]
        if task["binding"].get("semantic_payload_sha256"):
            record["engine"]["semantic_payload_sha256"] = task["binding"]["semantic_payload_sha256"]
        write_record(out, args.name, record)
        made = datetime.datetime.fromisoformat(task["generated_at"])
        try:
            item = result["data"][0]
            download_output(item["url"], target, record, args,
                            {"id": args.name, "source_url": item["url"], "source_url_expires_at": stamp(made + URL_TTL),
                             "generated_at": stamp(made), "face_trust_until": trust_until(args.model, made, not images)})
        except (ArkError, OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            persist_download_failure(out, args, record, exc)
            task["record"] = record
            write_json(task_file, task)
            raise ArkError(f"图像已在平台生成并计费，本地下载未完成：{exc}；相同命令可续接下载") from None
        record.update(status="succeeded", errors=[])
        task["record"] = record
        write_json(task_file, task)
        return write_record(out, args.name, record)


# ---------- 视频 ----------

def video_content(prompt, first=None, last=None, first_ref=None, images=(), videos=(), audios=()):
    """按方舟的三种互斥模式组装 content：首帧／首尾帧、全模态参考，或纯文本。"""
    if (first or last) and (images or videos or audios or first_ref):
        raise ArkError("首帧／首尾帧模式不能与参考素材混用；需要两者时用 --first-frame-ref")
    if last and not first:
        raise ArkError("--last-frame 需要同时给出 --first-frame")
    if first_ref:
        images = [first_ref, *images]
        prompt = "图片1是本镜首帧画面，视频从这一画面开始。\n" + prompt
    content = [{"type": "text", "text": prompt}]
    for url, role in ((first, "first_frame"), (last, "last_frame")):
        if url:
            content.append({"type": "image_url", "image_url": {"url": url}, "role": role})
    content += [{"type": "image_url", "image_url": {"url": url}, "role": "reference_image"} for url in images]
    content += [{"type": "video_url", "video_url": {"url": url}, "role": "reference_video"} for url in videos]
    content += [{"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"} for url in audios]
    return content


def frame_source(item, shot, state, project):
    """推断首帧来源：来自上一镜视频的尾帧或出点关键帧记作 previous_exit。"""
    previous = None
    if state:
        for scene in state["scenes"]:
            order = [entry["id"] for entry in scene["shots"]]
            if shot in order and order.index(shot) > 0:
                previous = order[order.index(shot) - 1]
    for _, record in records(project):
        for output in record.get("outputs", []):
            if output.get("sha256") == item["sha256"] and record.get("shot_id") and record["shot_id"] != shot:
                return {**item, "from": "previous_exit", "shot": record["shot_id"]} if record["shot_id"] == previous else {**item, "from": "reference"}
    return {**item, "from": "generated"}


def generate_video(args):
    poll_limits(args)  # 无效本轮限制必须在提交前失败。
    out, prompt, sources = output_dir(args), prompt_of(args), originals(args.project)
    pick = lambda values: [resolve(value, args.project, sources) for value in values]  # noqa: E731
    first = resolve(args.first_frame, args.project, sources) if args.first_frame else None
    last = resolve(args.last_frame, args.project, sources) if args.last_frame else None
    first_ref = resolve(args.first_frame_ref, args.project, sources) if args.first_frame_ref else None
    images, videos, audios = pick(args.ref_image), pick(args.ref_video), pick(args.ref_audio)
    content = video_content(prompt, first and first[0], last and last[0], first_ref and first_ref[0],
                            [u for u, _ in images], [u for u, _ in videos], [u for u, _ in audios])
    params = {"resolution": args.resolution, "ratio": args.ratio, "duration": args.duration, "generate_audio": not args.no_audio,
              "return_last_frame": True, "watermark": False}
    if args.draft:
        params["draft"] = True
    payload = {"model": args.model, "content": content, **params}
    state = consistency.load(args.state, consistency.STATE_FORMAT) if args.state else None
    inputs = {"anchors_sha256": anchors(args, args.shot),
              "references": [*typed_references(images, "image", args), *typed_references(videos, "video", args),
                             *typed_references(audios, "audio", args)],
              "prompt": content[0]["text"]}
    if not args.no_audio or audios:
        inputs["audio_anchors_sha256"] = audio_anchors(args, args.shot)
    for key, value in (("first_frame", first or first_ref), ("last_frame", last)):
        if value and value[1]:
            inputs[key] = frame_source(value[1], args.shot, state, args.project) if key == "first_frame" else {**value[1], "from": "generated"}
    if args.dry_run:
        shown = json.loads(json.dumps(payload))
        for entry in shown["content"]:
            for field in ("image_url", "video_url", "audio_url"):
                if field in entry and entry[field]["url"].startswith("data:"):
                    entry[field]["url"] = entry[field]["url"][:40] + "…"
        print(json.dumps({"payload": shown, "inputs": inputs}, ensure_ascii=False, indent=2))
        return None
    started = now()
    record = base_record(args, "video", "candidate", args.shot, inputs, {"model": args.model, "params": params}, started)
    video = out / f"{args.name}.mp4"
    frame = out / f"{args.name}-尾帧.jpeg"
    preflight_record(record)
    with generation_lock(out, args.name):
        media_inputs = ([first] if first else []) + ([last] if last else []) + ([first_ref] if first_ref else []) + images + videos + audios
        task_file, task = generation_task(out, args, record, payload, [video, frame], semantic_payload(payload, media_inputs))
        if "completed_record" in task:
            return out / f"{args.name}-生成记录.json"
        if "id" not in task:
            submission = submit_once(task_file, task, "/contents/generations/tasks", payload, out, args)
            task.update(submission=submission, submitted_at=stamp(started))
            task_id = submission.get("id") if isinstance(submission, dict) else None
            if not isinstance(task_id, str) or not consistency.SAFE_ID.fullmatch(task_id):
                write_json(task_file, task)
                record.update(finished_at=stamp(now()), errors=[{"error": "平台未返回有效任务编号，不能安全重提"}],
                              budget={"billable": True, "usage": {"note": "提交已有响应，计费用量待平台核实"}})
                write_record(out, args.name, record)
                raise ArkError("平台未返回有效任务编号；已保存提交响应，不能安全重提")
            task["id"] = task_id
            record["engine"]["task_id"] = task["id"]
            task["record"] = record
            write_json(task_file, task)
            print(f"{args.name} 已提交 {task['id']}", flush=True)
        else:
            record = task["record"]
            print(f"{args.name} 续接任务 {task['id']}", flush=True)
        if "result" not in task:
            poll_task(task_file, task, out, args)
        result = task["result"]
        record.update(finished_at=stamp(now()), budget={"billable": result.get("status") == "succeeded", "usage": result.get("usage") or {"note": "平台未返回用量"}})
        if result.get("status") != "succeeded":
            record["errors"] = [{"error": json.dumps(result.get("error") or {"status": result.get("status")}, ensure_ascii=False)}]
            write_record(out, args.name, record)
            raise ArkError(f"{args.name} 生成失败：{record['errors'][0]['error']}")
        remote_success(record, result)
        record["engine"]["request_sha256"] = digest_json(task["binding"])
        record["engine"]["payload_sha256"] = task["binding"]["payload_sha256"]
        if task["binding"].get("semantic_payload_sha256"):
            record["engine"]["semantic_payload_sha256"] = task["binding"]["semantic_payload_sha256"]
        write_record(out, args.name, record)
        made = datetime.datetime.fromisoformat(task["generated_at"])
        common = {"source_url_expires_at": stamp(made + URL_TTL), "generated_at": stamp(made),
                  "face_trust_until": trust_until(args.model, made, True)}
        try:
            download_output(result["content"]["video_url"], video, record, args,
                            {"id": args.name, "duration_ms": int(float(result.get("duration") or args.duration) * 1000),
                             "source_url": result["content"]["video_url"], **common})
            task["record"] = record
            write_json(task_file, task)
            write_record(out, args.name, record)
            if result["content"].get("last_frame_url"):
                download_output(result["content"]["last_frame_url"], frame, record, args,
                                {"id": f"{args.name}-尾帧", "role": "last_frame", "source_url": result["content"]["last_frame_url"], **common})
        except (ArkError, OSError, KeyError, TypeError, ValueError) as exc:
            persist_download_failure(out, args, record, exc)
            task["record"] = record
            write_json(task_file, task)
            raise ArkError(f"视频已在平台生成并计费，本地下载未完成：{exc}；相同命令可续接下载") from None
        record.update(status="succeeded", errors=[])
        record["engine"]["params"]["actual"] = {key: result.get(key) for key in ("resolution", "ratio", "duration", "framespersecond") if result.get(key) is not None}
        task["record"] = record
        write_json(task_file, task)
        return write_record(out, args.name, record)


def poll_limits(args):
    values = (getattr(args, "max_polls", 40), getattr(args, "deadline_seconds", 600), getattr(args, "poll_interval", 15))
    if (isinstance(values[0], bool) or not isinstance(values[0], int) or values[0] < 1
            or not consistency.number(values[1], 0, inclusive=False) or not consistency.number(values[2])
            or not math.isfinite(values[1]) or not math.isfinite(values[2])):
        raise ArkError("max-polls 必须为正整数，deadline-seconds 必须为正数，poll-interval 必须为非负数")
    return values


def poll_task(task_file, task, out, args):
    """每轮有界查询同一个 task；等待、超时或中断均不允许再次 POST。"""
    maximum, seconds, interval = poll_limits(args)
    deadline = time.monotonic() + seconds
    polling = task.setdefault("polling", {"polls_total": 0})
    token = QUERY_DEADLINE.set(deadline)
    reason = "达到 max-polls"
    try:
        for attempt in range(maximum):
            if time.monotonic() >= deadline:
                reason = "达到 deadline"
                break
            try:
                result = call(f"/contents/generations/tasks/{task['id']}")
            except ArkPending:
                reason = "达到 deadline"
                break
            if not isinstance(result, dict):
                raise ArkError("平台查询响应不是对象；保留原任务编号供续查")
            polling.update(polls_total=polling.get("polls_total", 0) + 1, last_result=result, last_poll_at=stamp(now()), state="waiting")
            task["record"]["engine"]["task_status"] = result.get("status")
            if result.get("status") in ("succeeded", "failed", "cancelled", "expired"):
                polling["state"] = "terminal"
                task.update(result=result, generated_at=stamp(generated_at(result, now())))
                write_json(task_file, task)
                return result
            write_json(task_file, task)
            if attempt + 1 < maximum:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "达到 deadline"
                    break
                time.sleep(min(interval, remaining))
    finally:
        QUERY_DEADLINE.reset(token)
    polling["state"] = "waiting"
    record = task["record"]
    record.update(finished_at=stamp(now()), errors=[{"stage": "poll", "error": f"本轮查询{reason}，远程任务仍待续查"}])
    write_json(task_file, task)
    write_record(out, args.name, record)
    raise ArkPending(f"{args.name} 本轮查询{reason}；任务 {task['id']} 仍保留，相同命令可续查，不会重新提交")


# ---------- 视觉检查 ----------

def checklist(pack, moment):
    """由锚点包推出可目视核对的条目：在场人物与道具、位置、手持物、不可变特征。"""
    names = {entity_id: info.get("name", entity_id) for entity_id, info in pack["entities"].items()}
    moments = [moment] if moment else ["entry", "exit"]
    location = pack["location"]
    items = [f"地点是{location.get('name', location['id'])}"]
    if location.get("identity"):
        items.append("地点的不可变特征：" + "、".join(location["identity"]))
    labels = {"entry": "开头", "exit": "结尾"}
    for when in moments:
        label = labels[when] if not moment else ""
        environment = pack.get("environment", {}).get(when, {})
        if environment:
            items.append(label + "环境：" + "、".join(f"{key}={value}" for key, value in environment.items()))
    for entity_id, info in pack["entities"].items():
        if info.get("kind") == "location":
            continue
        for when in moments:
            state = info.get(when)
            label = {"entry": "开头", "exit": "结尾"}[when] if not moment else ""
            if state is None:
                items.append(f"{label}画面中不应出现{names[entity_id]}")
                continue
            facts = [f"{names[entity_id]}在画面中"]
            if state.get("position"):
                facts.append(f"位于{state['position']}")
            if state.get("holding"):
                facts.append("手持" + "、".join(names.get(x, x) for x in state["holding"]))
            if state.get("variant_description"):
                facts.append("外观为" + str(state["variant_description"]))
            items.append(label + "，".join(facts))
        if info.get("identity"):
            items.append(f"{names[entity_id]}的不可变特征：{'、'.join(info['identity'])}")
    return items + consistency.observation_checklist(pack, moment)


def entity_checklist(bible, entity_ids):
    """资产图的核对条目：每个实体的不可变特征与默认外观。"""
    index, items = consistency.entity_index(bible), []
    for entity_id in entity_ids:
        if entity_id not in index:
            raise ArkError(f"资产库中没有实体 {entity_id}")
        info = index[entity_id]
        items += [f"{info.get('name', entity_id)}：{trait}" for trait in info.get("identity", [])]
        items.append(f"{info.get('name', entity_id)}的外观：{info['variants']['default']}")
    return items


def vision_prompt(items):
    lines = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(items))
    return ("你是短剧连续性检查员。逐条核对画面是否符合下列预期，只依据画面本身，看不清就判 unsure。"
            "另外数一数画面中的人数，并指出任何多出来、缺失或变形的人物与道具。\n" + lines +
            '\n只输出 JSON：{"results":[{"item":"原文","verdict":"pass|fail|unsure","evidence":"看到了什么"}],'
            '"people":整数,"issues":["其他问题"]}')


def parse_json(text):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ArkError("视觉模型没有返回 JSON")
    return json.loads(match.group(0))


def frames_of(media, workdir):
    """视频取首、中、尾三帧；图片原样返回。"""
    if not media_type(media).startswith("video/"):
        return [("画面", Path(media))]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)],
                           capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())
    picked = []
    for label, at in (("首帧", 0.0), ("中段", duration / 2), ("尾帧", max(duration - 0.1, 0.0))):
        target = Path(workdir) / f"{label}.jpeg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(media), "-frames:v", "1", "-q:v", "3", str(target)], check=True)
        picked.append((label, target))
    return picked


def prepare_inspection(args):
    """纯本地预检；批准与付费提交共用同一份固定输入绑定。"""
    project = Path(args.project).resolve()
    pid = project_id(project)
    shot, entities = getattr(args, "shot", None), getattr(args, "entity", None)
    moment = getattr(args, "moment", None)
    if not getattr(args, "bible", None) or bool(shot) == bool(entities) or (shot and not getattr(args, "state", None)):
        raise ArkError("inspect 需要 --bible，并选择 --shot/--state 或 --entity")
    if moment not in (None, *consistency.MOMENTS) or (moment and not shot):
        raise ArkError("inspect 的 --moment 只用于镜头的 entry 或 exit 检查")
    model = getattr(args, "model", None)
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
        raise ArkError("inspect 需要有效的视觉模型 ID")
    extra = getattr(args, "check", [])
    if not isinstance(extra, list) or any(not consistency.text(item) for item in extra):
        raise ArkError("视觉检查清单必须是非空文本条目")
    if entities is not None and (not isinstance(entities, list) or any(not consistency.text(item) for item in entities)):
        raise ArkError("视觉检查实体必须是非空 ID 数组")

    def local(raw):
        value = Path(raw)
        # 作品内相对路径优先；保留旧 CLI 从工作区传入 Bible/状态路径的用法。
        path = (project / value if not value.is_absolute() and (project / value).exists() else value).resolve()
        if not path.is_file():
            raise ArkError(f"视觉检查输入文件不存在：{raw}")
        try:
            name = str(path.relative_to(project))
        except ValueError:
            name = str(path)
        return path, {"path": name, "sha256": sha256(path)}

    def document(raw, expected):
        path, ref = local(raw)
        content = path.read_bytes()
        ref["sha256"] = hashlib.sha256(content).hexdigest()
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError):
            raise ArkError(f"视觉检查输入不是有效 JSON：{path.name}") from None
        if not isinstance(data, dict) or data.get("format") != expected:
            raise ArkError(f"视觉检查输入格式必须为 {expected}")
        return data, ref

    bible, bible_ref = document(args.bible, consistency.BIBLE_FORMAT)
    errors = consistency.bible_errors(bible)
    if bible.get("project_id") != pid:
        errors.append("资产库与当前项目编号必须一致")
    state, state_ref = None, None
    if getattr(args, "state", None):
        state, state_ref = document(args.state, consistency.STATE_FORMAT)
        errors += consistency.state_errors(state, bible)
        if state.get("project_id") != pid:
            errors.append("场景状态与当前项目编号必须一致")
    if errors:
        raise ArkError("视觉检查输入无效：" + "；".join(errors))
    if shot:
        try:
            pack = consistency.anchor_pack(bible, state, shot)
        except (KeyError, ValueError) as exc:
            raise ArkError(f"视觉检查镜头无效：{exc}") from None
        items = checklist(pack, moment) + extra
    else:
        pack, items = None, entity_checklist(bible, entities) + extra
    items = list(dict.fromkeys(items))
    media, media_ref = local(args.media)
    try:
        media.relative_to(project)
    except ValueError:
        raise ArkError("inspect 素材必须位于项目内") from None
    if not media_type(media).startswith(("image/", "video/")):
        raise ArkError("inspect 只接受图像或视频")
    inputs = {"bible": bible_ref, "media": media_ref}
    if state_ref:
        inputs["state"] = state_ref
    if pack:
        inputs["anchors_sha256"] = consistency.pack_sha256(pack)
    binding = {"project_id": pid, "kind": "inspect", "provider": PROVIDER, "model": model,
               "shot_id": shot, "moment": moment, "entities": entities or None, "checklist": items, "inputs": inputs}
    return binding, items, pack, media


def inspect(args):
    binding, items, pack, media = prepare_inspection(args)
    binding_sha256 = digest_json(binding)
    target = media.with_name(f"{media.stem}-视觉检查.json")
    attempt_file = media.with_name(f"{media.stem}-视觉检查-{binding_sha256}-尝试.json")
    reservation = getattr(args, "budget_reservation", None)
    with generation_lock(media.parent, media.stem + "-视觉检查"):
        for path in (target, attempt_file):
            if path.is_symlink():
                raise ArkError("视觉检查报告与尝试凭据不能是符号链接")
        if target.exists():
            try:
                old = json.loads(target.read_text("utf-8"))
            except ValueError:
                old = None
            if not isinstance(old, dict) or old.get("binding_sha256") != binding_sha256:
                target = media.with_name(f"{media.stem}-视觉检查-{binding_sha256}.json")
        if target.is_symlink():
            raise ArkError("视觉检查报告不能是符号链接")
        attempt = json.loads(attempt_file.read_text("utf-8")) if attempt_file.exists() else None
        if attempt is not None and (not isinstance(attempt, dict) or attempt.get("binding") != binding
                                    or attempt.get("binding_sha256") != binding_sha256):
            raise ArkError("视觉检查尝试凭据与当前输入不符，不能安全续接")
        if target.exists():
            report = json.loads(target.read_text("utf-8"))
            if (not isinstance(report, dict) or report.get("binding") != binding or report.get("binding_sha256") != binding_sha256
                    or consistency.visual_errors(report) or report.get("checklist") != items
                    or report.get("subject") != binding["inputs"]["media"]
                    or report.get("engine") != {"provider": PROVIDER, "model": binding["model"]}
                    or any(report.get(key) != binding[key] for key in ("project_id", "shot_id", "moment", "entities"))
                    or report.get("anchors_sha256") != binding["inputs"].get("anchors_sha256")
                    or (attempt and (report.get("budget_reservation") != attempt.get("budget_reservation")
                                     or (attempt.get("report_sha256") and attempt["report_sha256"] != sha256(target))))):
                raise ArkError("已有视觉检查报告不能通过原始绑定核验，拒绝重新付费或覆盖")
            return target
        if attempt is not None:
            if attempt.get("submission_state") != "responded" or "response" not in attempt:
                raise ArkError("视觉检查提交结果未知或已拒绝；不能自动重提，请先人工核查平台任务与账单")
            result = attempt["response"]
        else:
            # 新提交会直接调用对话模型；在写预算或提交意图之前就按套餐规则拒绝。
            problem = credentials.text_model_problem()
            if problem:
                raise ArkError(problem)
            # 即使换了输入，也不能把一个已经提交过的预留再次用于 POST。
            if reservation:
                for saved in Path(args.project).resolve().rglob("*-视觉检查-*-尝试.json"):
                    value = json.loads(saved.read_text("utf-8"))
                    if isinstance(value, dict) and value.get("budget_reservation") == reservation:
                        raise ArkError("该预算预留已有视觉检查提交凭据，不能重复提交")
            with tempfile.TemporaryDirectory() as workdir:
                content = []
                for label, path in frames_of(media, workdir):
                    content.append({"type": "text", "text": label})
                    content.append({"type": "image_url", "image_url": {"url": f"data:{media_type(path)};base64,{base64.b64encode(path.read_bytes()).decode()}"}})
                content.append({"type": "text", "text": vision_prompt(items)})
                if prepare_inspection(args)[0] != binding:
                    raise ArkError("视觉检查输入在预检后已改变，不能提交")
                key = api_key()  # 本地缺凭证不写可能已付费的提交意图。
                try:
                    from vsc.production import budget as vsc_budget
                    vsc_budget.check_authorization(args.project, reservation, "inspect:" + binding["inputs"]["media"]["path"],
                                                   {"remote_jobs": 1, "vision_jobs": 1}, request=binding)
                except (ImportError, ValueError, RuntimeError) as exc:
                    raise ArkError(f"预算授权无效：{exc}") from None
                attempt = {"format": "vsc.ark-inspection-attempt/v1", "binding": binding, "binding_sha256": binding_sha256,
                           "budget_reservation": reservation, "credential_sha256": hashlib.sha256(key.encode()).hexdigest(),
                           "submission_state": "intent", "submitted_at": stamp(now())}
                write_json(attempt_file, attempt)
                try:
                    result = call("/chat/completions", {"model": binding["model"], "messages": [{"role": "user", "content": content}]}, attempts=1)
                except BaseException as exc:
                    rejected = isinstance(exc, ArkHTTPError) and 400 <= exc.status_code < 500
                    attempt.update(submission_state="rejected" if rejected else "unknown",
                                   error=(str(exc) or type(exc).__name__).replace(key, "[REDACTED]"))
                    write_json(attempt_file, attempt)
                    raise
                attempt.update(submission_state="responded", response=result)
                write_json(attempt_file, attempt)
        return _inspection_report(args, binding, items, pack, media, target, attempt_file, attempt, result)


def _inspection_report(args, binding, items, pack, media, target, attempt_file, attempt, result):
    """已付费响应只在本地解析；解析失败也保留原响应，禁止重付费。"""
    try:
        answer = parse_json(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ArkError(f"视觉模型响应无效：{exc}") from None
    if not isinstance(answer, dict):
        raise ArkError("视觉模型响应必须是 JSON 对象")
    results = answer.get("results", [])
    if (not isinstance(results, list) or any(not isinstance(item, dict) or not consistency.text(item.get("item")) or not consistency.text(item.get("evidence")) for item in results)
            or len(results) != len(items) or sorted(item.get("item", "") for item in results) != sorted(items)):
        raise ArkError("视觉检查必须逐项返回原始 checklist，且每项恰好一次并提供非空 evidence")
    if prepare_inspection(args)[0] != binding:
        raise ArkError("检查期间输入已改变，不能把视觉结果绑定到新文件")
    report = {"format": consistency.VISUAL_FORMAT, "project_id": binding["project_id"], "shot_id": binding["shot_id"], "moment": binding["moment"],
              "subject": binding["inputs"]["media"],
              "anchors_sha256": consistency.pack_sha256(pack) if pack else None, "entities": binding["entities"],
              "engine": {"provider": PROVIDER, "model": binding["model"]},
              "binding": binding, "binding_sha256": digest_json(binding), "budget_reservation": attempt.get("budget_reservation"),
              "created_at": stamp(now()), "advisory": True, "usage": result.get("usage"),
              "checklist": items, "results": results, "people": answer.get("people"), "issues": answer.get("issues", [])}
    errors = consistency.visual_errors(report)
    if errors:
        raise ArkError("视觉检查结果无效：" + "；".join(errors))
    write_json(target, report)
    attempt["report_sha256"] = sha256(target)
    write_json(attempt_file, attempt)
    return target


# ---------- 命令行 ----------

def parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True)
    common.add_argument("--bible")
    common.add_argument("--state")
    made = argparse.ArgumentParser(add_help=False, parents=[common])
    made.add_argument("--out", required=True, help="相对作品目录的输出目录")
    made.add_argument("--name", required=True)
    made.add_argument("--prompt")
    made.add_argument("--prompt-file")
    made.add_argument("--budget-reservation", help="正式付费提交使用的共享预算预留 ID")

    image = sub.add_parser("image", parents=[made], help="Seedream 生成资产图或关键帧")
    image.add_argument("--ref", action="append", default=[])
    image.add_argument("--base-frame")
    image.add_argument("--base-use", choices=consistency.BASE_USES, default="edit")
    image.add_argument("--purpose", choices=("asset", "candidate"), default="candidate")
    image.add_argument("--shot")
    image.add_argument("--moment", choices=consistency.MOMENTS)
    image.add_argument("--model", default=IMAGE_MODEL)
    image.add_argument("--size", default="2K")

    video = sub.add_parser("video", parents=[made], help="Seedance 生成镜头视频")
    video.add_argument("--shot", required=True)
    video.add_argument("--first-frame")
    video.add_argument("--last-frame")
    video.add_argument("--first-frame-ref", help="全模态参考模式下作为图片1并指定为首帧")
    video.add_argument("--ref-image", action="append", default=[])
    video.add_argument("--ref-video", action="append", default=[])
    video.add_argument("--ref-audio", action="append", default=[])
    video.add_argument("--model", default=VIDEO_MODEL)
    video.add_argument("--resolution", default="480p")
    video.add_argument("--ratio", default="adaptive")
    video.add_argument("--duration", type=int, default=5)
    video.add_argument("--no-audio", action="store_true")
    video.add_argument("--draft", action="store_true", help="Seedance 2.5 样片模式（仅 480p，可在 7 天内升级为 1080p）")
    video.add_argument("--dry-run", action="store_true", help="只打印请求与记录输入，不提交")
    video.add_argument("--max-polls", type=int, default=40, help="本轮最多查询次数，续查沿用原 task")
    video.add_argument("--deadline-seconds", type=float, default=600, help="本轮查询时间上限（秒）")
    video.add_argument("--poll-interval", type=float, default=15, help="查询间隔（秒）")

    check = sub.add_parser("inspect", parents=[common], help="用豆包视觉模型按锚点包核对画面")
    check.add_argument("--media", required=True)
    target = check.add_mutually_exclusive_group(required=True)
    target.add_argument("--shot", help="按该镜锚点包核对镜头画面")
    target.add_argument("--entity", action="append", help="按资产库核对资产图中的实体，可重复")
    check.add_argument("--moment", choices=consistency.MOMENTS)
    check.add_argument("--check", action="append", default=[], help="额外核对条目")
    check.add_argument("--model", default=VISION_MODEL)
    check.add_argument("--budget-reservation", help="正式视觉检查使用的共享预算预留 ID")

    return parser


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "image":
            path = generate_image(args)
        elif args.command == "video":
            if args.shot and not (args.bible and args.state):
                print("提醒：未给 --bible/--state，生成记录不会绑定锚点包", file=sys.stderr)
            path = generate_video(args)
        else:
            path = inspect(args)
    except (ArkError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
