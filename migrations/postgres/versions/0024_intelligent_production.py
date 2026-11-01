"""Versioned intelligent creation/storyboard consumers."""
from alembic import op
revision="0024_intelligent_production"
down_revision="0023_service_operations"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE intelligent_definitions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tkey TEXT NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_definitions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_intelligent_definitions_project_id_key_version UNIQUE (project_id, key, '
 'version), \n'
 '\tCONSTRAINT fk_intelligent_definitions_project_id_artifact_id_artif_cc85 FOREIGN '
 'KEY(project_id, artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_definitions_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_definitions_artifact_id ON intelligent_definitions (project_id, '
 'artifact_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_definitions FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_workflows (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID NOT NULL, \n'
 '\tdefinition_id UUID NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_workflows PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_workflows_project_id_episode_id_episodes FOREIGN KEY(project_id, '
 'episode_id) REFERENCES episodes (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_workflows_project_id_definition_id_intel_9173 FOREIGN '
 'KEY(project_id, definition_id) REFERENCES intelligent_definitions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_workflows_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_workflows_definition_id ON intelligent_workflows (project_id, '
 'definition_id)',
 'CREATE INDEX ix_intelligent_workflows_episode_id ON intelligent_workflows (project_id, '
 'episode_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_workflows FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tworkflow_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tparent_id UUID, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tsource_artifact_id UUID, \n'
 '\ttemplate_artifact_id UUID, \n'
 '\troute TEXT NOT NULL, \n'
 '\tblocking_mode TEXT NOT NULL, \n'
 '\tunit_count INTEGER NOT NULL, \n'
 '\tasset_count INTEGER NOT NULL, \n'
 '\tdependency_count INTEGER NOT NULL, \n'
 '\tmedia_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_intelligent_versions_project_id_workflow_id_version UNIQUE (project_id, '
 'workflow_id, version), \n'
 '\tCONSTRAINT uq_intelligent_versions_project_id_workflow_id_id UNIQUE (project_id, workflow_id, '
 'id), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_workflow_id_intellig_fffd FOREIGN '
 'KEY(project_id, workflow_id) REFERENCES intelligent_workflows (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_artifact_id_artifact_c812 FOREIGN '
 'KEY(project_id, artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_source_artifact_id_a_ec48 FOREIGN '
 'KEY(project_id, source_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_template_artifact_id_86a3 FOREIGN '
 'KEY(project_id, template_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_workflow_id_parent_i_d855 FOREIGN '
 'KEY(project_id, workflow_id, parent_id) REFERENCES intelligent_versions (project_id, '
 'workflow_id, id), \n'
 '\tCONSTRAINT ck_intelligent_versions_route CHECK (route IN '
 "('creation','storyboard','storyboard_video','multi_reference_video') AND blocking_mode IN "
 "('2d','3d','skip')), \n"
 '\tCONSTRAINT ck_intelligent_versions_counts CHECK (version>0 AND unit_count BETWEEN 0 AND 200 '
 'AND asset_count BETWEEN 0 AND 200 AND dependency_count BETWEEN 0 AND 1000 AND media_count '
 'BETWEEN 0 AND 2000), \n'
 '\tCONSTRAINT fk_intelligent_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_versions_artifact_id ON intelligent_versions (project_id, '
 'artifact_id)',
 'CREATE INDEX ix_intelligent_versions_parent_id ON intelligent_versions (project_id, parent_id)',
 'CREATE INDEX ix_intelligent_versions_source_artifact_id ON intelligent_versions (project_id, '
 'source_artifact_id)',
 'CREATE INDEX ix_intelligent_versions_template_artifact_id ON intelligent_versions (project_id, '
 'template_artifact_id)',
 'CREATE INDEX ix_intelligent_versions_workflow_id ON intelligent_versions (project_id, '
 'workflow_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_versions FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_assets (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tasset_key TEXT NOT NULL, \n'
 '\tasset_id UUID NOT NULL, \n'
 '\tspec_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_assets PRIMARY KEY (project_id, version_id, asset_key), \n'
 '\tCONSTRAINT fk_intelligent_assets_project_id_version_id_intelligent_41d0 FOREIGN '
 'KEY(project_id, version_id) REFERENCES intelligent_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_assets_project_id_asset_id_asset_identities FOREIGN KEY(project_id, '
 'asset_id) REFERENCES asset_identities (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_assets_project_id_spec_id_asset_spec_versions FOREIGN '
 'KEY(project_id, spec_id) REFERENCES asset_spec_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_assets_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_assets_asset_id ON intelligent_assets (project_id, asset_id)',
 'CREATE INDEX ix_intelligent_assets_spec_id ON intelligent_assets (project_id, spec_id)',
 'CREATE INDEX ix_intelligent_assets_version_id ON intelligent_assets (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_assets FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_units (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tunit_key TEXT NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tdescription TEXT NOT NULL, \n'
 '\tduration_ms INTEGER NOT NULL, \n'
 '\tsegments JSONB NOT NULL, \n'
 '\tskip_reason TEXT NOT NULL, \n'
 '\tlineart_purpose TEXT NOT NULL, \n'
 '\tshot_id UUID, \n'
 '\tspatial_version_id UUID, \n'
 '\tCONSTRAINT pk_intelligent_units PRIMARY KEY (project_id, version_id, unit_key), \n'
 '\tCONSTRAINT uq_intelligent_units_project_id_version_id_ordinal UNIQUE (project_id, version_id, '
 'ordinal), \n'
 '\tCONSTRAINT fk_intelligent_units_project_id_version_id_intelligent_versions FOREIGN '
 'KEY(project_id, version_id) REFERENCES intelligent_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_units_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) '
 'REFERENCES shots (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_units_project_id_spatial_version_id_spat_9d7f FOREIGN '
 'KEY(project_id, spatial_version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 "\tCONSTRAINT ck_intelligent_units_shape CHECK (kind IN ('blocking','shot') AND lineart_purpose "
 "IN ('none','reference_image','first_frame') AND duration_ms BETWEEN 1 AND 3600000 AND "
 'ordinal>=0), \n'
 '\tCONSTRAINT fk_intelligent_units_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_units_shot_id ON intelligent_units (project_id, shot_id)',
 'CREATE INDEX ix_intelligent_units_spatial_version_id ON intelligent_units (project_id, '
 'spatial_version_id)',
 'CREATE INDEX ix_intelligent_units_version_id ON intelligent_units (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_units FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_dependencies (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tunit_key TEXT NOT NULL, \n'
 '\tsource_version_id UUID NOT NULL, \n'
 '\tsource_unit_key TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_dependencies PRIMARY KEY (project_id, version_id, unit_key, '
 'source_version_id, source_unit_key), \n'
 '\tCONSTRAINT fk_intelligent_dependencies_project_id_version_id_unit__6170 FOREIGN '
 'KEY(project_id, version_id, unit_key) REFERENCES intelligent_units (project_id, version_id, '
 'unit_key), \n'
 '\tCONSTRAINT fk_intelligent_dependencies_project_id_source_version_i_d49c FOREIGN '
 'KEY(project_id, source_version_id, source_unit_key) REFERENCES intelligent_units (project_id, '
 'version_id, unit_key), \n'
 "\tCONSTRAINT ck_intelligent_dependencies_edge CHECK (purpose IN ('anchor','blocking') AND NOT "
 '(version_id=source_version_id AND unit_key=source_unit_key)), \n'
 '\tCONSTRAINT fk_intelligent_dependencies_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_dependencies_source_version_id ON intelligent_dependencies '
 '(project_id, source_version_id)',
 'CREATE INDEX ix_intelligent_dependencies_version_id ON intelligent_dependencies (project_id, '
 'version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_dependencies FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_media (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tunit_key TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tdecision_id UUID NOT NULL, \n'
 '\tspatial_export_id UUID, \n'
 '\tCONSTRAINT pk_intelligent_media PRIMARY KEY (project_id, version_id, unit_key, purpose, '
 'media_id), \n'
 '\tCONSTRAINT fk_intelligent_media_project_id_version_id_unit_key_int_f616 FOREIGN '
 'KEY(project_id, version_id, unit_key) REFERENCES intelligent_units (project_id, version_id, '
 'unit_key), \n'
 '\tCONSTRAINT fk_intelligent_media_project_id_media_id_media_items FOREIGN KEY(project_id, '
 'media_id) REFERENCES media_items (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_media_project_id_decision_id_binding_decisions FOREIGN '
 'KEY(project_id, decision_id) REFERENCES binding_decisions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_media_project_id_spatial_export_id_spati_a203 FOREIGN '
 'KEY(project_id, spatial_export_id) REFERENCES spatial_exports (project_id, id), \n'
 '\tCONSTRAINT ck_intelligent_media_purpose CHECK (purpose IN '
 "('blocking','lineart','reference_image','first_frame')), \n"
 '\tCONSTRAINT fk_intelligent_media_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_media_decision_id ON intelligent_media (project_id, decision_id)',
 'CREATE INDEX ix_intelligent_media_media_id ON intelligent_media (project_id, media_id)',
 'CREATE INDEX ix_intelligent_media_spatial_export_id ON intelligent_media (project_id, '
 'spatial_export_id)',
 'CREATE INDEX ix_intelligent_media_version_id ON intelligent_media (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_media FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_runs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tunit_key TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tdraft_artifact_id UUID NOT NULL, \n'
 '\trun_artifact_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_runs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_runs_project_id_version_id_unit_key_inte_44bb FOREIGN '
 'KEY(project_id, version_id, unit_key) REFERENCES intelligent_units (project_id, version_id, '
 'unit_key), \n'
 '\tCONSTRAINT fk_intelligent_runs_project_id_draft_artifact_id_artifa_e0cc FOREIGN '
 'KEY(project_id, draft_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_runs_project_id_run_artifact_id_artifact_3ec4 FOREIGN '
 'KEY(project_id, run_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_runs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_runs_draft_artifact_id ON intelligent_runs (project_id, '
 'draft_artifact_id)',
 'CREATE INDEX ix_intelligent_runs_run_artifact_id ON intelligent_runs (project_id, '
 'run_artifact_id)',
 'CREATE INDEX ix_intelligent_runs_version_id ON intelligent_runs (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_runs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE intelligent_tasks (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tdispatch_id UUID NOT NULL, \n'
 '\tstage TEXT NOT NULL, \n'
 '\tmessage TEXT NOT NULL, \n'
 '\tskill_id TEXT NOT NULL, \n'
 '\tskill_sha256 TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE, \n'
 '\thost_result JSONB, \n'
 '\terror TEXT, \n'
 '\tplan_artifact_id UUID, \n'
 '\toutput_version_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_tasks PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_tasks_project_id_version_id_intelligent_versions FOREIGN '
 'KEY(project_id, version_id) REFERENCES intelligent_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_tasks_project_id_dispatch_id_role_dispatches FOREIGN KEY(project_id, '
 'dispatch_id) REFERENCES role_dispatches (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_tasks_project_id_plan_artifact_id_artifa_1ab2 FOREIGN '
 'KEY(project_id, plan_artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_intelligent_tasks_project_id_output_version_id_intel_0df1 FOREIGN '
 'KEY(project_id, output_version_id) REFERENCES intelligent_versions (project_id, id), \n'
 "\tCONSTRAINT ck_intelligent_tasks_state CHECK (stage IN ('assets','blocking','script') AND "
 'status IN '
 "('queued','running','result_ready','needs_input','planned','applied','rejected','stopped','failed','submission_unknown')), \n"
 '\tCONSTRAINT fk_intelligent_tasks_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_tasks_dispatch_id ON intelligent_tasks (project_id, dispatch_id)',
 'CREATE INDEX ix_intelligent_tasks_output_version_id ON intelligent_tasks (project_id, '
 'output_version_id)',
 'CREATE INDEX ix_intelligent_tasks_plan_artifact_id ON intelligent_tasks (project_id, '
 'plan_artifact_id)',
 'CREATE INDEX ix_intelligent_tasks_skill_id ON intelligent_tasks (project_id, skill_id)',
 'CREATE INDEX ix_intelligent_tasks_version_id ON intelligent_tasks (project_id, version_id)',
 '\n'
 'CREATE TABLE intelligent_decisions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttask_id UUID NOT NULL, \n'
 '\toutcome TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_intelligent_decisions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_intelligent_decisions_project_id_task_id UNIQUE (project_id, task_id), \n'
 '\tCONSTRAINT fk_intelligent_decisions_project_id_task_id_intelligent_tasks FOREIGN '
 'KEY(project_id, task_id) REFERENCES intelligent_tasks (project_id, id), \n'
 "\tCONSTRAINT ck_intelligent_decisions_outcome CHECK (outcome IN ('confirm','reject','stop')), \n"
 '\tCONSTRAINT fk_intelligent_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_intelligent_decisions_task_id ON intelligent_decisions (project_id, task_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON intelligent_decisions FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 'CREATE FUNCTION vsc_intelligent_members() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE p uuid; v uuid; counts record;\n'
 'BEGIN\n'
 " p:=NEW.project_id; IF TG_TABLE_NAME='intelligent_versions' THEN v:=NEW.id; ELSE "
 'v:=NEW.version_id; END IF;\n'
 ' SELECT * INTO counts FROM intelligent_versions WHERE project_id=p AND id=v;\n'
 ' IF counts.unit_count IS DISTINCT FROM (SELECT count(*)::integer FROM intelligent_units WHERE '
 'project_id=p AND version_id=v) OR\n'
 ' counts.asset_count IS DISTINCT FROM (SELECT count(*)::integer FROM intelligent_assets WHERE '
 'project_id=p AND version_id=v) OR\n'
 ' counts.media_count IS DISTINCT FROM (SELECT count(*)::integer FROM intelligent_media WHERE '
 'project_id=p AND version_id=v) OR\n'
 ' counts.dependency_count IS DISTINCT FROM (SELECT count(*)::integer FROM '
 'intelligent_dependencies WHERE project_id=p AND version_id=v) THEN\n'
 " RAISE EXCEPTION 'intelligent version members are incomplete or sealed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' RETURN NULL;\n'
 'END $$',
 'CREATE CONSTRAINT TRIGGER intelligent_members AFTER INSERT ON intelligent_versions DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_intelligent_members()',
 'CREATE CONSTRAINT TRIGGER intelligent_members AFTER INSERT ON intelligent_units DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_intelligent_members()',
 'CREATE CONSTRAINT TRIGGER intelligent_members AFTER INSERT ON intelligent_assets DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_intelligent_members()',
 'CREATE CONSTRAINT TRIGGER intelligent_members AFTER INSERT ON intelligent_media DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_intelligent_members()',
 'CREATE CONSTRAINT TRIGGER intelligent_members AFTER INSERT ON intelligent_dependencies '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_intelligent_members()',
 'CREATE FUNCTION vsc_intelligent_links() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE actual uuid; wanted uuid;\n'
 'BEGIN\n'
 " IF TG_TABLE_NAME='intelligent_assets' THEN\n"
 ' SELECT asset_id INTO actual FROM asset_spec_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.spec_id;\n'
 " IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION 'asset/spec mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " ELSIF TG_TABLE_NAME='intelligent_dependencies' THEN\n"
 ' SELECT workflow_id INTO actual FROM intelligent_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.version_id;\n'
 ' SELECT workflow_id INTO wanted FROM intelligent_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.source_version_id;\n'
 " IF actual IS DISTINCT FROM wanted THEN RAISE EXCEPTION 'cross workflow dependency' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF EXISTS(WITH RECURSIVE edges(v,k) AS (\n'
 ' SELECT NEW.source_version_id,NEW.source_unit_key UNION\n'
 ' SELECT d.source_version_id,d.source_unit_key FROM intelligent_dependencies d JOIN edges e ON '
 'd.version_id=e.v AND d.unit_key=e.k WHERE d.project_id=NEW.project_id\n'
 " ) SELECT 1 FROM edges WHERE v=NEW.version_id AND k=NEW.unit_key) THEN RAISE EXCEPTION 'cyclic "
 "workflow dependency' USING ERRCODE='23514'; END IF;\n"
 " ELSIF TG_TABLE_NAME='intelligent_media' THEN\n"
 ' SELECT c.media_id INTO actual FROM binding_decisions d JOIN binding_candidates c ON '
 'd.project_id=c.project_id AND d.candidate_id=c.id WHERE d.project_id=NEW.project_id AND '
 "d.id=NEW.decision_id AND d.outcome='select';\n"
 " IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'media must match original "
 "selection decision' USING ERRCODE='23514'; END IF;\n"
 ' IF NEW.spatial_export_id IS NOT NULL THEN\n'
 ' SELECT media_id INTO actual FROM spatial_export_outputs WHERE project_id=NEW.project_id AND '
 'export_id=NEW.spatial_export_id;\n'
 " IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'spatial screenshot mismatch' "
 "USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 ' END IF;\n'
 ' RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER intelligent_links BEFORE INSERT ON intelligent_assets FOR EACH ROW EXECUTE '
 'FUNCTION vsc_intelligent_links()',
 'CREATE TRIGGER intelligent_links BEFORE INSERT ON intelligent_dependencies FOR EACH ROW EXECUTE '
 'FUNCTION vsc_intelligent_links()',
 'CREATE TRIGGER intelligent_links BEFORE INSERT ON intelligent_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_intelligent_links()',
 'CREATE FUNCTION vsc_intelligent_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN RAISE EXCEPTION 'task history immutable' USING ERRCODE='23514'; END IF;\n"
 ' IF '
 "(to_jsonb(NEW)-ARRAY['status','started_at','host_result','error','plan_artifact_id','output_version_id']) "
 'IS DISTINCT FROM '
 "(to_jsonb(OLD)-ARRAY['status','started_at','host_result','error','plan_artifact_id','output_version_id']) "
 "THEN RAISE EXCEPTION 'task input immutable' USING ERRCODE='23514'; END IF;\n"
 ' IF OLD.host_result IS NOT NULL AND OLD.host_result IS DISTINCT FROM NEW.host_result OR '
 'OLD.plan_artifact_id IS NOT NULL AND OLD.plan_artifact_id IS DISTINCT FROM NEW.plan_artifact_id '
 'OR OLD.output_version_id IS NOT NULL AND OLD.output_version_id IS DISTINCT FROM '
 "NEW.output_version_id THEN RAISE EXCEPTION 'task result immutable' USING ERRCODE='23514'; END "
 'IF;\n'
 " IF OLD.status<>NEW.status AND NOT(OLD.status='queued' AND NEW.status IN ('running','stopped') "
 "OR OLD.status='running' AND NEW.status IN "
 "('result_ready','failed','submission_unknown','stopped') OR OLD.status='submission_unknown' AND "
 "NEW.status IN ('result_ready','failed','stopped') OR OLD.status='result_ready' AND NEW.status IN "
 "('planned','needs_input','stopped') OR OLD.status='planned' AND NEW.status IN "
 "('applied','rejected','stopped') OR OLD.status IN ('needs_input','failed') AND "
 "NEW.status='stopped') THEN RAISE EXCEPTION 'task state transition invalid' USING "
 "ERRCODE='23514'; END IF;\n"
 ' RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER intelligent_task_guard BEFORE UPDATE OR DELETE ON intelligent_tasks FOR EACH ROW '
 'EXECUTE FUNCTION vsc_intelligent_task_guard()']

def upgrade():
    for sql in DDL:op.execute(sql)

def downgrade():
    for name in ('intelligent_decisions', 'intelligent_tasks', 'intelligent_runs', 'intelligent_media', 'intelligent_dependencies', 'intelligent_units', 'intelligent_assets', 'intelligent_versions', 'intelligent_workflows', 'intelligent_definitions'):op.drop_table(name)
    for name in ("vsc_intelligent_members","vsc_intelligent_links","vsc_intelligent_task_guard"):op.execute("DROP FUNCTION "+name+"()")
