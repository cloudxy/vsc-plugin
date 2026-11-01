"""Resumable byte transport inside the existing controlled staging directory."""
import fcntl
from pathlib import Path
import re

from vsc.assets.resource_service import Conflict, ResourceError


class ImportUpload:
    MAX_CHUNK = 8 * 1024 * 1024

    def __init__(self, storage):
        self.storage = storage

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{48}", key):
            raise ResourceError("上传会话无效", "invalid_import_upload")
        path = self.storage.staging / ("import-"+key+".part")
        if path.is_symlink():
            raise ResourceError("上传暂存路径无效", "unsafe_location")
        return path

    def progress(self, key):
        path = self.path(key)
        return path.stat().st_size if path.is_file() else 0

    def append(self, key, offset, content, expected_size, filename):
        if type(offset) is not int or offset < 0 or len(content) > self.MAX_CHUNK:
            raise ResourceError("分片起点或大小无效", "invalid_import_chunk")
        path = self.path(key)
        with path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0, 2)
            current = stream.tell()
            # A repeated acknowledged range is compared, never appended twice.
            if offset < current and offset + len(content) <= current:
                stream.seek(offset)
                if stream.read(len(content)) != content:
                    raise Conflict("同一上传区间的字节已改变", "import_chunk_changed")
            elif offset != current:
                raise Conflict("上传已接收的字节位置改变，请读回后续传", "import_offset_conflict")
            elif current + len(content) > expected_size:
                raise ResourceError("文件大于固定导入清单中的大小", "import_size_mismatch")
            else:
                import os
                stream.seek(0, 2); stream.write(content); stream.flush(); os.fsync(stream.fileno())
                current += len(content)
            if current == expected_size:
                stream.seek(0)
                staged = self.storage.stage_upload(stream, filename)
                return {"uploaded_bytes": current, "metadata": self.storage.commit_upload(staged["staged_upload"])}
            return {"uploaded_bytes": current, "metadata": None}
