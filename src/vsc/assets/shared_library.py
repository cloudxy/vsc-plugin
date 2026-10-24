"""Workspace library: fixed bytes and descriptions, project-local decisions.

The shared module owns publication/import and atomic project adoption. A search
hit never implies a human choice. Existing resource consumers remain authoritative.
"""
from vsc.assets.resource_service import ResourceError, required


class SharedLibraryService:
    def _library(self):
        from vsc.adapters.persistence.postgres.shared_library import SharedLibraryRepository
        return SharedLibraryRepository(self.store, self.storage)

    def search_library(self, query="", category=None, offset=0, limit=24, include_retired=False):
        return self._library().search(query, category, offset, limit, include_retired)

    def get_library_version(self, version_id):
        return self._library().detail(version_id)

    def library_member_content(self, version_id, member_key):
        return self._library().content(version_id, member_key)

    def publish_library(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self._library().publish(project_id, payload, **kw)

    def import_library(self, payload, actor=None):
        self._actor(actor)
        if not isinstance(payload, dict) or "actor" in payload:
            raise ResourceError("库导入需要对象，身份由会话提供", "invalid_payload")
        if self.storage is None:
            raise ResourceError("库导入需要受控存储", "storage_unavailable")
        prepared = dict(payload)
        members = required(payload, "members")
        if (not isinstance(members, list) or len(members) > 32
                or not members and not payload.get("specification")):
            raise ResourceError("导入需要媒体成员或明确的独立规格", "invalid_library_members")
        prepared["members"] = [dict(self.storage.commit_upload(required(item, "staged_upload")),
            member_key=required(item, "member_key"), role=item.get("role", "reference")) for item in members]
        return self._library().import_entry(prepared, actor)

    def preview_library_use(self, project_id, payload):
        return self._library().preview_use(project_id, payload)

    def use_library(self, project_id, payload, **kw):
        self._validate_write(payload, **kw)
        return self._library().use(project_id, payload, **kw)

    def retire_library(self, entry_id, payload, actor=None):
        self._actor(actor)
        return self._library().retire(entry_id, payload, actor)

    def legacy_library_migration(self, root=None):
        from vsc.assets.library_migration import LegacyLibraryMigration
        return LegacyLibraryMigration(self, root)
