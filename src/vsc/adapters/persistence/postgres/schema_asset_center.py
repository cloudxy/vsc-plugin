"""Catalog annotations and personal selection lists over fixed shared-library versions."""
from sqlalchemy import Table, Column, Text, Integer, Boolean, ForeignKeyConstraint, UniqueConstraint, PrimaryKeyConstraint, CheckConstraint, Index

CENTER_IMMUTABLE = ("library_catalog_edits", "library_catalog_tags", "library_cart_imports", "library_download_requests")


def declare_asset_center(metadata, project_table, ref, uid, stamp):
    edits = Table("library_catalog_edits", metadata, uid(primary_key=True), uid("entry_id", nullable=False),
        uid("library_version_id", nullable=False), Column("revision", Integer, nullable=False),
        Column("asset_kind", Text, nullable=False), Column("form_name", Text, nullable=False),
        uid("workspace_id", nullable=True), Column("review_status", Text, nullable=False),
        Column("notes", Text, nullable=False), Column("tag_count", Integer, nullable=False), Column("actor", Text, nullable=False),
        Column("command_key", Text, nullable=False), Column("request_sha256", Text, nullable=False), stamp(),
        ForeignKeyConstraint(["entry_id", "library_version_id"], ["library_entry_versions.entry_id", "library_entry_versions.id"]),
        ForeignKeyConstraint(["workspace_id"], ["access_workspaces.id"]),
        UniqueConstraint("entry_id", "revision"), UniqueConstraint("actor", "command_key"),
        CheckConstraint("revision > 0", name="revision"),
        CheckConstraint("tag_count BETWEEN 0 AND 50", name="tag_count"),
        CheckConstraint("asset_kind IN ('character','location','prop','voice','blocking','other')", name="asset_kind"),
        CheckConstraint("review_status IN ('draft','confirmed','returned')", name="review_status"))
    tags = Table("library_catalog_tags", metadata, uid("edit_id", nullable=False), Column("tag", Text, nullable=False),
        PrimaryKeyConstraint("edit_id", "tag"), ForeignKeyConstraint(["edit_id"], ["library_catalog_edits.id"]),
        CheckConstraint("length(tag) BETWEEN 1 AND 80", name="tag"))
    cart = Table("library_cart_items", metadata, uid(primary_key=True), Column("actor", Text, nullable=False),
        uid("library_version_id", nullable=False), Column("member_key", Text, nullable=False),
        Column("active", Boolean, nullable=False, server_default="true"), stamp(),
        ForeignKeyConstraint(["library_version_id", "member_key"], ["library_version_media.library_version_id", "library_version_media.member_key"]),
        UniqueConstraint("actor", "library_version_id", "member_key"),UniqueConstraint("id","actor"))
    imported = project_table("library_cart_imports", uid("cart_id", nullable=False),
        *ref("creative_objects", "target_object_id"), *ref("media_items", "media_id"),
        *ref("binding_candidates", "candidate_id"), Column("role", Text, nullable=False), Column("actor", Text, nullable=False), stamp(),
        ForeignKeyConstraint(["cart_id"], ["library_cart_items.id"]),
        ForeignKeyConstraint(["cart_id","actor"], ["library_cart_items.id","library_cart_items.actor"]),
        UniqueConstraint("project_id", "cart_id", "target_object_id", "role"))
    downloads = Table("library_download_requests", metadata, uid(primary_key=True), Column("actor", Text, nullable=False),
        uid("library_version_id", nullable=False), Column("member_key", Text, nullable=False),
        Column("command_key", Text, nullable=False), stamp(), UniqueConstraint("actor", "command_key"),
        ForeignKeyConstraint(["library_version_id", "member_key"], ["library_version_media.library_version_id", "library_version_media.member_key"]))
    for table, columns in ((edits,("entry_id","revision")), (cart,("actor","active")), (downloads,("actor","created_at")), (imported,("project_id","cart_id"))):
        Index("ix_"+table.name+"_browse", *(table.c[name] for name in columns))
    return {table.name:table for table in (edits,tags,cart,imported,downloads)}
