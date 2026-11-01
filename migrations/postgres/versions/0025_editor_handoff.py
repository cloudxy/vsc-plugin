from alembic import op
revision="0025_editor_handoff"
down_revision="0024_intelligent_production"
branch_labels=None
depends_on=None
DDL=['\nCREATE TABLE edit_timeline_handoffs (\n\tproject_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tedit_version_id UUID NOT NULL, \n\tartifact_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_edit_timeline_handoffs PRIMARY KEY (project_id, id), \n\tCONSTRAINT fk_edit_timeline_handoffs_project_id_edit_version_id_ed_6cad FOREIGN KEY(project_id, edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_edit_timeline_handoffs_project_id_artifact_id_artifa_fd91 FOREIGN KEY(project_id, artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_edit_timeline_handoffs_project_id_artifact_id UNIQUE (project_id, artifact_id), \n\tCONSTRAINT fk_edit_timeline_handoffs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT\n)\n\n', 'CREATE INDEX ix_edit_timeline_handoffs_edit_version_id ON edit_timeline_handoffs (project_id, edit_version_id)', 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_timeline_handoffs FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()']
def upgrade():
    for sql in DDL:op.execute(sql)
def downgrade():
    op.drop_table("edit_timeline_handoffs")
