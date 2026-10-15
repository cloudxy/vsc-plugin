"""Durable preview execution. Derivatives never become approved production media."""
from pathlib import Path
import shutil
import subprocess
import tempfile

from vsc.assets.resource_service import ResourceError

RECIPE_VERSION = "vsc-preview-v1"
PURPOSES = {"thumbnail", "poster", "waveform", "document_pages", "proxy_video"}


class PreviewConverter:
    def __init__(self, runner=None, timeout=120, ffmpeg=None, pdftoppm=None):
        self.runner = runner or subprocess.run
        self.timeout = timeout
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.pdftoppm = pdftoppm or shutil.which("pdftoppm")

    def capabilities(self):
        return {"thumbnail": bool(self.ffmpeg), "poster": bool(self.ffmpeg), "waveform": bool(self.ffmpeg),
                "proxy_video": bool(self.ffmpeg), "document_pages": bool(self.pdftoppm), "recipe_version": RECIPE_VERSION}

    def _run(self, args):
        try:
            result = self.runner(args, capture_output=True, text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ResourceError("预览工具不可用或转换超时", "preview_tool_failed") from error
        if result.returncode:
            raise ResourceError("预览转换失败；原文件和既有用途选择保留", "preview_conversion_failed")
        return result

    def convert(self, path, media, purpose, output_directory, recipe_version=RECIPE_VERSION):
        path, output_directory = Path(path), Path(output_directory)
        if recipe_version != RECIPE_VERSION:
            raise ResourceError("未安装此预览配方版本", "preview_recipe_unavailable")
        if purpose not in PURPOSES:
            raise ResourceError("未知预览用途", "preview_purpose")
        expected = {"thumbnail": "image", "poster": "video", "waveform": "audio", "proxy_video": "video", "document_pages": "document"}[purpose]
        if media.get("modality") != expected or (purpose == "document_pages" and media.get("mime_type") != "application/pdf"):
            raise ResourceError("该素材格式不适用于所选预览用途", "preview_format")
        tool = self.pdftoppm if purpose == "document_pages" else self.ffmpeg
        if not tool:
            raise ResourceError("未安装对应预览转换器；可查看元数据并下载原文件", "preview_tool_unavailable")
        parameters = {"purpose": purpose}
        if purpose == "document_pages":
            stem = output_directory / "page-1"
            self._run([tool, "-f", "1", "-singlefile", "-scale-to", "1280", "-png", str(path), str(stem)])
            output = stem.with_suffix(".png")
            parameters.update(page=1, max_dimension=1280)
        else:
            output = output_directory / ("proxy.mp4" if purpose == "proxy_video" else "preview.png")
            args = [tool, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path)]
            if purpose == "waveform":
                args.extend(["-filter_complex", "aformat=channel_layouts=mono,showwavespic=s=1200x240:colors=0x17625a", "-frames:v", "1", "-c:v", "png", "-threads", "1"])
                parameters.update(width=1200, height=240, channels="mono_mix")
            elif purpose == "proxy_video":
                args.extend(["-vf", "scale=w='min(1080,iw)':h=-2", "-r", "24", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-threads", "1"])
                parameters.update(max_width=1080, fps=24, video_codec="h264", audio_codec="aac")
            else:
                width = 640 if purpose == "thumbnail" else 1080
                args.extend(["-vf", "scale=w='min(%d,iw)':h=-2" % width, "-frames:v", "1", "-an", "-c:v", "png", "-threads", "1"])
                parameters.update(max_width=width, frame=0)
            self._run(args + [str(output)])
        if not output.is_file() or not output.stat().st_size:
            raise ResourceError("转换器未产生可用预览字节", "preview_output_missing")
        version_args = [tool, "-v"] if purpose == "document_pages" else [tool, "-version"]
        version = self._run(version_args)
        tool_version = ((version.stdout or version.stderr).splitlines() or ["unknown"])[0][:500]
        return output, {"tool": Path(tool).name, "tool_version": tool_version, "recipe_version": recipe_version,
                        "purpose": purpose, "source_sha256": media["sha256"], "parameters": parameters}


class PreviewWorker:
    def __init__(self, store, storage, converter=None):
        self.store, self.storage = store, storage
        self.converter = converter or PreviewConverter()

    def run_once(self, project_id=None, retry_failed=False, stale_after_seconds=300):
        job = self.store.claim_preview_job(project_id=project_id, retry_failed=retry_failed,
                                           stale_after_seconds=stale_after_seconds)
        if job is None:
            return None
        try:
            media = self.store.get_media(job["project_id"], job["media_id"])
            location = next((row for row in media["locations"] if row["storage"] == "local" and row.get("available", True)), None)
            if location is None:
                raise ResourceError("预览执行器尚无该受控存储适配器", "preview_storage_unavailable")
            source = self.storage.verify(location["object_key"], media["sha256"])
            with tempfile.TemporaryDirectory(prefix="vsc-preview-") as temporary:
                output, evidence = self.converter.convert(source, media, job["purpose"], temporary, job["recipe_version"])
                with output.open("rb") as stream:
                    staged = self.storage.stage_upload(stream, output.name)
                verified = self.storage.commit_upload(staged["staged_upload"])
                verified.setdefault("probe", {})["preview"] = evidence
                return self.store.finish_preview_job(job["project_id"], job["id"], job["attempt"], verified)
        except Exception as error:
            # Store only safe, bounded diagnostics, not commands, paths or media contents.
            code = getattr(error, "code", type(error).__name__)
            message = getattr(error, "message", "预览执行失败")
            return self.store.fail_preview_job(job["project_id"], job["id"], job["attempt"], str(code) + ": " + message)

    def run_pending(self, project_id=None, maximum=20, retry_failed=False, stale_after_seconds=300):
        if not isinstance(maximum, int) or not 1 <= maximum <= 1000:
            raise ResourceError("单次预览批量数量须为 1–1000", "preview_batch")
        result = []
        for _ in range(maximum):
            job = self.run_once(project_id=project_id, retry_failed=retry_failed, stale_after_seconds=stale_after_seconds)
            if job is None:
                break
            result.append(job)
            # Failed jobs need a new explicit retry invocation, not an immediate hot loop.
            if job.get("status") == "failed" and retry_failed:
                break
        return result
