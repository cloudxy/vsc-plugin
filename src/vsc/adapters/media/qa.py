#!/usr/bin/env python3
"""Check local source ranges/render metadata and loudness, and bind a human sample review to evidence.

No model calls, generation, media modification, or automatic aesthetic approval.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from vsc.post.remotion_plan import frame_rate, load_plan, validate

FORMAT = "vsc.media-qa/v1"
REVIEW_FORMAT = "vsc.sample-review/v1"
REVIEW_CATEGORIES = ("story_and_motivation", "physical_continuity", "emotional_continuity", "edit_coverage", "dialogue_and_music")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProbeFailure(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class LocalProbeAdapter:
    """One real seam: a bounded read-only ffprobe process returning metadata."""
    name = "local-ffprobe/v1"
    simulated = False

    def __init__(self, executable="ffprobe", timeout=30, runner=None, ffmpeg="ffmpeg", decode_timeout=600):
        if finite(timeout) is None or not 0 < timeout <= 3600 or finite(decode_timeout) is None or not 0 < decode_timeout <= 3600:
            raise ValueError("探测/完整解码超时必须在 0..3600 秒内")
        self.executable = executable
        self.timeout = timeout
        self.runner = runner or subprocess.run
        self.ffmpeg = ffmpeg
        self.decode_timeout = decode_timeout

    def decode(self, path):
        """Decode every audio/video frame, never a sampled prefix; execution is bounded."""
        command = [self.ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
                   "-stats_period", "30", "-i", str(path), "-map", "0:v?", "-map", "0:a?",
                   "-progress", "pipe:1", "-f", "null", "-"]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=self.decode_timeout, check=False)
        except FileNotFoundError as exc:
            raise ProbeFailure("missing_tool", "完整解码需要 ffmpeg，未验证") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProbeFailure("decode_timeout", f"完整解码超过 {self.decode_timeout}s，未验证") from exc
        if result.returncode or "progress=end" not in (result.stdout or ""):
            raise ProbeFailure("decode_error", (result.stderr or "").strip()[-1000:] or "完整解码未完成")
        progress = dict(line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line)
        return {"status": "passed", "mode": "complete", "decoder": "ffmpeg", "error_policy": "xerror+explode",
                "video_frames": number(progress.get("frame")), "decoded_until_seconds": (finite(progress.get("out_time_us")) or 0) / 1_000_000}

    def audio_coverage(self, path, offset=0):
        """Collect intervals of real decoded samples, including timestamp gaps; spool logs to disk."""
        command = [self.ffmpeg, "-nostdin", "-hide_banner", "-v", "info", "-xerror", "-err_detect", "explode",
                   "-copyts", "-i", str(path), "-map", "0:a:0", "-vn", "-af", "ashowinfo", "-f", "null", "-"]
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as log:
            try:
                result = self.runner(command, stdout=subprocess.DEVNULL, stderr=log, text=True, timeout=self.decode_timeout, check=False)
            except FileNotFoundError as exc:
                raise ProbeFailure("missing_tool", "实际音频覆盖检查需要 ffmpeg，未验证") from exc
            except subprocess.TimeoutExpired as exc:
                raise ProbeFailure("decode_timeout", "实际音频覆盖检查超时，未验证") from exc
            if result.returncode:
                raise ProbeFailure("audio_decode_error", "实际音频覆盖解码失败，未验证")
            log.seek(0)
            intervals = []
            for line in log:
                if "Parsed_ashowinfo" not in line:
                    continue
                match = re.search(r"pts_time:([-+\d.eE]+).*?rate:(\d+).*?nb_samples:(\d+)", line)
                if match:
                    start, rate, count = float(match[1]) - offset, int(match[2]), int(match[3])
                    if math.isfinite(start) and rate > 0 and count > 0:
                        end = start + count / rate
                        if intervals and start <= intervals[-1][1] + 1 / rate:
                            intervals[-1][1] = max(end, intervals[-1][1])
                        else:
                            intervals.append([start, end])
        if not intervals:
            raise ProbeFailure("audio_decode_error", "没有可定位的实际音频样本，未验证")
        return intervals

    def loudness(self, path):
        """Read-only EBU R128 measurement via ffmpeg loudnorm analysis: LUFS, dBTP and LU."""
        command = [self.ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=max(self.timeout, 120), check=False)
        except FileNotFoundError as exc:
            raise ProbeFailure("missing_tool", "响度测量需要 ffmpeg，没有退化为假通过") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProbeFailure("timeout", "响度测量超时") from exc
        match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr or "")
        if result.returncode or not match:
            raise ProbeFailure("loudness_error", (result.stderr or "").strip()[-500:] or f"ffmpeg exit={result.returncode}")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProbeFailure("loudness_error", "响度测量 JSON 无效，未验证") from exc
        values = {"integrated_lufs": finite(data.get("input_i")), "true_peak_dbtp": finite(data.get("input_tp")), "range_lu": finite(data.get("input_lra"))}
        if data.get("input_i") == "-inf" and data.get("input_tp") == "-inf":
            return {**values, "silent": True}
        if any(value is None for value in values.values()):
            raise ProbeFailure("loudness_error", "响度测量含无效或非有限值，未验证")
        return values

    def probe(self, path):
        try:
            return self._probe(path)
        except OSError as exc:
            raise ProbeFailure("media_unreadable", str(exc)) from exc

    def _probe(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            raise ProbeFailure("missing_media", f"媒体不存在：{path}")
        initial_hash = sha256(path)
        try:
            result = self.runner([self.executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, timeout=self.timeout, check=False)
        except FileNotFoundError as exc:
            raise ProbeFailure("missing_tool", "需要安装 ffprobe（FFmpeg），没有退化为假通过") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProbeFailure("timeout", f"ffprobe 超过 {self.timeout}s") from exc
        except OSError as exc:
            raise ProbeFailure("probe_error", str(exc)) from exc
        if result.returncode:
            raise ProbeFailure("probe_error", result.stderr.strip()[:1000] or f"ffprobe exit={result.returncode}")
        try:
            raw = json.loads(result.stdout)
            if not isinstance(raw, dict) or not isinstance(raw.get("streams"), list) or not raw["streams"] or not isinstance(raw.get("format", {}), dict):
                raise ValueError("无有效 streams")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProbeFailure("invalid_metadata", f"ffprobe 元数据无效：{exc}") from exc
        if sha256(path) != initial_hash:
            raise ProbeFailure("media_changed_during_probe", "媒体在检查过程中变更，请重试新版本")
        decoded = self.decode(path)
        first_video = next((s for s in raw["streams"] if isinstance(s, dict) and s.get("codec_type") == "video"), None)
        if first_video is not None:
            expected_frames = number(first_video.get("nb_frames"))
            actual_frames = decoded.get("video_frames")
            if not actual_frames or (expected_frames and actual_frames < expected_frames):
                raise ProbeFailure("decode_incomplete", "实际解码帧数少于文件声明，未验证")
        if sha256(path) != initial_hash:
            raise ProbeFailure("media_changed_during_probe", "媒体在检查过程中变更，请重试新版本")
        streams = [{key: item[key] for key in ("index", "codec_type", "codec_name", "width", "height", "duration", "start_time", "avg_frame_rate", "sample_rate", "channels") if key in item} for item in raw["streams"] if isinstance(item, dict)]
        return {"path": str(path), "sha256": initial_hash, "bytes": path.stat().st_size, "duration_seconds": number(raw.get("format", {}).get("duration")), "start_time": finite(raw.get("format", {}).get("start_time")) or 0, "streams": streams, "decode": decoded}


class FaultProbeAdapter(LocalProbeAdapter):
    """Exercise exactly the real adapter's failure handling, never production evidence."""
    name = "fault-ffprobe/v1"
    simulated = True

    def __init__(self, fault="timeout"):
        def runner(command, **kwargs):
            if fault == "timeout":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            if fault == "missing_tool":
                raise FileNotFoundError("test ffprobe unavailable")
            if fault == "invalid_metadata":
                return subprocess.CompletedProcess(command, 0, stdout="{broken", stderr="")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="injected probe failure")
        super().__init__(runner=runner)


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def measured_fps(value):
    try:
        numerator, denominator = str(value).split("/")
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return number(value)


def stream_duration(metadata, kind):
    matching = [stream for stream in metadata["streams"] if stream.get("codec_type") == kind]
    if not matching:
        return None
    return number(matching[0].get("duration")) or metadata["duration_seconds"]


def gaps(segments, duration):
    cursor, missing = 0, []
    for start, end in sorted((s["from_frame"], s["from_frame"] + s["duration_in_frames"]) for s in segments if s["kind"] in {"video", "image"}):
        if start > cursor:
            missing.append([cursor, start])
        cursor = max(cursor, end)
    if cursor < duration:
        missing.append([cursor, duration])
    return missing


def validate_loudness_target(target):
    if target is None:
        return None
    keys = ("integrated_lufs", "tolerance_lu", "true_peak_max_dbtp")
    if not isinstance(target, dict) or set(target) != set(keys) or any(finite(target.get(key)) is None for key in keys):
        raise ValueError("loudness_target 需要有限数值 integrated_lufs、tolerance_lu、true_peak_max_dbtp")
    if float(target["tolerance_lu"]) < 0:
        raise ValueError("loudness_target.tolerance_lu 必须非负")
    return {key: float(target[key]) for key in keys}


def required_audio_intervals(plan, cached, root, fps):
    """Nonzero planned gains at actual timeline frames; an unmuted silent video is legal."""
    intervals = []
    for segment in plan["segments"]:
        if segment["kind"] not in {"audio", "video"} or segment.get("muted") or segment.get("volume", 1) == 0:
            continue
        metadata = cached.get((root / segment["source"]).resolve())
        if not metadata or not any(s.get("codec_type") == "audio" for s in metadata["streams"]):
            continue
        length, points = segment["duration_in_frames"], segment.get("volume_keyframes", [])
        cursor, run = 0, None
        for frame in range(length):
            envelope = 1
            if points:
                while cursor + 1 < len(points) and frame > points[cursor + 1]["frame"]:
                    cursor += 1
                envelope = points[cursor]["volume"]
                if cursor + 1 < len(points):
                    following = points[cursor + 1]
                    ratio = max(0, min(1, (frame - points[cursor]["frame"]) / (following["frame"] - points[cursor]["frame"])))
                    envelope += ratio * (following["volume"] - envelope)
            active = envelope > 0 and not (segment.get("audio_fade_in_frames", 0) and frame == 0) and not (segment.get("audio_fade_out_frames", 0) and frame == length - 1)
            if active and run is None:
                run = frame
            if run is not None and (not active or frame == length - 1):
                end = frame if not active else frame + 1
                intervals.append([(segment["from_frame"] + run) / fps, (segment["from_frame"] + end) / fps])
                run = None
    return intervals


def uncovered_intervals(required, available, tolerance):
    missing = []
    for start, end in required:
        cursor = start
        for begin, finish in available:
            if finish <= cursor:
                continue
            if begin > cursor + tolerance:
                break
            cursor = max(cursor, finish)
            if cursor >= end - tolerance:
                break
        if cursor < end - tolerance:
            missing.append([cursor, end])
    return missing


def check_plan(plan_path, media_root, adapter, render=None, loudness_target=None):
    loudness_target = validate_loudness_target(loudness_target)
    initial_hash = sha256(plan_path)
    plan = load_plan(plan_path)
    if isinstance(plan, dict) and plan.get("format") == "vsc.timeline/v1":
        plan = plan.get("render_plan")
    if sha256(plan_path) != initial_hash:
        raise ValueError("计划在检查开始时变更，请重试新版本")
    errors = validate(plan)
    report = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "project_id": plan.get("project_id") if isinstance(plan, dict) else None, "plan_path": str(Path(plan_path).resolve()), "plan_sha256": initial_hash, "media_root": str(Path(media_root).resolve()), "adapter": adapter.name, "simulated": adapter.simulated, "sources": [], "render": None, "errors": list(errors), "warnings": [], "loudness_target": loudness_target}
    if errors:
        report["status"] = "failed"
        return report
    root = Path(media_root).resolve()
    fps = frame_rate(plan["composition"]["fps"])
    duration = plan["composition"]["duration_in_frames"]
    report["expected"] = {"duration_seconds": duration / fps, "fps": fps, "width": plan["composition"]["width"], "height": plan["composition"]["height"]}
    report["visual_gaps_frames"] = gaps(plan["segments"], duration)
    if report["visual_gaps_frames"]:
        report["warnings"].append("视觉时间线有空隙，需审片确认是否刻意黑场")
    cached = {}
    for segment in plan["segments"]:
        if segment["kind"] not in {"video", "audio", "image"}:
            continue
        source = (root / segment["source"]).resolve()
        item = {"segment_id": segment["id"], "source": segment["source"], "status": "passed"}
        report["sources"].append(item)
        try:
            if not source.is_relative_to(root):
                raise ProbeFailure("unsafe_media", "媒体符号链接指向 media-root 外部")
            if source not in cached:
                cached[source] = adapter.probe(source)
            metadata = cached[source]
            item["metadata"] = metadata
            expected_kind = "audio" if segment["kind"] == "audio" else "video"
            if not any(stream.get("codec_type") == expected_kind for stream in metadata["streams"]):
                raise ProbeFailure("missing_stream", f"需要 {expected_kind} stream")
            if segment["kind"] in {"audio", "video"}:
                actual = stream_duration(metadata, expected_kind)
                if actual is None:
                    raise ProbeFailure("unknown_duration", "不能确认源时长")
                required = (segment.get("source_in_frame", 0) + segment["duration_in_frames"] + segment.get("handle_out_frames", 0)) / fps
                item["required_end_seconds"] = required
                if required > actual + 0.000001:
                    raise ProbeFailure("source_range_overflow", f"裁切+尾手柄需 {required:.6f}s，源仅 {actual:.6f}s")
        except ProbeFailure as exc:
            item.update(status="failed", error_code=exc.code, error=str(exc))
            report["errors"].append(f"{segment['id']}: {exc.code}: {exc}")
    if render is not None:
        rendered = {"status": "passed"}
        report["render"] = rendered
        try:
            metadata = adapter.probe(Path(render))
            rendered["metadata"] = metadata
            video = next((s for s in metadata["streams"] if s.get("codec_type") == "video"), None)
            if video is None:
                raise ProbeFailure("missing_stream", "成片缺少 video stream")
            actual = stream_duration(metadata, "video")
            if actual is None or abs(actual - duration / fps) > 1 / fps + 0.000001:
                raise ProbeFailure("render_duration_mismatch", "成片时长与计划相差超过一帧")
            if video.get("width") != plan["composition"]["width"] or video.get("height") != plan["composition"]["height"]:
                raise ProbeFailure("render_dimensions_mismatch", "成片画幅与计划不一致")
            actual_fps = measured_fps(video.get("avg_frame_rate"))
            if actual_fps is None or not math.isfinite(actual_fps) or abs(actual_fps - fps) > 0.001:
                raise ProbeFailure("render_fps_mismatch", "成片平均帧率与计划不一致")
            required_audio = required_audio_intervals(plan, cached, root, fps)
            rendered["required_audio_intervals_seconds"] = required_audio
            if required_audio and not any(s.get("codec_type") == "audio" for s in metadata["streams"]):
                raise ProbeFailure("missing_audio", "计划含非静音音频区间，成片缺少 audio stream")
            if any(s.get("codec_type") == "audio" for s in metadata["streams"]):
                available = adapter.audio_coverage(Path(render), metadata.get("start_time", 0))
                rendered["audio_coverage_seconds"] = available
                missing = uncovered_intervals(required_audio, available, 1 / fps)
                if missing:
                    raise ProbeFailure("render_audio_coverage_gap", f"成片实际音频样本没有覆盖计划非静音区间：{missing}")
                measured = adapter.loudness(Path(render))
                rendered["loudness"] = measured
                if loudness_target:
                    if measured.get("silent") or any(finite(measured.get(key)) is None for key in ("integrated_lufs", "true_peak_dbtp", "range_lu")):
                        raise ProbeFailure("loudness_error", "指定响度目标时必须有有限的真实测量值")
                    deviation = abs(measured["integrated_lufs"] - loudness_target["integrated_lufs"])
                    if deviation > loudness_target["tolerance_lu"]:
                        raise ProbeFailure("render_loudness_out_of_range", f"综合响度 {measured['integrated_lufs']} LUFS 偏离目标 {loudness_target['integrated_lufs']}±{loudness_target['tolerance_lu']} LU")
                    peak = measured["true_peak_dbtp"]
                    if peak is not None and peak > loudness_target["true_peak_max_dbtp"]:
                        raise ProbeFailure("render_true_peak_exceeded", f"真峰值 {peak} dBTP 超过上限 {loudness_target['true_peak_max_dbtp']} dBTP")
            elif loudness_target:
                raise ProbeFailure("missing_audio", "指定了响度目标，但成片没有音轨")
            if sha256(render) != metadata["sha256"]:
                raise ProbeFailure("media_changed_during_probe", "成片在音频检查过程中变更，请重试")
        except ProbeFailure as exc:
            rendered.update(status="failed", error_code=exc.code, error=str(exc))
            report["errors"].append(f"render: {exc.code}: {exc}")
    report["status"] = "failed" if report["errors"] else "passed"
    # Fault adapters are never eligible for approval, including future success simulations.
    report["eligible_for_review"] = report["status"] == "passed" and not adapter.simulated and report["render"] is not None
    return report


def validate_report(path):
    """Reprobe the original files; a forged/stale/partial JSON is not approval evidence."""
    qa = load_plan(path)
    if not isinstance(qa, dict):
        return ["技术报告必须是 object"]
    errors = []
    if qa.get("format") != FORMAT or qa.get("adapter") != LocalProbeAdapter.name or qa.get("status") != "passed" or qa.get("simulated") is not False or qa.get("eligible_for_review") is not True or qa.get("errors") != []:
        errors.append("需要真实且通过的成片技术报告；源素材检查或故障模拟不能替代")
    try:
        if not isinstance(qa.get("created_at"), str):
            raise ValueError("created_at missing")
        datetime.fromisoformat(qa["created_at"])
        if not isinstance(qa.get("warnings"), list) or not isinstance(qa.get("visual_gaps_frames"), list) or not isinstance(qa.get("expected"), dict):
            raise ValueError("预期规格/警告/视觉覆盖字段不完整")
        if not isinstance(qa.get("sources"), list) or not qa["sources"]:
            raise ValueError("sources 必须是非空真实媒体数组")
        if any(not isinstance(item, dict) or item.get("status") != "passed" or not isinstance(item.get("metadata"), dict) for item in qa["sources"]):
            raise ValueError("source 状态或元数据不完整")
        if not isinstance(qa.get("render"), dict) or qa["render"].get("status") != "passed" or not isinstance(qa["render"].get("metadata"), dict):
            raise ValueError("需要完整的成片 metadata")
        if not all(isinstance(qa.get(key), str) and Path(qa[key]).is_absolute() for key in ("plan_path", "media_root")):
            raise ValueError("plan_path/media_root 必须是实际绝对路径")
        render_path = qa["render"]["metadata"].get("path")
        if not isinstance(render_path, str) or not Path(render_path).is_absolute():
            raise ValueError("render metadata.path 必须是实际绝对路径")
        if "loudness_target" not in qa:
            raise ValueError("缺少固定 loudness_target（未指定目标应为 null），需重跑技术检查")
        rebuilt = check_plan(qa["plan_path"], qa["media_root"], LocalProbeAdapter(), render_path, qa["loudness_target"])
        if rebuilt["status"] != "passed":
            errors.extend(f"复检失败：{error}" for error in rebuilt["errors"])
        for key in ("project_id", "plan_sha256", "expected", "visual_gaps_frames", "warnings", "sources", "render", "loudness_target"):
            if qa.get(key) != rebuilt.get(key):
                errors.append(f"技术报告 {key} 与当前真实媒体/计划不一致，需生成新报告")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"技术报告证据不完整或不可读取：{exc}")
    return errors


def validate_review(review_path, strict=False):
    """Validate evidence provenance and completeness, not the truth of aesthetic opinions."""
    review_path = Path(review_path).resolve()
    review = load_plan(review_path)
    if not isinstance(review, dict):
        return ["样片审查必须是 object"]
    errors = []
    if review.get("format") != REVIEW_FORMAT:
        errors.append(f"format 必须为 {REVIEW_FORMAT}")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        errors.append("需要具名 reviewer")
    qa, plan = {}, {}
    try:
        qa_path = (review_path.parent / review["technical_report"]).resolve()
        qa = load_plan(qa_path)
        if sha256(qa_path) != review.get("technical_report_sha256"):
            errors.append("技术报告 hash 不匹配")
        errors.extend(validate_report(qa_path))
        if isinstance(qa, dict) and review.get("project_id") != qa.get("project_id"):
            errors.append("样片审查与技术报告 project_id 不一致")
        plan = load_plan(qa["plan_path"])
        if isinstance(plan, dict) and plan.get("format") == "vsc.timeline/v1":
            plan = plan.get("render_plan", {})
    except (KeyError, OSError, ValueError, TypeError):
        errors.append("技术报告或绑定的媒体/计划不可读取")
    structured = review.get("evidence_mode") == "structured"
    if review.get("evidence_mode") not in (None, "legacy", "structured"):
        errors.append("evidence_mode 必须为 structured 或 legacy")
    if strict and not structured:
        errors.append("legacy 文本审片不可用于严格新交付；需要 structured 证据")
    scope = review.get("scope", {})
    composition = plan.get("composition") if isinstance(plan, dict) else None
    duration = composition.get("duration_in_frames", 0) if isinstance(composition, dict) else 0
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        duration = 0
    def valid_range(item, start=0, end=duration):
        return isinstance(item, dict) and all(isinstance(item.get(key), int) and not isinstance(item[key], bool) for key in ("start_frame", "end_frame")) and start <= item["start_frame"] < item["end_frame"] <= end
    scope_valid = structured and valid_range(scope) and scope.get("kind") in ("sample", "complete")
    if structured:
        if not scope_valid:
            errors.append("scope 需要有效 sample/complete 与成片内 [start_frame,end_frame) 范围")
        elif scope["kind"] == "complete" and (scope["start_frame"] != 0 or scope["end_frame"] != duration):
            errors.append("complete 审片必须覆盖完整 composition")
        if strict and (not scope_valid or scope.get("kind") != "complete" or not isinstance(scope.get("delivery_id"), str) or not scope["delivery_id"].strip()):
            errors.append("严格交付需要完整审片范围及具名 delivery_id")
        render = qa.get("render") if isinstance(qa, dict) else None
        render_metadata = render.get("metadata") if isinstance(render, dict) else None
        render_hash = render_metadata.get("sha256") if isinstance(render_metadata, dict) else None
        if review.get("render_sha256") != render_hash or not isinstance(review.get("render_sha256"), str):
            errors.append("审片 render_sha256 与实际成片版本不一致")
    assessments = review.get("assessments", {})
    if not isinstance(assessments, dict):
        errors.append("assessments 必须为 object")
        assessments = {}
    for category in REVIEW_CATEGORIES:
        item = assessments.get(category, {})
        evidence = item.get("evidence") if isinstance(item, dict) else None
        if not isinstance(item, dict) or item.get("result") not in ("pass", "fail") or (not structured and (not isinstance(evidence, str) or not evidence.strip())):
            errors.append(f"{category}: 需要 pass/fail 与具体时间码/镜头证据")
        elif item["result"] == "fail":
            errors.append(f"{category}: 尚有未解决失败")
        if structured:
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{category}: structured evidence 必须为非空数组")
                continue
            for index, position in enumerate(evidence):
                label = f"{category}.evidence[{index}]"
                if not scope_valid or not valid_range(position, scope["start_frame"], scope["end_frame"]):
                    errors.append(f"{label}: 证据帧范围越界或无效")
                    continue
                if not isinstance(position.get("note"), str) or not position["note"].strip():
                    errors.append(f"{label}: 需要观察说明 note")
                candidates = plan.get("segments", [])
                for key, plan_key in (("segment_id", "id"), ("shot_id", "source_shot_id")):
                    if key in position:
                        candidates = [s for s in candidates if s.get(plan_key) == position[key]]
                        if not candidates:
                            errors.append(f"{label}: {key} 不属于实际计划或与另一 ID 不一致")
                if ("segment_id" in position or "shot_id" in position) and candidates and not any(s["from_frame"] <= position["start_frame"] and position["end_frame"] <= s["from_frame"] + s["duration_in_frames"] for s in candidates):
                    errors.append(f"{label}: 证据范围不在所指镜头/片段内")
    run = review.get("run", {})
    if not isinstance(run, dict) or number(run.get("elapsed_seconds")) is None or number(run.get("cost_amount")) is None or not isinstance(run.get("currency"), str) or not run["currency"].strip() or not isinstance(run.get("failures"), list):
        errors.append("run 需要实际 elapsed_seconds、cost_amount、currency 和 failures 数组（没有失败填 []）")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="只读检查源范围及可选成片；报告不是审美批准")
    check.add_argument("plan")
    check.add_argument("media_root")
    check.add_argument("--render")
    check.add_argument("--output", required=True)
    check.add_argument("--adapter", choices=("local", "fault"), default="local")
    check.add_argument("--fault", choices=("timeout", "missing_tool", "invalid_metadata", "probe_error"), default="timeout")
    check.add_argument("--ffprobe", default="ffprobe")
    check.add_argument("--ffmpeg", default="ffmpeg")
    check.add_argument("--decode-timeout", type=float, default=600, help="完整解码/音频覆盖检查的秒数上限（最大 3600）")
    check.add_argument("--loudness-target", type=float, help="成片综合响度目标（LUFS），按发布平台规范填写；不填则只测量不判定")
    check.add_argument("--loudness-tolerance", type=float, default=1.0, help="允许偏离目标的 LU（默认 1.0）")
    check.add_argument("--true-peak-max", type=float, default=-1.0, help="真峰值上限 dBTP（默认 -1.0）")
    review = commands.add_parser("review", help="校验人工审片记录及未变更的真实媒体证据")
    review.add_argument("review")
    review.add_argument("--strict", action="store_true", help="新交付要求 structured、complete、delivery_id 与成片 hash")
    report_parser = commands.add_parser("validate-report", help="复检真实成片报告，用于契约校验/批准")
    report_parser.add_argument("report")
    args = parser.parse_args()
    try:
        if args.command in {"review", "validate-report"}:
            errors = validate_review(args.review, strict=args.strict) if args.command == "review" else validate_report(args.report)
            if errors:
                for error in errors:
                    print(f"INVALID: {error}", file=sys.stderr)
                return 1
            if args.command == "review" and load_plan(args.review).get("evidence_mode") != "structured":
                print("REVIEW LEGACY: 文本记录仅兼容读取，不可用于严格新交付")
            else:
                print("REVIEW VALID: 具名人工判断、范围及媒体版本已绑定；不是自动审美判断" if args.command == "review" else "MEDIA QA VALID: 已重新检查真实计划、素材与成片")
            return 0
        adapter = LocalProbeAdapter(executable=args.ffprobe, ffmpeg=args.ffmpeg, decode_timeout=args.decode_timeout) if args.adapter == "local" else FaultProbeAdapter(args.fault)
        target = None
        if args.loudness_target is not None:
            if not args.render:
                raise ValueError("--loudness-target 需要同时给出 --render")
            target = {"integrated_lufs": args.loudness_target, "tolerance_lu": args.loudness_tolerance, "true_peak_max_dbtp": args.true_peak_max}
        report = check_plan(args.plan, args.media_root, adapter, args.render, target)
        output = Path(args.output)
        if output.exists():
            raise ValueError(f"拒绝覆盖已有技术报告：{output}，请指定新的版本路径")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"MEDIA QA {report['status'].upper()}: {output}")
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
