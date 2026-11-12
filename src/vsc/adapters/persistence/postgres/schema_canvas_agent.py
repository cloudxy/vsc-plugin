"""Fixed canvas planning inputs and template versions; no parallel ACL."""
from sqlalchemy import Table,Column,Text,String,Integer,Boolean,DateTime,ForeignKeyConstraint,PrimaryKeyConstraint,UniqueConstraint,CheckConstraint,Index,text
from sqlalchemy.dialects.postgresql import UUID,JSONB

CANVAS_AGENT_TABLES=(
    "canvas_agent_attachments","canvas_agent_sessions","canvas_agent_session_states",
    "canvas_agent_turns","canvas_agent_queue_items","canvas_agent_refs",
    "canvas_agent_models","canvas_agent_decisions","canvas_templates",
    "canvas_template_favorites","canvas_template_copies","canvas_camera_motion_templates",
)
CANVAS_AGENT_IMMUTABLE=("canvas_agent_attachments","canvas_agent_sessions","canvas_agent_refs","canvas_agent_models","canvas_agent_decisions","canvas_templates","canvas_template_copies")


def install_canvas_agent_schema(metadata):
    def uid(name,**kw):return Column(name,UUID(as_uuid=False),**kw)
    def table(name,*columns):return Table(name,metadata,uid("project_id",nullable=False),*columns,ForeignKeyConstraint(["project_id"],["projects.id"]))
    def stamp():return Column("created_at",DateTime(timezone=True),nullable=False,server_default=text("now()"))
    sessions=table("canvas_agent_sessions",uid("id",nullable=False),uid("canvas_id",nullable=False),Column("title",Text,nullable=False),Column("created_by",Text,nullable=False),stamp(),
        PrimaryKeyConstraint("project_id","id"),ForeignKeyConstraint(["project_id","canvas_id"],["creative_canvases.project_id","creative_canvases.id"]))
    session_states=table("canvas_agent_session_states",uid("session_id",nullable=False),
        Column("title",Text,nullable=False),
        Column("archived",Boolean,nullable=False,server_default=text("false")),
        Column("auto_approve",Boolean,nullable=False,server_default=text("false")),
        Column("updated_by",Text,nullable=False),
        Column("updated_at",DateTime(timezone=True),nullable=False,server_default=text("now()")),
        PrimaryKeyConstraint("project_id","session_id"),
        ForeignKeyConstraint(["project_id","session_id"],["canvas_agent_sessions.project_id","canvas_agent_sessions.id"]),
        CheckConstraint("btrim(title) <> '' AND char_length(title) <= 200 AND btrim(updated_by) <> ''",name="session_state_bounds"))
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
    queue_items=table("canvas_agent_queue_items",uid("id",nullable=False),uid("session_id",nullable=False),
        Column("ordinal",Integer,nullable=False),
        Column("message",Text,nullable=False),
        Column("skill_id",Text,nullable=False),
        Column("mode",Text,nullable=False),
        Column("status",Text,nullable=False,server_default=text("'queued'")),
        uid("dispatched_turn_id"),
        Column("created_by",Text,nullable=False),
        stamp(),
        Column("updated_at",DateTime(timezone=True),nullable=False,server_default=text("now()")),
        PrimaryKeyConstraint("project_id","id"),
        ForeignKeyConstraint(["project_id","session_id"],["canvas_agent_sessions.project_id","canvas_agent_sessions.id"]),
        ForeignKeyConstraint(["project_id","dispatched_turn_id"],["canvas_agent_turns.project_id","canvas_agent_turns.id"]),
        CheckConstraint("ordinal >= 0 AND btrim(message) <> '' AND char_length(message) <= 6000 AND btrim(skill_id) <> '' AND mode IN ('manual','auto_drafts') AND status IN ('queued','steered','editing','dispatched','cancelled') AND btrim(created_by) <> ''",name="queue_item_state"))
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
    camera_motions=table("canvas_camera_motion_templates",uid("id",nullable=False),
        Column("name",Text,nullable=False),
        Column("prompt_fragment",Text,nullable=False),
        Column("horizontal_pan",Integer,nullable=False,server_default=text("0")),
        Column("vertical_tilt",Integer,nullable=False,server_default=text("0")),
        Column("zoom_delta",Integer,nullable=False,server_default=text("0")),
        Column("roll_deg",Integer,nullable=False,server_default=text("0")),
        Column("speed_preset",Text,nullable=False,server_default=text("'normal'")),
        Column("favorite",Boolean,nullable=False,server_default=text("false")),
        Column("archived",Boolean,nullable=False,server_default=text("false")),
        Column("created_by",Text,nullable=False),
        stamp(),
        Column("updated_at",DateTime(timezone=True),nullable=False,server_default=text("now()")),
        PrimaryKeyConstraint("project_id","id"),
        CheckConstraint("btrim(name) <> '' AND char_length(name) <= 100 AND char_length(prompt_fragment) <= 1000 AND horizontal_pan BETWEEN -100 AND 100 AND vertical_tilt BETWEEN -100 AND 100 AND zoom_delta BETWEEN -100 AND 100 AND roll_deg BETWEEN -45 AND 45 AND speed_preset IN ('slow','normal','fast') AND btrim(created_by) <> ''",name="camera_motion_bounds"))
    Index("ix_canvas_camera_motion_templates_active",camera_motions.c.project_id,camera_motions.c.archived,camera_motions.c.favorite)
    all_relations=(sessions,session_states,turns,queue_items,refs,attachments,models,decisions,templates,favorites,copies,camera_motions)
    for relation in all_relations:
        pk_cols={col.name for col in relation.primary_key.columns}
        for column in relation.c:
            if column.name.endswith("_id") and column.name not in {"id","project_id","source_project_id"} and not (pk_cols=={"project_id",column.name}):
                Index("ix_%s_%s"%(relation.name,column.name),relation.c.project_id,column)
    return {r.name:r for r in all_relations}
