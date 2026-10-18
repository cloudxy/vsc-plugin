"""Shared preview, human-review proposal and explicit enqueue use cases."""
from vsc.assets.resource_service import required


class LocalProduction:
    def __init__(self, service):
        self.service = service

    def preview(self, project_id, payload):
        from vsc.adapters.persistence.postgres.local_edits import preview
        return preview(self.service.store, project_id, payload)

    def options(self, project_id, action, entity_id):
        from vsc.adapters.persistence.postgres.local_edits import options
        return options(self.service.store, project_id, action, entity_id)

    def propose(self, project_id, payload, **kw):
        from vsc.adapters.persistence.postgres.local_edits import propose
        self.service._validate_write(payload, **kw)
        return propose(self.service.store, project_id, payload, **kw)

    def enqueue(self, project_id, payload, **kw):
        from vsc.adapters.persistence.postgres.local_edits import enqueue
        self.service._validate_write(payload, **kw)
        required(payload, "artifact_id")
        return enqueue(self.service.store, project_id, payload, self.service._preflight_generation_job, **kw)
