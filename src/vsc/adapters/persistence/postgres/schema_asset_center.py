"""Catalog annotations and personal selection lists over fixed shared-library versions."""
from sqlalchemy import Table, Column, Text, Integer, Boolean, DateTime, func, ForeignKeyConstraint, UniqueConstraint, PrimaryKeyConstraint, CheckConstraint, Index

CENTER_IMMUTABLE = ("library_catalog_edits", "library_catalog_tags", "library_cart_imports", "library_download_requests", "official_asset_publications", "official_asset_backups", "library_media_actions")


def declare_asset_center(metadata, project_table, ref, uid, stamp):
    backups = Table("official_asset_backups", metadata,
        uid("entry_id", nullable=False), uid("library_version_id", nullable=False), Column("member_key", Text, nullable=False),
        Column("actor", Text, nullable=False), Column("reason", Text, nullable=False), stamp(),
        PrimaryKeyConstraint("entry_id", "library_version_id", "member_key"),
        ForeignKeyConstraint(["entry_id"], ["library_entries.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["library_version_id", "member_key"], ["library_version_media.library_version_id", "library_version_media.member_key"], ondelete="RESTRICT"))
    states = Table("library_media_states", metadata,
        uid("library_version_id", nullable=False), Column("member_key", Text, nullable=False),
        Column("state", Text, nullable=False), Column("revision", Integer, nullable=False),
        Column("actor", Text, nullable=False), Column("reason", Text, nullable=False), Column("changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("cleanup_pending", Boolean, nullable=False, server_default="false"),
        PrimaryKeyConstraint("library_version_id", "member_key"),
        ForeignKeyConstraint(["library_version_id", "member_key"], ["library_version_media.library_version_id", "library_version_media.member_key"], ondelete="RESTRICT"),
        CheckConstraint("state IN ('active','trashed','purged') AND revision > 0 AND (NOT cleanup_pending OR state='purged')", name="lifecycle"))
    actions = Table("library_media_actions", metadata, uid(primary_key=True),
        uid("library_version_id", nullable=False), Column("member_key", Text, nullable=False),
        Column("operation", Text, nullable=False), Column("revision", Integer, nullable=False),
        Column("actor", Text, nullable=False), Column("reason", Text, nullable=False),
        Column("command_key", Text, nullable=False), Column("request_sha256", Text, nullable=False), stamp(),
        ForeignKeyConstraint(["library_version_id", "member_key"], ["library_version_media.library_version_id", "library_version_media.member_key"], ondelete="RESTRICT"),
        UniqueConstraint("actor", "command_key"), UniqueConstraint("library_version_id", "member_key", "revision"),
        CheckConstraint("operation IN ('trash','restore','purge') AND revision > 0", name="operation"))
    Index("ix_library_media_states_recycle", states.c.state, states.c.changed_at)
    # One immutable publisher classification of one original fixed library
    # version. No copy of its rights, bytes, membership or selection authority.
    official = Table("official_asset_publications", metadata, uid(primary_key=True),
        uid("entry_id", nullable=False), uid("library_version_id", nullable=False),
        Column("asset_kind", Text, nullable=False), Column("role_level", Text, nullable=False),
        Column("role_tag", Text, nullable=False), Column("gender", Text, nullable=False),
        Column("age_band", Text, nullable=False), Column("publisher", Text, nullable=False),
        Column("notes", Text, nullable=False), Column("command_key", Text, nullable=False),
        Column("request_sha256", Text, nullable=False), stamp(),
        ForeignKeyConstraint(["entry_id","library_version_id"], ["library_entry_versions.entry_id","library_entry_versions.id"], ondelete="RESTRICT"),
        UniqueConstraint("library_version_id"), UniqueConstraint("publisher","command_key"),
        CheckConstraint("asset_kind IN ('character','location','prop','voice','blocking','other')", name="asset_kind"),
        CheckConstraint("role_level IN ('lead','supporting','extra','unspecified')", name="role_level"),
        CheckConstraint("gender IN ('female','male','other','unspecified')", name="gender"),
        CheckConstraint("age_band IN ('child','teen','young_adult','middle_aged','senior','unspecified')", name="age_band"),
        CheckConstraint("asset_kind='character' OR (role_level='unspecified' AND gender='unspecified' AND age_band='unspecified')", name="character_dimensions"),
        CheckConstraint("length(btrim(role_tag)) BETWEEN 1 AND 80 AND length(btrim(notes)) BETWEEN 1 AND 4000 AND length(btrim(publisher)) BETWEEN 1 AND 200 AND length(btrim(command_key)) BETWEEN 1 AND 200", name="text_fields"))
    Index("ix_official_asset_publications_browse", official.c.asset_kind,official.c.role_level,official.c.gender,official.c.age_band)
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
    return {table.name:table for table in (edits,tags,cart,imported,downloads,official,backups,states,actions)}
