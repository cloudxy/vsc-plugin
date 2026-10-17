#!/usr/bin/env python3
"""豆包原生有界生产队列。plan/validate/status 只读；run --execute --plan-hash 才执行。"""
from vsc.bootstrap import repository_root, script_path
import argparse
import contextlib
import fcntl
import functools
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from vsc.adapters.providers.volc_ark import api as ark

FORMAT = "vsc.production-batch/v1"
JOURNAL_FORMAT = "vsc.production-journal/v1"
COMMON = {"out", "name", "prompt", "prompt_file", "bible", "state", "shot", "model"}
IMAGE = {"ref", "base_frame", "base_use", "purpose", "moment", "size"}
VIDEO = {"first_frame", "last_frame", "first_frame_ref", "ref_image", "ref_video", "ref_audio",
         "resolution", "ratio", "duration", "no_audio", "draft"}
MULTI = {"ref", "ref_image", "ref_video", "ref_audio"}
MEDIA = MULTI | {"base_frame", "first_frame", "last_frame", "first_frame_ref"}
FILES = {"bible", "state", "prompt_file"}


class ProductionError(RuntimeError):
    pass


def read(path):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ProductionError(f"无法读取 JSON {path}: {exc}") from None


def require(condition, message):
    if not condition:
        raise ProductionError(message)


def safe_id(value):
    return isinstance(value, str) and bool(ark.consistency.SAFE_ID.fullmatch(value))


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def path_in(project, value):
    try:
        return ark.project_path(project, value)
    except ark.ArkError as exc:
        raise ProductionError(str(exc)) from None


def fingerprint(project, relative, inputs):
    path = path_in(project, relative)
    require(path.is_file(), f"输入不存在：{relative}")
    inputs[relative] = ark.sha256(path)
    return path


@functools.lru_cache(maxsize=256)
def decoded_media(path, digest, expected):
    """按内容探测并实际解码；缓存键含文件 SHA，不依赖扩展名。"""
    del digest  # 仅用于使缓存与输入字节绑定。
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "format=format_name:stream=codec_type,codec_name,nb_read_frames",
                                "-of", "json", path], capture_output=True, text=True, check=True, timeout=60)
        info = json.loads(probe.stdout)
        streams = info.get("streams", [])
        formats = set(info.get("format", {}).get("format_name", "").split(","))
        image_formats = {"image2", "image2pipe", "png_pipe", "jpeg_pipe", "gif", "bmp_pipe", "webp_pipe", "apng"}
        image_codecs = {"png", "mjpeg", "gif", "bmp", "webp", "apng"}
        image = bool(formats & image_formats) and bool(streams) and all(
            stream.get("codec_type") == "video" and stream.get("codec_name") in image_codecs for stream in streams)
        video = not image and any(stream.get("codec_type") == "video" for stream in streams)
        audio = not image and not video and any(stream.get("codec_type") == "audio" for stream in streams)
        require({"image": image, "video": video, "audio": audio}[expected], f"媒体类别不匹配，需要 {expected}：{path}")
        selected_type = "audio" if expected == "audio" else "video"
        selected = next(stream for stream in streams if stream.get("codec_type") == selected_type)
        require(str(selected.get("nb_read_frames", "")).isdigit() and int(selected["nb_read_frames"]) > 0,
                f"媒体没有可解码的帧：{path}")
        mapping = "0:a:0" if expected == "audio" else "0:v:0"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-i", path,
                        "-map", mapping, "-f", "null", "-"], capture_output=True, check=True, timeout=180)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ProductionError(f"媒体探测或解码失败：{path}（{type(exc).__name__}）") from None


def check_media(path, expected):
    decoded_media(str(Path(path).resolve()), ark.sha256(path), expected)


def check_directory_ancestors(project, directory):
    root = Path(project).resolve()
    cursor = directory
    while cursor != root:
        require(not (cursor.exists() or cursor.is_symlink()) or cursor.is_dir(), f"输出祖先不是目录：{cursor}")
        cursor = cursor.parent


def outputs(job):
    args = job["args"]
    prefix = str(Path(args["out"]) / args["name"])
    if job["kind"] == "image":
        return {"image": prefix + (".png" if args["model"].startswith("doubao-seedream-5") else ".jpeg")}
    return {"video": prefix + ".mp4", "last_frame": prefix + "-尾帧.jpeg"}


def source(project, value, job, jobs, inputs, allow_job=True):
    require(isinstance(value, dict), "输入必须是明确的 path、library/path 或 job/output 对象")
    keys = set(value)
    if keys == {"path"}:
        fingerprint(project, value["path"], inputs)
        return value
    if keys == {"library", "path"}:
        require(safe_id(value["library"]), "library ID 无效")
        manifest_path = f"06-素材/素材库/{value['library']}/来源.json"
        manifest = read(fingerprint(project, manifest_path, inputs))
        require(manifest.get("format") == "vsc.library-use/v1" and manifest.get("project_id") == ark.project_id(project)
                and manifest.get("item_id") == value["library"], "库素材必须先通过 scripts/assets/library.py use 绑定到当前作品")
        matches = [item for item in manifest.get("files", []) if item.get("path") == value["path"]]
        path = fingerprint(project, value["path"], inputs)
        require(len(matches) == 1 and matches[0].get("sha256") == ark.sha256(path), "库素材来源清单不匹配或文件已漂移")
        return value
    if keys == {"job", "output"} and allow_job:
        upstream = jobs.get(value["job"])
        require(upstream is not None and value["job"] in job["depends_on"], "输出引用必须指向显式 depends_on 上游")
        require(value["output"] in outputs(upstream), "输出引用与上游任务种类不匹配")
        return value
    raise ProductionError("不支持的输入结构（不能传 URL、shell 或未声明输出）")


def build_plan(project, batch):
    """全量本地预检；不创建目录、不写记录、不访问平台。"""
    project = Path(project).resolve()
    require(all(shutil.which(tool) for tool in ("ffprobe", "ffmpeg")), "生产媒体预检需要已安装 ffprobe 和 ffmpeg")
    require(isinstance(batch, dict), "batch 必须是对象")
    require(set(batch) <= {"format", "project_id", "id", "max_remote_jobs", "max_attempts", "budget", "jobs"}, "未知 batch 字段")
    require(batch.get("format") == FORMAT and safe_id(batch.get("id")), "batch format 或 id 无效")
    require(batch.get("project_id") == ark.project_id(project), "batch project_id 与作品不一致")
    require(integer(batch.get("max_remote_jobs"), 1), "max_remote_jobs 必须为正整数")
    require(integer(batch.get("max_attempts", 3), 1), "max_attempts 必须为正整数")
    budget = batch.get("budget")
    require(isinstance(budget, dict) and set(budget) == {"max_images", "max_video_seconds"}
            and all(integer(value) for value in budget.values()), "budget 必须给出非负整数 max_images/max_video_seconds")
    raw_jobs = batch.get("jobs")
    require(isinstance(raw_jobs, list) and raw_jobs, "jobs 必须为非空数组")
    require(len(raw_jobs) <= batch["max_remote_jobs"], "生成任务数超过 max_remote_jobs")
    jobs = {}
    for raw in raw_jobs:
        require(isinstance(raw, dict) and set(raw) == {"id", "kind", "depends_on", "args"}, "job 必须写 id/kind/depends_on/args")
        job = json.loads(json.dumps(raw))
        require(safe_id(job["id"]) and job["id"] not in jobs, "job ID 无效或重复")
        require(job["kind"] in ("image", "video"), "仅支持豆包 image/video")
        require(isinstance(job["depends_on"], list) and all(safe_id(item) for item in job["depends_on"])
                and len(set(job["depends_on"])) == len(job["depends_on"]), "depends_on 必须是无重复 ID 数组")
        args = job["args"]
        require(isinstance(args, dict) and set(args) <= COMMON | (IMAGE if job["kind"] == "image" else VIDEO), "未知或越权 args 字段")
        require(safe_id(args.get("name")), "args.name 必须是安全文件名")
        check_directory_ancestors(project, path_in(project, args.get("out")))
        require(Path(args["out"]).parts and Path(args["out"]).parts[0] != ".vsc-production", "输出必须使用独立目录，不能进入队列 journal 目录")
        require(("prompt" in args) != ("prompt_file" in args), "prompt 与 prompt_file 必须二选一")
        if "prompt" in args:
            require(isinstance(args["prompt"], str) and bool(args["prompt"].strip()), "prompt 必须非空")
        defaults = ({"model": ark.IMAGE_MODEL, "size": "2K", "purpose": "candidate", "base_use": "edit", "ref": []}
                    if job["kind"] == "image" else {"model": ark.VIDEO_MODEL, "resolution": "480p", "ratio": "adaptive",
                                                   "duration": 5, "no_audio": False, "draft": False,
                                                   "ref_image": [], "ref_video": [], "ref_audio": []})
        job["args"] = {**defaults, **args}
        args = job["args"]
        prefix = "doubao-seedream-" if job["kind"] == "image" else "doubao-seedance-"
        require(isinstance(args["model"], str) and args["model"].startswith(prefix), "队列只支持豆包 Seedream/Seedance 模型")
        for key in set(args) - MEDIA - FILES - {"duration", "no_audio", "draft"}:
            require(isinstance(args[key], str) and bool(args[key]), f"{key} 必须是非空字符串")
        if job["kind"] == "image":
            require(args["purpose"] in ("asset", "candidate") and args["base_use"] in ark.consistency.BASE_USES, "图像 purpose/base_use 无效")
            require("moment" not in args or args["moment"] in ark.consistency.MOMENTS, "moment 必须为 entry/exit")
            if args["purpose"] == "candidate":
                require(args.get("moment") in ark.consistency.MOMENTS, "候选关键帧需要 moment entry/exit")
        else:
            require(integer(args["duration"], 1), "视频 duration 必须为正整数；不接受无法预估的自适应时长")
            require(type(args["no_audio"]) is bool and type(args["draft"]) is bool, "no_audio/draft 必须为布尔值")
            require(not args["draft"] or args["resolution"] == "480p", "draft 仅支持 480p")
            ark.video_content("preflight", args.get("first_frame"), args.get("last_frame"), args.get("first_frame_ref"),
                              args["ref_image"], args["ref_video"], args["ref_audio"])
        if job["kind"] == "video" or args["purpose"] == "candidate" or "bible" in args or "state" in args:
            require(all(args.get(key) for key in ("bible", "state", "shot")), "镜头生成需要 bible/state/shot 锚点")
        jobs[job["id"]] = job
    # 拓扑排序独立于清单输入顺序。
    order, visiting = [], set()
    def visit(identifier):
        require(identifier in jobs, f"依赖任务不存在：{identifier}")
        require(identifier not in visiting, "任务依赖存在循环")
        if identifier in order:
            return
        visiting.add(identifier)
        for dependency in jobs[identifier]["depends_on"]:
            visit(dependency)
        visiting.remove(identifier)
        order.append(identifier)
    for identifier in jobs:
        visit(identifier)
    inputs, destinations = {}, set()
    for job in jobs.values():
        args = job["args"]
        for key in FILES & set(args):
            source(project, args[key], job, jobs, inputs, allow_job=False)
            require(set(args[key]) == {"path"}, f"{key} 必须使用本地 path")
        if "prompt_file" in args:
            require(path_in(project, args["prompt_file"]["path"]).read_text("utf-8").strip(), "prompt_file 为空")
        for key in MEDIA & set(args):
            values = args[key] if key in MULTI else [args[key]]
            require(isinstance(values, list), f"{key} 必须为数组")
            for value in values:
                source(project, value, job, jobs, inputs)
                # 引用媒体类别必须吻合（首尾帧都是图片）。
                expected = "video" if key == "ref_video" else "audio" if key == "ref_audio" else "image"
                if "job" in value:
                    actual = "video" if value["output"] == "video" else "image"
                    require(expected == actual, f"{key} 的输出媒体类别不匹配")
                else:
                    check_media(path_in(project, value["path"]), expected)
        if args.get("bible"):
            anchor_args = SimpleNamespace(project=str(project), bible=str(path_in(project, args["bible"]["path"])),
                                          state=str(path_in(project, args["state"]["path"])))
            ark.anchors(anchor_args, args["shot"])
        for relative in list(outputs(job).values()) + [record_path(job), task_path(job)]:
            destination = path_in(project, relative)
            require(not destination.is_symlink(), "生成输出不能是符号链接")
            resolved = str(destination.resolve())
            require(resolved not in destinations, "任务输出路径重复")
            destinations.add(resolved)
    require(not any(str(path_in(project, relative).resolve()) in destinations for relative in inputs), "生成输出不能覆盖任何输入")
    require(not any(str(parent) in destinations for destination in destinations for parent in Path(destination).parents),
            "生成输出不能同时作为其他任务的目录祖先")
    usage = {"remote_jobs": len(jobs), "images": sum(job["kind"] == "image" for job in jobs.values()),
             "video_seconds": sum(job["args"]["duration"] for job in jobs.values() if job["kind"] == "video")}
    require(usage["images"] <= budget["max_images"] and usage["video_seconds"] <= budget["max_video_seconds"], "计划超过聚合图像/视频预算")
    plan = {"format": "vsc.production-plan/v1", "project_id": batch["project_id"], "id": batch["id"],
            "max_remote_jobs": batch["max_remote_jobs"], "max_attempts": batch.get("max_attempts", 3), "budget": budget,
            "usage_bound": usage, "estimated_currency": None, "inputs_sha256": inputs, "jobs": [jobs[key] for key in order]}
    plan["plan_sha256"] = ark.digest_json(plan)
    return plan


def record_path(job):
    return str(Path(job["args"]["out"]) / (job["args"]["name"] + "-生成记录.json"))


def task_path(job):
    return str(Path(job["args"]["out"]) / (job["args"]["name"] + "-任务.json"))


def journal_path(project, identifier):
    return path_in(project, f".vsc-production/{identifier}.json")


@contextlib.contextmanager
def queue_lock(project, identifier):
    path = path_in(project, f".vsc-production/{identifier}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), "队列锁不能是符号链接")
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProductionError("同一批次正在执行") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def completed(project, job):
    path = path_in(project, record_path(job))
    if not path.is_file():
        return None
    record = read(path)
    if (record.get("status") != "succeeded" or record.get("project_id") != ark.project_id(project)
            or record.get("kind") != job["kind"] or record.get("engine", {}).get("provider") != ark.PROVIDER):
        return None
    require(not ark.consistency.record_errors(record), "生成记录格式无效")
    require(ark.checked_outputs(record, project), "已完成任务产物缺失或 SHA-256 漂移")
    primary = outputs(job)[job["kind"]]
    require(any(item["path"] == primary for item in record["outputs"]), "成功记录缺少本任务主产物")
    task = read(path_in(project, task_path(job)))
    engine = record["engine"]
    params = {key: value for key, value in engine.get("params", {}).items() if key != "actual"}
    rebuilt = {"project_id": record["project_id"], "kind": record["kind"], "purpose": record["purpose"],
               "shot_id": record["shot_id"], "inputs": record["inputs"], "model": engine["model"],
               "params": params, "payload_sha256": engine.get("payload_sha256")}
    if engine.get("semantic_payload_sha256"):
        rebuilt["semantic_payload_sha256"] = engine["semantic_payload_sha256"]
    require(isinstance(task.get("binding"), dict) and rebuilt == task["binding"]
            and engine.get("request_sha256") == ark.digest_json(rebuilt) and task.get("record") == record,
            "生成记录与方舟任务请求绑定不一致")
    args = job["args"]
    expected_params = ({"size": args["size"]} if job["kind"] == "image" else
                       {"resolution": args["resolution"], "ratio": args["ratio"], "duration": args["duration"],
                        "generate_audio": not args["no_audio"], "return_last_frame": True, "watermark": False})
    if args.get("draft"):
        expected_params["draft"] = True
    prompt = args["prompt"].strip() if "prompt" in args else path_in(project, args["prompt_file"]["path"]).read_text("utf-8").strip()
    if job["kind"] == "video" and args.get("first_frame_ref"):
        prompt = ark.video_content(prompt, first_ref="input")[0]["text"]
    require(engine["model"] == args["model"] and params == expected_params and record["shot_id"] == args.get("shot")
            and record["purpose"] == args.get("purpose", "candidate") and record["inputs"].get("prompt") == prompt,
            "生成记录与计划的提示词、模型、镜头或参数不一致")
    if rebuilt.get("semantic_payload_sha256"):
        # 从计划声明的模式与实际输入摘要重建语义请求；不使用会过期的运输 URL。
        inputs, references = record["inputs"], record["inputs"].get("references", [])
        shape = ([("image", spec) for spec in args.get("ref", [])] if job["kind"] == "image" else
                 [(media, spec) for key, media in (("ref_image", "image"), ("ref_video", "video"), ("ref_audio", "audio"))
                  for spec in args.get(key, [])])
        require(len(references) == len(shape), "参考输入数量与计划不一致")
        normalized_refs = []
        for ref, (media, spec) in zip(references, shape):
            info = ark.consistency.reference_info(ref)
            require(info["media_type"] == media and info.get("role", "reference_" + media) == "reference_" + media,
                    "参考媒体角色与计划不一致")
            require(info.get("sha256"), "本地队列参考缺少内容 SHA-256")
            if isinstance(ref, dict) and ref.get("path"):
                require(ark.sha256(path_in(project, ref["path"])) == ref["sha256"], "参考输入内容已漂移")
                if spec.get("path"):
                    require(ref["path"] == spec["path"], "参考输入路径与计划不一致")
            normalized_refs.append((media, "sha256:" + info["sha256"]))
        if job["kind"] == "image":
            base = inputs.get("base_frame")
            require(bool(base) == bool(args.get("base_frame")), "基础帧模式与计划不一致")
            if base:
                require(base.get("use") == args["base_use"] and ark.sha256(path_in(project, base["path"])) == base["sha256"],
                        "基础帧用途或内容与计划不一致")
                if args["base_frame"].get("path"):
                    require(base["path"] == args["base_frame"]["path"], "基础帧路径与计划不一致")
            images = (["sha256:" + base["sha256"]] if base else []) + [url for _, url in normalized_refs]
            semantic = ark.image_payload(engine["model"], prompt, args["size"], images)
        else:
            content = [{"type": "text", "text": prompt}]
            for key, role in (("first_frame", "reference_image" if args.get("first_frame_ref") else "first_frame"),
                              ("last_frame", "last_frame")):
                frame = inputs.get(key)
                declared = args.get(key) or (args.get("first_frame_ref") if key == "first_frame" else None)
                require(bool(frame) == bool(declared), "首尾帧模式与计划不一致")
                if frame:
                    require(ark.sha256(path_in(project, frame["path"])) == frame["sha256"], "首尾帧输入内容已漂移")
                    if declared.get("path"):
                        require(frame["path"] == declared["path"], "首尾帧输入路径与计划不一致")
                    content.append({"type": "image_url", "image_url": {"url": "sha256:" + frame["sha256"]}, "role": role})
            content += [{"type": media + "_url", media + "_url": {"url": url}, "role": "reference_" + media}
                        for media, url in normalized_refs]
            semantic = {"model": engine["model"], "content": content, **params}
        require(ark.digest_json(semantic) == rebuilt["semantic_payload_sha256"], "生成记录的语义请求与计划输入不一致")
    expected_outputs = {relative: key for key, relative in outputs(job).items()}
    for item in record["outputs"]:
        output = expected_outputs.get(item["path"])
        require(output is not None, "生成记录含本任务未声明的输出")
        expected_id = args["name"] + ("-尾帧" if output == "last_frame" else "")
        require(item["id"] == expected_id and item.get("role") == ("last_frame" if output == "last_frame" else None),
                "产物 ID 或角色与声明的输出类别不一致")
        check_media(path_in(project, item["path"]), "video" if output == "video" else "image")
    return record


def resolve_args(project, job, jobs):
    args, hashes = {}, {}
    def resolve(value):
        if "job" in value:
            upstream = jobs[value["job"]]
            record = completed(project, upstream)
            require(record is not None, "依赖尚未成功")
            relative = outputs(upstream)[value["output"]]
            matches = [item for item in record["outputs"] if item["path"] == relative]
            require(len(matches) == 1, "上游没有登记所需输出；不能猜测尾帧")
        else:
            relative = value["path"]
        path = fingerprint(project, relative, hashes)
        return str(path)
    for key, value in job["args"].items():
        args[key] = [resolve(item) for item in value] if key in MULTI else resolve(value) if key in MEDIA | FILES else value
    argv = [job["kind"], "--project", str(Path(project).resolve())]
    for key, value in args.items():
        flag = "--" + key.replace("_", "-")
        if type(value) is bool:
            if value:
                argv.append(flag)
        elif isinstance(value, list):
            for item in value:
                argv.extend([flag, str(item)])
        else:
            # Equals keeps literal prompt text beginning with -- as data.
            argv.append(flag + "=" + str(value))
    return argv, hashes


def default_runner(argv):
    subprocess.run([sys.executable, str(script_path("providers/volcengine/ark.py")), *argv], check=True)


def run(project, plan, plan_hash, runner=None, before_job=None, after_job=None, formal=False):
    state = read(Path(project) / 'vsc.json')
    require(formal or state.get('profile_snapshot', {}).get('contract_policy') != 'production-v2',
            '新项目执行必须经 scripts/production/run.py，plan hash 不是人工批准')
    require(plan_hash == plan["plan_sha256"], "执行 plan hash 与当前计划不一致；请重新 plan 并审阅")
    runner = runner or default_runner
    path = journal_path(project, plan["id"])
    with queue_lock(project, plan["id"]):
        for job in plan["jobs"]:
            check_directory_ancestors(project, path_in(project, job["args"]["out"]))
        for relative, digest in plan["inputs_sha256"].items():
            require(ark.sha256(path_in(project, relative)) == digest, "计划预检后本地输入已漂移")
        require(not path.is_symlink(), "journal 不能是符号链接")
        if path.exists():
            journal = read(path)
            require(journal.get("format") == JOURNAL_FORMAT and journal.get("plan_sha256") == plan_hash, "旧队列的计划/输入已漂移；请使用新的 batch id 与 job name")
        else:
            # 不接管其他命令留下的同名任务；必须先有本队列的调用绑定。
            for job in plan["jobs"]:
                require(not any(path_in(project, item).exists() for item in [record_path(job), task_path(job), *outputs(job).values()]),
                        "同名任务或输出已存在，不能接管；请使用新的 name")
            journal = {"format": JOURNAL_FORMAT, "id": plan["id"], "project_id": plan["project_id"],
                       "plan_sha256": plan_hash, "jobs": {}, "usage_bound": plan["usage_bound"]}
            ark.write_json(path, journal)
        jobs = {job["id"]: job for job in plan["jobs"]}
        for job in plan["jobs"]:
            entry = journal["jobs"].get(job["id"])
            if before_job:
                extra = before_job(job, journal)
                if extra is None:
                    journal['status'] = 'awaiting_review'
                    ark.write_json(path, journal)
                    return journal
            else:
                extra = []
            argv, hashes = resolve_args(project, job, jobs)
            for relative, digest in hashes.items():
                if relative in plan["inputs_sha256"]:
                    require(digest == plan["inputs_sha256"][relative], "执行期间计划输入已漂移")
            binding = ark.digest_json({"argv": argv, "inputs": hashes})
            if entry:
                require(entry.get("binding") == binding, "任务输入/上游产物已漂移，不能续接旧任务")
                record = completed(project, job)
                if record:
                    request_digest = record["engine"]["request_sha256"]
                    require(entry.get("request_binding_sha256", request_digest) == request_digest,
                            "方舟请求绑定与原队列执行记录不一致")
                    entry["request_binding_sha256"] = request_digest
                    output_hashes = {item["path"]: item["sha256"] for item in record["outputs"]}
                    require(entry.get("outputs_sha256", output_hashes) == output_hashes, "已完成任务输出清单已漂移")
                    entry["outputs_sha256"] = output_hashes
                    entry["status"] = "succeeded"
                    ark.write_json(path, journal)
                    if after_job and not after_job(job, record, journal):
                        journal['status'] = 'awaiting_review'; ark.write_json(path, journal)
                        return journal
                    continue
                # 没有方舟任务凭证时无法证明提交失败：绝不自动重提。
                require(path_in(project, task_path(job)).is_file(), "上次调用没有可续接的方舟任务凭证；提交状态未知，须人工核查后使用新任务")
            else:
                entry = {"binding": binding, "inputs_sha256": hashes, "attempts": 0, "status": "pending"}
                journal["jobs"][job["id"]] = entry
            require(entry["attempts"] < plan["max_attempts"], "任务调用次数达到 max_attempts；未再次调用")
            entry.update(attempts=entry["attempts"] + 1, status="running")
            ark.write_json(path, journal)
            try:
                runner(argv + extra)
                record = completed(project, job)
                require(record is not None, "调用结束但未发现成功生成记录")
            except Exception as exc:
                entry.update(status="failed", error=str(exc))
                ark.write_json(path, journal)
                raise ProductionError(f"{job['id']} 中断；下游未执行：{exc}") from None
            entry.update(status="succeeded")
            entry["request_binding_sha256"] = record["engine"]["request_sha256"]
            entry["outputs_sha256"] = {item["path"]: item["sha256"] for item in record["outputs"]}
            entry.pop("error", None)
            ark.write_json(path, journal)
            if after_job and not after_job(job, record, journal):
                journal['status'] = 'awaiting_review'; ark.write_json(path, journal)
                return journal
        journal['status'] = 'completed'
        ark.write_json(path, journal)
        return journal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "plan", "run", "status"):
        child = sub.add_parser(command)
        child.add_argument("batch")
        child.add_argument("--project", required=True)
        if command == "run":
            child.add_argument("--execute", action="store_true")
            child.add_argument("--plan-hash")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.project, read(args.batch))
        result = plan
        if args.command == "run" and args.execute:
            result = run(args.project, plan, args.plan_hash)
        elif args.command == "status":
            path = journal_path(args.project, plan["id"])
            result = read(path) if path.is_file() else {"status": "not_started", "plan_sha256": plan["plan_sha256"]}
            require(result.get("plan_sha256") == plan["plan_sha256"], "当前计划与旧 journal 已漂移")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ProductionError, ark.ArkError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
