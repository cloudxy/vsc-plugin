"""User-facing recoverable organization; physical deletion is intentionally absent."""


class MediaRecycleService:
    def _recycle(self):
        from vsc.adapters.persistence.postgres.media_recycle import MediaRecycleRepository
        return MediaRecycleRepository(self.store)

    def list_recycled_media(self, project_id, **filters):
        return self._recycle().read(project_id, **filters)

    def preview_media_recycle(self, project_id, media_ids):
        return self._recycle().preview(project_id, media_ids)

    def recycle_media(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self._recycle().act(project_id, payload, **kw)
