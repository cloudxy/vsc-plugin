"""Scoped API credentials and local operations; no second identity or job queue."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from .schema_commerce import ENTITY_SCOPE_CHECK, PLATFORM_SCOPE_CHECK, make_scoped_table

SERVICE_OPERATIONS_IMMUTABLE = (
    "service_configuration_versions",
    "service_announcements",
    "service_requests",
    "service_request_events",
    "service_export_files",
    "service_api_calls",
    "service_api_call_jobs",
)


def declare_service_operations(metadata, project_table, ref, uid, stamp):
    def identity(name):
        return Column(name, UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT"), nullable=False)

    def platform_table(name, *columns):
        return make_scoped_table(metadata, uid, name, PLATFORM_SCOPE_CHECK, *columns)

    def entity_table(name, *columns):
        return make_scoped_table(metadata, uid, name, ENTITY_SCOPE_CHECK, *columns)

    configs = platform_table(
        "service_configuration_versions",
        Column("version", Integer, nullable=False),
        Column("document", JSONB, nullable=False),
        Column("sha256", Text, nullable=False),
        identity("created_by"),
        stamp(),
        CheckConstraint("version > 0", name="version"),
    )
    Index("uq_service_configuration_versions_platform_ver", configs.c.version, unique=True,
          postgresql_where=text("scope_kind = 'platform'"))
    Index("uq_service_configuration_versions_workspace_ver", configs.c.workspace_id, configs.c.version, unique=True,
          postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_service_configuration_versions_project_ver", configs.c.project_id, configs.c.version, unique=True,
          postgresql_where=text("scope_kind = 'project'"))
    Index("ix_service_configuration_versions_created_by", configs.c.created_by)

    announcements = platform_table(
        "service_announcements",
        Column("announcement_key", Text, nullable=False),
        Column("version", Integer, nullable=False),
        Column("title", Text, nullable=False),
        Column("body", Text, nullable=False),
        Column("status", Text, nullable=False),
        identity("created_by"),
        stamp(),
        CheckConstraint("status IN ('published','withdrawn') AND version > 0", name="status"),
    )
    Index("uq_service_announcements_platform_key_ver", announcements.c.announcement_key, announcements.c.version, unique=True,
          postgresql_where=text("scope_kind = 'platform'"))
    Index("uq_service_announcements_workspace_key_ver", announcements.c.workspace_id, announcements.c.announcement_key,
          announcements.c.version, unique=True, postgresql_where=text("scope_kind = 'workspace'"))
    Index("uq_service_announcements_project_key_ver", announcements.c.project_id, announcements.c.announcement_key,
          announcements.c.version, unique=True, postgresql_where=text("scope_kind = 'project'"))
    Index("ix_service_announcements_created_by", announcements.c.created_by)

    requests = entity_table(
        "service_requests",
        identity("requester_id"),
        Column("kind", Text, nullable=False),
        Column("title", Text, nullable=False),
        Column("body", Text, nullable=False),
        Column("contact", Text, nullable=False, server_default=""),
        Column("channel", Text, nullable=False),
        *ref("artifact_versions", "artifact_id", nullable=True),
        *ref("media_items", "media_id", nullable=True),
        Column("requested_fields", JSONB, nullable=False),
        Column("feedback_category", Text),
        stamp(),
        UniqueConstraint("id", "requester_id", name="uq_service_requests_id_requester_id"),
        CheckConstraint("project_id IS NOT NULL OR (artifact_id IS NULL AND media_id IS NULL)", name="project_attachments"),
        CheckConstraint("char_length(contact) <= 254", name="contact"),
        CheckConstraint(
            "feedback_category IS NULL OR (kind='feedback' AND feedback_category IN ('feature','quality','billing','ux','bug'))",
            name="feedback_category",
        ),
        CheckConstraint(
            "kind IN ('feedback','support','fcp','studio','production_service','distribution','account_close','personal_export')",
            name="kind",
        ),
    )
    Index("ix_service_requests_owner_kind_created", requests.c.requester_id, requests.c.scope_kind,
          requests.c.kind, requests.c.created_at.desc(), requests.c.id.desc())
    Index("ix_service_requests_manage_scope_created", requests.c.scope_kind,
          func.coalesce(requests.c.workspace_id, requests.c.project_id),
          requests.c.kind, requests.c.created_at.desc(), requests.c.id.desc(),
          postgresql_where=text("scope_kind IN ('workspace','project')"))
    Index("ix_service_requests_artifact_id", requests.c.project_id, requests.c.artifact_id,
          postgresql_where=text("artifact_id IS NOT NULL"))
    Index("ix_service_requests_media_id", requests.c.project_id, requests.c.media_id,
          postgresql_where=text("media_id IS NOT NULL"))

    events = entity_table(
        "service_request_events",
        Column("request_id", UUID(as_uuid=False), ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False),
        Column("sequence", Integer, nullable=False),
        Column("status", Text, nullable=False),
        Column("reason", Text, nullable=False),
        identity("created_by"),
        stamp(),
        UniqueConstraint("request_id", "sequence", name="uq_service_request_events_request_sequence"),
        CheckConstraint(
            "status IN ('received','under_review','awaiting_configuration','local_approved','rejected','withdrawn','export_ready','error','account_closed') AND sequence > 0",
            name="status",
        ),
    )
    Index("ix_service_request_events_created_by", events.c.created_by)

    exports = entity_table(
        "service_export_files",
        Column("request_id", UUID(as_uuid=False), ForeignKey("service_requests.id", ondelete="RESTRICT"), nullable=False),
        identity("requester_id"),
        Column("snapshot_revision", BigInteger, nullable=False),
        Column("snapshot", JSONB, nullable=False),
        Column("snapshot_sha256", Text, nullable=False),
        Column("object_key", Text, nullable=False),
        Column("sha256", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        stamp(),
        UniqueConstraint("request_id", name="uq_service_export_files_request_id"),
        ForeignKeyConstraint(
            ["request_id", "requester_id"],
            ["service_requests.id", "service_requests.requester_id"],
            ondelete="RESTRICT",
            match="FULL",
        ),
        CheckConstraint("snapshot_revision >= 0 AND size_bytes > 0", name="size"),
    )
    Index("ix_service_export_files_requester_id", exports.c.requester_id)

    keys = entity_table(
        "service_api_keys",
        identity("identity_id"),
        Column("name", Text, nullable=False),
        Column("secret_sha256", Text, nullable=False, unique=True),
        Column("prefix", Text, nullable=False),
        Column("ip_allowlist", JSONB, nullable=False, server_default="[]"),
        Column("requests_per_minute", Integer, nullable=False, server_default="0"),
        CheckConstraint("jsonb_typeof(ip_allowlist)='array' AND requests_per_minute BETWEEN 0 AND 10000", name="network_limits"),
        Column("capabilities", JSONB, nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("revoked", Boolean, nullable=False, server_default="false"),
        stamp(),
        CheckConstraint(
            "jsonb_typeof(capabilities)='array' AND capabilities <@ '[\"read\",\"execute\"]'::jsonb AND capabilities @> '[\"read\"]'::jsonb",
            name="capabilities",
        ),
    )
    Index("uq_service_api_keys_identity_active_name", keys.c.owner_identity_id, keys.c.identity_id,
          func.lower(func.btrim(keys.c.name)), unique=True,
          postgresql_where=text("scope_kind = 'identity' AND revoked = false"))
    Index("uq_service_api_keys_workspace_active_name", keys.c.workspace_id, keys.c.identity_id,
          func.lower(func.btrim(keys.c.name)), unique=True,
          postgresql_where=text("scope_kind = 'workspace' AND revoked = false"))
    Index("uq_service_api_keys_project_active_name", keys.c.project_id, keys.c.identity_id,
          func.lower(func.btrim(keys.c.name)), unique=True,
          postgresql_where=text("scope_kind = 'project' AND revoked = false"))
    Index("ix_service_api_keys_scope_created", keys.c.scope_kind,
          func.coalesce(keys.c.owner_identity_id, keys.c.workspace_id, keys.c.project_id),
          keys.c.created_at.desc(), keys.c.id.desc())
    Index("ix_service_api_keys_identity_active", keys.c.identity_id,
          postgresql_where=text("revoked = false"))

    calls = entity_table(
        "service_api_calls",
        Column("api_key_id", UUID(as_uuid=False), ForeignKey("service_api_keys.id", ondelete="RESTRICT"), nullable=False),
        Column("call_id", UUID(as_uuid=False), nullable=False),
        Column("phase", Text, nullable=False),
        Column("operation", Text, nullable=False),
        Column("status_code", Integer, nullable=False),
        Column("error_code", Text),
        *ref("artifact_versions", "run_version_id", nullable=True),
        stamp(),
        UniqueConstraint("project_id", "id", name="uq_service_api_calls_project_id_id"),
        UniqueConstraint("call_id", "phase", name="uq_service_api_calls_call_id_phase"),
        CheckConstraint("project_id IS NOT NULL OR run_version_id IS NULL", name="project_run"),
        CheckConstraint("phase IN ('started','finished') AND status_code BETWEEN 0 AND 599", name="phase"),
    )
    Index("ix_service_api_calls_key_rpm_window", calls.c.api_key_id, calls.c.created_at.desc(),
          postgresql_where=text("phase = 'started'"))
    Index("ix_service_api_calls_run_version_id", calls.c.project_id, calls.c.run_version_id,
          postgresql_where=text("run_version_id IS NOT NULL"))

    call_jobs = project_table(
        "service_api_call_jobs",
        *ref("service_api_calls", "call_event_id"),
        *ref("generation_jobs", "job_id"),
        UniqueConstraint("project_id", "call_event_id", "job_id"),
    )
    for col in call_jobs.c:
        if col.name.endswith("_id") and col.name not in {"id", "project_id"}:
            Index("ix_" + call_jobs.name + "_" + col.name, call_jobs.c.project_id, col)

    tables = (configs, announcements, requests, events, exports, keys, calls, call_jobs)
    return {table.name: table for table in tables}
