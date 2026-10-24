"""Local render-plan audio adapter; original timing/envelopes remain authority."""
import json
import shutil
import subprocess
from pathlib import Path
from vsc.production.handoffs import digest, local_file


def bind_sound_files(document, specifications):
    """CLI attachments must match every immutable sound-plan ref, never names."""
    expected = {ref["id"]: ref["sha256"] for ref in document.get("sound_plans", [])}
    bound = {}
    for specification in specifications:
        identifier, separator, filename = specification.partition("=")
        if not separator or identifier in bound or identifier not in expected:
            raise ValueError("sound-plan须为本timeline固定引用的ID=FILE，且不能重复")
        path = Path(filename)
        if digest(path) != expected[identifier]:
            raise ValueError("声音计划SHA与timeline固定引用不符: " + identifier)
        bound[identifier] = json.loads(path.read_text("utf-8"))
    if set(bound) != set(expected):
        raise ValueError("必须提供timeline全部固定sound_plans，不能漏掉ducking声明")
    return list(bound.values())


def _gain_expression(segment, fps):
    points = segment.get("volume_keyframes", [])
    expression = str(points[-1]["volume"]) if points else "1"
    for previous, current in reversed(list(zip(points, points[1:]))):
        interpolation = "(%s+(t*%s-%s)*%s/%s)" % (previous["volume"], fps, previous["frame"],
            current["volume"] - previous["volume"], current["frame"] - previous["frame"])
        expression = "if(lt(t*%s,%s),%s,%s)" % (fps, current["frame"], interpolation, expression)
    if points:
        expression = "if(lt(t*%s,%s),%s,%s)" % (fps, points[0]["frame"], points[0]["volume"], expression)
    gain = segment.get("volume", 1)
    expression = "(%s)*%s" % (expression, gain)
    if segment.get("audio_fade_in_frames"):
        expression += "*min(1,t*%s/%s)" % (fps, segment["audio_fade_in_frames"])
    if segment.get("audio_fade_out_frames"):
        expression += "*max(0,min(1,(%s-1-t*%s)/%s))" % (segment["duration_in_frames"], fps, segment["audio_fade_out_frames"])
    return expression


def render_audio(document, media_root, output, *, sound_plans=None, run=subprocess.run):
    from vsc.post.remotion_plan import validate, render_plan, frame_rate
    from vsc.post.sound_rules import project_ducking
    errors = validate(document)
    if errors:
        raise ValueError("；".join(errors))
    if document.get("sound_plans") and sound_plans is None:
        raise ValueError("此timeline有固定声音计划，混音不能忽略其声明")
    projected, intents = project_ducking(document, sound_plans or [])
    plan = render_plan(projected)
    root, output = Path(media_root).resolve(), Path(output)
    if output.exists():
        raise ValueError("混音输出必须为新文件，拒绝覆盖")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("本机FFmpeg不可用，不能声称已混音")
    fps = frame_rate(plan["composition"]["fps"])
    duration = plan["composition"]["duration_in_frames"] / fps
    audible = [segment for segment in plan["segments"] if segment["kind"] in {"audio", "video"}
        and not segment.get("muted", False) and segment.get("volume", 1) > 0]
    command = [ffmpeg, "-v", "error", "-nostdin"]
    filters, records = [], []
    for index, segment in enumerate(audible):
        path = local_file(root, segment["source"])
        expected = next((row["sha256"] for row in projected.get("bindings", []) if row["segment_id"] == segment["id"]), None)
        actual = digest(path)
        if expected is not None and actual != expected:
            raise ValueError("混音源字节与固定binding不符: " + segment["id"])
        command += ["-i", str(path)]
        source = segment.get("source_in_frame", 0) / fps
        length = segment["duration_in_frames"] / fps
        delay = round(segment["from_frame"] * 1000 / fps)
        filters.append("[%d:a]atrim=start=%.9f:duration=%.9f,asetpts=PTS-STARTPTS,volume='%s':eval=frame,adelay=%d|%d,apad=whole_dur=%.9f[a%d]" %
            (index, source, length, _gain_expression(segment, fps), delay, delay, duration, index))
        records.append({"segment_id": segment["id"], "sha256": actual, "volume_keyframes": segment.get("volume_keyframes", [])})
    if audible:
        filters.append("".join("[a%d]" % i for i in range(len(audible))) + "amix=inputs=%d:duration=longest:dropout_transition=0:normalize=0,atrim=duration=%.9f[mix]" % (len(audible), duration))
        command += ["-filter_complex", ";".join(filters), "-map", "[mix]"]
    else:
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration)]
    command += ["-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)]
    result = run(command, capture_output=True, text=True, timeout=180)
    if result.returncode:
        output.unlink(missing_ok=True)
        raise ValueError("本地混音失败: " + (result.stderr or "")[-500:])
    if not output.is_file():
        raise ValueError("混音器未输出真实媒体")
    return {"output": str(output), "sha256": digest(output), "duration_seconds": duration, "sources": records,
            "sound_intents": intents, "applied": "original_render_plan_volume_keyframes", "human_listening": "not_reviewed"}
