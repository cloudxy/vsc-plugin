"""Content addressed local storage with durable staging and verified reads."""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import tempfile

from vsc.assets.resource_service import ResourceError


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class LocalStorage:
    def __init__(self, root, probe=None, max_bytes=1024 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.staging = self.root / ".staging"
        if self.staging.is_symlink():
            raise ResourceError("暂存目录不能是符号链接", "unsafe_location")
        self.staging.mkdir(parents=True, exist_ok=True)
        self.probe = probe
        self.max_bytes = max_bytes

    def resolve(self, object_key):
        if not isinstance(object_key, str) or "\\" in object_key or Path(object_key).is_absolute() or ".." in Path(object_key).parts:
            raise ResourceError("对象键越过受控存储", "unsafe_location")
        candidate = self.root / object_key
        cursor = candidate
        while cursor != self.root:
            if cursor.is_symlink():
                raise ResourceError("存储路径不能包含符号链接", "unsafe_location")
            cursor = cursor.parent
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise ResourceError("对象路径越界", "unsafe_location")
        return resolved

    def stage_upload(self, stream, filename="upload.bin"):
        """Caller supplies a binary stream, never an arbitrary server path."""
        token = secrets.token_hex(24)
        target = self.staging / (token + ".bytes")
        size, digest = 0, hashlib.sha256()
        try:
            with target.open("xb") as output:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    if size > self.max_bytes:
                        raise ResourceError("上传超过存储大小限制", "upload_too_large")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            record = {"filename": Path(filename).name, "size_bytes": size, "sha256": digest.hexdigest()}
            (self.staging / (token + ".json")).write_text(json.dumps(record), "utf-8")
            return {"staged_upload": token, **record}
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def _metadata(self, path, record):
        filename = record["filename"]
        suffix = Path(filename).suffix.lower()
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with path.open("rb") as header_file:
            signature = header_file.read(32)
        if signature.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif signature.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif signature.startswith((b"GIF87a", b"GIF89a")):
            mime = "image/gif"
        elif signature.startswith(b"RIFF") and signature[8:12] == b"WAVE":
            mime = "audio/wav"
        elif signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
            mime = "image/webp"
        elif signature[4:8] == b"ftyp":
            mime = "video/mp4"
        elif signature.startswith(b"%PDF-"):
            mime = "application/pdf"
        metadata = {"name": filename, "mime_type": mime, "modality": "document", "probe": {}}
        if mime.startswith(("image/", "audio/", "video/")) and suffix != ".svg":
            if self.probe is None:
                from vsc.adapters.media.qa import LocalProbeAdapter
                probe = LocalProbeAdapter()
            else:
                probe = self.probe
            raw = probe.probe(path)
            raw = {key: value for key, value in raw.items() if key != "path"}
            streams = raw.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            with path.open("rb") as header_file:
                header = header_file.read(32)
            image_mime = ("image/png" if header.startswith(b"\x89PNG\r\n\x1a\n") else
                          "image/jpeg" if header.startswith(b"\xff\xd8\xff") else
                          "image/gif" if header.startswith((b"GIF87a", b"GIF89a")) else
                          "image/webp" if header.startswith(b"RIFF") and header[8:12] == b"WEBP" else None)
            if image_mime and video:
                modality = "image"
                metadata["mime_type"] = image_mime
            elif video:
                modality = "video"
                metadata["mime_type"] = "video/mp4" if header[4:8] == b"ftyp" else mime if mime.startswith("video/") else "application/octet-stream"
            elif audio:
                modality = "audio"
                metadata["mime_type"] = "audio/wav" if header.startswith(b"RIFF") and header[8:12] == b"WAVE" else mime if mime.startswith("audio/") else "application/octet-stream"
            else:
                raise ResourceError("上传不是可解码媒体", "invalid_media")
            metadata.update(modality=modality, probe=raw)
            if video:
                metadata.update(width=video.get("width"), height=video.get("height"))
            if audio and audio.get("sample_rate"):
                metadata["sample_rate"] = int(audio["sample_rate"])
            duration = raw.get("duration_seconds")
            if duration is not None:
                metadata["duration_ms"] = round(duration * 1000)
        elif suffix in {".txt", ".md", ".json", ".srt", ".vtt", ".csv"}:
            try:
                path.read_text("utf-8")
            except UnicodeError:
                # Preserve encoded source files without pretending they are a
                # UTF-8 preview. The source extractor owns decoding and errors.
                metadata.update(modality="document", mime_type="application/octet-stream")
            else:
                metadata.update(modality="text", mime_type="text/plain")
        return metadata

    def commit_upload(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{48}", token):
            raise ResourceError("暂存凭据无效", "invalid_upload")
        record_path = self.staging / (token + ".json")
        if not record_path.is_file() or record_path.is_symlink():
            raise ResourceError("暂存上传不存在", "invalid_upload")
        record = json.loads(record_path.read_text("utf-8"))
        sha = record["sha256"]
        key = "blobs/" + sha[:2] + "/" + sha
        staged = self.staging / (token + ".bytes")
        target = self.resolve(key)
        source = staged if staged.is_file() else target
        if source.is_symlink() or not source.is_file() or file_sha(source) != sha or source.stat().st_size != record["size_bytes"]:
            raise ResourceError("暂存字节缺失或摘要改变", "upload_changed")
        metadata = self._metadata(source, record)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self.verify(key, sha)
            staged.unlink(missing_ok=True)
        else:
            os.replace(staged, target)
        # Keep the receipt for safe retry after a database failure. Orphan cleanup
        # is an explicit maintenance operation with a grace period, never a UI delete.
        return {**metadata, "sha256": sha, "size_bytes": record["size_bytes"],
                "storage": "local", "object_key": key}

    def verify(self, object_key, expected_sha):
        path = self.resolve(object_key)
        if not path.is_file() or file_sha(path) != expected_sha:
            raise ResourceError("素材字节缺失或摘要不符", "media_unavailable")
        return path

    def read(self, object_key, expected_sha):
        return self.verify(object_key, expected_sha).read_bytes()
