"""Typed text-tool editing units and bounded host attempts; no execution queue."""
from sqlalchemy import Column, Integer, Text, Boolean, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB


TEXT_TOOL_TABLES = ("text_tool_units", "text_tool_attempts", "text_tool_receipts", "text_tool_novel_plans", "text_tool_novel_episodes", "text_tool_attempt_inputs", "text_tool_batches", "text_tool_batch_items", "text_tool_issue_decisions")


def declare_text_tools(project_table, ref, uid, stamp):
    units = project_table("text_tool_units",
        Column("tool", Text, nullable=False), Column("group_key", Text, nullable=False),
        Column("unit_key", Text, nullable=False), Column("title", Text, nullable=False),
        Column("ordinal", Integer, nullable=False), *ref("episodes", "episode_id", nullable=True),
        *ref("artifact_versions", "current_version_id", nullable=True),
        Column("locked", Boolean, nullable=False, server_default="false"), stamp(),
        UniqueConstraint("project_id", "tool", "group_key", "unit_key"),
        CheckConstraint("tool IN ('novel','translation','scoring','breakdown','qc','overseas')", name="tool"),
        CheckConstraint("ordinal >= 0 AND length(group_key) BETWEEN 1 AND 100 AND length(unit_key) BETWEEN 1 AND 100", name="identity"))
    attempts = project_table("text_tool_attempts", *ref("text_tool_units", "unit_id"),
        *ref("artifact_versions", "input_version_id"), Column("action", Text, nullable=False),
        Column("backend", Text, nullable=False), Column("status", Text, nullable=False),
        Column("input_count", Integer, nullable=False, server_default="0"),
        *ref("artifact_versions", "result_version_id", nullable=True),
        Column("error_code", Text), Column("created_by", Text, nullable=False), stamp(),
        CheckConstraint("action IN ('synopsis','characters','outline','scenes','body','qa_notes','translate','terms','analyze','score','observe','understand','localize','check')", name="action"),
        CheckConstraint("status IN ('running','completed','failed','submission_unknown')", name="status"),
        CheckConstraint("input_count>=0", name="input_count"),
        CheckConstraint("(status='completed') = (result_version_id IS NOT NULL)", name="result"))
    Index("uq_text_tool_unit_running", attempts.c.project_id, attempts.c.unit_id, unique=True,
          postgresql_where=text("status = 'running'"))
    receipts = project_table("text_tool_receipts", *ref("text_tool_attempts", "attempt_id"),
        Column("result", JSONB(none_as_null=True)), Column("error_code", Text), stamp(),
        UniqueConstraint("project_id", "attempt_id"),
        CheckConstraint("(result IS NOT NULL) <> (error_code IS NOT NULL)", name="outcome"))
    plans = project_table('text_tool_novel_plans', *ref('text_tool_units','unit_id'),
        *ref('artifact_versions','baseline_version_id'), *ref('artifact_versions','plan_version_id'), stamp(),
        UniqueConstraint('project_id','plan_version_id'))
    episodes = project_table('text_tool_novel_episodes', *ref('text_tool_novel_plans','plan_id'),
        *ref('text_tool_units','unit_id'), Column('ordinal',Integer,nullable=False),
        Column('chapter_start',Integer,nullable=False),Column('chapter_end',Integer,nullable=False),
        UniqueConstraint('project_id','plan_id','ordinal'),UniqueConstraint('project_id','unit_id'),
        CheckConstraint('ordinal>0 AND chapter_start>0 AND chapter_end>=chapter_start',name='range'))
    inputs = project_table('text_tool_attempt_inputs', *ref('text_tool_attempts','attempt_id'),
        *ref('artifact_versions','version_id'),Column('ordinal',Integer,nullable=False),
        UniqueConstraint('project_id','attempt_id','ordinal'),UniqueConstraint('project_id','attempt_id','version_id'),
        CheckConstraint('ordinal>=0',name='ordinal'))
    batches=project_table('text_tool_batches',Column('tool',Text,nullable=False),Column('action',Text,nullable=False),Column('auto_accept',Boolean,nullable=False),
        Column('status',Text,nullable=False),Column('item_count',Integer,nullable=False),Column('created_by',Text,nullable=False),stamp(),
        CheckConstraint('item_count BETWEEN 1 AND 201',name='item_count'),CheckConstraint("status IN ('ready','running','stopped','completed')",name='status'))
    items=project_table('text_tool_batch_items',*ref('text_tool_batches','batch_id'),*ref('text_tool_units','unit_id'),*ref('artifact_versions','input_version_id'),
        Column('ordinal',Integer,nullable=False),Column('action',Text,nullable=False),Column('status',Text,nullable=False),
        *ref('text_tool_attempts','attempt_id',nullable=True),*ref('artifact_versions','output_version_id',nullable=True),Column('error_code',Text),
        UniqueConstraint('project_id','batch_id','ordinal'),CheckConstraint("ordinal>=0 AND status IN ('pending','running','completed','failed','blocked','skipped')",name='status'))
    decisions=project_table('text_tool_issue_decisions',*ref('artifact_versions','version_id'),Column('issue_index',Integer,nullable=False),Column('decision',Text,nullable=False),
        Column('reason',Text,nullable=False),Column('created_by',Text,nullable=False),stamp(),CheckConstraint("issue_index>=0 AND decision IN ('open','fixed','dismissed') AND length(reason)>0",name='decision'))
    for table in (units, attempts, receipts, plans, episodes, inputs, batches, items, decisions):
        for col in table.c:
            if col.name.endswith("_id") and col.name not in {"id", "project_id"}:
                Index("ix_"+table.name+"_"+col.name, table.c.project_id, col)
    return {t.name:t for t in (units, attempts, receipts, plans, episodes, inputs, batches, items, decisions)}
