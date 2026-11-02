"""Bounded text batches, original attempt links and immutable issue decisions."""
from alembic import op
revision="0037_text_media_review"
down_revision="0036_text_product_flow"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE text_tool_batches (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttool TEXT NOT NULL, \n'
 '\taction TEXT NOT NULL, \n'
 '\tauto_accept BOOLEAN NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\titem_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_batches PRIMARY KEY (project_id, id), \n'
 "\tCONSTRAINT ck_text_tool_batches_status CHECK (status IN ('ready','running','stopped','completed')), \n"
 '\tCONSTRAINT ck_text_tool_batches_item_count CHECK (item_count BETWEEN 1 AND 201), \n'
 '\tCONSTRAINT fk_text_tool_batches_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE text_tool_batch_items (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tbatch_id UUID NOT NULL, \n'
 '\tunit_id UUID NOT NULL, \n'
 '\tinput_version_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\taction TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tattempt_id UUID, \n'
 '\toutput_version_id UUID, \n'
 '\terror_code TEXT, \n'
 '\tCONSTRAINT pk_text_tool_batch_items PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_batch_id_text_tool_batches FOREIGN KEY(project_id, '
 'batch_id) REFERENCES text_tool_batches (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_unit_id_text_tool_units FOREIGN KEY(project_id, unit_id) '
 'REFERENCES text_tool_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_input_version_id_ar_a3cc FOREIGN KEY(project_id, '
 'input_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_attempt_id_text_too_b403 FOREIGN KEY(project_id, '
 'attempt_id) REFERENCES text_tool_attempts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_output_version_id_a_2fe9 FOREIGN KEY(project_id, '
 'output_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_batch_items_project_id_batch_id_ordinal UNIQUE (project_id, batch_id, '
 'ordinal), \n'
 '\tCONSTRAINT ck_text_tool_batch_items_status CHECK (ordinal>=0 AND status IN '
 "('pending','running','completed','failed','blocked','skipped')), \n"
 '\tCONSTRAINT fk_text_tool_batch_items_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_batch_items_attempt_id ON text_tool_batch_items (project_id, attempt_id)',
 'CREATE INDEX ix_text_tool_batch_items_batch_id ON text_tool_batch_items (project_id, batch_id)',
 'CREATE INDEX ix_text_tool_batch_items_input_version_id ON text_tool_batch_items (project_id, '
 'input_version_id)',
 'CREATE INDEX ix_text_tool_batch_items_output_version_id ON text_tool_batch_items (project_id, '
 'output_version_id)',
 'CREATE INDEX ix_text_tool_batch_items_unit_id ON text_tool_batch_items (project_id, unit_id)',
 '\n'
 'CREATE TABLE text_tool_issue_decisions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tissue_index INTEGER NOT NULL, \n'
 '\tdecision TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_issue_decisions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_issue_decisions_project_id_version_id_arti_9ec6 FOREIGN KEY(project_id, '
 'version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_text_tool_issue_decisions_decision CHECK (issue_index>=0 AND decision IN '
 "('open','fixed','dismissed') AND length(reason)>0), \n"
 '\tCONSTRAINT fk_text_tool_issue_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_issue_decisions_version_id ON text_tool_issue_decisions (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_issue_decisions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']
GUARD="\nCREATE FUNCTION vsc_text_batch_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE fixed artifact_versions%ROWTYPE; task text_tool_attempts%ROWTYPE; unit text_tool_units%ROWTYPE; batch text_tool_batches%ROWTYPE;\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'text batch history cannot be deleted' USING ERRCODE='23514'; END IF;\n IF TG_TABLE_NAME='text_tool_batches' THEN\n  IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') THEN RAISE EXCEPTION 'batch request is fixed' USING ERRCODE='23514'; END IF;\n ELSE\n  IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-ARRAY['status','attempt_id','output_version_id','error_code']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','attempt_id','output_version_id','error_code']) OR OLD.status IN ('completed','skipped')) THEN RAISE EXCEPTION 'batch input and terminal item are fixed' USING ERRCODE='23514'; END IF;\n  SELECT * INTO fixed FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.input_version_id;\n  SELECT * INTO unit FROM text_tool_units WHERE project_id=NEW.project_id AND id=NEW.unit_id;\n  SELECT * INTO batch FROM text_tool_batches WHERE project_id=NEW.project_id AND id=NEW.batch_id;\n  IF fixed.artifact_key IS DISTINCT FROM 'text-tool:'||NEW.unit_id::text OR fixed.artifact_type<>'text-tool-draft' OR unit.tool IS DISTINCT FROM batch.tool THEN RAISE EXCEPTION 'batch fixed input scope mismatch' USING ERRCODE='23514'; END IF;\n  IF NEW.attempt_id IS NOT NULL THEN\n   SELECT * INTO task FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.attempt_id;\n   IF task.unit_id IS DISTINCT FROM NEW.unit_id OR task.input_version_id IS DISTINCT FROM NEW.input_version_id OR task.action IS DISTINCT FROM NEW.action THEN RAISE EXCEPTION 'batch task scope mismatch' USING ERRCODE='23514'; END IF;\n  END IF;\n  IF NEW.output_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.output_version_id AND artifact_key='text-tool:'||NEW.unit_id::text AND artifact_type='text-tool-draft') THEN RAISE EXCEPTION 'batch output scope mismatch' USING ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER text_batch_guard BEFORE INSERT OR UPDATE OR DELETE ON text_tool_batches FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_guard();\nCREATE TRIGGER text_batch_guard BEFORE INSERT OR UPDATE OR DELETE ON text_tool_batch_items FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_guard();\n"
MEMBERS="""
CREATE FUNCTION vsc_text_batch_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; b uuid; n integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='text_tool_batches' THEN b:=NEW.id; ELSE b:=NEW.batch_id; END IF;
 SELECT item_count INTO n FROM text_tool_batches WHERE project_id=p AND id=b;
 IF n IS DISTINCT FROM (SELECT count(*)::integer FROM text_tool_batch_items WHERE project_id=p AND batch_id=b)
   OR EXISTS(SELECT 1 FROM text_tool_batch_items WHERE project_id=p AND batch_id=b AND ordinal>=n) THEN
  RAISE EXCEPTION 'text batch members are incomplete or already sealed' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER text_batch_members AFTER INSERT ON text_tool_batches DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_members();
CREATE CONSTRAINT TRIGGER text_batch_members AFTER INSERT ON text_tool_batch_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_members();
"""
def upgrade():
    for sql in DDL:op.execute(sql)
    op.execute(GUARD)
    op.execute(MEMBERS)
def downgrade():
    tables=('text_tool_batches','text_tool_batch_items','text_tool_issue_decisions')
    op.execute('LOCK TABLE '+', '.join(tables)+', artifact_versions IN ACCESS EXCLUSIVE MODE')
    predicates=['EXISTS(SELECT 1 FROM '+table+')' for table in tables]
    predicates += ["EXISTS(SELECT 1 FROM artifact_versions WHERE artifact_type IN ('text-tool-review-report','breakdown-canvas-import'))"]
    op.execute("DO $$ BEGIN IF "+' OR '.join(predicates)+" THEN RAISE EXCEPTION 'text batch or media review history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    for table in ('text_tool_issue_decisions','text_tool_batch_items','text_tool_batches'):
        op.execute('DROP TABLE '+table)
    op.execute('DROP FUNCTION vsc_text_batch_guard()')
    op.execute('DROP FUNCTION vsc_text_batch_members()')
