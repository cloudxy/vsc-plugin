#!/usr/bin/env python3
"""豆包语音合成 2.0 HTTP 单向流适配器。默认预检，--execute 才会提交一次付费请求。

仅从 DOUBAO_SPEECH_API_KEY 读取新版语音凭证；不使用方舟 key，不自动重试。
同名任务先落盘绑定，再提交。未完成、失败或输出损坏时禁止自动重新提交。
"""
import argparse
import base64
import binascii
import contextlib
import datetime
import fcntl
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

import consistency

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
ENDPOINTS = {"speech": ENDPOINT, "agent-plan": "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"}
PROVIDER = "doubao_speech"
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 128 * 1024 * 1024
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class SpeechError(RuntimeError):
    """预检、协议或媒体失败；不得据此自动重试付费请求。"""


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def digest_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_key(env_name="DOUBAO_SPEECH_API_KEY"):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise SpeechError("--key-env 只接受环境变量名，不接受密钥字面值")
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SpeechError(f"缺少语音凭证环境变量 {env_name}；默认不回退到方舟密钥")
    if any(ord(char) < 32 for char in key):
        raise SpeechError("语音凭证含非法控制字符")
    return key


def project_path(project, value):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise SpeechError("路径必须是作品内相对路径")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SpeechError("路径必须是作品内相对路径，不能包含 ..")
    root = Path(project).resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise SpeechError("路径不能通过符号链接越出作品目录")
    if target.is_symlink():
        raise SpeechError("输入与输出不能覆盖或读取符号链接")
    return target


def write_json(path, value):
    if path.is_symlink():
        raise SpeechError("记录不能覆盖符号链接")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".speech-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        # 任务标记必须在请求发出前持久化，包括目录项。
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def generation_lock(path):
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise SpeechError(f"无法安全打开生成锁：{exc}") from None
    with os.fdopen(descriptor, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SpeechError("同名语音任务正在运行") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def plan(args):
    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SpeechError("--project 必须是已有作品目录")
    state_file = project_path(project, "vsc.json")
    try:
        project_id = json.loads(state_file.read_text("utf-8"))["project_id"]
    except (OSError, ValueError, KeyError, TypeError):
        raise SpeechError("无法从作品 vsc.json 读取 project_id") from None
    if not isinstance(project_id, str) or not project_id.strip():
        raise SpeechError("project_id 必须是非空字符串")
    if not SAFE_ID.fullmatch(args.name):
        raise SpeechError("--name 必须以字母或数字开头，只含字母、数字、点、下划线、连字符（最多128字）")
    service = getattr(args, "service", "speech")
    if service not in ENDPOINTS:
        raise SpeechError("未知语音服务；仅支持 speech 或 agent-plan")
    if service == "agent-plan" and args.resource_id != "seed-tts-2.0":
        raise SpeechError("Agent Plan 目前只支持已声明的 seed-tts-2.0 预置音色，不支持复刻资源")
    out = project_path(project, args.out)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.key_env):
        raise SpeechError("--key-env 只接受环境变量名，不接受密钥字面值")
    if args.text_file:
        text = project_path(project, args.text_file).read_text("utf-8")
    else:
        text = args.text
    if not text or not text.strip():
        raise SpeechError("合成文本不能为空")
    if args.max_chars <= 0 or len(text) > args.max_chars:
        raise SpeechError(f"文本字符预算超限：{len(text)} / {args.max_chars}（含标点和空白）")
    if not SAFE_ID.fullmatch(args.speaker):
        raise SpeechError("--speaker 必须是控制台音色库中的安全 ID")
    if any(not context.strip() for context in args.context):
        raise SpeechError("--context 不能为空")
    if args.resource_id == "seed-icl-2.0":
        if args.context:
            raise SpeechError("复刻音色不支持 context_texts；请移除 --context")
        if not args.model:
            raise SpeechError("已有复刻音色需要显式 --model（例如 seed-tts-2.0-standard）")
    elif args.model:
        raise SpeechError("--model 仅用于已有复刻音色")
    if args.model and not SAFE_ID.fullmatch(args.model):
        raise SpeechError("--model 必须是安全 ID")
    if not -50 <= args.speech_rate <= 100:
        raise SpeechError("--speech-rate 范围为 -50 到 100")
    inputs = {"prompt": text, "text": text, "references": [], "speaker": args.speaker, "context_texts": args.context}
    if args.entity:
        if not SAFE_ID.fullmatch(args.entity) or not args.bible:
            raise SpeechError("人物绑定需要有效 --entity 和作品内 --bible")
        bible_path = project_path(project, args.bible)
        bible = consistency.load(bible_path, consistency.BIBLE_FORMAT)
        if bible.get("project_id") != project_id:
            raise SpeechError("资产库与作品 project_id 不一致")
        entity = consistency.entity_index(bible).get(args.entity)
        if not entity or entity.get("kind") != "character":
            raise SpeechError("--entity 必须指向资产库中的人物")
        voice = entity.get("voice", {})
        if voice.get("voice") and voice["voice"] != args.speaker:
            raise SpeechError("speaker 与人物已绑定音色不一致")
        if voice.get("engine") and voice["engine"] != PROVIDER:
            raise SpeechError("人物已绑定其他语音供应商")
        if voice.get("resource_id") and voice["resource_id"] != args.resource_id:
            raise SpeechError("resource_id 与人物已绑定音色不一致")
        inputs.update(entity=args.entity, bible={"path": str(bible_path.relative_to(project)), "sha256": sha256(bible_path)})
    elif args.bible:
        raise SpeechError("--bible 需要同时指定 --entity")
    params = {"format": args.format, "sample_rate": args.sample_rate, "speech_rate": args.speech_rate}
    req_params = {"text": text, "speaker": args.speaker, "audio_params": params}
    if args.context:
        req_params["additions"] = json.dumps({"context_texts": args.context}, ensure_ascii=False)
    if args.model:
        req_params["model"] = args.model
    payload = {"req_params": req_params}
    binding = {"project_id": project_id, "kind": "audio", "purpose": "asset", "inputs": inputs,
               "endpoint": ENDPOINTS[service], "resource_id": args.resource_id, "payload": payload,
               "max_chars": args.max_chars, "key_env": args.key_env, "output": str(out.relative_to(project)), "name": args.name}
    return project, out, payload, binding


def probe_audio(path, expected_format, expected_rate):
    """实际检查容器、音频流、采样率和完整解码；仅有扩展名或 WAV 头不能算成功。"""
    for tool in ("ffprobe", "ffmpeg"):
        if not shutil.which(tool):
            raise SpeechError(f"缺少 {tool}，无法验证音频，不提交付费请求")
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                                capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        streams = data.get("streams", [])
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        duration = float(data.get("format", {}).get("duration", 0))
        formats = data.get("format", {}).get("format_name", "").split(",")
        if (len(audio) != 1 or len(streams) != 1 or expected_format not in formats
                or not math.isfinite(duration) or duration <= 0 or int(audio[0].get("sample_rate", 0)) != expected_rate):
            raise SpeechError("返回音频容器、时长、采样率或音轨无效")
        if expected_format == "mp3" and audio[0].get("codec_name") != "mp3":
            raise SpeechError("返回文件不是 MP3 音频")
        decoded = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                                 capture_output=True, timeout=60)
        if decoded.returncode or decoded.stderr.strip():
            raise SpeechError("返回音频无法完整解码")
        return {"duration_ms": round(duration * 1000), "sample_rate": expected_rate,
                "codec": audio[0].get("codec_name"), "container": expected_format, "channels": audio[0].get("channels")}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        raise SpeechError(f"音频验证失败：{exc}") from None


def stream_audio(response, audio, journal, record, key):
    """urllib 解 HTTP chunked；协议体是逐行 JSON，完成码必需，不以 EOF 代替完成。"""
    total = 0
    index = 0
    while True:
        line = response.readline(MAX_LINE_BYTES + 1)
        if not line:
            raise SpeechError("响应流在完成码 20000000 前结束；不会自动重试")
        if len(line) > MAX_LINE_BYTES:
            raise SpeechError("响应行超出安全上限")
        if not line.strip():
            continue
        index += 1
        try:
            item = json.loads(line)
        except (ValueError, UnicodeError):
            raise SpeechError("响应流含无效 JSON") from None
        if not isinstance(item, dict) or type(item.get("code")) is not int:
            raise SpeechError("响应流缺少整数 code")
        code = item["code"]
        chunk = b""
        if code == 0 and item.get("data"):
            try:
                chunk = base64.b64decode(item["data"], validate=True)
            except (ValueError, TypeError, binascii.Error):
                raise SpeechError("响应音频不是有效 Base64") from None
        metadata = {k: v for k, v in item.items() if k != "data"}
        metadata.update(index=index, wire_sha256=hashlib.sha256(line).hexdigest(), audio_bytes=len(chunk),
                        audio_sha256=hashlib.sha256(chunk).hexdigest() if chunk else None)
        # 供应商错误消息也必须去掉可能回显的凭证。
        journal.write(json.dumps(metadata, ensure_ascii=False).replace(key, "[REDACTED]") + "\n")
        journal.flush()
        os.fsync(journal.fileno())
        record["engine"]["response_chunks"] = index
        if isinstance(item.get("usage"), dict) and item["usage"]:
            record["budget"]["usage"] = json.loads(json.dumps(item["usage"], ensure_ascii=False).replace(key, "[REDACTED]"))
        if code == 20000000:
            if item.get("data"):
                raise SpeechError("完成帧含未预期音频，拒绝丢弃或猜测协议")
            if not total:
                raise SpeechError("响应已结束但没有音频")
            record["engine"]["completion_code"] = code
            return
        if code != 0:
            raise SpeechError(f"豆包语音错误 {code}：{str(item.get('message', ''))[:500].replace(key, '[REDACTED]')}")
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise SpeechError("响应音频超出安全上限")
        audio.write(chunk)


def checked_record(record, binding, project):
    if (not isinstance(record, dict) or record.get("status") != "succeeded"
            or record.get("engine", {}).get("request_sha256") != digest_json(binding)
            or record.get("project_id") != binding["project_id"] or record.get("inputs") != binding["inputs"]
            or record.get("kind") != "audio" or record.get("purpose") != "asset"
            or consistency.record_errors(record) or len(record.get("outputs", [])) != 1):
        raise SpeechError("同名任务没有可核实的完整成功记录；不会重新提交")
    engine = record["engine"]
    params = binding["payload"]["req_params"]
    if (engine.get("provider") != PROVIDER or engine.get("params") != {**params, "resource_id": binding["resource_id"]}
            or engine.get("payload_sha256") != digest_json(binding["payload"])
            or engine.get("speaker") != params["speaker"] or engine.get("resource_id") != binding["resource_id"]
            or engine.get("model") != (params.get("model") or binding["resource_id"])
            or engine.get("completion_code") != 20000000):
        raise SpeechError("成功记录中的请求或完成码与原任务不一致")
    output = record["outputs"][0]
    if (output.get("id") != binding["name"] or output.get("voice") != params["speaker"]
            or output.get("speaker") != params["speaker"] or output.get("resource_id") != binding["resource_id"]
            or output.get("provider") != PROVIDER or output.get("entity") != binding["inputs"].get("entity")):
        raise SpeechError("成功输出中的音色或人物与原任务不一致")
    expected = f"{binding['output']}/{binding['name']}.{binding['payload']['req_params']['audio_params']['format']}"
    if str(Path(output.get("path", ""))) != str(Path(expected)):
        raise SpeechError("成功输出路径与原请求不一致")
    target = project_path(project, output["path"])
    if not target.is_file() or sha256(target) != output.get("sha256"):
        raise SpeechError("成功输出不存在或 SHA-256 已改变；不会重新提交")
    journal = engine.get("response_journal", {})
    if journal.get("path") != str(Path(binding["output"]) / f"{binding['name']}-响应.jsonl"):
        raise SpeechError("响应分块台账路径与原任务不一致")
    journal_path = project_path(project, journal.get("path"))
    if not journal_path.is_file() or sha256(journal_path) != journal.get("sha256"):
        raise SpeechError("响应分块台账缺失或内容改变")
    probe_audio(target, binding["payload"]["req_params"]["audio_params"]["format"],
                binding["payload"]["req_params"]["audio_params"]["sample_rate"])
    return record


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpeechError(f"语音接口返回重定向 HTTP {code}；不跟随、不重试")


def open_stream(request):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=180)


def synthesize(args):
    project, out, payload, binding = plan(args)
    if not args.execute:
        return {"format": "vsc.speech-request/v1", "dry_run": True, "billable": False, "binding": binding,
                "request_sha256": digest_json(binding), "text_chars": len(payload["req_params"]["text"])}
    out.mkdir(parents=True, exist_ok=True)
    target = project_path(project, str((out / f"{args.name}.{args.format}").relative_to(project)))
    task_file, record_file, chunks_file = [out / f"{args.name}-{suffix}" for suffix in ("任务.json", "生成记录.json", "响应.jsonl")]
    for path in (task_file, record_file, chunks_file):
        project_path(project, str(path.relative_to(project)))
    with generation_lock(out / f".{args.name}-生成.lock"):
        if task_file.exists():
            try:
                task = json.loads(task_file.read_text("utf-8"))
            except (ValueError, OSError):
                raise SpeechError("同名任务文件损坏；不会重新提交") from None
            if not isinstance(task, dict) or task.get("binding") != binding:
                raise SpeechError("同名任务的输入或预算已改变；请使用新的 --name")
            # 完成记录先于任务状态写入，崩溃后的恢复只读该记录，永远不再次提交。
            try:
                saved = json.loads(record_file.read_text("utf-8"))
            except (OSError, ValueError):
                raise SpeechError("同名任务未完成或失败，计费状态可能未知；不会重新提交") from None
            return checked_record(saved, binding, project)
        if any(path.exists() for path in (target, record_file, chunks_file)):
            raise SpeechError("同名输出或记录已存在；请使用新的 --name")
        key = api_key(args.key_env)
        for tool in ("ffprobe", "ffmpeg"):
            if not shutil.which(tool):
                raise SpeechError(f"缺少 {tool}，无法验证音频，不提交付费请求")
        request_id = str(uuid.uuid4())
        record = {"format": consistency.RECORD_FORMAT, "project_id": binding["project_id"], "kind": "audio", "purpose": "asset",
                  "shot_id": None, "inputs": binding["inputs"], "engine": {"provider": PROVIDER, "model": args.model or args.resource_id,
                  "version": "http-v3", "speaker": args.speaker, "resource_id": args.resource_id,
                  "params": {**payload["req_params"], "resource_id": args.resource_id},
                  "request_id": request_id, "request_sha256": digest_json(binding), "payload_sha256": digest_json(payload),
                  "response_chunks": 0}, "budget": {"billable": True, "max_chars": args.max_chars, "text_chars": len(payload['req_params']['text']),
                  "usage": {"note": "请求可能计费；未收到平台用量，金额未知"}}, "submitted_at": stamp(), "finished_at": stamp(),
                  "status": "failed", "outputs": [], "errors": [], "selection": None}
        errors = consistency.record_errors(record)
        if errors:
            raise SpeechError("生成记录预检失败：" + "；".join(errors))
        task = {"format": "vsc.speech-task/v1", "binding": binding, "request_id": request_id, "status": "submitted", "submitted_at": record["submitted_at"]}
        write_json(task_file, task)
        write_json(record_file, record)
        temporary = None
        try:
            request = urllib.request.Request(binding["endpoint"], data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                headers={"X-Api-Key": key, "X-Api-Resource-Id": args.resource_id, "X-Api-Request-Id": request_id,
                         "X-Control-Require-Usage-Tokens-Return": "*", "Content-Type": "application/json", "Connection": "keep-alive"})
            with tempfile.NamedTemporaryFile(dir=out, prefix=".speech-audio-", suffix="." + args.format, delete=False) as audio:
                temporary = Path(audio.name)
                with chunks_file.open("x", encoding="utf-8") as journal:
                    with open_stream(request) as response:
                        log_id = response.headers.get("X-Tt-Logid")
                        record["engine"]["log_id"] = str(log_id).replace(key, "[REDACTED]") if log_id else None
                        stream_audio(response, audio, journal, record, key)
                audio.flush()
                os.fsync(audio.fileno())
            metadata = probe_audio(temporary, args.format, args.sample_rate)
            output = {"id": args.name, "path": str(target.relative_to(project)), "sha256": sha256(temporary),
                      "voice": args.speaker, "speaker": args.speaker, "resource_id": args.resource_id, "provider": PROVIDER, **metadata}
            if args.entity:
                output["entity"] = args.entity
            record.update(status="succeeded", finished_at=stamp(), outputs=[output])
            errors = consistency.record_errors(record)
            if errors:
                raise SpeechError("生成记录无效：" + "；".join(errors))
            temporary.replace(target)
        except (SpeechError, OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
            message = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else str(exc)
            record.update(status="failed", finished_at=stamp(), outputs=[], errors=[message.replace(key, "[REDACTED]")[:1000]])
            task["status"] = "failed"
            raise SpeechError(record["errors"][0] + "；同名任务不会自动重试") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if chunks_file.is_file():
                record["engine"]["response_journal"] = {"path": str(chunks_file.relative_to(project)), "sha256": sha256(chunks_file)}
            write_json(record_file, record)
            task["status"] = record["status"]
            write_json(task_file, task)
        return record


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    synth = commands.add_parser("synthesize", help="固定音色合成；默认 dry run，--execute 才发请求")
    synth.add_argument("--project", required=True)
    synth.add_argument("--out", "--output", dest="out", default="06-素材/声音")
    synth.add_argument("--name", required=True)
    text = synth.add_mutually_exclusive_group(required=True)
    text.add_argument("--text")
    text.add_argument("--text-file", help="作品内 UTF-8 文本相对路径")
    synth.add_argument("--service", choices=tuple(ENDPOINTS), default="speech", help="speech 为普通语音服务；agent-plan 为方舟套餐专属接口，不自动切换")
    synth.add_argument("--speaker", required=True)
    synth.add_argument("--context", action="append", default=[], help="2.0预置音色的情绪/表达指令，可重复")
    synth.add_argument("--resource-id", choices=("seed-tts-2.0", "seed-icl-2.0"), default="seed-tts-2.0")
    synth.add_argument("--model", help="已有复刻音色的模型版本；不支持与context共用")
    synth.add_argument("--format", choices=("mp3", "wav"), default="mp3")
    synth.add_argument("--sample-rate", type=int, choices=(8000, 16000, 22050, 24000, 32000, 44100, 48000), default=24000)
    synth.add_argument("--speech-rate", type=int, default=0)
    synth.add_argument("--entity", help="可选人物ID；需要bible")
    synth.add_argument("--bible", help="作品内资产库相对路径")
    synth.add_argument("--max-chars", type=int, required=True, help="本次文本字符预算上限（含标点空白）")
    synth.add_argument("--key-env", default="DOUBAO_SPEECH_API_KEY", help="显式选择语音鉴权环境变量（仅变量名）；不会自动回退")
    mode = synth.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true", help="明确提交一次可能计费的请求，无自动重试")
    return cli


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        print(json.dumps(synthesize(args), ensure_ascii=False, indent=2))
        return 0
    except (SpeechError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
