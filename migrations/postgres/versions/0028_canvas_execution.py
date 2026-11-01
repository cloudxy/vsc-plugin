"""Typed canvas execution provenance and scene planner tasks."""
from alembic import op
revision="0028_canvas_execution"
down_revision="0027_service_access_policy"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE canvas_execution_steps (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tshot_id UUID, \n'
 '\tasset_id UUID, \n'
 '\tspec_id UUID, \n'
 '\trun_artifact_id UUID NOT NULL, \n'
 '\tsource_step_id UUID, \n'
 '\tmodel_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_execution_steps PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_canvas_execution_steps_project_id_source_step_id UNIQUE (project_id, source_step_id), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_version_id_node_ke_350e FOREIGN KEY(project_id, '
 'version_id, node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) '
 'REFERENCES shots (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_asset_id_asset_identities FOREIGN KEY(project_id, '
 'asset_id) REFERENCES asset_identities (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_spec_id_asset_spec_e9b8 FOREIGN KEY(project_id, spec_id) '
 'REFERENCES asset_spec_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_run_artifact_id_ar_f444 FOREIGN KEY(project_id, '
 'run_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_source_step_id_can_b450 FOREIGN KEY(project_id, '
 'source_step_id) REFERENCES canvas_execution_steps (project_id, id), \n'
 '\tCONSTRAINT ck_canvas_execution_steps_shape CHECK ((shot_id IS NULL)<>(asset_id IS NULL) AND (spec_id IS '
 'NULL OR asset_id IS NOT NULL) AND model_count BETWEEN 1 AND 8), \n'
 '\tCONSTRAINT fk_canvas_execution_steps_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_execution_steps_asset_id ON canvas_execution_steps (project_id, asset_id)',
 'CREATE INDEX ix_canvas_execution_steps_run_artifact_id ON canvas_execution_steps (project_id, '
 'run_artifact_id)',
 'CREATE INDEX ix_canvas_execution_steps_shot_id ON canvas_execution_steps (project_id, shot_id)',
 'CREATE INDEX ix_canvas_execution_steps_source_step_id ON canvas_execution_steps (project_id, '
 'source_step_id)',
 'CREATE INDEX ix_canvas_execution_steps_spec_id ON canvas_execution_steps (project_id, spec_id)',
 'CREATE INDEX ix_canvas_execution_steps_version_id ON canvas_execution_steps (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_execution_steps FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_execution_models (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tstep_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tmodel_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_execution_models PRIMARY KEY (project_id, step_id, ordinal), \n'
 '\tCONSTRAINT uq_canvas_execution_models_project_id_step_id_model_id UNIQUE (project_id, step_id, '
 'model_id), \n'
 '\tCONSTRAINT fk_canvas_execution_models_project_id_step_id_canvas_ex_5cf9 FOREIGN KEY(project_id, step_id) '
 'REFERENCES canvas_execution_steps (project_id, id), \n'
 '\tCONSTRAINT ck_canvas_execution_models_ordinal CHECK (ordinal BETWEEN 0 AND 7), \n'
 '\tCONSTRAINT fk_canvas_execution_models_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id), \n'
 '\tCONSTRAINT fk_canvas_execution_models_model_id_provider_models FOREIGN KEY(model_id) REFERENCES '
 'provider_models (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_execution_models_model_id ON canvas_execution_models (project_id, model_id)',
 'CREATE INDEX ix_canvas_execution_models_step_id ON canvas_execution_models (project_id, step_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_execution_models FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE spatial_plan_tasks (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tdispatch_id UUID NOT NULL, \n'
 '\tmessage TEXT NOT NULL, \n'
 '\tskill_sha256 TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\thost_result JSONB, \n'
 '\terror TEXT, \n'
 '\tplan_artifact_id UUID, \n'
 '\toutput_version_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_plan_tasks PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_plan_tasks_project_id_version_id_spatial_sce_9e1a FOREIGN KEY(project_id, '
 'version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_plan_tasks_project_id_dispatch_id_role_dispatches FOREIGN KEY(project_id, '
 'dispatch_id) REFERENCES role_dispatches (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_plan_tasks_project_id_plan_artifact_id_artif_3793 FOREIGN KEY(project_id, '
 'plan_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_plan_tasks_project_id_output_version_id_spat_2d8e FOREIGN KEY(project_id, '
 'output_version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 '\tCONSTRAINT ck_spatial_plan_tasks_status CHECK (status IN '
 "('queued','running','result_ready','needs_input','planned','applied','rejected','stopped','failed','submission_unknown')), \n"
 '\tCONSTRAINT fk_spatial_plan_tasks_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_plan_tasks_dispatch_id ON spatial_plan_tasks (project_id, dispatch_id)',
 'CREATE INDEX ix_spatial_plan_tasks_output_version_id ON spatial_plan_tasks (project_id, output_version_id)',
 'CREATE INDEX ix_spatial_plan_tasks_plan_artifact_id ON spatial_plan_tasks (project_id, plan_artifact_id)',
 'CREATE INDEX ix_spatial_plan_tasks_version_id ON spatial_plan_tasks (project_id, version_id)',
 '\n'
 'CREATE TABLE spatial_plan_decisions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttask_id UUID NOT NULL, \n'
 '\toutcome TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_plan_decisions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_spatial_plan_decisions_project_id_task_id UNIQUE (project_id, task_id), \n'
 '\tCONSTRAINT fk_spatial_plan_decisions_project_id_task_id_spatial_plan_tasks FOREIGN KEY(project_id, '
 'task_id) REFERENCES spatial_plan_tasks (project_id, id), \n'
 "\tCONSTRAINT ck_spatial_plan_decisions_outcome CHECK (outcome IN ('confirm','reject','stop')), \n"
 '\tCONSTRAINT fk_spatial_plan_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_plan_decisions_task_id ON spatial_plan_decisions (project_id, task_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON spatial_plan_decisions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE canvas_agent_action_results (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tturn_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tbase_version_id UUID NOT NULL, \n'
 '\toutput_version_id UUID, \n'
 '\trun_artifact_id UUID, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_agent_action_results PRIMARY KEY (project_id, turn_id, ordinal), \n'
 '\tCONSTRAINT fk_canvas_agent_action_results_project_id_turn_id_canva_b1c7 FOREIGN KEY(project_id, turn_id) '
 'REFERENCES canvas_agent_turns (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_action_results_project_id_base_version__d0e1 FOREIGN KEY(project_id, '
 'base_version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_action_results_project_id_output_versio_c285 FOREIGN KEY(project_id, '
 'output_version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_agent_action_results_project_id_run_artifact__dd42 FOREIGN KEY(project_id, '
 'run_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT ck_canvas_agent_action_results_ordinal CHECK (ordinal BETWEEN 0 AND 7), \n'
 '\tCONSTRAINT fk_canvas_agent_action_results_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_canvas_agent_action_results_base_version_id ON canvas_agent_action_results (project_id, '
 'base_version_id)',
 'CREATE INDEX ix_canvas_agent_action_results_output_version_id ON canvas_agent_action_results (project_id, '
 'output_version_id)',
 'CREATE INDEX ix_canvas_agent_action_results_run_artifact_id ON canvas_agent_action_results (project_id, '
 'run_artifact_id)',
 'CREATE INDEX ix_canvas_agent_action_results_turn_id ON canvas_agent_action_results (project_id, turn_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_action_results FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_asset_runs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tasset_key TEXT NOT NULL, \n'
 '\trun_artifact_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_asset_runs PRIMARY KEY (project_id, version_id, asset_key, run_artifact_id), \n'
 '\tCONSTRAINT fk_intelligent_asset_runs_project_id_version_id_asset_k_62f7 FOREIGN KEY(project_id, '
 'version_id, asset_key) REFERENCES intelligent_assets (project_id, version_id, asset_key), \n'
 '\tCONSTRAINT fk_intelligent_asset_runs_project_id_run_artifact_id_ar_e31f FOREIGN KEY(project_id, '
 'run_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_asset_runs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_asset_runs_run_artifact_id ON intelligent_asset_runs (project_id, '
 'run_artifact_id)',
 'CREATE INDEX ix_intelligent_asset_runs_version_id ON intelligent_asset_runs (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_asset_runs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE FUNCTION vsc_canvas_execution_members() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE p uuid; step uuid; expected integer; rowdata record; parent record; request jsonb; task jsonb;\n'
 'BEGIN\n'
 "p:=NEW.project_id; IF TG_TABLE_NAME='canvas_execution_steps' THEN step:=NEW.id; ELSE step:=NEW.step_id; "
 'END IF;\n'
 'SELECT model_count INTO expected FROM canvas_execution_steps WHERE project_id=p AND id=step;\n'
 'IF expected IS DISTINCT FROM (SELECT count(*)::integer FROM canvas_execution_models WHERE project_id=p AND '
 'step_id=step) OR EXISTS(SELECT 1 FROM canvas_execution_models WHERE project_id=p AND step_id=step AND '
 "ordinal>=expected) THEN RAISE EXCEPTION 'execution model members incomplete or sealed' USING "
 "ERRCODE='23514'; END IF;\n"
 'SELECT * INTO rowdata FROM canvas_execution_steps WHERE project_id=p AND id=step;\n'
 "SELECT convert_from(document,'UTF8')::jsonb->'series_batch'->'jobs'->0 INTO task FROM artifact_versions "
 'WHERE project_id=p AND id=rowdata.run_artifact_id;\n'
 "request:=task->'request';\n"
 "IF (request->>'shot_id')::uuid IS DISTINCT FROM rowdata.shot_id OR (request->>'asset_id')::uuid IS "
 "DISTINCT FROM rowdata.asset_id OR (request->>'spec_version_id')::uuid IS DISTINCT FROM rowdata.spec_id OR "
 "(task->>'model_id')::uuid IS DISTINCT FROM (SELECT model_id FROM canvas_execution_models WHERE "
 "project_id=p AND step_id=step AND ordinal=0) THEN RAISE EXCEPTION 'execution target/model must match "
 "original run' USING ERRCODE='23514'; END IF;\n"
 'IF rowdata.source_step_id IS NOT NULL THEN\n'
 ' SELECT * INTO parent FROM canvas_execution_steps WHERE project_id=p AND id=rowdata.source_step_id;\n'
 ' IF expected<>parent.model_count-1 OR EXISTS(SELECT 1 FROM canvas_execution_models child LEFT JOIN '
 'canvas_execution_models prior_model ON prior_model.project_id=child.project_id AND '
 'prior_model.step_id=parent.id AND prior_model.ordinal=child.ordinal+1 WHERE child.project_id=p AND '
 'child.step_id=step AND child.model_id IS DISTINCT FROM prior_model.model_id) OR NOT EXISTS(SELECT 1 FROM '
 'generation_jobs WHERE project_id=p AND run_version_id=parent.run_artifact_id) OR EXISTS(SELECT 1 FROM '
 "generation_jobs WHERE project_id=p AND run_version_id=parent.run_artifact_id AND status<>'failed') THEN "
 "RAISE EXCEPTION 'fallback requires failed original jobs and next fixed model order' USING ERRCODE='23514'; "
 'END IF;\n'
 'END IF;\n'
 'RETURN NULL; END $$',
 'CREATE CONSTRAINT TRIGGER execution_members AFTER INSERT ON canvas_execution_steps DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_canvas_execution_members()',
 'CREATE CONSTRAINT TRIGGER execution_members AFTER INSERT ON canvas_execution_models DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_canvas_execution_members()',
 'CREATE FUNCTION vsc_canvas_execution_links() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE old_step record; actual uuid; kind text;\n'
 'BEGIN\n'
 'IF NEW.spec_id IS NOT NULL THEN SELECT asset_id INTO actual FROM asset_spec_versions WHERE '
 'project_id=NEW.project_id AND id=NEW.spec_id; IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION '
 "'execution asset/spec mismatch' USING ERRCODE='23514'; END IF; END IF;\n"
 'SELECT artifact_type INTO kind FROM artifact_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.run_artifact_id;\n'
 "IF kind NOT IN ('production-run','vsc.production_run') THEN RAISE EXCEPTION 'execution must reference "
 "original run' USING ERRCODE='23514'; END IF;\n"
 'IF NEW.source_step_id IS NOT NULL THEN SELECT * INTO old_step FROM canvas_execution_steps WHERE '
 'project_id=NEW.project_id AND id=NEW.source_step_id; IF '
 '(NEW.version_id,NEW.node_key,NEW.shot_id,NEW.asset_id,NEW.spec_id) IS DISTINCT FROM '
 '(old_step.version_id,old_step.node_key,old_step.shot_id,old_step.asset_id,old_step.spec_id) THEN RAISE '
 "EXCEPTION 'fallback target changed' USING ERRCODE='23514'; END IF; END IF;\n"
 'RETURN NEW; END $$',
 'CREATE TRIGGER execution_links BEFORE INSERT ON canvas_execution_steps FOR EACH ROW EXECUTE FUNCTION '
 'vsc_canvas_execution_links()',
 'CREATE TRIGGER spatial_plan_guard BEFORE UPDATE OR DELETE ON spatial_plan_tasks FOR EACH ROW EXECUTE '
 'FUNCTION vsc_intelligent_task_guard()']

def upgrade():
    for sql in DDL:op.execute(sql)

def downgrade():
    for name in ('intelligent_asset_runs', 'canvas_agent_action_results', 'spatial_plan_decisions', 'spatial_plan_tasks', 'canvas_execution_models', 'canvas_execution_steps'):op.drop_table(name)
    for name in ("vsc_canvas_execution_links","vsc_canvas_execution_members"):op.execute("DROP FUNCTION "+name+"()")
