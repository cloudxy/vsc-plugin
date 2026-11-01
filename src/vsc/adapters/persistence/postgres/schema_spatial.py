"""Typed ownership for blocking/previs versions and fixed export receipts."""
from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKeyConstraint, Index, Integer,
    PrimaryKeyConstraint, String, Table, Text, UniqueConstraint, CheckConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID

SPATIAL_TABLES = ("spatial_scenes", "spatial_scene_versions", "spatial_objects", "spatial_cameras", "spatial_exports", "spatial_export_outputs")
SPATIAL_IMMUTABLE = ("spatial_scene_versions", "spatial_objects", "spatial_cameras", "spatial_export_outputs")


def install_spatial_schema(metadata):
    def uid(name, **kw):return Column(name, UUID(as_uuid=False), **kw)
    def table(name,*columns):return Table(name,metadata,uid("project_id",nullable=False),*columns,
        ForeignKeyConstraint(["project_id"],["projects.id"]))
    def stamp():return Column("created_at",DateTime(timezone=True),nullable=False,server_default=text("now()"))
    scenes=table("spatial_scenes",uid("id",nullable=False),Column("mode",Text,nullable=False),uid("scene_id"),uid("episode_id"),uid("current_version_id"),stamp(),
        PrimaryKeyConstraint("project_id","id"),ForeignKeyConstraint(["project_id","scene_id"],["scenes.project_id","scenes.id"]),
        ForeignKeyConstraint(["project_id","episode_id"],["episodes.project_id","episodes.id"]),
        CheckConstraint("mode IN ('blocking','previs') AND (mode <> 'blocking' OR scene_id IS NOT NULL)",name="mode_scope"))
    versions=table("spatial_scene_versions",uid("id",nullable=False),uid("spatial_scene_id",nullable=False),Column("version",Integer,nullable=False),
        Column("title",Text,nullable=False),Column("description",Text,nullable=False),Column("settings",JSONB,nullable=False),
        Column("sha256",String(64),nullable=False),Column("object_count",Integer,nullable=False),Column("camera_count",Integer,nullable=False),
        Column("created_by",Text,nullable=False),stamp(),PrimaryKeyConstraint("project_id","id"),
        UniqueConstraint("project_id","spatial_scene_id","version"),UniqueConstraint("project_id","spatial_scene_id","id"),
        ForeignKeyConstraint(["project_id","spatial_scene_id"],["spatial_scenes.project_id","spatial_scenes.id"]),
        CheckConstraint("version > 0 AND object_count BETWEEN 0 AND 64 AND camera_count BETWEEN 1 AND 8",name="counts"))
    scenes.append_constraint(ForeignKeyConstraint(["project_id","id","current_version_id"],
        ["spatial_scene_versions.project_id","spatial_scene_versions.spatial_scene_id","spatial_scene_versions.id"],
        name="fk_spatial_scene_current",use_alter=True))
    objects=table("spatial_objects",uid("version_id",nullable=False),Column("object_key",Text,nullable=False),Column("kind",Text,nullable=False),
        Column("ordinal",Integer,nullable=False),Column("spec",JSONB,nullable=False),uid("media_id"),PrimaryKeyConstraint("project_id","version_id","object_key"),
        UniqueConstraint("project_id","version_id","ordinal"),ForeignKeyConstraint(["project_id","version_id"],["spatial_scene_versions.project_id","spatial_scene_versions.id"]),
        ForeignKeyConstraint(["project_id","media_id"],["media_items.project_id","media_items.id"]),
        CheckConstraint("kind IN ('box','sphere','actor','light','mesh','reference') AND ordinal >= 0",name="kind"))
    cameras=table("spatial_cameras",uid("version_id",nullable=False),Column("camera_key",Text,nullable=False),Column("ordinal",Integer,nullable=False),
        Column("spec",JSONB,nullable=False),PrimaryKeyConstraint("project_id","version_id","camera_key"),UniqueConstraint("project_id","version_id","ordinal"),
        ForeignKeyConstraint(["project_id","version_id"],["spatial_scene_versions.project_id","spatial_scene_versions.id"]),CheckConstraint("ordinal >= 0",name="ordinal"))
    exports=table("spatial_exports",uid("id",nullable=False),uid("version_id",nullable=False),Column("camera_key",Text,nullable=False),
        Column("format",Text,nullable=False),Column("time_seconds",Float,nullable=False),Column("duration_seconds",Float,nullable=False),
        Column("fps",Integer,nullable=False),Column("total_frames",Integer,nullable=False),Column("progress_frames",Integer,nullable=False,server_default="0"),
        Column("status",Text,nullable=False),Column("attempt",Integer,nullable=False,server_default="0"),Column("claim_token",Text),
        Column("claim_until",DateTime(timezone=True)),Column("cancel_requested",Boolean,nullable=False,server_default="false"),Column("error",Text),
        Column("created_by",Text,nullable=False),stamp(),PrimaryKeyConstraint("project_id","id"),
        ForeignKeyConstraint(["project_id","version_id","camera_key"],["spatial_cameras.project_id","spatial_cameras.version_id","spatial_cameras.camera_key"]),
        CheckConstraint("format IN ('png','glb','mp4')",name="format"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled') AND attempt >= 0",name="status"),
        CheckConstraint("time_seconds >= 0 AND duration_seconds >= 0 AND fps IN (12,24) AND total_frames BETWEEN 1 AND 360 AND progress_frames BETWEEN 0 AND total_frames",name="bounds"))
    outputs=table("spatial_export_outputs",uid("id",nullable=False),uid("export_id",nullable=False),uid("media_id",nullable=False),
        Column("sha256",String(64),nullable=False),stamp(),PrimaryKeyConstraint("project_id","id"),UniqueConstraint("project_id","export_id"),
        ForeignKeyConstraint(["project_id","export_id"],["spatial_exports.project_id","spatial_exports.id"]),
        ForeignKeyConstraint(["project_id","media_id"],["media_items.project_id","media_items.id"]))
    for relation in (scenes,versions,objects,cameras,exports,outputs):
        for column in relation.c:
            if column.name.endswith("_id") and column.name not in {"id","project_id"}:
                Index("ix_%s_%s"%(relation.name,column.name),relation.c.project_id,column)
    return {relation.name:relation for relation in (scenes,versions,objects,cameras,exports,outputs)}
