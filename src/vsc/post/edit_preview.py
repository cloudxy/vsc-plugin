"""Restricted subtitle previews over a verified, already composed clean master.

This executor has no model, shell, approval or provider API. Its only edit is the
fixed caption layout; all subprocess arguments come from this module.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from vsc.assets.resource_service import ResourceError
from vsc.post import remotion_plan as RP, subtitle_burn as SB, subtitles

RECIPE_VERSION = "vsc-caption-edit-preview/v1"
OPERATIONS = ("move_up", "move_down", "top", "center", "bottom")


def position_edit(document, caption_id, operation, body="", frame_range=None):
    """Interpret only a small position vocabulary; never evaluate free prose."""
    plan = RP.render_plan(document)
    cues = [s for s in plan.get("segments", []) if s.get("kind") == "caption"]
    if caption_id is None and frame_range:
        cues = [s for s in cues if s["from_frame"] == frame_range["from_frame"]
                and s["duration_in_frames"] == frame_range["duration_in_frames"]]
    else:
        cues = [s for s in cues if s["id"] == caption_id]
    if len(cues) != 1:
        raise ResourceError("请在当前样片选择一条字幕，再提交位置修改。", "caption_target_ambiguous")
    if operation is None:
        matches = []
        for candidate, words in (("move_up", ("上移", "往上", "向上")), ("move_down", ("下移", "往下", "向下")),
                                 ("top", ("顶部", "顶端")), ("center", ("居中", "中间")), ("bottom", ("底部", "底端"))):
            if any(word in body for word in words):
                matches.append(candidate)
        if len(matches) != 1:
            raise ResourceError("当前自动编辑支持字幕上移、下移、顶部、居中或底部；请明确一个方向。", "caption_operation_ambiguous")
        operation = matches[0]
    if operation not in OPERATIONS:
        raise ResourceError("当前自动编辑只支持字幕位置调整。", "caption_operation_unavailable")
    cue = cues[0]
    style = subtitles.caption_style({**subtitles.DEFAULT_STYLE, **plan.get("subtitle_style", {})}, cue.get("subtitle_style"))
    if operation in {"move_up", "move_down"}:
        position = style["position"]
        point = style.get("custom_position", 50) if position == "custom" else {"top": 5, "center": 50, "bottom": 95}[position]
        layout = {"position": "custom", "custom_position": max(5, min(95, point + (-10 if operation == "move_up" else 10)))}
    else:
        layout = {"position": operation}
    edited = RP.edit_caption_position(document, caption_id=cue["id"], expected_sha256=RP.document_sha256(document),
                                     layout=layout, frame_range=frame_range)
    return {**edited, "caption_id": cue["id"], "operation": operation, "layout": layout}


class EditPreviewConverter:
    def __init__(self, timeout=180):
        self.timeout = timeout
        self.ffmpeg, self.ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")

    def _run(self, args):
        # ffmpeg cannot inherit application/DB/provider credentials.
        environment = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "LC_ALL") if key in os.environ}
        try:
            result = subprocess.run(args, capture_output=True, timeout=self.timeout, check=False, env=environment)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ResourceError("本地字幕合成不可用或超时。", "edit_preview_tool_failed") from error
        if result.returncode:
            raise ResourceError("本地字幕合成失败；原样片和已登记输入仍保留。", "edit_preview_conversion_failed")
        return result.stdout

    def capabilities(self):
        reason = None
        if not self.ffmpeg or not self.ffprobe:
            reason = "本机尚未安装 FFmpeg / ffprobe。"
        elif importlib.util.find_spec("PIL") is None:
            reason = "当前应用环境未安装 Pillow 字幕排版依赖。"
        version = ""
        if not reason:
            try:
                version = self._run([self.ffmpeg, "-version"]).decode().splitlines()[0][:500]
            except ResourceError:
                reason = "本地 FFmpeg 无法执行。"
        return {"available": reason is None, "reason": reason, "recipe_version": RECIPE_VERSION, "tool_version": version}

    def convert(self, job, master, font, directory):
        capability = self.capabilities()
        if not capability["available"] or job["recipe_version"] != RECIPE_VERSION or job["tool_version"] != capability["tool_version"]:
            raise ResourceError("已固定的字幕预览配方或工具版本不可用，请重新评估原意见。", "edit_preview_recipe_changed")
        document = job["document"]
        plan = RP.render_plan(document)
        width, height, duration = SB.probe_video(master)
        composition = plan["composition"]
        fps = RP.frame_rate(composition["fps"])
        if (width, height) != (composition["width"], composition["height"]) or abs(duration - composition["duration_in_frames"] / fps) > 1 / fps:
            raise ResourceError("无字幕底片的画幅、时长与固定计划不一致。", "edit_preview_master_mismatch")
        style, _ = subtitles.resolve_style(overrides={**plan.get("subtitle_style", {}), "font": str(font)})
        # Reuse the same validation, measured timecode and Pillow layout code as
        # the formal subtitle consumer, without invoking uv/network installation.
        compiled, _ = RP.compile_subtitles(plan, style, require_font=True, media_root=directory, local_layout=True)
        segments = sorted((s for s in plan["segments"] if s["kind"] in {"caption", "text"}), key=lambda s: s["from_frame"])
        cues = [{"start": begin, "end": end, "text": text, **({"subtitle_style": segment["subtitle_style"]}
                if "subtitle_style" in segment else {})} for (begin, end, text), segment in zip(compiled["cues"], segments)]
        directory = Path(directory)
        job_path = directory / "caption-layout.json"
        job_path.write_text(json.dumps({"directory": str(directory), "width": width, "height": height,
            "cues": cues, "style": style, "subtitle_checks": compiled["checks"]}, ensure_ascii=False), "utf-8")
        SB.render(job_path)
        rendered = json.loads(job_path.read_text("utf-8"))
        full = directory / "captioned.mp4"
        command = SB.overlay_command(master, rendered["cues"], full)
        command[0] = self.ffmpeg
        command[1:1] = ["-nostdin", "-threads", "1", "-filter_complex_threads", "1"]
        self._run(command)
        start, end = job["start_frame"], job["end_frame"]
        output = directory / "edit-preview.mp4"
        # Audio is explicitly trimmed on the same timeline; AAC may be reencoded
        # for browser playback. Never substitute another shot or synthetic sound.
        probe = json.loads(self._run([self.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(master)]))
        has_audio = any(s.get("codec_type") == "audio" for s in probe["streams"])
        args = [self.ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(full), "-vf",
                f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS", "-map", "0:v:0",
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "1"]
        if has_audio:
            args += ["-map", "0:a:0", "-af", f"atrim=start={start/fps:.9f}:end={end/fps:.9f},asetpts=PTS-STARTPTS",
                     "-c:a", "aac", "-b:a", "192k"]
        args += ["-movflags", "+faststart", str(output)]
        self._run(args)
        self._run([self.ffmpeg, "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"])
        _, _, actual_duration = SB.probe_video(output)
        if abs(actual_duration - (end-start)/fps) > max(0.06, 1/fps):
            raise ResourceError("字幕预览实际时长与固定区间不一致。", "edit_preview_duration_mismatch")
        receipt = {"recipe_version": RECIPE_VERSION, "tool_version": capability["tool_version"],
                   "source_sha256": job["master_sha256"], "font_sha256": job["font_sha256"],
                   "draft_sha256": job["draft_sha256"], "start_frame": start, "end_frame": end,
                   "audio": "same_master_trimmed_aac" if has_audio else "source_has_no_audio",
                   "subtitle_checks": rendered["subtitle_checks"], "full_decode": "passed",
                   "adoption": "unapproved_edit_preview"}
        return output, receipt


class EditPreviewWorker:
    def __init__(self, store, storage, converter=None, *, lease_seconds=300, poll_seconds=1):
        from vsc.adapters.persistence.postgres.edit_preview_store import EditPreviewRepository
        self.store, self.storage, self.repository = store, storage, EditPreviewRepository(store)
        self.converter = converter or EditPreviewConverter()
        self.lease_seconds, self.poll_seconds = lease_seconds, poll_seconds
        self.worker_id = "caption-preview-" + uuid.uuid4().hex
        self._stop = threading.Event()
        self._lifecycle = threading.RLock()
        self._thread = None
        self._last_poll = None
        self._error = None

    def status(self):
        return {"running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()),
                "finishing": bool(self._thread and self._thread.is_alive() and self._stop.is_set()), "last_poll": self._last_poll,
                "error": self._error, **self.converter.capabilities()}

    def start(self):
        with self._lifecycle:
            self._stop.clear()
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name=self.worker_id, daemon=True)
                self._thread.start()
        return self

    def stop(self):
        with self._lifecycle:
            self._stop.set()
            thread = self._thread
        if thread:
            thread.join(timeout=5)

    def _loop(self):
        try:
            while not self._stop.is_set():
                try:
                    self._last_poll = time.time()
                    result = self.run_once()
                    self._error = None
                except Exception as error:
                    result = None
                    self._error = getattr(error, "code", type(error).__name__)
                if result is None:
                    self._stop.wait(self.poll_seconds)
        finally:
            with self._lifecycle:
                self._thread = None
                # Resume may arrive after the loop chose to exit but before this
                # finally block. Honor that request without two active workers.
                if not self._stop.is_set():
                    self.start()

    def run_once(self, project_id=None):
        if not self.converter.capabilities()["available"]:
            return None
        job = self.repository.claim(self.worker_id, project_id, self.lease_seconds)
        if job is None:
            return None
        pulse_stop = threading.Event()
        def heartbeat():
            while not pulse_stop.wait(max(.1, self.lease_seconds / 3)):
                try:
                    self.repository.heartbeat(job["project_id"], job["id"], self.worker_id, job["attempt"], self.lease_seconds)
                except Exception:
                    return
        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            job = self.repository.prepare(job, self.worker_id)
            # A saved output is authoritative recovery evidence. A restart
            # returns it; it never burns the same completed attempt again.
            if not job.get("output"):
                paths, audio_paths = {}, []
                for item in job["inputs"]:
                    media = self.store.get_media(job["project_id"], item["media_id"])
                    location = next((l for l in media["locations"] if l["storage"] == "local" and l.get("available", True)), None)
                    if location is None:
                        raise ResourceError("固定底片或字体缺少受控本地副本。", "edit_preview_input_missing")
                    path = self.storage.verify(location["object_key"], item["blob_sha256"])
                    if item["role"] == "subtitle_audio":
                        audio_paths.append((item, path))
                    else:
                        paths[item["role"]] = path
                with tempfile.TemporaryDirectory(prefix="vsc-caption-preview-") as directory:
                    for item, path in audio_paths:
                        target = Path(directory) / item["source_path"]
                        if not target.resolve().is_relative_to(Path(directory).resolve()):
                            raise ResourceError("字幕包音频路径越界。", "edit_preview_package_path")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                    output, receipt = self.converter.convert(job, paths["clean_master"], paths["subtitle_font"], directory)
                    with output.open("rb") as stream:
                        staged = self.storage.stage_upload(stream, output.name)
                    verified = self.storage.commit_upload(staged["staged_upload"])
                    self.repository.record_output(job, self.worker_id, verified, receipt)
            return self.repository.finish(job, self.worker_id)
        except Exception as error:
            return self.repository.fail(job, self.worker_id, error)
        finally:
            pulse_stop.set()
            pulse.join(timeout=1)
