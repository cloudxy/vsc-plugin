"""Read fixed source evidence without changing its bytes, hash or approval state."""
import hashlib
from sqlalchemy import and_, select

from vsc.assets.resource_service import ResourceError
from . import schema as S
from .values import clean


class SourceRepository:
    def get_source_version(self, project_id, source_id):
        with self.engine.connect() as connection:
            project = self._project(connection, project_id)
            source = self._one(connection, S.source_versions, project["id"], source_id)
            raw = bytes(source["document"])
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ResourceError("登记来源证据摘要不符，停止读取", "source_sha_mismatch", 409)
            try:
                source["content"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                source["content"] = None
            source.pop("document")
            source["content_size_bytes"] = len(raw)
            source["untrusted_material"] = True
            source["media"] = [dict(row) for row in connection.execute(select(S.media_items.c.id,
                S.media_items.c.name, S.media_items.c.modality, S.media_blobs.c.sha256, S.media_blobs.c.mime_type,
                S.media_blobs.c.size_bytes).select_from(S.media_sources.join(S.media_items,
                    and_(S.media_sources.c.project_id == S.media_items.c.project_id,
                         S.media_sources.c.media_id == S.media_items.c.id)).join(S.media_blobs,
                         S.media_items.c.blob_id == S.media_blobs.c.id)).where(S.media_sources.c.project_id == project["id"],
                         S.media_sources.c.source_id == source["id"])).mappings()]
            source["revision"] = project["revision"]
            return clean(source)
