"""Fixed canvas planning inputs and template versions; no parallel ACL."""
from sqlalchemy import Table,Column,Text,String,Integer,Boolean,DateTime,ForeignKeyConstraint,PrimaryKeyConstraint,UniqueConstraint,CheckConstraint,Index,text
from sqlalchemy.dialects.postgresql import UUID,JSONB

CANVAS_AGENT_TABLES=("canvas_agent_attachments","canvas_agent_sessions","canvas_agent_turns","canvas_agent_refs","canvas_agent_models","canvas_agent_decisions","canvas_templates","canvas_template_favorites","canvas_template_copies")
CANVAS_AGENT_IMMUTABLE=("canvas_agent_attachments","canvas_agent_sessions","canvas_agent_refs","canvas_agent_models","canvas_agent_decisions","canvas_templates","canvas_template_copies")


def install_canvas_agent_schema(metadata):
    def uid(name,**kw):return Column(name,UUID(as_uuid=False),**kw)
    def table(name,*columns):return Table(name,metadata,uid("project_id",nullable=False),*columns,ForeignKeyConstraint(["project_id"],["projects.id"]))
    def stamp():return Column("created_at",DateTime(timezone=True),nullable=False,server_default=text("now()"))
    sessions=table("canvas_agent_sessions",uid("id",nullable=False),uid("canvas_id",nullable=False),Column("title",Text,nullable=False),Column("created_by",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),ForeignKeyConstraint(["project_id","canvas_id"],["creative_canvases.project_id","creative_canvases.id"]))
    turns=table("canvas_agent_turns",uid("id",nullable=False),uid("session_id",nullable=False),uid("version_id",nullable=False),uid("dispatch_id",nullable=False),uid("parent_turn_id"),
        Column("message",Text,nullable=False),Column("skill_id",Text,nullable=False),Column("skill_sha256",Text,nullable=False),Column("mode",Text,nullable=False),Column("status",Text,nullable=False),
        Column("node_count",Integer,nullable=False),Column("model_count",Integer,nullable=False),Column("attachment_count",Integer,nullable=False,server_default=text("0")),Column("target_node_key",Text),uid("target_shot_id"),
        Column("execution_settings",JSONB,nullable=False),Column("host_result",JSONB),Column("host_started_at",DateTime(timezone=True)),Column("error",Text),
        uid("plan_artifact_id"),uid("output_version_id"),uid("run_artifact_id"),Column("created_by",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),UniqueConstraint("project_id","id","version_id"),
        ForeignKeyConstraint(["project_id","session_id"],["canvas_agent_sessions.project_id","canvas_agent_sessions.id"]),
        ForeignKeyConstraint(["project_id","version_id"],["creative_canvas_versions.project_id","creative_canvas_versions.id"]),
        ForeignKeyConstraint(["project_id","dispatch_id"],["role_dispatches.project_id","role_dispatches.id"]),
        ForeignKeyConstraint(["project_id","parent_turn_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id"]),
        ForeignKeyConstraint(["project_id","version_id","target_node_key"],["creative_canvas_nodes.project_id","creative_canvas_nodes.version_id","creative_canvas_nodes.node_key"]),
        ForeignKeyConstraint(["project_id","target_shot_id"],["shots.project_id","shots.id"]),
        ForeignKeyConstraint(["project_id","plan_artifact_id"],["artifact_versions.project_id","artifact_versions.id"]),
        ForeignKeyConstraint(["project_id","output_version_id"],["creative_canvas_versions.project_id","creative_canvas_versions.id"]),
        ForeignKeyConstraint(["project_id","run_artifact_id"],["artifact_versions.project_id","artifact_versions.id"]),
        CheckConstraint("mode IN ('manual','auto_drafts') AND status IN ('queued','running','result_ready','needs_input','planned','applied','rejected','stopped','failed','submission_unknown')",name="state"),
        CheckConstraint("node_count BETWEEN 0 AND 200 AND model_count BETWEEN 0 AND 8",name="counts"),
        CheckConstraint("attachment_count BETWEEN 0 AND 8",name="attachment_count"),
        CheckConstraint("status NOT IN ('needs_input','planned','applied','rejected') OR plan_artifact_id IS NOT NULL",name="plan_required"))
    refs=table("canvas_agent_refs",uid("turn_id",nullable=False),uid("version_id",nullable=False),Column("node_key",Text,nullable=False),
        PrimaryKeyConstraint("project_id","turn_id","node_key"),
        ForeignKeyConstraint(["project_id","turn_id","version_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id","canvas_agent_turns.version_id"]),
        ForeignKeyConstraint(["project_id","version_id","node_key"],["creative_canvas_nodes.project_id","creative_canvas_nodes.version_id","creative_canvas_nodes.node_key"]))
    attachments=table("canvas_agent_attachments",uid("turn_id",nullable=False),Column("ordinal",Integer,nullable=False),uid("media_id",nullable=False),uid("blob_id",nullable=False),Column("blob_sha256",String(64),nullable=False),
        PrimaryKeyConstraint("project_id","turn_id","ordinal"),UniqueConstraint("project_id","turn_id","media_id"),
        ForeignKeyConstraint(["project_id","turn_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id"]),
        ForeignKeyConstraint(["project_id","media_id","blob_id"],["media_items.project_id","media_items.id","media_items.blob_id"]),
        ForeignKeyConstraint(["blob_id","blob_sha256"],["media_blobs.id","media_blobs.sha256"]),CheckConstraint("ordinal BETWEEN 0 AND 7",name="ordinal"))
    models=table("canvas_agent_models",uid("turn_id",nullable=False),Column("ordinal",Integer,nullable=False),uid("model_id",nullable=False),
        PrimaryKeyConstraint("project_id","turn_id","ordinal"),UniqueConstraint("project_id","turn_id","model_id"),
        ForeignKeyConstraint(["project_id","turn_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id"]),ForeignKeyConstraint(["model_id"],["provider_models.id"]),
        CheckConstraint("ordinal BETWEEN 0 AND 7",name="ordinal"))
    decisions=table("canvas_agent_decisions",uid("id",nullable=False),uid("turn_id",nullable=False),Column("outcome",Text,nullable=False),Column("reason",Text,nullable=False),Column("actor",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),UniqueConstraint("project_id","turn_id"),ForeignKeyConstraint(["project_id","turn_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id"]),CheckConstraint("outcome IN ('confirm','reject','stop','auto_draft')",name="outcome"))
    templates=table("canvas_templates",uid("id",nullable=False),uid("version_id",nullable=False),Column("title",Text,nullable=False),Column("created_by",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),ForeignKeyConstraint(["project_id","version_id"],["creative_canvas_versions.project_id","creative_canvas_versions.id"]))
    favorites=table("canvas_template_favorites",uid("template_id",nullable=False),Column("actor",Text,nullable=False),Column("active",Boolean,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","template_id","actor"),ForeignKeyConstraint(["project_id","template_id"],["canvas_templates.project_id","canvas_templates.id"]))
    copies=table("canvas_template_copies",uid("id",nullable=False),uid("source_project_id",nullable=False),uid("template_id",nullable=False),uid("canvas_id",nullable=False),Column("created_by",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),ForeignKeyConstraint(["source_project_id","template_id"],["canvas_templates.project_id","canvas_templates.id"]),
        ForeignKeyConstraint(["project_id","canvas_id"],["creative_canvases.project_id","creative_canvases.id"]))
    for relation in (sessions,turns,refs,attachments,models,decisions,templates,favorites,copies):
        for column in relation.c:
            if column.name.endswith("_id") and column.name not in {"id","project_id","source_project_id"}:Index("ix_%s_%s"%(relation.name,column.name),relation.c.project_id,column)
    return {r.name:r for r in (sessions,turns,refs,attachments,models,decisions,templates,favorites,copies)}
