"""Canvas-owned relations; imported by the authoritative schema registry."""
from sqlalchemy import (BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKeyConstraint,
    Index, Integer, PrimaryKeyConstraint, String, Table, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID

CANVAS_TABLES = ("creative_canvases", "creative_canvas_versions", "creative_canvas_nodes",
                 "creative_canvas_edges", "creative_canvas_preparations", "creative_canvas_runs", "canvas_generation_inputs")
CANVAS_APPEND_ONLY = CANVAS_TABLES[1:]


def install_canvas_schema(metadata):
    def uid(name, **kw):
        return Column(name, UUID(as_uuid=False), **kw)
    def table(name, *columns):
        return Table(name, metadata, uid("project_id", nullable=False), *columns,
            ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"))
    def stamp():
        return Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()"))
    canvases = table("creative_canvases", uid("id", nullable=False), uid("episode_id"),
        uid("current_version_id"), Column("created_by", Text, nullable=False), stamp(),
        PrimaryKeyConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "episode_id"], ["episodes.project_id", "episodes.id"]))
    versions = table("creative_canvas_versions", uid("id", nullable=False), uid("canvas_id", nullable=False),
        Column("version", BigInteger, nullable=False), Column("title", Text, nullable=False),
        Column("viewport", JSONB, nullable=False), Column("sha256", String(64), nullable=False),
        Column("node_count", Integer, nullable=False), Column("edge_count", Integer, nullable=False),
        uid("parent_version_id"), Column("created_by", Text, nullable=False), stamp(),
        PrimaryKeyConstraint("project_id", "id"), UniqueConstraint("project_id", "canvas_id", "id"),
        UniqueConstraint("project_id", "canvas_id", "version"),
        ForeignKeyConstraint(["project_id", "canvas_id"], ["creative_canvases.project_id", "creative_canvases.id"]),
        ForeignKeyConstraint(["project_id", "canvas_id", "parent_version_id"],
            ["creative_canvas_versions.project_id", "creative_canvas_versions.canvas_id", "creative_canvas_versions.id"]),
        CheckConstraint("version > 0 AND node_count BETWEEN 0 AND 200 AND edge_count BETWEEN 0 AND 800", name="counts"))
    canvases.append_constraint(ForeignKeyConstraint(["project_id", "id", "current_version_id"],
        ["creative_canvas_versions.project_id", "creative_canvas_versions.canvas_id", "creative_canvas_versions.id"],
        name="fk_creative_canvases_current_version", use_alter=True))
    nodes = table("creative_canvas_nodes", uid("version_id", nullable=False), Column("node_key", Text, nullable=False),
        Column("node_type", Text, nullable=False), Column("ordinal", Integer, nullable=False),
        Column("title", Text, nullable=False), Column("x", Float, nullable=False), Column("y", Float, nullable=False),
        Column("content", Text, nullable=False), Column("params", JSONB, nullable=False), Column("group_name", Text, nullable=False),
        uid("media_id"), uid("job_id"), uid("spatial_scene_id"), uid("spatial_version_id"),
        uid("edit_workspace_id"), uid("edit_version_id"), uid("tool_draft_id"),
        PrimaryKeyConstraint("project_id", "version_id", "node_key"),
        UniqueConstraint("project_id", "version_id", "ordinal"),
        UniqueConstraint("project_id", "version_id", "node_key", "node_type"),
        ForeignKeyConstraint(["project_id", "version_id"], ["creative_canvas_versions.project_id", "creative_canvas_versions.id"]),
        ForeignKeyConstraint(["project_id", "media_id"], ["media_items.project_id", "media_items.id"]),
        ForeignKeyConstraint(["project_id", "job_id"], ["generation_jobs.project_id", "generation_jobs.id"]),
        ForeignKeyConstraint(["project_id", "spatial_scene_id"], ["spatial_scenes.project_id", "spatial_scenes.id"]),
        ForeignKeyConstraint(["project_id", "spatial_scene_id", "spatial_version_id"], ["spatial_scene_versions.project_id", "spatial_scene_versions.spatial_scene_id", "spatial_scene_versions.id"]),
        ForeignKeyConstraint(["project_id", "edit_workspace_id"], ["edit_workspaces.project_id", "edit_workspaces.id"]),
        ForeignKeyConstraint(["project_id", "edit_workspace_id", "edit_version_id"], ["edit_revisions.project_id", "edit_revisions.workspace_id", "edit_revisions.id"]),
        ForeignKeyConstraint(["project_id", "tool_draft_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
        CheckConstraint("node_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing')", name="type"),
        CheckConstraint("(spatial_scene_id IS NULL) = (spatial_version_id IS NULL) AND (edit_workspace_id IS NULL) = (edit_version_id IS NULL) AND "
            "(spatial_scene_id IS NULL OR node_type IN ('spatial','director')) AND (edit_workspace_id IS NULL OR node_type='edit') AND "
            "(tool_draft_id IS NULL OR node_type IN ('music_mix','processing')) AND (node_type IN ('text','image','video','audio') OR (media_id IS NULL AND job_id IS NULL))", name="domain_shape"),
        CheckConstraint("node_type <> 'text' OR (media_id IS NULL AND job_id IS NULL)", name="text_reference"),
        CheckConstraint("ordinal >= 0 AND x BETWEEN -100000 AND 100000 AND y BETWEEN -100000 AND 100000", name="position"))
    edges = table("creative_canvas_edges", uid("version_id", nullable=False), Column("edge_key", Text, nullable=False),
        Column("ordinal", Integer, nullable=False), Column("source_key", Text, nullable=False),
        Column("target_key", Text, nullable=False), Column("source_type", Text, nullable=False),
        Column("target_type", Text, nullable=False), Column("port", Text, nullable=False),
        PrimaryKeyConstraint("project_id", "version_id", "edge_key"),
        UniqueConstraint("project_id", "version_id", "ordinal"),
        UniqueConstraint("project_id", "version_id", "source_key", "target_key", "port"),
        ForeignKeyConstraint(["project_id", "version_id", "source_key", "source_type"],
            ["creative_canvas_nodes.project_id", "creative_canvas_nodes.version_id", "creative_canvas_nodes.node_key", "creative_canvas_nodes.node_type"]),
        ForeignKeyConstraint(["project_id", "version_id", "target_key", "target_type"],
            ["creative_canvas_nodes.project_id", "creative_canvas_nodes.version_id", "creative_canvas_nodes.node_key", "creative_canvas_nodes.node_type"]),
        CheckConstraint("source_key <> target_key AND ordinal >= 0", name="endpoints"),
        CheckConstraint("(port = 'prompt' AND source_type = 'text' AND target_type IN ('image','video','audio','spatial','director','music_mix','processing')) OR "
            "(port = 'reference' AND source_type = 'image' AND target_type IN ('image','spatial','director')) OR "
            "(port IN ('first_frame','last_frame','reference_image') AND source_type = 'image' AND target_type = 'video') OR "
            "(port = 'reference_video' AND source_type = 'video' AND target_type = 'video') OR "
            "(port = 'reference_audio' AND source_type = 'audio' AND target_type IN ('video','audio')) OR "
            "(port='visual' AND source_type IN ('image','video') AND target_type='edit') OR "
            "(port='sound' AND source_type='audio' AND target_type IN ('edit','music_mix')) OR "
            "(port='source_video' AND source_type='video' AND target_type IN ('music_mix','processing')) OR "
            "(port='derived_from' AND source_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing') AND target_type IN ('text','image','video','audio'))", name="port_type"))
    Index("uq_canvas_single_frame", edges.c.project_id, edges.c.version_id, edges.c.target_key, edges.c.port,
          unique=True, postgresql_where=text("port IN ('first_frame','last_frame')"))
    preparations = table("creative_canvas_preparations", uid("id", nullable=False), uid("version_id", nullable=False),
        Column("node_key", Text, nullable=False), uid("job_id"), Column("input_sha256", String(64), nullable=False),
        Column("prompt", Text, nullable=False), Column("params", JSONB, nullable=False),
        Column("gaps", JSONB, nullable=False), Column("created_by", Text, nullable=False), stamp(),
        PrimaryKeyConstraint("project_id", "id"),
        ForeignKeyConstraint(["project_id", "version_id", "node_key"],
            ["creative_canvas_nodes.project_id", "creative_canvas_nodes.version_id", "creative_canvas_nodes.node_key"]),
        ForeignKeyConstraint(["project_id", "job_id"], ["generation_jobs.project_id", "generation_jobs.id"]))
    runs = table("creative_canvas_runs", uid("id", nullable=False), uid("version_id", nullable=False),
        Column("node_key", Text, nullable=False), uid("artifact_id", nullable=False),
        Column("preview_sha256", String(64), nullable=False), stamp(),
        PrimaryKeyConstraint("project_id", "id"), UniqueConstraint("project_id", "artifact_id"),
        ForeignKeyConstraint(["project_id", "version_id", "node_key"],
            ["creative_canvas_nodes.project_id", "creative_canvas_nodes.version_id", "creative_canvas_nodes.node_key"]),
        ForeignKeyConstraint(["project_id", "artifact_id"], ["artifact_versions.project_id", "artifact_versions.id"]))
    generation_inputs = table("canvas_generation_inputs", uid("draft_version_id", nullable=False), uid("version_id", nullable=False),
        Column("node_key", Text, nullable=False), uid("shot_id", nullable=False), stamp(),
        PrimaryKeyConstraint("project_id", "draft_version_id"),
        ForeignKeyConstraint(["project_id", "draft_version_id"], ["artifact_versions.project_id", "artifact_versions.id"]),
        ForeignKeyConstraint(["project_id", "version_id", "node_key"], ["creative_canvas_nodes.project_id", "creative_canvas_nodes.version_id", "creative_canvas_nodes.node_key"]),
        ForeignKeyConstraint(["project_id", "shot_id"], ["shots.project_id", "shots.id"]))
    for relation in (canvases, versions, nodes, preparations, runs):
        for column in relation.c:
            if column.name.endswith("_id") and column.name != "project_id":
                Index("ix_%s_%s" % (relation.name, column.name), relation.c.project_id, column)
    return {relation.name: relation for relation in (canvases, versions, nodes, edges, preparations, runs, generation_inputs)}


DIRECT_COPY_TABLES = ('canvas_direct_copies', 'canvas_direct_copy_media', 'canvas_direct_copy_domains')


def install_direct_copy_schema(metadata):
    def uid(name, **kw):return Column(name, UUID(as_uuid=False), **kw)
    def table(name, *columns):
        return Table(name, metadata, uid('project_id', nullable=False), uid('id', nullable=False), *columns,
            PrimaryKeyConstraint('project_id', 'id'),
            ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'))
    roots = table('canvas_direct_copies', uid('canvas_id', nullable=False), uid('canvas_version_id', nullable=False),
        uid('source_project_id', nullable=False), uid('source_canvas_id', nullable=False), uid('source_version_id', nullable=False),
        Column('command_key', Text, nullable=False), Column('created_by', Text, nullable=False),
        Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
        UniqueConstraint('project_id', 'canvas_id'), UniqueConstraint('project_id', 'command_key'),
        UniqueConstraint('project_id', 'id', 'source_project_id'),
        ForeignKeyConstraint(['project_id','canvas_id','canvas_version_id'],
            ['creative_canvas_versions.project_id','creative_canvas_versions.canvas_id','creative_canvas_versions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['source_project_id','source_canvas_id','source_version_id'],
            ['creative_canvas_versions.project_id','creative_canvas_versions.canvas_id','creative_canvas_versions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id','command_key'], ['command_receipts.project_id','command_receipts.idempotency_key'],
            ondelete='RESTRICT', deferrable=True, initially='DEFERRED'),
        CheckConstraint('canvas_id<>source_canvas_id AND canvas_version_id<>source_version_id', name='new_identity'),
        CheckConstraint('length(btrim(command_key)) BETWEEN 1 AND 200 AND length(btrim(created_by)) BETWEEN 1 AND 200', name='command_actor'))
    def root_fk():return ForeignKeyConstraint(['project_id','copy_id','source_project_id'],
        ['canvas_direct_copies.project_id','canvas_direct_copies.id','canvas_direct_copies.source_project_id'], ondelete='RESTRICT')
    media = table('canvas_direct_copy_media', uid('copy_id', nullable=False), uid('source_project_id', nullable=False),
        uid('source_media_id', nullable=False), uid('target_media_id', nullable=False), uid('blob_id', nullable=False),
        Column('sha256', String(64), nullable=False), root_fk(),
        ForeignKeyConstraint(['source_project_id','source_media_id','blob_id'], ['media_items.project_id','media_items.id','media_items.blob_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id','target_media_id','blob_id'], ['media_items.project_id','media_items.id','media_items.blob_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['blob_id','sha256'], ['media_blobs.id','media_blobs.sha256'], ondelete='RESTRICT'),
        UniqueConstraint('project_id','copy_id','source_media_id'), UniqueConstraint('project_id','target_media_id'),
        CheckConstraint('source_media_id<>target_media_id', name='new_identity'))
    columns = [uid('copy_id', nullable=False), uid('source_project_id', nullable=False), root_fk()]
    targets = {'spatial':'spatial_scene_versions','edit':'edit_revisions','tool':'artifact_versions'}
    for kind, target in targets.items():
        for side, project in (('source','source_project_id'),('target','project_id')):
            col=side+'_'+kind+'_version_id';columns.extend((uid(col),ForeignKeyConstraint([project,col],[target+'.project_id',target+'.id'],ondelete='RESTRICT')))
    columns.append(CheckConstraint('num_nonnulls(source_spatial_version_id,source_edit_version_id,source_tool_version_id)=1 AND '+
        ' AND '.join('(source_%s_version_id IS NULL)=(target_%s_version_id IS NULL)'%(k,k) for k in targets)+' AND '+
        ' AND '.join('(source_%s_version_id IS NULL OR source_%s_version_id<>target_%s_version_id)'%(k,k,k) for k in targets),name='typed_mapping'))
    domains=table('canvas_direct_copy_domains',*columns)
    for kind in targets:
        for side in ('source','target'):
            column=side+'_'+kind+'_version_id'
            keys=[domains.c.project_id]+([domains.c.copy_id] if side=='source' else [])+[domains.c[column]]
            Index('uq_direct_domain_'+side+'_'+kind,*keys,unique=True,postgresql_where=text(column+' IS NOT NULL'))
    Index('ix_direct_copy_source_canvas',roots.c.source_project_id,roots.c.source_canvas_id)
    Index('ix_direct_copy_source_project',roots.c.project_id,roots.c.source_project_id)
    Index('ix_direct_copy_media_source',media.c.source_project_id,media.c.source_media_id)
    return {t.name:t for t in (roots,media,domains)}
