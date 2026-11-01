"""Fixed canvas Agent operations and immutable templates."""
from alembic import op

revision = "0020_canvas_agent"
down_revision = "0019_access_control"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE canvas_agent_sessions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcanvas_id UUID NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_sessions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_sessions_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, '
 'canvas_id) REFERENCES creative_canvases (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_sessions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_sessions_canvas_id ON canvas_agent_sessions (project_id, canvas_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_sessions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_agent_turns (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tsession_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tdispatch_id UUID NOT NULL, \n'
 '\tparent_turn_id UUID, \n'
 '\tmessage TEXT NOT NULL, \n'
 '\tskill_id TEXT NOT NULL, \n'
 '\tskill_sha256 TEXT NOT NULL, \n'
 '\tmode TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tnode_count INTEGER NOT NULL, \n'
 '\tmodel_count INTEGER NOT NULL, \n'
 '\ttarget_node_key TEXT, \n'
 '\ttarget_shot_id UUID, \n'
 '\texecution_settings JSONB NOT NULL, \n'
 '\thost_result JSONB, \n'
 '\thost_started_at TIMESTAMP WITH TIME ZONE, \n'
 '\terror TEXT, \n'
 '\tplan_artifact_id UUID, \n'
 '\toutput_version_id UUID, \n'
 '\trun_artifact_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_turns PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_canvas_agent_turns_project_id_id_version_id UNIQUE (project_id, id, version_id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_session_id_canvas_agen_68f7 FOREIGN KEY(project_id, '
 'session_id) REFERENCES canvas_agent_sessions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_version_id_creative_ca_25e3 FOREIGN KEY(project_id, '
 'version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_dispatch_id_role_dispatches FOREIGN KEY(project_id, '
 'dispatch_id) REFERENCES role_dispatches (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_parent_turn_id_canvas__4e4c FOREIGN KEY(project_id, '
 'parent_turn_id) REFERENCES canvas_agent_turns (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_version_id_target_node_b8d4 FOREIGN KEY(project_id, '
 'version_id, target_node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_target_shot_id_shots FOREIGN KEY(project_id, target_shot_id) '
 'REFERENCES shots (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_plan_artifact_id_artif_1749 FOREIGN KEY(project_id, '
 'plan_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_output_version_id_crea_0311 FOREIGN KEY(project_id, '
 'output_version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_run_artifact_id_artifa_5f16 FOREIGN KEY(project_id, '
 'run_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 "\tCONSTRAINT ck_canvas_agent_turns_state CHECK (mode IN ('manual','auto_drafts') AND status IN "
 "('queued','running','result_ready','needs_input','planned','applied','rejected','stopped','failed','submission_unknown')), \n"
 '\tCONSTRAINT ck_canvas_agent_turns_counts CHECK (node_count BETWEEN 0 AND 200 AND model_count BETWEEN 0 '
 'AND 8), \n'
 '\tCONSTRAINT ck_canvas_agent_turns_plan_required CHECK (status NOT IN '
 "('needs_input','planned','applied','rejected') OR plan_artifact_id IS NOT NULL), \n"
 '\tCONSTRAINT fk_canvas_agent_turns_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_turns_dispatch_id ON canvas_agent_turns (project_id, dispatch_id)',
 'CREATE INDEX ix_canvas_agent_turns_output_version_id ON canvas_agent_turns (project_id, output_version_id)',
 'CREATE INDEX ix_canvas_agent_turns_parent_turn_id ON canvas_agent_turns (project_id, parent_turn_id)',
 'CREATE INDEX ix_canvas_agent_turns_plan_artifact_id ON canvas_agent_turns (project_id, plan_artifact_id)',
 'CREATE INDEX ix_canvas_agent_turns_run_artifact_id ON canvas_agent_turns (project_id, run_artifact_id)',
 'CREATE INDEX ix_canvas_agent_turns_session_id ON canvas_agent_turns (project_id, session_id)',
 'CREATE INDEX ix_canvas_agent_turns_skill_id ON canvas_agent_turns (project_id, skill_id)',
 'CREATE INDEX ix_canvas_agent_turns_target_shot_id ON canvas_agent_turns (project_id, target_shot_id)',
 'CREATE INDEX ix_canvas_agent_turns_version_id ON canvas_agent_turns (project_id, version_id)',
 '\n'
 'CREATE TABLE canvas_agent_refs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tturn_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_refs PRIMARY KEY (project_id, turn_id, node_key), \n'
 '\tCONSTRAINT fk_canvas_agent_refs_project_id_turn_id_version_id_canv_f4be FOREIGN KEY(project_id, turn_id, '
 'version_id) REFERENCES canvas_agent_turns (project_id, id, version_id), \n'
 '\tCONSTRAINT fk_canvas_agent_refs_project_id_version_id_node_key_cre_a81e FOREIGN KEY(project_id, '
 'version_id, node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_canvas_agent_refs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_refs_turn_id ON canvas_agent_refs (project_id, turn_id)',
 'CREATE INDEX ix_canvas_agent_refs_version_id ON canvas_agent_refs (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_agent_models (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tturn_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tmodel_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_models PRIMARY KEY (project_id, turn_id, ordinal), \n'
 '\tCONSTRAINT uq_canvas_agent_models_project_id_turn_id_model_id UNIQUE (project_id, turn_id, model_id), \n'
 '\tCONSTRAINT fk_canvas_agent_models_project_id_turn_id_canvas_agent_turns FOREIGN KEY(project_id, turn_id) '
 'REFERENCES canvas_agent_turns (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_models_model_id_provider_models FOREIGN KEY(model_id) REFERENCES '
 'provider_models (id), \n'
 '\tCONSTRAINT ck_canvas_agent_models_ordinal CHECK (ordinal BETWEEN 0 AND 7), \n'
 '\tCONSTRAINT fk_canvas_agent_models_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_models_model_id ON canvas_agent_models (project_id, model_id)',
 'CREATE INDEX ix_canvas_agent_models_turn_id ON canvas_agent_models (project_id, turn_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_models FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_agent_decisions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tturn_id UUID NOT NULL, \n'
 '\toutcome TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_decisions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_canvas_agent_decisions_project_id_turn_id UNIQUE (project_id, turn_id), \n'
 '\tCONSTRAINT fk_canvas_agent_decisions_project_id_turn_id_canvas_agent_turns FOREIGN KEY(project_id, '
 'turn_id) REFERENCES canvas_agent_turns (project_id, id), \n'
 '\tCONSTRAINT ck_canvas_agent_decisions_outcome CHECK (outcome IN '
 "('confirm','reject','stop','auto_draft')), \n"
 '\tCONSTRAINT fk_canvas_agent_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_decisions_turn_id ON canvas_agent_decisions (project_id, turn_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_decisions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_templates (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_templates PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_templates_project_id_version_id_creative_canv_8db5 FOREIGN KEY(project_id, '
 'version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_templates_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_templates_version_id ON canvas_templates (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_templates FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_template_favorites (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\ttemplate_id UUID NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tactive BOOLEAN NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_template_favorites PRIMARY KEY (project_id, template_id, actor), \n'
 '\tCONSTRAINT fk_canvas_template_favorites_project_id_template_id_can_d921 FOREIGN KEY(project_id, '
 'template_id) REFERENCES canvas_templates (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_template_favorites_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_template_favorites_template_id ON canvas_template_favorites (project_id, '
 'template_id)',
 '\n'
 'CREATE TABLE canvas_template_copies (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tsource_project_id UUID NOT NULL, \n'
 '\ttemplate_id UUID NOT NULL, \n'
 '\tcanvas_id UUID NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_template_copies PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_template_copies_source_project_id_template_id_fc4c FOREIGN KEY(source_project_id, '
 'template_id) REFERENCES canvas_templates (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_template_copies_project_id_canvas_id_creative_f63e FOREIGN KEY(project_id, '
 'canvas_id) REFERENCES creative_canvases (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_template_copies_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_template_copies_canvas_id ON canvas_template_copies (project_id, canvas_id)',
 'CREATE INDEX ix_canvas_template_copies_template_id ON canvas_template_copies (project_id, template_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_template_copies FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']

DDL += ["""
CREATE FUNCTION vsc_canvas_agent_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; t uuid; n integer; m integer;
BEGIN
 p:=NEW.project_id; IF TG_TABLE_NAME='canvas_agent_turns' THEN t:=NEW.id; ELSE t:=NEW.turn_id; END IF;
 SELECT node_count,model_count INTO n,m FROM canvas_agent_turns WHERE project_id=p AND id=t;
 IF n IS DISTINCT FROM (SELECT count(*)::integer FROM canvas_agent_refs WHERE project_id=p AND turn_id=t)
   OR m IS DISTINCT FROM (SELECT count(*)::integer FROM canvas_agent_models WHERE project_id=p AND turn_id=t) THEN
   RAISE EXCEPTION 'canvas agent input members are incomplete or already sealed' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$
""", """
CREATE FUNCTION vsc_canvas_agent_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE canvas uuid; session_canvas uuid; parent_session uuid;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'canvas agent request is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
   SELECT canvas_id INTO canvas FROM creative_canvas_versions WHERE project_id=NEW.project_id AND id=NEW.version_id;
   SELECT canvas_id INTO session_canvas FROM canvas_agent_sessions WHERE project_id=NEW.project_id AND id=NEW.session_id;
   IF canvas IS DISTINCT FROM session_canvas THEN RAISE EXCEPTION 'canvas agent session/version mismatch' USING ERRCODE='23514'; END IF;
   IF NEW.parent_turn_id IS NOT NULL THEN
     SELECT session_id INTO parent_session FROM canvas_agent_turns WHERE project_id=NEW.project_id AND id=NEW.parent_turn_id;
     IF parent_session IS DISTINCT FROM NEW.session_id THEN RAISE EXCEPTION 'canvas agent parent session mismatch' USING ERRCODE='23514'; END IF;
   END IF;
 ELSE
   IF (to_jsonb(NEW)-ARRAY['status','host_result','host_started_at','error','plan_artifact_id','output_version_id','run_artifact_id'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','host_result','host_started_at','error','plan_artifact_id','output_version_id','run_artifact_id']) THEN
     RAISE EXCEPTION 'canvas agent request is immutable' USING ERRCODE='23514'; END IF;
   IF OLD.host_result IS NOT NULL AND OLD.host_result IS DISTINCT FROM NEW.host_result OR
      OLD.plan_artifact_id IS NOT NULL AND OLD.plan_artifact_id IS DISTINCT FROM NEW.plan_artifact_id OR
      OLD.output_version_id IS NOT NULL AND OLD.output_version_id IS DISTINCT FROM NEW.output_version_id OR
      OLD.run_artifact_id IS NOT NULL AND OLD.run_artifact_id IS DISTINCT FROM NEW.run_artifact_id THEN
     RAISE EXCEPTION 'canvas agent fixed result cannot change' USING ERRCODE='23514'; END IF;
   IF OLD.status<>NEW.status AND NOT (
      OLD.status='queued' AND NEW.status IN ('running','stopped') OR
      OLD.status='running' AND NEW.status IN ('result_ready','submission_unknown','failed','stopped') OR
      OLD.status='submission_unknown' AND NEW.status IN ('result_ready','failed','stopped') OR
      OLD.status='result_ready' AND NEW.status IN ('needs_input','planned','stopped') OR
      OLD.status IN ('needs_input','failed') AND NEW.status='stopped' OR
      OLD.status='planned' AND NEW.status IN ('applied','rejected','stopped')) THEN
     RAISE EXCEPTION 'canvas agent status transition invalid' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$
"""]
for _table in ('canvas_agent_turns','canvas_agent_refs','canvas_agent_models'):
    DDL.append('CREATE CONSTRAINT TRIGGER canvas_agent_members AFTER INSERT ON '+_table+' DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_canvas_agent_members()')
DDL.append('CREATE TRIGGER canvas_agent_identity BEFORE INSERT OR UPDATE OR DELETE ON canvas_agent_turns FOR EACH ROW EXECUTE FUNCTION vsc_canvas_agent_identity()')


def upgrade():
    for sql in DDL:op.execute(sql)


def downgrade():
    for name in ('canvas_template_copies','canvas_template_favorites','canvas_templates','canvas_agent_decisions','canvas_agent_models','canvas_agent_refs','canvas_agent_turns','canvas_agent_sessions'):
        op.drop_table(name)
    for name in ('vsc_canvas_agent_members','vsc_canvas_agent_identity'):op.execute('DROP FUNCTION '+name+'()')
