"""Explicit fixed text handoffs from independent tool workspaces."""
from alembic import op
revision="0031_text_tool_copies"
down_revision="0030_edit_cancel"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE text_tool_copies (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tsource_project_id UUID NOT NULL, \n'
 '\tsource_version_id UUID NOT NULL, \n'
 '\tunit_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_copies PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_copies_source_project_id_source_version_id_ae70 FOREIGN KEY(source_project_id, '
 'source_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_copies_project_id_unit_id_text_tool_units FOREIGN KEY(project_id, unit_id) '
 'REFERENCES text_tool_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_copies_project_id_version_id_artifact_versions FOREIGN KEY(project_id, '
 'version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_copies_project_id_source_project_id_source_f6c1 UNIQUE (project_id, '
 'source_project_id, source_version_id), \n'
 '\tCONSTRAINT fk_text_tool_copies_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_copies_source ON text_tool_copies (source_project_id, source_version_id)',
 'CREATE INDEX ix_text_tool_copies_unit ON text_tool_copies (project_id, unit_id)',
 'CREATE INDEX ix_text_tool_copies_version ON text_tool_copies (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_copies FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()']
def upgrade():
    for sql in DDL:op.execute(sql)
def downgrade():
    op.drop_table("text_tool_copies")
