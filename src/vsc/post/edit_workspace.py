"""Editable first-cut recipes and a real local renderer, separate from approval.

The workspace holds editorial intent. Media references are fixed by its PG
repository. A draft export never changes candidate selection or a formal render.
"""
import copy
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path


FORMAT = "vsc.edit-workspace/v1"
RECIPE = "first-cut-1"


def validate_edit(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError("剪辑工作稿格式错误")
    if set(document) - {"format", "width", "height", "fps", "clips", "audio", "captions"}:
        raise ValueError("剪辑工作稿含未知字段")
    for key in ("width", "height"):
        if type(document.get(key)) is not int or not 64 <= document[key] <= 3840 or document[key] % 2:
            raise ValueError("画幅须为 64–3840 内的偶数")
    if type(document.get("fps")) is not int or not 12 <= document["fps"] <= 60:
        raise ValueError("帧率须为 12–60 的整数")
    if not isinstance(document.get("clips"), list) or len(document["clips"]) > 500:
        raise ValueError("剪辑最多容纳 500 段素材")
    ids, total = set(), 0
    for track in ("clips", "audio"):
        items = document.get(track, [])
        if not isinstance(items, list) or len(items) > 500:
            raise ValueError("音轨必须为不超过 500 段的列表")
        for clip in items:
            fields = {"id", "media_id", "in_frame", "out_frame", "volume", "muted", "shot_id", "at_frame", "fade_in", "fade_out", "purpose"}
            if not isinstance(clip, dict) or set(clip) - fields:
                raise ValueError("素材片段含未知字段")
            if not isinstance(clip.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", clip["id"]) or clip["id"] in ids:
                raise ValueError("每个片段须有独立且稳定的编号")
            ids.add(clip["id"])
            if not isinstance(clip.get("media_id"), str) or not clip["media_id"]:
                raise ValueError("片段必须引用已登记素材")
            if "purpose" in clip and (track != "audio" or clip["purpose"] not in {"music", "ambience", "sfx", "dialogue_dry"}):
                raise ValueError("音轨用途须为音乐、环境、音效或配音")
            for key in ("in_frame", "out_frame"):
                if type(clip.get(key)) is not int or clip[key] < 0:
                    raise ValueError("裁剪边界必须为非负整数帧")
            duration = clip["out_frame"] - clip["in_frame"]
            if duration <= 0:
                raise ValueError("片段结束帧须晚于起始帧")
            if type(clip.get("muted", False)) is not bool:
                raise ValueError("原声开关必须为布尔值")
            volume = clip.get("volume", 1)
            if type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 4:
                raise ValueError("音量须在 0–4 之间")
            for key in ("at_frame", "fade_in", "fade_out"):
                if type(clip.get(key, 0)) is not int or clip.get(key, 0) < 0:
                    raise ValueError("音轨位置和淡入淡出须为非负整数帧")
            if clip.get("fade_in", 0) + clip.get("fade_out", 0) > duration:
                raise ValueError("淡入淡出不能超过片段长度")
            if track == "clips":
                total += duration
    if total > document["fps"] * 3600:
        raise ValueError("单次剪辑最长一小时")
    captions = document.get("captions", [])
    if not isinstance(captions, list) or len(captions) > 5000:
        raise ValueError("字幕须为不超过 5000 条的列表")
    for caption in captions:
        if not isinstance(caption, dict) or set(caption) != {"start_frame", "end_frame", "text"}:
            raise ValueError("字幕需要起止帧和正文")
        a, b = caption["start_frame"], caption["end_frame"]
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= total:
            raise ValueError("字幕区间须位于当前成片内")
        if not isinstance(caption["text"], str) or not caption["text"].strip() or len(caption["text"]) > 2000:
            raise ValueError("字幕正文为空或过长")
    return total


def edit_operation(document, operation):
    """Explicit editing commands never alter the source media bytes."""
    result = copy.deepcopy(document)
    clips = result["clips"]
    action, clip_id = operation.get("action"), operation.get("clip_id")
    index = next((i for i, item in enumerate(clips) if item["id"] == clip_id), None)
    if index is None:
        raise ValueError("所选片段已不存在")
    if action == "trim":
        clips[index].update(in_frame=operation.get("in_frame"), out_frame=operation.get("out_frame"))
    elif action == "split":
        frame = operation.get("frame")
        if type(frame) is not int or not clips[index]["in_frame"] < frame < clips[index]["out_frame"]:
            raise ValueError("分割点须位于片段内部")
        right = dict(clips[index], id=operation.get("new_id"), in_frame=frame)
        clips[index]["out_frame"] = frame
        clips.insert(index + 1, right)
    elif action == "move":
        target = operation.get("index")
        if type(target) is not int or not 0 <= target < len(clips):
            raise ValueError("片段目标位置无效")
        clips.insert(target, clips.pop(index))
    elif action == "remove":
        clips.pop(index)
    else:
        raise ValueError("不支持的剪辑操作")
    validate_edit(result)
    return result


class EditRenderCancelled(Exception):
    """Local process stopped; the fenced repository decides final job status."""


def _run(args, *, cwd=None, timeout=600, cancelled=None):
    if cancelled and cancelled():raise EditRenderCancelled('单次合成已取消')
    process=subprocess.Popen(args,cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+timeout
    try:
        while True:
            if cancelled and cancelled():raise EditRenderCancelled('单次合成已取消')
            remaining=deadline-time.monotonic()
            if remaining<=0:raise subprocess.TimeoutExpired(args,timeout)
            try:
                out,err=process.communicate(timeout=min(.25,remaining));break
            except subprocess.TimeoutExpired:continue
        if process.returncode:raise ValueError('本地合成失败：'+err.decode('utf-8',errors='replace')[-1200:])
        return out
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill();process.communicate(timeout=1)
        raise


def _probe(path,cancelled=None):
    return json.loads(_run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],cancelled=cancelled))


class FirstCutRenderer:
    def capabilities(self):
        available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        return {"available": available, "recipe": RECIPE,
                "reason": None if available else "需要本机 FFmpeg 和 ffprobe 才能合成工作稿。"}

    def render(self, document, inputs, directory, *, cancelled=None):
        total = validate_edit(document)
        if not total:
            raise ValueError("先向时间线加入视频或图片")
        if not self.capabilities()["available"]:
            raise ValueError(self.capabilities()["reason"])
        directory = Path(directory)
        fps, width, height = (document[k] for k in ("fps", "width", "height"))
        recipe, normalized = [], []
        for index, clip in enumerate(document["clips"]):
            source = inputs[clip["id"]]
            path, modality = source["path"], source["modality"]
            start, duration = clip["in_frame"] / fps, (clip["out_frame"] - clip["in_frame"]) / fps
            probe = _probe(path,cancelled)
            streams = probe.get("streams", [])
            if modality == "video" and float(probe["format"].get("duration", 0)) + 1 / fps < start + duration:
                raise ValueError("裁剪区间超过源视频长度：" + clip["id"])
            target = directory / ("clip-%04d.mp4" % index)
            args = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
            if modality == "image":
                args += ["-loop", "1", "-framerate", str(fps)]
            else:
                args += ["-ss", str(start)]
            args += ["-i", str(path)]
            has_audio = modality == "video" and any(s["codec_type"] == "audio" for s in streams) and not clip.get("muted")
            if not has_audio:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            args += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf",
                     f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}",
                     "-af", f"aresample=48000,volume={clip.get('volume', 1)}", "-ac", "2", "-c:v", "libx264",
                     "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(duration), "-movflags", "+faststart", str(target)]
            _run(args,cancelled=cancelled)
            normalized.append(target)
            recipe.append({"clip_id": clip["id"], "in_frame": clip["in_frame"], "out_frame": clip["out_frame"], "modality": modality})
        (directory / "concat.txt").write_text("\n".join("file '" + p.name + "'" for p in normalized) + "\n")
        master = directory / "master.mp4"
        _run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "1", "-i", "concat.txt", "-c", "copy", str(master)], cwd=directory,cancelled=cancelled)
        audio = [item for item in document.get("audio", []) if not item.get("muted")]
        if audio:
            args = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(master)]
            filters, labels = [], ["[0:a:0]"]
            for i, clip in enumerate(audio, 1):
                path = inputs[clip["id"]]["path"]
                probe = _probe(path,cancelled)
                if not any(s["codec_type"] == "audio" for s in probe["streams"]):
                    raise ValueError("音轨素材没有可解码声音")
                if float(probe["format"].get("duration", 0)) + 1 / fps < clip["out_frame"] / fps:
                    raise ValueError("音轨裁剪区间超过源音频长度")
                args += ["-i", str(path)]
                length = (clip["out_frame"] - clip["in_frame"]) / fps
                chain = f"[{i}:a:0]atrim=start={clip['in_frame']/fps}:end={clip['out_frame']/fps},asetpts=PTS-STARTPTS,volume={clip.get('volume', 1)}"
                if clip.get("fade_in"):
                    chain += f",afade=t=in:d={clip['fade_in']/fps}"
                if clip.get("fade_out"):
                    fade = clip["fade_out"] / fps
                    chain += f",afade=t=out:st={max(0,length-fade)}:d={fade}"
                chain += f",adelay={round(clip.get('at_frame', 0)*1000/fps)}:all=1[a{i}]"
                filters.append(chain); labels.append(f"[a{i}]")
            filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95:latency=1[mix]")
            mixed = directory / "mixed.mp4"
            _run(args + ["-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-t", str(total / fps), str(mixed)],cancelled=cancelled)
            master = mixed
        captions = document.get("captions", [])
        subtitle_receipt = {}
        if captions:
            from vsc.post import subtitle_burn, subtitles
            style, _ = subtitles.resolve_style(overrides={"font_size": max(12, round(width / 18)), "stroke_width": max(1, width / 720)})
            if not style.get("font") or not Path(style["font"]).is_file():
                raise ValueError("字幕合成需要已安装的 Noto Sans SC 字体，请先在工作区设置中安装字幕字体。")
            job_path = directory / "caption-layout.json"
            job_path.write_text(json.dumps({"directory": str(directory), "width": width, "height": height,
                "cues": [{"start": c["start_frame"] / fps, "end": c["end_frame"] / fps, "text": c["text"]} for c in captions],
                "style": style}, ensure_ascii=False), encoding="utf-8")
            if cancelled and cancelled():raise EditRenderCancelled('单次合成已取消')
            subtitle_burn.render(job_path)
            if cancelled and cancelled():raise EditRenderCancelled('单次合成已取消')
            rendered = json.loads(job_path.read_text("utf-8"))
            captioned = directory / "captioned.mp4"
            command = subtitle_burn.overlay_command(master, rendered["cues"], captioned)
            command[1:1] = ["-nostdin", "-threads", "1", "-filter_complex_threads", "1"]
            _run(command,cancelled=cancelled)
            import hashlib
            subtitle_receipt = {"subtitle_checks": rendered["subtitle_checks"],
                                "font_sha256": hashlib.sha256(Path(style["font"]).read_bytes()).hexdigest()}
            master = captioned
        output = directory / "first-cut.mp4"
        shutil.copyfile(master, output)
        probe = _probe(output,cancelled)
        actual = float(probe["format"]["duration"])
        if abs(actual - total / fps) > max(.15, len(normalized) / fps):
            raise ValueError("合成时长与固定剪辑稿不符")
        _run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", str(output),
              "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],cancelled=cancelled)
        return output, {"recipe": RECIPE, "duration_ms": round(actual * 1000), "frames": total,
                        "full_decode": "passed", **subtitle_receipt,
                        "clips": recipe, "caption_count": len(captions), "draft": True,
                        "dynamic_frames": sum(c["out_frame"] - c["in_frame"] for c in recipe if c["modality"] == "video")}
