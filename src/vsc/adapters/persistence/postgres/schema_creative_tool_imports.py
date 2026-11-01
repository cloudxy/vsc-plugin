"""A fixed local-tool output copied to one target episode, under original media authority."""
from sqlalchemy import Column,Text,ForeignKeyConstraint,UniqueConstraint,Index,CheckConstraint
from sqlalchemy.dialects.postgresql import UUID


def declare_creative_tool_imports(project_table,ref,stamp):
    table=project_table('creative_tool_imports',
        *ref('episodes','episode_id'),
        Column('media_id',UUID(as_uuid=False),nullable=False),
        Column('blob_id',UUID(as_uuid=False),nullable=False),
        Column('source_project_id',UUID(as_uuid=False),nullable=False),
        Column('source_artifact_id',UUID(as_uuid=False),nullable=False),
        Column('source_media_id',UUID(as_uuid=False),nullable=False),
        Column('sha256',Text,nullable=False),stamp(),
        ForeignKeyConstraint(['source_project_id','source_artifact_id'],
            ['artifact_versions.project_id','artifact_versions.id'],ondelete='RESTRICT'),
        ForeignKeyConstraint(['source_project_id','source_media_id','blob_id'],
            ['media_items.project_id','media_items.id','media_items.blob_id'],ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id','media_id','blob_id'],
            ['media_items.project_id','media_items.id','media_items.blob_id'],ondelete='RESTRICT'),
        ForeignKeyConstraint(['blob_id','sha256'],
            ['media_blobs.id','media_blobs.sha256'],ondelete='RESTRICT'),
        UniqueConstraint('project_id','episode_id','source_project_id','source_artifact_id','source_media_id'),
        CheckConstraint('project_id <> source_project_id',name='different_project'))
    for field in ('episode_id','media_id'):
        Index('ix_creative_tool_imports_'+field,table.c.project_id,table.c[field])
    for field in ('source_artifact_id','source_media_id'):
        Index('ix_creative_tool_imports_'+field,table.c.source_project_id,table.c[field])
    Index('ix_creative_tool_imports_blob',table.c.blob_id,table.c.sha256)
    return {table.name:table}
