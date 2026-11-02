"""Fixed novel adaptation plans and typed episode ranges; expanded text actions."""
from alembic import op
revision="0036_text_product_flow"
down_revision="0035_canvas_product_flow"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE text_tool_novel_plans (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tunit_id UUID NOT NULL, \n'
 '\tbaseline_version_id UUID NOT NULL, \n'
 '\tplan_version_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_novel_plans PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_novel_plans_project_id_unit_id_text_tool_units FOREIGN KEY(project_id, unit_id) '
 'REFERENCES text_tool_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_novel_plans_project_id_baseline_version_id_8bf7 FOREIGN KEY(project_id, '
 'baseline_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_novel_plans_project_id_plan_version_id_art_b8e3 FOREIGN KEY(project_id, '
 'plan_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_novel_plans_project_id_plan_version_id UNIQUE (project_id, plan_version_id), \n'
 '\tCONSTRAINT fk_text_tool_novel_plans_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_novel_plans_baseline_version_id ON text_tool_novel_plans (project_id, '
 'baseline_version_id)',
 'CREATE INDEX ix_text_tool_novel_plans_plan_version_id ON text_tool_novel_plans (project_id, '
 'plan_version_id)',
 'CREATE INDEX ix_text_tool_novel_plans_unit_id ON text_tool_novel_plans (project_id, unit_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_novel_plans FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE text_tool_novel_episodes (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tplan_id UUID NOT NULL, \n'
 '\tunit_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tchapter_start INTEGER NOT NULL, \n'
 '\tchapter_end INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_novel_episodes PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_novel_episodes_project_id_plan_id_text_too_616c FOREIGN KEY(project_id, plan_id) '
 'REFERENCES text_tool_novel_plans (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_novel_episodes_project_id_unit_id_text_tool_units FOREIGN KEY(project_id, '
 'unit_id) REFERENCES text_tool_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_novel_episodes_project_id_plan_id_ordinal UNIQUE (project_id, plan_id, '
 'ordinal), \n'
 '\tCONSTRAINT uq_text_tool_novel_episodes_project_id_unit_id UNIQUE (project_id, unit_id), \n'
 '\tCONSTRAINT ck_text_tool_novel_episodes_range CHECK (ordinal>0 AND chapter_start>0 AND '
 'chapter_end>=chapter_start), \n'
 '\tCONSTRAINT fk_text_tool_novel_episodes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_novel_episodes_plan_id ON text_tool_novel_episodes (project_id, plan_id)',
 'CREATE INDEX ix_text_tool_novel_episodes_unit_id ON text_tool_novel_episodes (project_id, unit_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_novel_episodes FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE text_tool_attempt_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tattempt_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_text_tool_attempt_inputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_text_tool_attempt_inputs_project_id_attempt_id_text__3ff7 FOREIGN KEY(project_id, '
 'attempt_id) REFERENCES text_tool_attempts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_text_tool_attempt_inputs_project_id_version_id_artif_1e60 FOREIGN KEY(project_id, '
 'version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_text_tool_attempt_inputs_project_id_attempt_id_ordinal UNIQUE (project_id, attempt_id, '
 'ordinal), \n'
 '\tCONSTRAINT uq_text_tool_attempt_inputs_project_id_attempt_id_version_id UNIQUE (project_id, attempt_id, '
 'version_id), \n'
 '\tCONSTRAINT ck_text_tool_attempt_inputs_ordinal CHECK (ordinal>=0), \n'
 '\tCONSTRAINT fk_text_tool_attempt_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_text_tool_attempt_inputs_attempt_id ON text_tool_attempt_inputs (project_id, attempt_id)',
 'CREATE INDEX ix_text_tool_attempt_inputs_version_id ON text_tool_attempt_inputs (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON text_tool_attempt_inputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'ALTER TABLE text_tool_attempts DROP CONSTRAINT ck_text_tool_attempts_action',
 'ALTER TABLE text_tool_attempts ADD CONSTRAINT ck_text_tool_attempts_action CHECK (action IN '
 "('synopsis','characters','outline','scenes','body','qa_notes','translate','terms','analyze','score','observe','localize','check'))"]
BINDING="\nCREATE OR REPLACE FUNCTION vsc_text_tool_binding() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE u text_tool_units%ROWTYPE; a artifact_versions%ROWTYPE; r text_tool_attempts%ROWTYPE;\nBEGIN\n IF TG_TABLE_NAME='text_tool_units' THEN\n  SELECT * INTO u FROM text_tool_units WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=u.project_id AND id=u.current_version_id;\n  IF a.id IS NULL OR a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'format' IS DISTINCT FROM 'vsc.text-tool/'||u.tool||'/v1' THEN\n   RAISE EXCEPTION 'text unit must point to its own typed fixed draft' USING ERRCODE='23514'; END IF;\n ELSE\n  SELECT * INTO r FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO u FROM text_tool_units WHERE project_id=r.project_id AND id=r.unit_id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.input_version_id;\n  IF a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text THEN\n   RAISE EXCEPTION 'text attempt input belongs to another unit' USING ERRCODE='23514'; END IF;\n  IF NOT ((u.tool='novel' AND r.action IN ('synopsis','characters','outline','scenes','body','qa_notes')) OR (u.tool='translation' AND r.action IN ('translate','terms')) OR (u.tool='scoring' AND r.action IN ('score','analyze')) OR (u.tool='breakdown' AND r.action='observe') OR (u.tool='qc' AND r.action='check') OR (u.tool='overseas' AND r.action='localize')) THEN\n   RAISE EXCEPTION 'text action does not belong to tool' USING ERRCODE='23514'; END IF;\n  IF r.result_version_id IS NOT NULL THEN\n   SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.result_version_id;\n   IF a.artifact_type<>'text-tool-result' OR convert_from(a.document,'UTF8')::jsonb->>'unit_id' IS DISTINCT FROM u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'input_version_id' IS DISTINCT FROM r.input_version_id::text OR convert_from(a.document,'UTF8')::jsonb->>'action' IS DISTINCT FROM r.action THEN\n    RAISE EXCEPTION 'text result must pin its own input and action' USING ERRCODE='23514'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND $$\n"
MEMBERS="""
CREATE FUNCTION vsc_text_attempt_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; n integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='text_tool_attempts' THEN a:=NEW.id; ELSE a:=NEW.attempt_id; END IF;
 SELECT input_count INTO n FROM text_tool_attempts WHERE project_id=p AND id=a;
 IF n IS DISTINCT FROM (SELECT count(*)::integer FROM text_tool_attempt_inputs WHERE project_id=p AND attempt_id=a)
   OR EXISTS(SELECT 1 FROM text_tool_attempt_inputs WHERE project_id=p AND attempt_id=a AND ordinal>=n) THEN
  RAISE EXCEPTION 'text attempt input members are incomplete or already sealed' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER text_attempt_members AFTER INSERT ON text_tool_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_attempt_members();
CREATE CONSTRAINT TRIGGER text_attempt_members AFTER INSERT ON text_tool_attempt_inputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_attempt_members();
CREATE FUNCTION vsc_text_novel_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; plan uuid; fixed artifact_versions%ROWTYPE; doc jsonb; n integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='text_tool_novel_plans' THEN plan:=NEW.id; ELSE plan:=NEW.plan_id; END IF;
 SELECT a.* INTO fixed FROM artifact_versions a JOIN text_tool_novel_plans b ON b.project_id=a.project_id AND b.plan_version_id=a.id WHERE b.project_id=p AND b.id=plan;
 doc:=convert_from(fixed.document,'UTF8')::jsonb;
 IF fixed.artifact_type IS DISTINCT FROM 'novel-adaptation-plan' OR doc->>'format' IS DISTINCT FROM 'vsc.novel-plan/v1' OR jsonb_typeof(doc->'episodes') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'novel members require their fixed typed plan' USING ERRCODE='23514'; END IF;
 n:=jsonb_array_length(doc->'episodes');
 IF n<1 OR n IS DISTINCT FROM (SELECT count(*)::integer FROM text_tool_novel_episodes WHERE project_id=p AND plan_id=plan)
   OR EXISTS(SELECT 1 FROM text_tool_novel_episodes e JOIN text_tool_units u ON u.project_id=e.project_id AND u.id=e.unit_id
      WHERE e.project_id=p AND e.plan_id=plan AND (u.tool<>'novel' OR NOT EXISTS(
       SELECT 1 FROM jsonb_array_elements(doc->'episodes') row
       WHERE (row->>'ordinal')::integer=e.ordinal AND (row->>'chapter_start')::integer=e.chapter_start AND (row->>'chapter_end')::integer=e.chapter_end))) THEN
  RAISE EXCEPTION 'novel episode members are incomplete, changed, or already sealed' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER text_novel_members AFTER INSERT ON text_tool_novel_plans DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_novel_members();
CREATE CONSTRAINT TRIGGER text_novel_members AFTER INSERT ON text_tool_novel_episodes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_novel_members();
"""
def upgrade():
    op.execute('ALTER TABLE text_tool_attempts ADD COLUMN input_count INTEGER NOT NULL DEFAULT 0, ADD CONSTRAINT ck_text_tool_attempts_input_count CHECK (input_count>=0)')
    for sql in DDL:op.execute(sql)
    op.execute(BINDING)
    op.execute(MEMBERS)
# Frozen pre-0036 definition; no live schema imports during recovery.
LEGACY_BINDING = "\nCREATE OR REPLACE FUNCTION vsc_text_tool_binding() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE u text_tool_units%ROWTYPE; a artifact_versions%ROWTYPE; r text_tool_attempts%ROWTYPE;\nBEGIN\n IF TG_TABLE_NAME='text_tool_units' THEN\n  SELECT * INTO u FROM text_tool_units WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=u.project_id AND id=u.current_version_id;\n  IF a.id IS NULL OR a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'format' IS DISTINCT FROM 'vsc.text-tool/'||u.tool||'/v1' THEN\n   RAISE EXCEPTION 'text unit must point to its own typed fixed draft' USING ERRCODE='23514'; END IF;\n ELSE\n  SELECT * INTO r FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO u FROM text_tool_units WHERE project_id=r.project_id AND id=r.unit_id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.input_version_id;\n  IF a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text THEN\n   RAISE EXCEPTION 'text attempt input belongs to another unit' USING ERRCODE='23514'; END IF;\n  IF NOT ((u.tool='novel' AND r.action IN ('synopsis','characters','outline','scenes','body','qa_notes')) OR (u.tool='translation' AND r.action='translate') OR (u.tool='scoring' AND r.action='score') OR (u.tool='breakdown' AND r.action='observe') OR (u.tool='qc' AND r.action='check') OR (u.tool='overseas' AND r.action='localize')) THEN\n   RAISE EXCEPTION 'text action does not belong to tool' USING ERRCODE='23514'; END IF;\n  IF r.result_version_id IS NOT NULL THEN\n   SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.result_version_id;\n   IF a.artifact_type<>'text-tool-result' OR convert_from(a.document,'UTF8')::jsonb->>'unit_id' IS DISTINCT FROM u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'input_version_id' IS DISTINCT FROM r.input_version_id::text OR convert_from(a.document,'UTF8')::jsonb->>'action' IS DISTINCT FROM r.action THEN\n    RAISE EXCEPTION 'text result must pin its own input and action' USING ERRCODE='23514'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND $$\n"

def downgrade():
    tables=('text_tool_novel_plans','text_tool_novel_episodes','text_tool_attempt_inputs')
    op.execute('LOCK TABLE '+', '.join(tables)+', text_tool_attempts, artifact_versions IN ACCESS EXCLUSIVE MODE')
    predicates=['EXISTS(SELECT 1 FROM '+table+')' for table in tables]
    predicates += ["EXISTS(SELECT 1 FROM text_tool_attempts WHERE action IN ('terms','analyze'))", "EXISTS(SELECT 1 FROM artifact_versions WHERE artifact_type IN ('novel-adaptation-plan','novel-batch-import'))"]
    op.execute("DO $$ BEGIN IF "+' OR '.join(predicates)+" THEN RAISE EXCEPTION 'fixed novel or expanded text history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute(LEGACY_BINDING)
    op.execute('ALTER TABLE text_tool_attempts DROP CONSTRAINT ck_text_tool_attempts_action')
    op.execute("ALTER TABLE text_tool_attempts ADD CONSTRAINT ck_text_tool_attempts_action CHECK (action IN ('synopsis','characters','outline','scenes','body','qa_notes','translate','score','observe','localize','check'))")
    for table in ('text_tool_attempt_inputs','text_tool_novel_episodes','text_tool_novel_plans'):
        op.execute('DROP TABLE '+table)
    op.execute('DROP TRIGGER text_attempt_members ON text_tool_attempts')
    op.execute('DROP FUNCTION vsc_text_attempt_members()')
    op.execute('DROP FUNCTION vsc_text_novel_members()')
    op.execute('ALTER TABLE text_tool_attempts DROP COLUMN input_count')
