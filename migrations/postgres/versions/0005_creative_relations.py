"""Immutable creative-use, sound, execution and quality evidence projections."""
from alembic import op
revision = "0005_creative_relations"
down_revision = "0004_trial_adoptions"
branch_labels = None
depends_on = None

DDL = ['CREATE TABLE method_evaluations (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tmethod_artifact_id UUID NOT NULL, \n'
 '\ttrial_run_id UUID NOT NULL, \n'
 '\tbaseline_media_id UUID NOT NULL, \n'
 '\toutput_media_id UUID NOT NULL, \n'
 '\tcriteria_artifact_id UUID NOT NULL, \n'
 '\tresult TEXT NOT NULL, \n'
 '\tenvironment_sha256 VARCHAR(64) NOT NULL, \n'
 '\tCONSTRAINT pk_method_evaluations PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_method_artifact_id_art_431c FOREIGN KEY(project_id, '
 'method_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_trial_run_id_artifact_versions FOREIGN KEY(project_id, '
 'trial_run_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_baseline_media_id_media_items FOREIGN KEY(project_id, '
 'baseline_media_id) REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_output_media_id_media_items FOREIGN KEY(project_id, '
 'output_media_id) REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_method_evaluations_project_id_criteria_artifact_id_a_4c7a FOREIGN KEY(project_id, '
 'criteria_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_method_evaluations_result CHECK (result IN ('pass','fail','unknown')), \n"
 '\tCONSTRAINT fk_method_evaluations_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_method_evaluations_environment_sha256_format CHECK (environment_sha256 IS NULL OR '
 "environment_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')',
 'CREATE INDEX ix_method_evaluations_project_artifact_id ON method_evaluations (project_id, artifact_id)',
 'CREATE INDEX ix_method_evaluations_project_baseline_media_id ON method_evaluations (project_id, '
 'baseline_media_id)',
 'CREATE INDEX ix_method_evaluations_project_criteria_artifact_id ON method_evaluations (project_id, '
 'criteria_artifact_id)',
 'CREATE INDEX ix_method_evaluations_project_method_artifact_id ON method_evaluations (project_id, '
 'method_artifact_id)',
 'CREATE INDEX ix_method_evaluations_project_output_media_id ON method_evaluations (project_id, '
 'output_media_id)',
 'CREATE INDEX ix_method_evaluations_project_trial_run_id ON method_evaluations (project_id, trial_run_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON method_evaluations FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE execution_instances (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tmethod_artifact_id UUID, \n'
 '\tline_id UUID, \n'
 '\tvoice_spec_id UUID, \n'
 '\texecution_key TEXT NOT NULL, \n'
 '\tlabel TEXT NOT NULL, \n'
 '\tdomain TEXT NOT NULL, \n'
 '\tparameters JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_execution_instances PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_execution_instances_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_instances_project_id_method_artifact_id_ar_864f FOREIGN KEY(project_id, '
 'method_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_instances_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) '
 'REFERENCES script_lines (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_instances_project_id_voice_spec_id_voice_s_852c FOREIGN KEY(project_id, '
 'voice_spec_id) REFERENCES voice_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_execution_instances_domain CHECK (domain IN '
 "('combat','dance','vfx','voice','acting','action')), \n"
 '\tCONSTRAINT uq_execution_instances_project_id_artifact_id_execution_key UNIQUE (project_id, artifact_id, '
 'execution_key), \n'
 '\tCONSTRAINT fk_execution_instances_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_execution_instances_project_artifact_id ON execution_instances (project_id, artifact_id)',
 'CREATE INDEX ix_execution_instances_project_line_id ON execution_instances (project_id, line_id)',
 'CREATE INDEX ix_execution_instances_project_method_artifact_id ON execution_instances (project_id, '
 'method_artifact_id)',
 'CREATE INDEX ix_execution_instances_project_voice_spec_id ON execution_instances (project_id, '
 'voice_spec_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON execution_instances FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE script_line_dispositions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tline_id UUID NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tdisposition TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_script_line_dispositions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_script_line_dispositions_project_id_artifact_id_arti_0102 FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_script_line_dispositions_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) '
 'REFERENCES script_lines (project_id, id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_script_line_dispositions_disposition CHECK (disposition IN ('omit','defer')), \n"
 '\tCONSTRAINT uq_script_line_dispositions_project_id_artifact_id_line_id UNIQUE (project_id, artifact_id, '
 'line_id), \n'
 '\tCONSTRAINT fk_script_line_dispositions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_script_line_dispositions_project_artifact_id ON script_line_dispositions (project_id, '
 'artifact_id)',
 'CREATE INDEX ix_script_line_dispositions_project_line_id ON script_line_dispositions (project_id, line_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_line_dispositions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE execution_materials (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\texecution_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_execution_materials PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_execution_materials_project_id_execution_id_executio_2c04 FOREIGN KEY(project_id, '
 'execution_id) REFERENCES execution_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_materials_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_execution_materials_project_id_execution_id_media_id_role UNIQUE (project_id, '
 'execution_id, media_id, role), \n'
 '\tCONSTRAINT fk_execution_materials_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_execution_materials_project_execution_id ON execution_materials (project_id, execution_id)',
 'CREATE INDEX ix_execution_materials_project_media_id ON execution_materials (project_id, media_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON execution_materials FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE execution_shots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\texecution_id UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_execution_shots PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_execution_shots_project_id_execution_id_execution_instances FOREIGN KEY(project_id, '
 'execution_id) REFERENCES execution_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_shots_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES shots '
 '(project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_execution_shots_project_id_execution_id_shot_id UNIQUE (project_id, execution_id, '
 'shot_id), \n'
 '\tCONSTRAINT fk_execution_shots_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_execution_shots_project_execution_id ON execution_shots (project_id, execution_id)',
 'CREATE INDEX ix_execution_shots_project_shot_id ON execution_shots (project_id, shot_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON execution_shots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TABLE sound_cues (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tscope_object_id UUID NOT NULL, \n'
 '\tline_id UUID, \n'
 '\tvoice_spec_id UUID, \n'
 '\texecution_id UUID, \n'
 '\tsubtitle_version_id UUID, \n'
 '\tlipsync_version_id UUID, \n'
 '\tcue_key TEXT NOT NULL, \n'
 '\tlabel TEXT NOT NULL, \n'
 '\tcue_kind TEXT NOT NULL, \n'
 '\tparameters JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_sound_cues PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_sound_cues_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, artifact_id) '
 'REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_scope_object_id_creative_objects FOREIGN KEY(project_id, '
 'scope_object_id) REFERENCES creative_objects (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) REFERENCES '
 'script_lines (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_voice_spec_id_voice_spec_versions FOREIGN KEY(project_id, '
 'voice_spec_id) REFERENCES voice_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_execution_id_execution_instances FOREIGN KEY(project_id, '
 'execution_id) REFERENCES execution_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_subtitle_version_id_artifact_versions FOREIGN KEY(project_id, '
 'subtitle_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_sound_cues_project_id_lipsync_version_id_artifact_versions FOREIGN KEY(project_id, '
 'lipsync_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_sound_cues_cue_kind CHECK (cue_kind IN '
 "('dialogue','narration','ambience','foley','sfx','music','silence')), \n"
 '\tCONSTRAINT uq_sound_cues_project_id_artifact_id_cue_key UNIQUE (project_id, artifact_id, cue_key), \n'
 '\tCONSTRAINT fk_sound_cues_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE '
 'RESTRICT\n'
 ')',
 'CREATE INDEX ix_sound_cues_project_artifact_id ON sound_cues (project_id, artifact_id)',
 'CREATE INDEX ix_sound_cues_project_execution_id ON sound_cues (project_id, execution_id)',
 'CREATE INDEX ix_sound_cues_project_line_id ON sound_cues (project_id, line_id)',
 'CREATE INDEX ix_sound_cues_project_lipsync_version_id ON sound_cues (project_id, lipsync_version_id)',
 'CREATE INDEX ix_sound_cues_project_scope_object_id ON sound_cues (project_id, scope_object_id)',
 'CREATE INDEX ix_sound_cues_project_subtitle_version_id ON sound_cues (project_id, subtitle_version_id)',
 'CREATE INDEX ix_sound_cues_project_voice_spec_id ON sound_cues (project_id, voice_spec_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON sound_cues FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TABLE asset_use_instances (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tasset_id UUID NOT NULL, \n'
 '\tspec_version_id UUID, \n'
 '\tstate_id UUID, \n'
 '\tscene_id UUID NOT NULL, \n'
 '\tshot_id UUID, \n'
 '\tinstance_key TEXT NOT NULL, \n'
 '\tlabel TEXT NOT NULL, \n'
 '\tstate JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_asset_use_instances PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_asset_id_asset_identities FOREIGN KEY(project_id, asset_id) '
 'REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_spec_version_id_asset_0b0f FOREIGN KEY(project_id, '
 'spec_version_id) REFERENCES asset_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_state_id_state_versions FOREIGN KEY(project_id, state_id) '
 'REFERENCES state_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) '
 'REFERENCES scenes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_asset_id_spec_version_1d45 FOREIGN KEY(project_id, '
 'asset_id, spec_version_id) REFERENCES asset_spec_versions (project_id, asset_id, id), \n'
 '\tCONSTRAINT uq_asset_use_instances_project_id_artifact_id_instance_key UNIQUE (project_id, artifact_id, '
 'instance_key), \n'
 '\tCONSTRAINT fk_asset_use_instances_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_asset_use_instances_project_artifact_id ON asset_use_instances (project_id, artifact_id)',
 'CREATE INDEX ix_asset_use_instances_project_asset_id ON asset_use_instances (project_id, asset_id)',
 'CREATE INDEX ix_asset_use_instances_project_scene_id ON asset_use_instances (project_id, scene_id)',
 'CREATE INDEX ix_asset_use_instances_project_shot_id ON asset_use_instances (project_id, shot_id)',
 'CREATE INDEX ix_asset_use_instances_project_spec_version_id ON asset_use_instances (project_id, '
 'spec_version_id)',
 'CREATE INDEX ix_asset_use_instances_project_state_id ON asset_use_instances (project_id, state_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON asset_use_instances FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE cue_shots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcue_id UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\tstart_ms INTEGER, \n'
 '\tend_ms INTEGER, \n'
 '\tCONSTRAINT pk_cue_shots PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_cue_shots_project_id_cue_id_sound_cues FOREIGN KEY(project_id, cue_id) REFERENCES '
 'sound_cues (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_cue_shots_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES shots '
 '(project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_cue_shots_range CHECK ((start_ms IS NULL AND end_ms IS NULL) OR (start_ms IS NOT NULL AND '
 'end_ms IS NOT NULL AND start_ms >= 0 AND end_ms > start_ms)), \n'
 '\tCONSTRAINT uq_cue_shots_project_id_cue_id_shot_id UNIQUE (project_id, cue_id, shot_id), \n'
 '\tCONSTRAINT fk_cue_shots_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE '
 'RESTRICT\n'
 ')',
 'CREATE INDEX ix_cue_shots_project_cue_id ON cue_shots (project_id, cue_id)',
 'CREATE INDEX ix_cue_shots_project_shot_id ON cue_shots (project_id, shot_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON cue_shots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TABLE cue_timeline_items (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcue_id UUID NOT NULL, \n'
 '\titem_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_cue_timeline_items PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_cue_timeline_items_project_id_cue_id_sound_cues FOREIGN KEY(project_id, cue_id) REFERENCES '
 'sound_cues (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_cue_timeline_items_project_id_item_id_timeline_items FOREIGN KEY(project_id, item_id) '
 'REFERENCES timeline_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_cue_timeline_items_project_id_cue_id_item_id UNIQUE (project_id, cue_id, item_id), \n'
 '\tCONSTRAINT fk_cue_timeline_items_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_cue_timeline_items_project_cue_id ON cue_timeline_items (project_id, cue_id)',
 'CREATE INDEX ix_cue_timeline_items_project_item_id ON cue_timeline_items (project_id, item_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON cue_timeline_items FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE quality_observations (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tmedia_id UUID, \n'
 '\tmethod_artifact_id UUID, \n'
 '\tcriteria_artifact_id UUID NOT NULL, \n'
 '\tresult TEXT NOT NULL, \n'
 '\tdefect_code TEXT, \n'
 '\tobservation TEXT NOT NULL, \n'
 '\tposition JSONB NOT NULL, \n'
 '\teffort_seconds INTEGER, \n'
 '\twait_seconds INTEGER, \n'
 '\tcost_amount NUMERIC(20, 6), \n'
 '\tcost_unit TEXT, \n'
 '\tcost_basis TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_quality_observations PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_quality_observations_project_id_artifact_id_artifact_3b31 FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_quality_observations_project_id_job_id_generation_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES generation_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_quality_observations_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_quality_observations_project_id_method_artifact_id_a_3dbc FOREIGN KEY(project_id, '
 'method_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_quality_observations_project_id_criteria_artifact_id_0c00 FOREIGN KEY(project_id, '
 'criteria_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_quality_observations_result CHECK (result IN ('usable','failed','unknown')), \n"
 "\tCONSTRAINT ck_quality_observations_cost_basis CHECK (cost_basis IN ('actual','estimate','unknown')), \n"
 '\tCONSTRAINT ck_quality_observations_nonnegative CHECK ((effort_seconds IS NULL OR effort_seconds >= 0) '
 'AND (wait_seconds IS NULL OR wait_seconds >= 0) AND (cost_amount IS NULL OR cost_amount >= 0)), \n'
 '\tCONSTRAINT fk_quality_observations_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_quality_observations_project_artifact_id ON quality_observations (project_id, artifact_id)',
 'CREATE INDEX ix_quality_observations_project_criteria_artifact_id ON quality_observations (project_id, '
 'criteria_artifact_id)',
 'CREATE INDEX ix_quality_observations_project_job_id ON quality_observations (project_id, job_id)',
 'CREATE INDEX ix_quality_observations_project_media_id ON quality_observations (project_id, media_id)',
 'CREATE INDEX ix_quality_observations_project_method_artifact_id ON quality_observations (project_id, '
 'method_artifact_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON quality_observations FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE cue_slots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcue_id UUID NOT NULL, \n'
 '\tslot_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_cue_slots PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_cue_slots_project_id_cue_id_sound_cues FOREIGN KEY(project_id, cue_id) REFERENCES '
 'sound_cues (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_cue_slots_project_id_slot_id_binding_slots FOREIGN KEY(project_id, slot_id) REFERENCES '
 'binding_slots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_cue_slots_project_id_cue_id_slot_id UNIQUE (project_id, cue_id, slot_id), \n'
 '\tCONSTRAINT fk_cue_slots_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE '
 'RESTRICT\n'
 ')',
 'CREATE INDEX ix_cue_slots_project_cue_id ON cue_slots (project_id, cue_id)',
 'CREATE INDEX ix_cue_slots_project_slot_id ON cue_slots (project_id, slot_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON cue_slots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TABLE execution_participants (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\texecution_id UUID NOT NULL, \n'
 '\tinstance_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_execution_participants PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_execution_participants_project_id_execution_id_execu_31af FOREIGN KEY(project_id, '
 'execution_id) REFERENCES execution_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_participants_project_id_instance_id_asset__b83b FOREIGN KEY(project_id, '
 'instance_id) REFERENCES asset_use_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_execution_participants_project_id_execution_id_insta_dd26 UNIQUE (project_id, '
 'execution_id, instance_id, role), \n'
 '\tCONSTRAINT fk_execution_participants_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_execution_participants_project_execution_id ON execution_participants (project_id, '
 'execution_id)',
 'CREATE INDEX ix_execution_participants_project_instance_id ON execution_participants (project_id, '
 'instance_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON execution_participants FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TABLE execution_slots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\texecution_id UUID NOT NULL, \n'
 '\tslot_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_execution_slots PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_execution_slots_project_id_execution_id_execution_instances FOREIGN KEY(project_id, '
 'execution_id) REFERENCES execution_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_execution_slots_project_id_slot_id_binding_slots FOREIGN KEY(project_id, slot_id) '
 'REFERENCES binding_slots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_execution_slots_project_id_execution_id_slot_id_role UNIQUE (project_id, execution_id, '
 'slot_id, role), \n'
 '\tCONSTRAINT fk_execution_slots_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_execution_slots_project_execution_id ON execution_slots (project_id, execution_id)',
 'CREATE INDEX ix_execution_slots_project_slot_id ON execution_slots (project_id, slot_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON execution_slots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TABLE instance_interactions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tsubject_id UUID NOT NULL, \n'
 '\tobject_id UUID NOT NULL, \n'
 '\trelation TEXT NOT NULL, \n'
 '\thand TEXT, \n'
 '\tparameters JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_instance_interactions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_instance_interactions_project_id_artifact_id_artifac_2d7d FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_instance_interactions_project_id_subject_id_asset_us_9e8e FOREIGN KEY(project_id, '
 'subject_id) REFERENCES asset_use_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_instance_interactions_project_id_object_id_asset_use_b3dc FOREIGN KEY(project_id, '
 'object_id) REFERENCES asset_use_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_instance_interactions_distinct_instances CHECK (subject_id <> object_id), \n'
 '\tCONSTRAINT ck_instance_interactions_relation CHECK (relation IN '
 "('holds','wears','touches','supports','targets','restores','consumes')), \n"
 '\tCONSTRAINT fk_instance_interactions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')',
 'CREATE INDEX ix_instance_interactions_project_artifact_id ON instance_interactions (project_id, '
 'artifact_id)',
 'CREATE INDEX ix_instance_interactions_project_object_id ON instance_interactions (project_id, object_id)',
 'CREATE INDEX ix_instance_interactions_project_subject_id ON instance_interactions (project_id, subject_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON instance_interactions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']

def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    op.drop_table('instance_interactions')
    op.drop_table('execution_slots')
    op.drop_table('execution_participants')
    op.drop_table('cue_slots')
    op.drop_table('quality_observations')
    op.drop_table('cue_timeline_items')
    op.drop_table('cue_shots')
    op.drop_table('asset_use_instances')
    op.drop_table('sound_cues')
    op.drop_table('execution_shots')
    op.drop_table('execution_materials')
    op.drop_table('script_line_dispositions')
    op.drop_table('execution_instances')
    op.drop_table('method_evaluations')
