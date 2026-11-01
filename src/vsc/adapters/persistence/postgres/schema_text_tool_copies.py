"""Cross-project fixed text handoffs keep source and destination identities."""
from sqlalchemy import Column,ForeignKeyConstraint,UniqueConstraint,Index
from sqlalchemy.dialects.postgresql import UUID


def declare_text_tool_copies(project_table,ref,stamp):
    table=project_table('text_tool_copies',
        Column('source_project_id',UUID(as_uuid=False),nullable=False),
        Column('source_version_id',UUID(as_uuid=False),nullable=False),
        ForeignKeyConstraint(['source_project_id','source_version_id'],
            ['artifact_versions.project_id','artifact_versions.id'],ondelete='RESTRICT'),
        *ref('text_tool_units','unit_id'),*ref('artifact_versions','version_id'),stamp(),
        UniqueConstraint('project_id','source_project_id','source_version_id'))
    Index('ix_text_tool_copies_source',table.c.source_project_id,table.c.source_version_id)
    Index('ix_text_tool_copies_unit',table.c.project_id,table.c.unit_id)
    Index('ix_text_tool_copies_version',table.c.project_id,table.c.version_id)
    return {table.name:table}
