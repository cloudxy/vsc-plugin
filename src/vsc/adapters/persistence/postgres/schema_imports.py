"""A fixed file manifest and per-file outcomes for resumable project imports."""
from sqlalchemy import Column, Text, Integer, BigInteger, String, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB

IMPORT_TABLES = ("media_import_batches", "media_import_items")


def declare_imports(project_table, ref, uid, stamp):
    batches = project_table("media_import_batches", *ref("episodes", "episode_id", nullable=True),
        Column("title", Text, nullable=False), Column("asset_kind", Text),
        Column("rights", Text, nullable=False), Column("rights_scope", JSONB, nullable=False),
        Column("source_evidence", Text, nullable=False), Column("member_count", Integer, nullable=False),
        Column("created_by", Text, nullable=False), stamp(),
        CheckConstraint("member_count BETWEEN 1 AND 200", name="member_count"),
        CheckConstraint("asset_kind IS NULL OR asset_kind IN ('character','location','prop','voice')", name="asset_kind"),
        CheckConstraint("rights IN ('owned','licensed','unknown')", name="rights"))
    items = project_table("media_import_items", *ref("media_import_batches", "batch_id"),
        Column("ordinal", Integer, nullable=False), Column("filename", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False), Column("expected_sha256", String(64), nullable=False),
        Column("upload_key", String(48), nullable=False), Column("status", Text, nullable=False),
        Column("uploaded_metadata", JSONB), Column("error", Text),
        *ref("media_items", "media_id", nullable=True), *ref("asset_identities", "asset_id", nullable=True), stamp(),
        UniqueConstraint("project_id", "batch_id", "ordinal"), UniqueConstraint("upload_key"),
        CheckConstraint("ordinal >= 0 AND size_bytes BETWEEN 1 AND 1073741824", name="size"),
        CheckConstraint("status IN ('awaiting_upload','uploaded','completed','failed','cancelled')", name="status"),
        CheckConstraint("status <> 'completed' OR media_id IS NOT NULL", name="completed_media"))
    items.append_constraint(CheckConstraint("upload_key ~ '^[0-9a-f]{48}$'", name="upload_key_format"))
    for table in (batches, items):
        for column in table.c:
            if column.name.endswith("_id") and column.name not in {"project_id", "id"}:
                Index("ix_"+table.name+"_"+column.name, table.c.project_id, column)
    return {table.name: table for table in (batches, items)}
