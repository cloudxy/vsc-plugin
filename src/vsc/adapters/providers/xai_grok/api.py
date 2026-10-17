#!/usr/bin/env python3
"""xAI Grok Imagine 生成适配器（订阅登录路线）：图像文生图、视频图生视频。只用标准库。

  image  --project P --out DIR --name N (--prompt T | --prompt-file F)
          [--ref X ...] [--purpose asset|candidate] [--shot S --moment entry|exit --bible B --state S]
          [--model M] [--aspect-ratio 9:16] [--resolution 1k|2k] [--count 1]
  video  --project P --out DIR --name N --shot S (--prompt T | --prompt-file F)
          [--first-frame X] [--last-frame X] [--ref-image X ...] [--keyframe FILE@SEC ...] [--voice-id V ...]
          [--ratio R] [--no-audio] [--bible B --state S] [--model M] [--resolution 480p] [--duration 6]
          [--dry-run] [--max-polls N] [--deadline-seconds S] [--poll-interval S]
  edit   --project P --out DIR --name N --shot S --video V (--prompt T | --prompt-file F) [--dry-run ...]
  extend --project P --out DIR --name N --shot S --video V [--prompt T] [--dry-run ...]

X 是本地图片文件或 https 链接；本地图以 data URI 提交。图像：无 --ref 走文生图；带 --ref（≤5）
走 /v1/images/edits 局部编辑或多图合成，提示词只写要改的内容。视频按官方模式组装：--first-frame
首帧锚定；--ref-image（≤14）参考模式（提示词用 <IMAGE_n> 指位，与首帧同用时首帧占 <IMAGE_0>、参
考图从 <IMAGE_1> 起编号）；--last-frame 钉定尾帧（可与首帧或参考同用）；--keyframe（≤4，1.5 系列）
钉中段帧；--voice-id（≤3）平台预置声音，提示词用 <AUDIO_n> 指位；--no-audio 请求无声视频；都不给
则纯文生视频。参考模式分辨率最高 720p。图生视频默认画幅跟随源图，参考／文生模式可用 --ratio 显式
指定。edit／extend 对既有视频做编辑或从结尾续接（输出跟随输入，不可改时长／分辨率／画幅；编辑上限
约 8.7s、720p）。

密钥只从 grok CLI 订阅登录态（~/.grok/auth.json 的 key）读取，不打印、不落盘；找不到时提示
在终端运行 grok 完成登录。请求必须带浏览器 User-Agent，否则平台网关回 403。默认端点
https://api.x.ai/v1，GROK_BASE_URL 只能设为同一地址。提交生成任务不自动重试，避免重复计费；
视频任务的编号先写入 <名称>-任务.json，中断后重跑同一命令会续接查询，不会重新提交。
每次生成写一份 vsc.generation-record/v1，放在输出旁边；返回的 URL 是临时的，必须立即转存。
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
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from vsc.story import consistency as consistency
from vsc.adapters.providers.xai_grok import credentials as grok_credentials

API_BASE = grok_credentials.API_BASE
USER_AGENT = grok_credentials.USER_AGENT
IMAGE_MODEL = "grok-imagine-image-2.0"
VIDEO_MODEL = "grok-imagine-video-1.5"
EDIT_MODEL = "grok-imagine-video"  # 官方：视频编辑/续接由经典模型承担（1.5 返回不支持）
PROVIDER = "xai_grok"
ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20", "auto")
IMAGE_RESOLUTIONS = ("1k", "2k")
VIDEO_RESOLUTIONS = ("480p", "720p", "1080p")
MIN_DURATION, MAX_DURATION = 1, 15
# 官方未公布结果 URL 的时效；这里只作记录元数据，下载总是在完成后立即执行。
URL_TTL = datetime.timedelta(hours=1)
QUERY_DEADLINE = contextvars.ContextVar("grok_query_deadline", default=None)
IMAGE_SUFFIXES = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp",
                  "image/gif": "gif", "image/bmp": "bmp"}


class GrokError(RuntimeError):
    """请求无效、平台拒绝或运行环境未就绪。"""


class GrokHTTPError(GrokError):
    """HTTP 错误保留状态码；计费分类不依赖异常文本。"""
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class GrokPending(GrokError):
    """本轮查询有界退出；远程任务仍可用同一编号续查。"""


def now():
    return datetime.datetime.now().astimezone()


def stamp(moment):
    return moment.isoformat(timespec="seconds")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def api_key():
    return grok_credentials.read_key(error=GrokError)


def base_url():
    """The subscription login only works on the official REST plane."""
    value = os.environ.get("GROK_BASE_URL", API_BASE).strip().rstrip("/")
    if value != API_BASE:
        raise GrokError("Grok 订阅路线只能使用 GROK_BASE_URL=" + API_BASE)
    return value


def call(path, payload=None, attempts=None):
    """调用 xAI 接口。提交（有 payload）只发一次，查询失败时重试。"""
    key = api_key()
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": USER_AGENT, "Authorization": "Bearer " + key}
    request = urllib.request.Request(base_url() + path, data=data, headers=headers)
    attempts = 1 if payload is not None else (attempts or 6)
    deadline = QUERY_DEADLINE.get() if payload is None else None
    if deadline is not None:
        attempts = 1
    for attempt in range(attempts):
        timeout = 300 if deadline is None else min(300, deadline - time.monotonic())
        if timeout <= 0:
            raise GrokPending("本轮查询已达到 deadline；相同命令可续查原任务")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace").replace(key, "[REDACTED]")
            denied = grok_credentials.permission_denied(exc.code, "xAI Grok Imagine 接口")
            message = f"{denied}。平台返回：{body[:800]}" if denied else f"HTTP {exc.code}: {body[:800]}"
            raise GrokHTTPError(exc.code, message) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt == attempts - 1:
                raise GrokError(f"网络错误：{str(exc).replace(key, '[REDACTED]')}") from None
            time.sleep(10)


def download(url, target):
    """完整下载后原子落盘；网络中断不会留下看似完整的产物。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
                temporary = Path(handle.name)
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=180) as response:
                    while chunk := response.read(1 << 20):
                        handle.write(chunk)
            temporary.replace(target)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt == 3:
                raise GrokError(f"下载失败：{exc}") from None
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

def media_type(path):
    """按文件头判断媒体类型；扩展名可能与内容不符（例如 JPEG 内容存成 .png）。"""
    with Path(path).open("rb") as handle:
        head = handle.read(16)
    for magic, kind in ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"), (b"GIF8", "image/gif"), (b"BM", "image/bmp")):
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF":
        return {b"WEBP": "image/webp", b"WAVE": "audio/wav"}.get(head[8:12], "application/octet-stream")
    if head[4:8] == b"ftyp":
        return "video/quicktime" if head[8:10] == b"qt" else "video/mp4"
    return mimetypes.guess_type(Path(path).name)[0] or "application/octet-stream"


def resolve(value, project):
    """把命令行给出的素材转成 Grok 可接受的地址；本地文件同时返回 {path, sha256} 供生成记录使用。"""
    if value.startswith(("https://", "http://")):
        return value, None
    if value.startswith("asset://"):
        raise GrokError("Grok 路线暂不解析 asset:// 素材；请给出本地文件路径或 https 链接")
    path = Path(value)
    if not path.is_file():
        raise GrokError(f"素材不存在：{value}")
    if not media_type(path).startswith("image/"):
        raise GrokError(f"首帧必须是图片：{value}")
    try:
        shown = str(path.resolve().relative_to(Path(project).resolve()))
    except ValueError:
        shown = str(path.resolve())
    item = {"path": shown, "sha256": sha256(path)}
    return f"data:{media_type(path)};base64,{base64.b64encode(path.read_bytes()).decode()}", item


def prompt_of(args):
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text("utf-8").strip()
        if prompt:
            return prompt
    if args.prompt:
        if args.prompt.strip():
            return args.prompt.strip()
    raise GrokError("需要 --prompt 或 --prompt-file")


def anchors(args, shot):
    if not (args.bible or args.state):
        return None
    if not (args.bible and args.state and shot):
        raise GrokError("绑定锚点包需要同时给出 --shot、--bible、--state")
    bible = consistency.load(args.bible, consistency.BIBLE_FORMAT)
    state = consistency.load(args.state, consistency.STATE_FORMAT)
    errors = consistency.bible_errors(bible) + consistency.state_errors(state, bible)
    if bible.get("project_id") != project_id(args.project) or state.get("project_id") != project_id(args.project):
        errors.append("资产库、场景状态与当前项目编号必须一致")
    if errors:
        raise GrokError("锚点输入无效：" + "；".join(errors))
    return consistency.pack_sha256(consistency.anchor_pack(bible, state, shot))


def project_id(project):
    try:
        return json.loads((Path(project) / "vsc.json").read_text("utf-8"))["project_id"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise GrokError(f"无法读取项目编号：{exc}") from None


def write_record(out, name, record):
    errors = consistency.record_errors(record)
    if errors:
        raise GrokError("生成记录无效：" + "；".join(errors))
    path = out / f"{name}-生成记录.json"
    write_json(path, record)
    return path


def base_record(args, kind, purpose, shot, inputs, engine, started):
    return {"format": consistency.RECORD_FORMAT, "project_id": project_id(args.project), "kind": kind, "purpose": purpose,
            "shot_id": shot, "inputs": inputs, "engine": {"provider": PROVIDER, **engine}, "budget": {"billable": False, "usage": None},
            "submitted_at": stamp(started), "finished_at": None, "status": "failed", "outputs": [], "errors": [], "selection": None}


def output_dir(args):
    if not isinstance(args.name, str) or not consistency.SAFE_ID.fullmatch(args.name):
        raise GrokError("--name 必须是安全文件名：以字母或数字开头，只含字母、数字、点、下划线或连字符")
    out = project_path(args.project, args.out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def project_path(project, relative):
    """拒绝绝对路径、父目录、反斜杠与跨项目的符号链接。"""
    if not isinstance(relative, str) or not relative or "\\" in relative or any(ord(char) < 32 for char in relative):
        raise GrokError("输出与来源路径必须是项目内的相对路径")
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise GrokError("输出与来源路径必须是项目内的相对路径")
    root = Path(project).resolve()
    target = root / value
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise GrokError("输出与来源路径不能通过符号链接离开项目") from None
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
        raise GrokError("生成锁不能是符号链接")
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GrokError(f"同名生成正在运行：{name}") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def request_binding(record, payload, semantic=None):
    binding = {"project_id": record["project_id"], "kind": record["kind"], "purpose": record["purpose"],
            "shot_id": record["shot_id"], "inputs": record["inputs"], "model": record["engine"]["model"],
            "params": record["engine"]["params"], "payload_sha256": digest_json(payload)}
    if semantic is not None:
        binding["semantic_payload_sha256"] = digest_json(semantic)
    return json.loads(json.dumps(binding, ensure_ascii=False))


def semantic_payload(payload, media_inputs):
    """运输地址可过期；本地输入的语义固定为内容 SHA，媒体角色仍由原 payload 保留。

    media_inputs 顺序须与 payload 中出现的顺序一致：首帧、尾帧，然后参考图。
    """
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    media_inputs = iter(media_inputs)

    def swap(holder):
        _, item = next(media_inputs)
        if item and isinstance(holder, dict) and isinstance(holder.get("url"), str):
            holder["url"] = "sha256:" + item["sha256"]

    if isinstance(normalized.get("image"), dict):
        swap(normalized["image"])
    if isinstance(normalized.get("last_frame"), dict):
        swap(normalized["last_frame"])
    for holder in normalized.get("reference_images") or []:
        swap(holder)
    for holder in normalized.get("keyframes") or []:
        swap(holder.get("image") if isinstance(holder, dict) else None)
    if isinstance(normalized.get("video"), dict):
        swap(normalized["video"])
    return normalized


def truncate_payload(payload):
    """dry-run 展示用：所有 data URI 只留前 40 字符。"""
    shown = json.loads(json.dumps(payload, ensure_ascii=False))

    def trim(holder):
        if isinstance(holder, dict) and isinstance(holder.get("url"), str) and holder["url"].startswith("data:"):
            holder["url"] = holder["url"][:40] + "…"

    trim(shown.get("image") if isinstance(shown.get("image"), dict) else None)
    trim(shown.get("last_frame") if isinstance(shown.get("last_frame"), dict) else None)
    trim(shown.get("video") if isinstance(shown.get("video"), dict) else None)
    for holder in shown.get("reference_images") or []:
        trim(holder)
    for holder in shown.get("keyframes") or []:
        trim(holder.get("image") if isinstance(holder, dict) else None)
    return shown


def preflight_record(record):
    checked = {**record, "finished_at": stamp(now())}
    errors = consistency.record_errors(checked)
    if errors:
        raise GrokError("生成输入无效：" + "；".join(errors))


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
            raise GrokError(f"生成输出不能是符号链接：{path.name}")
    binding = request_binding(record, payload, semantic)
    if task_file.exists():
        task = json.loads(task_file.read_text("utf-8"))
        if not isinstance(task, dict):
            raise GrokError("任务文件无效，不能安全续接")
        saved_binding = task.get("binding")
        same_semantics = (isinstance(saved_binding, dict) and saved_binding.get("semantic_payload_sha256")
                          and {key: value for key, value in saved_binding.items() if key != "payload_sha256"}
                          == {key: value for key, value in binding.items() if key != "payload_sha256"})
        if saved_binding != binding and not same_semantics:
            raise GrokError("同名任务的输入或请求参数已改变；请使用新的 --name，不能把新输入记到旧任务")
        saved = task.get("record")
        if not isinstance(saved, dict) or any(saved.get(key) != record.get(key) for key in ("project_id", "kind", "purpose", "shot_id", "inputs")):
            raise GrokError("任务文件缺少原始生成记录，不能安全续接")
        engine = saved.get("engine", {})
        if (not isinstance(engine, dict) or engine.get("provider") != PROVIDER or engine.get("model") != record["engine"]["model"]
                or not isinstance(engine.get("params"), dict)
                or {key: value for key, value in engine["params"].items() if key != "actual"} != record["engine"]["params"]):
            raise GrokError("任务文件的原始模型或参数与绑定不符，不能安全续接")
        if record["kind"] == "video" and (not isinstance(task.get("id"), str) or not consistency.SAFE_ID.fullmatch(task["id"])):
            reason = "平台已明确拒绝该提交" if task.get("submission_state") == "rejected" else "提交状态未知，任务文件缺少有效远程编号"
            raise GrokError(reason + "；不能自动重提，请先人工核查平台任务与账单")
        if task.get("credential_sha256") and task["credential_sha256"] != hashlib.sha256(api_key().encode()).hexdigest():
            raise GrokError("当前登录态与原任务提交凭证不一致；请恢复原登录后续查或下载，不能自动重提")
        return task_file, task
    if any(path.exists() for path in [record_file, *targets]):
        raise GrokError(f"同名输出或生成记录已存在：{args.name}；请使用新的 --name")
    return task_file, {"format": "vsc.grok-task/v1", "binding": binding, "record": record}


def submit_once(task_file, task, path, payload, out, args):
    """提交意图先持久化；进程退出或响应丢失时不能靠重跑再次扣费。"""
    if task_file.exists():
        reason = "平台已明确拒绝该提交" if task.get("submission_state") == "rejected" else "提交结果未知"
        raise GrokError(reason + "；不能自动重提，请先人工核查平台任务与账单")
    base_url()
    key = api_key()  # 本地缺登录态不留下可能已提交的凭证。
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
        rejected = isinstance(exc, GrokHTTPError) and 400 <= exc.status_code < 500
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
            identifier = result.get("request_id")
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
            raise GrokError("正式运行缺少预算授权模块，不能提交付费请求") from None
        return
    try:
        required = ({"remote_jobs": 1, "images": getattr(args, "count", 1)} if operation == "image"
                    else {"remote_jobs": 1, "video_seconds": getattr(args, "duration", 9)})
        vsc_budget.check_authorization(args.project, getattr(args, "budget_reservation", None),
                                       f"{operation}:{args.out}/{args.name}", required, request=vars(args))
    except (ValueError, RuntimeError) as exc:
        raise GrokError(f"预算授权无效：{exc}") from None


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


def download_video_output(url, target, record, args, metadata):
    expected = next((item for item in record["outputs"] if item.get("id") == metadata["id"]), None)
    if target.exists():
        if expected and target.is_file() and sha256(target) == expected.get("sha256"):
            return
        raise GrokError(f"本地产物已存在但无法核实，拒绝覆盖：{target.name}")
    download(url, target)
    record["outputs"].append({**metadata, "path": str(target.relative_to(Path(args.project).resolve())), "sha256": sha256(target)})


def download_image_output(url, out, name, record, args, metadata):
    """图像结果的扩展名以字节内容为准；先下载到临时名再原子定名。"""
    expected = next((item for item in record["outputs"] if item.get("id") == metadata["id"]), None)
    if expected:
        target = project_path(args.project, expected["path"])
        if target.is_file() and sha256(target) == expected.get("sha256"):
            return target
        raise GrokError(f"本地产物已存在但无法核实，拒绝覆盖：{target.name}")
    part = out / f".{name}.下载中"
    if part.exists():
        part.unlink()
    download(url, part)
    kind = media_type(part)
    suffix = IMAGE_SUFFIXES.get(kind)
    target = out / f"{name}.{suffix}" if suffix else None
    if target is None or target.exists():
        part.unlink(missing_ok=True)
        raise GrokError(f"平台返回的不是受支持的图像格式：{kind or '未知'}")
    part.replace(target)
    record["outputs"].append({**metadata, "path": str(target.relative_to(Path(args.project).resolve())), "sha256": sha256(target)})
    return target


def persist_download_failure(out, args, record, exc):
    record.update(status="partial" if record["outputs"] else "failed", errors=[{"error": str(exc), "stage": "download"}])
    write_record(out, args.name, record)


# ---------- 图像 ----------

def image_payload(model, prompt, aspect_ratio, resolution, count):
    return {"model": model, "prompt": prompt, "n": count, "aspect_ratio": aspect_ratio,
            "resolution": resolution, "response_format": "url"}


def edit_payload(model, prompt, images):
    """/v1/images/edits：单源图 image、多源图（≤5）images 合成；提示词只写要改的内容。"""
    if len(images) == 1:
        return {"model": model, "prompt": prompt, "image": {"url": images[0], "type": "image_url"}}
    return {"model": model, "prompt": prompt, "images": [{"url": url, "type": "image_url"} for url in images]}


def generate_image(args):
    if args.purpose == "candidate" and not (args.shot and args.moment and args.bible and args.state):
        raise GrokError("候选关键帧需要 --shot、--moment、--bible、--state；资产图请用 --purpose asset")
    if args.aspect_ratio not in ASPECT_RATIOS or args.resolution not in IMAGE_RESOLUTIONS:
        raise GrokError("画幅须为平台支持的取值；分辨率须为 1k 或 2k")
    if not isinstance(args.count, int) or not 1 <= args.count <= 10:
        raise GrokError("同提示词张数须为 1–10")
    out, prompt = output_dir(args), prompt_of(args)
    refs = [resolve(value, args.project) for value in args.ref]
    if len(refs) > 5:
        raise GrokError("图像编辑一次最多 5 张源图")
    inputs = {"anchors_sha256": anchors(args, args.shot),
              "references": [{"source_uri": url, "sha256": item and item["sha256"], "media_type": "image",
                              "role": "reference_image", "purpose": "identity", "entity_id": None}
                             for url, item in refs],
              "prompt": prompt}
    if args.moment:
        inputs["moment"] = args.moment
    started = now()
    if refs:
        params = {"edit": True, "source_images": len(refs), "resolution": args.resolution, "n": args.count}
        payload = edit_payload(args.model, prompt, [url for url, _ in refs])
        path = "/images/edits"
    else:
        params = {"aspect_ratio": args.aspect_ratio, "resolution": args.resolution, "n": args.count}
        payload = image_payload(args.model, prompt, args.aspect_ratio, args.resolution, args.count)
        path = "/images/generations"
    record = base_record(args, "image", args.purpose, args.shot, inputs, {"model": args.model, "params": params}, started)
    preflight_record(record)
    with generation_lock(out, args.name):
        task_file, task = generation_task(out, args, record, payload, [], semantic_payload(payload, refs))
        if "result" not in task:
            result = submit_once(task_file, task, path, payload, out, args)
            if not isinstance(result, dict):
                raise GrokError("平台图像响应不是对象；提交已有响应，不能安全重提")
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
            items = result["data"]
            if not isinstance(items, list) or not items:
                raise GrokError("平台图像响应缺少候选")
            for index, item in enumerate(items):
                url = item.get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise GrokError(f"第 {index + 1} 张图像缺 URL（临时链接）")
                download_image_output(url, out, args.name if len(items) == 1 else f"{args.name}-{index + 1}",
                                      record, args, {"id": args.name if len(items) == 1 else f"{args.name}-{index + 1}",
                                                     "source_url": url, "source_url_expires_at": stamp(made + URL_TTL),
                                                     "generated_at": stamp(made)})
        except (GrokError, OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            persist_download_failure(out, args, record, exc)
            task["record"] = record
            write_json(task_file, task)
            raise GrokError(f"图像已在平台生成并计费，本地下载未完成：{exc}；相同命令可续接下载") from None
        record.update(status="succeeded", errors=[])
        task["record"] = record
        write_json(task_file, task)
        return write_record(out, args.name, record)


# ---------- 视频 ----------

def video_payload(model, prompt, image, duration, resolution, last_frame=None, reference_images=(), aspect_ratio="",
                  keyframes=(), voice_ids=(), generate_audio=True):
    """按官方模式组装 /v1/videos/generations：文生视频、首帧图生视频、参考模式、尾帧钉定。

    image 单独出现即首帧锚定；reference_images（≤14）为参考模式，可与 image 组合
    （image 成为钉定首帧，提示词占位符从 <IMAGE_1> 起编号）；last_frame 钉定尾帧；
    keyframes 为 (url, 秒) 中段关键帧（≤4）；voice_ids 为平台预置 voice_id（≤3，提示词用
    <AUDIO_n> 指位）。图生视频默认不传 aspect_ratio（跟随源图）；参考／文生模式可显式指定。
    generate_audio=False 请求无声视频。
    """
    payload = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution}
    if image:
        payload["image"] = {"url": image}
    if last_frame:
        payload["last_frame"] = {"url": last_frame}
    if reference_images:
        payload["reference_images"] = [{"url": url} for url in reference_images]
    if keyframes:
        payload["keyframes"] = [{"image": {"url": url}, "timestamp_s": seconds} for url, seconds in keyframes]
    if voice_ids:
        payload["reference_audios"] = [{"voice_id": voice} for voice in voice_ids]
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if generate_audio is False:
        payload["generate_audio"] = False
    return payload


def video_operation_payload(model, video, prompt):
    """/v1/videos/edits 与 /v1/videos/extensions：video 输入，输出跟随输入（不可改时长/分辨率/画幅）。"""
    payload = {"model": model, "video": {"url": video}}
    if prompt and prompt.strip():
        payload["prompt"] = prompt.strip()
    return payload


def resolve_video(value, project):
    """把本地视频转成 data URI；https 链接原样传入。"""
    if value.startswith(("https://", "http://")):
        return value, None
    path = Path(value)
    if not path.is_file():
        raise GrokError(f"视频不存在：{value}")
    try:
        shown = str(path.resolve().relative_to(Path(project).resolve()))
    except ValueError:
        shown = str(path.resolve())
    item = {"path": shown, "sha256": sha256(path)}
    return f"data:{media_type(path)};base64,{base64.b64encode(path.read_bytes()).decode()}", item


def poll_limits(args):
    values = (getattr(args, "max_polls", 40), getattr(args, "deadline_seconds", 600), getattr(args, "poll_interval", 10))
    if (isinstance(values[0], bool) or not isinstance(values[0], int) or values[0] < 1
            or not consistency.number(values[1], 0, inclusive=False) or not consistency.number(values[2])
            or not math.isfinite(values[1]) or not math.isfinite(values[2])):
        raise GrokError("max-polls 必须为正整数，deadline-seconds 必须为正数，poll-interval 必须为非负数")
    return values


def poll_task(task_file, task, out, args):
    """每轮有界查询同一个 request；等待、超时或中断均不允许再次 POST。"""
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
                result = call(f"/videos/{urllib.parse.quote(task['id'], safe='')}")
            except GrokPending:
                reason = "达到 deadline"
                break
            if not isinstance(result, dict):
                raise GrokError("平台查询响应不是对象；保留原任务编号供续查")
            polling.update(polls_total=polling.get("polls_total", 0) + 1, last_result=result, last_poll_at=stamp(now()), state="waiting")
            task["record"]["engine"]["task_status"] = result.get("status")
            if result.get("status") in ("done", "failed", "expired"):
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
    raise GrokPending(f"{args.name} 本轮查询{reason}；任务 {task['id']} 仍保留，相同命令可续查，不会重新提交")


def generate_video(args):
    poll_limits(args)  # 无效本轮限制必须在提交前失败。
    if args.resolution not in VIDEO_RESOLUTIONS:
        raise GrokError("视频分辨率须为 480p、720p 或 1080p")
    if not isinstance(args.duration, int) or not MIN_DURATION <= args.duration <= MAX_DURATION:
        raise GrokError(f"视频时长须为 {MIN_DURATION}–{MAX_DURATION} 整秒")
    if getattr(args, "ratio", "") and args.ratio not in ASPECT_RATIOS:
        raise GrokError("--ratio 须为平台支持的画幅取值")
    out, prompt = output_dir(args), prompt_of(args)
    first = resolve(args.first_frame, args.project) if args.first_frame else None
    last = resolve(args.last_frame, args.project) if args.last_frame else None
    refs = [resolve(value, args.project) for value in args.ref_image]
    if len(refs) > 14:
        raise GrokError("参考模式一次最多 14 张参考图")
    if refs and args.resolution not in ("480p", "720p"):
        raise GrokError("参考模式分辨率最高 720p；更高分辨率请走首帧图生视频")
    voice_ids = list(getattr(args, "voice_id", []) or [])
    if len(voice_ids) > 3 or any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) for value in voice_ids):
        raise GrokError("预置声音参考最多 3 个，且必须是平台 voice_id（如 eve）")
    keyframes = []
    for value in getattr(args, "keyframe", []) or []:
        name, _, at_text = value.rpartition("@")
        try:
            seconds = float(at_text)
        except ValueError:
            raise GrokError(f"--keyframe 需要 文件@秒 形式：{value}") from None
        if not 0 < seconds < args.duration:
            raise GrokError(f"关键帧时间戳必须严格落在片内（0–{args.duration}s）：{value}")
        keyframes.append(resolve(name, args.project) + (seconds,))
    if len(keyframes) > 4:
        raise GrokError("中段关键帧最多 4 个")
    marks = sorted(row[2] for row in keyframes)
    for before, after in zip(marks, marks[1:]):
        if after - before < 1 / 3:
            raise GrokError("关键帧时间戳须彼此间隔至少 1/3 秒")
    if not (first or last or refs or keyframes or voice_ids):
        print("提醒：未给首帧／尾帧／参考图／关键帧，将走纯文生视频；镜头可控性弱，不作为默认路线。", file=sys.stderr)
    params = {"resolution": args.resolution, "duration": args.duration, "generate_audio": not args.no_audio}
    if getattr(args, "ratio", ""):
        params["aspect_ratio"] = args.ratio
    if refs:
        params["reference_images"] = len(refs)
    if voice_ids:
        params["reference_voice_ids"] = voice_ids
    if keyframes:
        params["keyframes"] = [{"sha256": row[1]["sha256"] if row[1] else None, "timestamp_s": row[2]} for row in keyframes]
    payload = video_payload(args.model, prompt, first and first[0], args.duration, args.resolution,
                            last_frame=last and last[0], reference_images=[url for url, _ in refs],
                            aspect_ratio=getattr(args, "ratio", ""), keyframes=[(row[0], row[2]) for row in keyframes],
                            voice_ids=voice_ids, generate_audio=not args.no_audio)
    state = consistency.load(args.state, consistency.STATE_FORMAT) if args.state else None
    inputs = {"anchors_sha256": anchors(args, args.shot),
              "references": [{"source_uri": url, "sha256": item and item["sha256"], "media_type": "image",
                              "role": "reference_image", "purpose": "identity", "entity_id": None}
                             for url, item in refs]
                            + [{"source_uri": row[0], "sha256": row[1]["sha256"] if row[1] else None,
                                "media_type": "image", "role": "reference_image", "purpose": "identity",
                                "timestamp_s": row[2], "entity_id": None} for row in keyframes],
              "prompt": prompt}
    if first and first[1]:
        inputs["first_frame"] = frame_source(first[1], args.shot, state, args.project)
    if last and last[1]:
        inputs["last_frame"] = {**last[1], "from": "generated"}
    if args.dry_run:
        print(json.dumps({"payload": truncate_payload(payload), "inputs": inputs}, ensure_ascii=False, indent=2))
        return None
    started = now()
    record = base_record(args, "video", "candidate", args.shot, inputs, {"model": args.model, "params": params}, started)
    video = out / f"{args.name}.mp4"
    preflight_record(record)
    media_inputs = ([first] if first else []) + ([last] if last else []) + refs \
        + [(row[0], row[1]) for row in keyframes]
    with generation_lock(out, args.name):
        task_file, task = generation_task(out, args, record, payload, [video], semantic_payload(payload, media_inputs))
        if "id" not in task:
            submission = submit_once(task_file, task, "/videos/generations", payload, out, args)
            task.update(submission=submission, submitted_at=stamp(started))
            task_id = submission.get("request_id") if isinstance(submission, dict) else None
            if not isinstance(task_id, str) or not consistency.SAFE_ID.fullmatch(task_id):
                write_json(task_file, task)
                record.update(finished_at=stamp(now()), errors=[{"error": "平台未返回有效任务编号，不能安全重提"}],
                              budget={"billable": True, "usage": {"note": "提交已有响应，计费用量待平台核实"}})
                write_record(out, args.name, record)
                raise GrokError("平台未返回有效任务编号；已保存提交响应，不能安全重提")
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
        record.update(finished_at=stamp(now()), budget={"billable": result.get("status") == "done", "usage": result.get("usage") or {"note": "平台未返回用量"}})
        if result.get("status") != "done":
            record["errors"] = [{"error": json.dumps(result.get("error") or {"status": result.get("status")}, ensure_ascii=False)}]
            write_record(out, args.name, record)
            raise GrokError(f"{args.name} 生成失败：{record['errors'][0]['error']}")
        remote_success(record, result)
        record["engine"]["request_sha256"] = digest_json(task["binding"])
        record["engine"]["payload_sha256"] = task["binding"]["payload_sha256"]
        if task["binding"].get("semantic_payload_sha256"):
            record["engine"]["semantic_payload_sha256"] = task["binding"]["semantic_payload_sha256"]
        write_record(out, args.name, record)
        made = datetime.datetime.fromisoformat(task["generated_at"])
        common = {"source_url_expires_at": stamp(made + URL_TTL), "generated_at": stamp(made)}
        try:
            content = result.get("video")
            if not isinstance(content, dict) or not isinstance(content.get("url"), str):
                raise GrokError("视频结果缺有效下载 URL")
            duration = content.get("duration")
            download_video_output(content["url"], video, record, args,
                                  {"id": args.name, "duration_ms": int(float(duration) * 1000) if duration is not None else args.duration * 1000,
                                   "source_url": content["url"], **common})
        except (GrokError, OSError, KeyError, TypeError, ValueError) as exc:
            persist_download_failure(out, args, record, exc)
            task["record"] = record
            write_json(task_file, task)
            raise GrokError(f"视频已在平台生成并计费，本地下载未完成：{exc}；相同命令可续接下载") from None
        record.update(status="succeeded", errors=[])
        record["engine"]["params"]["actual"] = {key: content.get(key) for key in ("duration", "respect_moderation") if content.get(key) is not None}
        task["record"] = record
        write_json(task_file, task)
        return write_record(out, args.name, record)


def generate_video_operation(args, operation):
    """/v1/videos/edits 或 /v1/videos/extensions：对既有 take 做编辑或从其结尾续接。

    官方规则：输出跟随输入视频（不可另设时长／分辨率／画幅）；编辑时长上限约 8.7s、分辨率上限 720p。
    """
    poll_limits(args)
    out = args.out and output_dir(args)
    prompt = (args.prompt or "").strip() or (args.prompt_file and Path(args.prompt_file).read_text("utf-8").strip() or "")
    if not prompt:
        raise GrokError(f"视频{ '编辑' if operation == 'edit' else '续接' }需要 --prompt（平台必填：编辑写要改什么，续接写继续发生什么）")
    video = resolve_video(args.video, args.project)
    params = {"operation": operation, "source_video": video[1]}
    payload = video_operation_payload(args.model, video[0], prompt)
    inputs = {"anchors_sha256": anchors(args, args.shot),
              "references": [], "video": video[1], "prompt": prompt or None}
    if args.dry_run:
        print(json.dumps({"payload": truncate_payload(payload), "inputs": inputs}, ensure_ascii=False, indent=2))
        return None
    started = now()
    record = base_record(args, "video", "candidate", args.shot, inputs, {"model": args.model, "params": params}, started)
    target = out / f"{args.name}.mp4"
    preflight_record(record)
    with generation_lock(out, args.name):
        task_file, task = generation_task(out, args, record, payload, [target], semantic_payload(payload, [video]))
        path = {"edit": "/videos/edits", "extend": "/videos/extensions"}[operation]
        if "id" not in task:
            submission = submit_once(task_file, task, path, payload, out, args)
            task.update(submission=submission, submitted_at=stamp(started))
            task_id = submission.get("request_id") if isinstance(submission, dict) else None
            if not isinstance(task_id, str) or not consistency.SAFE_ID.fullmatch(task_id):
                write_json(task_file, task)
                record.update(finished_at=stamp(now()), errors=[{"error": "平台未返回有效任务编号，不能安全重提"}],
                              budget={"billable": True, "usage": {"note": "提交已有响应，计费用量待平台核实"}})
                write_record(out, args.name, record)
                raise GrokError("平台未返回有效任务编号；已保存提交响应，不能安全重提")
            task["id"] = task_id
            record["engine"]["task_id"] = task_id
            task["record"] = record
            write_json(task_file, task)
            print(f"{args.name} 已提交 {task_id}", flush=True)
        else:
            record = task["record"]
            print(f"{args.name} 续接任务 {task['id']}", flush=True)
        if "result" not in task:
            poll_task(task_file, task, out, args)
        result = task["result"]
        record.update(finished_at=stamp(now()), budget={"billable": result.get("status") == "done",
                                                        "usage": result.get("usage") or {"note": "平台未返回用量"}})
        if result.get("status") != "done":
            record["errors"] = [{"error": json.dumps(result.get("error") or {"status": result.get("status")},
                                                     ensure_ascii=False)}]
            write_record(out, args.name, record)
            raise GrokError(f"{args.name} {operation} 失败：{record['errors'][0]['error']}")
        remote_success(record, result)
        record["engine"]["request_sha256"] = digest_json(task["binding"])
        record["engine"]["payload_sha256"] = task["binding"]["payload_sha256"]
        if task["binding"].get("semantic_payload_sha256"):
            record["engine"]["semantic_payload_sha256"] = task["binding"]["semantic_payload_sha256"]
        write_record(out, args.name, record)
        made = datetime.datetime.fromisoformat(task["generated_at"])
        try:
            content = result.get("video")
            if not isinstance(content, dict) or not isinstance(content.get("url"), str):
                raise GrokError("结果缺有效下载 URL")
            duration = content.get("duration")
            download_video_output(content["url"], target, record, args,
                                  {"id": args.name,
                                   "duration_ms": int(float(duration) * 1000) if duration is not None else None,
                                   "source_url": content["url"],
                                   "source_url_expires_at": stamp(made + URL_TTL), "generated_at": stamp(made)})
        except (GrokError, OSError, KeyError, TypeError, ValueError) as exc:
            persist_download_failure(out, args, record, exc)
            task["record"] = record
            write_json(task_file, task)
            raise GrokError(f"视频已在平台处理并计费，本地下载未完成：{exc}；相同命令可续接下载") from None
        record.update(status="succeeded", errors=[])
        task["record"] = record
        write_json(task_file, task)
        return write_record(out, args.name, record)


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

    image = sub.add_parser("image", parents=[made], help="Grok Imagine 文生图／参考图编辑（资产图或关键帧）")
    image.add_argument("--ref", action="append", default=[], help="参考／源图（本地图或 https，最多 5 张；给出即走图像编辑）")
    image.add_argument("--purpose", choices=("asset", "candidate"), default="candidate")
    image.add_argument("--shot")
    image.add_argument("--moment", choices=consistency.MOMENTS)
    image.add_argument("--model", default=IMAGE_MODEL)
    image.add_argument("--aspect-ratio", default="9:16")
    image.add_argument("--resolution", default="2k")
    image.add_argument("--count", type=int, default=1, help="同一提示词一次出几张（1–10）")

    video = sub.add_parser("video", parents=[made], help="Grok Imagine 视频（首帧／尾帧／参考图／文生模式）")
    video.add_argument("--shot", required=True)
    video.add_argument("--first-frame", help="首帧图片；与参考图同用时成为钉定首帧（占位符 <IMAGE_0>）")
    video.add_argument("--last-frame", help="尾帧图片；平台生成过程并落在该画面")
    video.add_argument("--ref-image", action="append", default=[],
                       help="参考图（最多 14 张）；提示词用 <IMAGE_n> 指位，身份／场景不钉死首帧")
    video.add_argument("--ratio", default="", help="画幅（如 9:16）；图生视频默认跟随源图，强行指定可能拉伸")
    video.add_argument("--voice-id", action="append", default=[],
                       help="平台预置声音 voice_id（≤3，如 eve）；提示词用 <AUDIO_n> 指位；音频素材文件不支持")
    video.add_argument("--keyframe", action="append", default=[],
                       help="中段关键帧 文件@秒（≤4，1.5 系列；时间戳须在片内且彼此间隔 ≥1/3 秒）")
    video.add_argument("--no-audio", action="store_true", help="请求无声视频（generate_audio=false）")
    video.add_argument("--model", default=VIDEO_MODEL)
    video.add_argument("--resolution", default="480p")
    video.add_argument("--duration", type=int, default=6)
    video.add_argument("--dry-run", action="store_true", help="只打印请求与记录输入，不提交")
    video.add_argument("--max-polls", type=int, default=60, help="本轮最多查询次数，续查沿用原任务")
    video.add_argument("--deadline-seconds", type=float, default=900, help="本轮查询时间上限（秒）")
    video.add_argument("--poll-interval", type=float, default=10, help="查询间隔（秒）")

    for name, help_text in (("edit", "编辑既有 take（输出跟随输入；时长上限约 8.7s、720p）"),
                            ("extend", "从既有 take 的结尾续接成一个片段（输出跟随输入；--prompt 必填）")):
        sub_command = sub.add_parser(name, parents=[made], help=help_text)
        sub_command.add_argument("--shot", required=True)
        sub_command.add_argument("--video", required=True, help="既有视频（本机文件或 https 链接）")
        sub_command.add_argument("--model", default=EDIT_MODEL)
        sub_command.add_argument("--dry-run", action="store_true", help="只打印请求与记录输入，不提交")
        sub_command.add_argument("--max-polls", type=int, default=60)
        sub_command.add_argument("--deadline-seconds", type=float, default=900)
        sub_command.add_argument("--poll-interval", type=float, default=10)

    return parser


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "image":
            path = generate_image(args)
        elif args.command in ("edit", "extend"):
            path = generate_video_operation(args, args.command)
        else:
            if args.shot and not (args.bible and args.state):
                print("提醒：未给 --bible/--state，生成记录不会绑定锚点包", file=sys.stderr)
            path = generate_video(args)
    except (GrokError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
