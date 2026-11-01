"""Typed text-tool editing units and bounded host attempts; no execution queue."""
from sqlalchemy import Column, Integer, Text, Boolean, CheckConstraint, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB


TEXT_TOOL_TABLES = ("text_tool_units", "text_tool_attempts", "text_tool_receipts")


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
        *ref("artifact_versions", "result_version_id", nullable=True),
        Column("error_code", Text), Column("created_by", Text, nullable=False), stamp(),
        CheckConstraint("action IN ('synopsis','characters','outline','scenes','body','qa_notes','translate','score','observe','localize','check')", name="action"),
        CheckConstraint("status IN ('running','completed','failed','submission_unknown')", name="status"),
        CheckConstraint("(status='completed') = (result_version_id IS NOT NULL)", name="result"))
    Index("uq_text_tool_unit_running", attempts.c.project_id, attempts.c.unit_id, unique=True,
          postgresql_where=text("status = 'running'"))
    receipts = project_table("text_tool_receipts", *ref("text_tool_attempts", "attempt_id"),
        Column("result", JSONB(none_as_null=True)), Column("error_code", Text), stamp(),
        UniqueConstraint("project_id", "attempt_id"),
        CheckConstraint("(result IS NOT NULL) <> (error_code IS NOT NULL)", name="outcome"))
    for table in (units, attempts, receipts):
        for col in table.c:
            if col.name.endswith("_id") and col.name not in {"id", "project_id"}:
                Index("ix_"+table.name+"_"+col.name, table.c.project_id, col)
    return {t.name:t for t in (units, attempts, receipts)}
