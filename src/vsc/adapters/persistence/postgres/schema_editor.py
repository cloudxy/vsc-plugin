"""Working editorial revisions; formal timelines remain in the original tables."""
from sqlalchemy import Column, Integer, Text, String, DateTime, Boolean, CheckConstraint, ForeignKeyConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB


EDITOR_TABLES = ("edit_workspaces", "edit_revisions", "edit_revision_media", "edit_render_jobs")
EDITOR_IMMUTABLE = ("edit_revisions", "edit_revision_media")


def declare_editor(project_table, ref, uid, stamp):
    workspaces = project_table("edit_workspaces", *ref("episodes", "episode_id"),
        Column("title", Text, nullable=False), Column("revision", Integer, nullable=False),
        uid("current_version_id", nullable=True), stamp(),
        UniqueConstraint("project_id", "episode_id"),
        CheckConstraint("revision >= 0", name="revision"))
    revisions = project_table("edit_revisions", *ref("edit_workspaces", "workspace_id"),
        Column("version", Integer, nullable=False), Column("document", JSONB, nullable=False),
        Column("sha256", String(64), nullable=False), Column("member_count", Integer, nullable=False),
        Column("created_by", Text, nullable=False), stamp(),
        UniqueConstraint("project_id", "workspace_id", "version"),
        UniqueConstraint("project_id", "workspace_id", "id"),
        CheckConstraint("version > 0 AND member_count >= 0 AND member_count <= 1000", name="version_members"))
    workspaces.append_constraint(ForeignKeyConstraint(
        ["project_id", "id", "current_version_id"],
        ["edit_revisions.project_id", "edit_revisions.workspace_id", "edit_revisions.id"],
        name="fk_edit_workspace_current_version", use_alter=True))
    media = project_table("edit_revision_media", *ref("edit_revisions", "edit_version_id"),
        *ref("media_items", "media_id"), *ref("shots", "shot_id", nullable=True),
        uid("blob_id", nullable=False), Column("blob_sha256", String(64), nullable=False),
        Column("clip_key", Text, nullable=False), Column("track", Text, nullable=False),
        Column("ordinal", Integer, nullable=False), Column("source_in_frame", Integer, nullable=False),
        Column("source_out_frame", Integer, nullable=False), Column("offset_frame", Integer, nullable=False),
        Column("modality", Text, nullable=False),
        ForeignKeyConstraint(["project_id", "media_id", "blob_id"], ["media_items.project_id", "media_items.id", "media_items.blob_id"]),
        ForeignKeyConstraint(["blob_id", "blob_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
        UniqueConstraint("project_id", "edit_version_id", "clip_key"),
        UniqueConstraint("project_id", "edit_version_id", "track", "ordinal"),
        CheckConstraint("track IN ('clips','audio')", name="track"),
        CheckConstraint("(track='clips' AND modality IN ('video','image')) OR (track='audio' AND modality IN ('audio','video'))", name="modality"),
        CheckConstraint("ordinal >= 0 AND offset_frame >= 0 AND source_in_frame >= 0 AND source_out_frame > source_in_frame", name="range"))
    renders = project_table("edit_render_jobs", *ref("edit_revisions", "edit_version_id"),
        Column("status", Text, nullable=False), Column("attempt", Integer, nullable=False),
        Column("cancel_requested", Boolean, nullable=False, server_default="false"),
        Column("claim_owner", Text), Column("claim_until", DateTime(timezone=True)),
        Column("error", Text), uid("output_blob_id", nullable=True), Column("output_sha256", String(64)),
        Column("receipt", JSONB, nullable=False), stamp(),
        ForeignKeyConstraint(["output_blob_id", "output_sha256"], ["media_blobs.id", "media_blobs.sha256"]),
        UniqueConstraint("project_id", "edit_version_id"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled') AND attempt >= 0", name="status"),
        CheckConstraint("(output_blob_id IS NULL) = (output_sha256 IS NULL)", name="output_pair"),
        CheckConstraint("status <> 'succeeded' OR output_blob_id IS NOT NULL", name="successful_output"))
    Index("ix_edit_render_queue", renders.c.status, renders.c.created_at)
    for table in (workspaces, revisions, media, renders):
        for col in table.c:
            if col.name.endswith("_id") and col.name not in {"id", "project_id"}:
                Index("ix_" + table.name + "_" + col.name, table.c.project_id, col)
    return {table.name: table for table in (workspaces, revisions, media, renders)}
