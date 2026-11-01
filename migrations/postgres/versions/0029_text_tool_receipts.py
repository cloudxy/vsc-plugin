"""Retain accepted text-host responses across access revocation."""
from alembic import op
revision="0029_text_tool_receipts"
down_revision="0028_canvas_execution"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE text_tool_receipts (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tattempt_id UUID NOT NULL, \n'
 '\tresult JSONB, \n'
 '\terror_code TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_receipts PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_receipts_project_id_attempt_id_text_tool_attempts FOREIGN KEY(project_id, '
 'attempt_id) REFERENCES text_tool_attempts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_receipts_project_id_attempt_id UNIQUE (project_id, attempt_id), \n'
 '\tCONSTRAINT ck_text_tool_receipts_outcome CHECK ((result IS NOT NULL) <> (error_code IS NOT NULL)), \n'
 '\tCONSTRAINT fk_text_tool_receipts_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_receipts_attempt_id ON text_tool_receipts (project_id, attempt_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_receipts FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']
def upgrade():
    for sql in DDL:op.execute(sql)
def downgrade():
    op.drop_table("text_tool_receipts")
