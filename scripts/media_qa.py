#!/usr/bin/env python3
"""Check local source ranges/render metadata and bind a human sample review to evidence.

No model calls, generation, media modification, or automatic aesthetic approval.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from remotion_plan import frame_rate, load_plan, validate

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

    def __init__(self, executable="ffprobe", timeout=30, runner=None):
        self.executable = executable
        self.timeout = timeout
        self.runner = runner or subprocess.run

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
        streams = [{key: item[key] for key in ("index", "codec_type", "codec_name", "width", "height", "duration", "avg_frame_rate", "sample_rate", "channels") if key in item} for item in raw["streams"] if isinstance(item, dict)]
        return {"path": str(path), "sha256": initial_hash, "bytes": path.stat().st_size, "duration_seconds": number(raw.get("format", {}).get("duration")), "streams": streams}


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


def check_plan(plan_path, media_root, adapter, render=None):
    initial_hash = sha256(plan_path)
    plan = load_plan(plan_path)
    if sha256(plan_path) != initial_hash:
        raise ValueError("计划在检查开始时变更，请重试新版本")
    errors = validate(plan)
    report = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "project_id": plan.get("project_id") if isinstance(plan, dict) else None, "plan_path": str(Path(plan_path).resolve()), "plan_sha256": initial_hash, "media_root": str(Path(media_root).resolve()), "adapter": adapter.name, "simulated": adapter.simulated, "sources": [], "render": None, "errors": list(errors), "warnings": []}
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
            audible = any(s["kind"] == "audio" or (s["kind"] == "video" and not s.get("muted", False)) for s in plan["segments"])
            if audible and not any(s.get("codec_type") == "audio" for s in metadata["streams"]):
                # Unmuted video can legitimately be silent; only explicit audio is a requirement.
                if any(s["kind"] == "audio" for s in plan["segments"]):
                    raise ProbeFailure("missing_audio", "计划含独立音轨，成片缺少 audio stream")
                report["warnings"].append("成片没有音轨，请确认是否刻意静音")
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
        rebuilt = check_plan(qa["plan_path"], qa["media_root"], LocalProbeAdapter(), render_path)
        if rebuilt["status"] != "passed":
            errors.extend(f"复检失败：{error}" for error in rebuilt["errors"])
        for key in ("project_id", "plan_sha256", "expected", "visual_gaps_frames", "warnings", "sources", "render"):
            if qa.get(key) != rebuilt.get(key):
                errors.append(f"技术报告 {key} 与当前真实媒体/计划不一致，需生成新报告")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"技术报告证据不完整或不可读取：{exc}")
    return errors


def validate_review(review_path):
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
    try:
        qa_path = (review_path.parent / review["technical_report"]).resolve()
        qa = load_plan(qa_path)
        if sha256(qa_path) != review.get("technical_report_sha256"):
            errors.append("技术报告 hash 不匹配")
        errors.extend(validate_report(qa_path))
        if isinstance(qa, dict) and review.get("project_id") != qa.get("project_id"):
            errors.append("样片审查与技术报告 project_id 不一致")
    except (KeyError, OSError, ValueError, TypeError):
        errors.append("技术报告或绑定的媒体/计划不可读取")
    assessments = review.get("assessments", {})
    if not isinstance(assessments, dict):
        errors.append("assessments 必须为 object")
        assessments = {}
    for category in REVIEW_CATEGORIES:
        item = assessments.get(category, {})
        if not isinstance(item, dict) or item.get("result") not in {"pass", "fail"} or not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            errors.append(f"{category}: 需要 pass/fail 与具体时间码/镜头证据")
        elif item["result"] == "fail":
            errors.append(f"{category}: 尚有未解决失败")
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
    review = commands.add_parser("review", help="校验人工审片记录及未变更的真实媒体证据")
    review.add_argument("review")
    report_parser = commands.add_parser("validate-report", help="复检真实成片报告，用于契约校验/批准")
    report_parser.add_argument("report")
    args = parser.parse_args()
    try:
        if args.command in {"review", "validate-report"}:
            errors = validate_review(args.review) if args.command == "review" else validate_report(args.report)
            if errors:
                for error in errors:
                    print(f"INVALID: {error}", file=sys.stderr)
                return 1
            print("REVIEW COMPLETE: 具名人工判断及媒体版本已绑定；不是自动审美判断" if args.command == "review" else "MEDIA QA VALID: 已重新检查真实计划、素材与成片")
            return 0
        adapter = LocalProbeAdapter(executable=args.ffprobe) if args.adapter == "local" else FaultProbeAdapter(args.fault)
        report = check_plan(args.plan, args.media_root, adapter, args.render)
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
