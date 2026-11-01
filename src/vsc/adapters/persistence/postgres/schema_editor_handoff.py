"""The working revision that produced an original canonical timeline artifact."""
from sqlalchemy import UniqueConstraint, Index

EDITOR_HANDOFF_IMMUTABLE=('edit_timeline_handoffs',)


def declare_editor_handoff(project_table, ref, stamp):
    table=project_table('edit_timeline_handoffs',*ref('edit_revisions','edit_version_id'),
        *ref('artifact_versions','artifact_id'),stamp(),UniqueConstraint('project_id','artifact_id'))
    Index('ix_edit_timeline_handoffs_edit_version_id',table.c.project_id,table.c.edit_version_id)
    return {table.name:table}
