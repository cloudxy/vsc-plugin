"""Working selections, episode references and fixed generation inputs."""
from alembic import op
revision="0034_working_state"
down_revision="0033_creative_tool_imports"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE episode_assets (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID NOT NULL, \n'
 '\tasset_key TEXT NOT NULL, \n'
 '\tname TEXT NOT NULL, \n'
 '\tasset_kind TEXT NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_episode_assets PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_episode_assets_project_id_episode_id_episodes FOREIGN KEY(project_id, episode_id) '
 'REFERENCES episodes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_episode_assets_project_id_episode_id_asset_key UNIQUE (project_id, episode_id, '
 'asset_key), \n'
 '\tCONSTRAINT ck_episode_assets_shape CHECK (revision>0 AND length(asset_key)>0 AND length(name)>0 AND '
 'asset_kind IN '
 "('character','location','prop','voice','style','costume','object','creature','vehicle','plant')), \n"
 '\tCONSTRAINT fk_episode_assets_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_episode_assets_episode_id ON episode_assets (project_id, episode_id)',
 '\n'
 'CREATE TABLE episode_asset_forms (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_asset_id UUID NOT NULL, \n'
 '\tform_key TEXT NOT NULL, \n'
 '\tname TEXT NOT NULL, \n'
 '\tcurrent_version_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_episode_asset_forms PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_episode_asset_forms_project_id_episode_asset_id_epis_6b14 FOREIGN KEY(project_id, '
 'episode_asset_id) REFERENCES episode_assets (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_episode_asset_forms_project_id_episode_asset_id_form_key UNIQUE (project_id, '
 'episode_asset_id, form_key), \n'
 '\tCONSTRAINT ck_episode_asset_forms_names CHECK (length(form_key)>0 AND length(name)>0), \n'
 '\tCONSTRAINT fk_episode_asset_forms_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_episode_asset_forms_current_version_id ON episode_asset_forms (project_id, '
 'current_version_id)',
 'CREATE INDEX ix_episode_asset_forms_episode_asset_id ON episode_asset_forms (project_id, episode_asset_id)',
 '\n'
 'CREATE TABLE episode_asset_form_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tform_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tasset_name TEXT NOT NULL, \n'
 '\tform_name TEXT NOT NULL, \n'
 '\tsource_asset_id UUID, \n'
 '\tspec_id UUID, \n'
 '\tmedia_id UUID, \n'
 '\tblob_id UUID, \n'
 '\tblob_sha256 VARCHAR(64), \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_episode_asset_form_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_episode_asset_form_versions_project_id_form_id_episo_7c67 FOREIGN KEY(project_id, form_id) '
 'REFERENCES episode_asset_forms (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_episode_asset_form_versions_project_id_form_id_version UNIQUE (project_id, form_id, '
 'version), \n'
 '\tCONSTRAINT uq_episode_asset_form_versions_project_id_form_id_id UNIQUE (project_id, form_id, id), \n'
 '\tCONSTRAINT fk_episode_asset_form_versions_project_id_source_asset__fdcf FOREIGN KEY(project_id, '
 'source_asset_id, spec_id) REFERENCES asset_spec_versions (project_id, asset_id, id), \n'
 '\tCONSTRAINT fk_episode_asset_form_versions_project_id_media_id_blob_4bf1 FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_episode_asset_form_versions_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, '
 'blob_sha256) REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT ck_episode_asset_form_versions_source_pair CHECK (version>0 AND (source_asset_id IS NULL) = '
 '(spec_id IS NULL)), \n'
 '\tCONSTRAINT ck_episode_asset_form_versions_media_tuple CHECK ((media_id IS NULL) = (blob_id IS NULL) AND '
 '(media_id IS NULL) = (blob_sha256 IS NULL)), \n'
 '\tCONSTRAINT fk_episode_asset_form_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_episode_asset_form_versions_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_episode_asset_form_versions_blob_id ON episode_asset_form_versions (project_id, blob_id)',
 'CREATE INDEX ix_episode_asset_form_versions_form_id ON episode_asset_form_versions (project_id, form_id)',
 'CREATE INDEX ix_episode_asset_form_versions_media_id ON episode_asset_form_versions (project_id, media_id)',
 'CREATE INDEX ix_episode_asset_form_versions_source_asset_id ON episode_asset_form_versions (project_id, '
 'source_asset_id)',
 'CREATE INDEX ix_episode_asset_form_versions_spec_id ON episode_asset_form_versions (project_id, spec_id)',
 '\n'
 'CREATE TABLE classic_draft_media (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tdraft_version_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\treference_key TEXT NOT NULL, \n'
 '\tdisplay_name TEXT NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tblob_sha256 VARCHAR(64) NOT NULL, \n'
 '\tepisode_asset_form_version_id UUID, \n'
 '\tannotation_artifact_id UUID, \n'
 '\tCONSTRAINT pk_classic_draft_media PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_classic_draft_media_project_id_draft_version_id_arti_8bd9 FOREIGN KEY(project_id, '
 'draft_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_media_project_id_episode_asset_form_ve_5b62 FOREIGN KEY(project_id, '
 'episode_asset_form_version_id) REFERENCES episode_asset_form_versions (project_id, id) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_media_project_id_annotation_artifact_i_f991 FOREIGN KEY(project_id, '
 'annotation_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_media_project_id_media_id_blob_id_media_items FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_classic_draft_media_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_classic_draft_media_project_id_draft_version_id_ordinal UNIQUE (project_id, '
 'draft_version_id, ordinal), \n'
 '\tCONSTRAINT uq_classic_draft_media_project_id_draft_version_id_role_509e UNIQUE (project_id, '
 'draft_version_id, role, media_id), \n'
 '\tCONSTRAINT uq_classic_draft_media_project_id_draft_version_id_refe_fe9e UNIQUE (project_id, '
 'draft_version_id, reference_key), \n'
 '\tCONSTRAINT ck_classic_draft_media_shape CHECK (ordinal>=0 AND length(role)>0 AND '
 'length(reference_key)>0), \n'
 '\tCONSTRAINT fk_classic_draft_media_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_classic_draft_media_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_classic_draft_media_annotation_artifact_id ON classic_draft_media (project_id, '
 'annotation_artifact_id)',
 'CREATE INDEX ix_classic_draft_media_blob_id ON classic_draft_media (project_id, blob_id)',
 'CREATE INDEX ix_classic_draft_media_draft_version_id ON classic_draft_media (project_id, draft_version_id)',
 'CREATE INDEX ix_classic_draft_media_episode_asset_form_version_id ON classic_draft_media (project_id, '
 'episode_asset_form_version_id)',
 'CREATE INDEX ix_classic_draft_media_media_id ON classic_draft_media (project_id, media_id)',
 '\n'
 'CREATE TABLE working_selection_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\toutput_kind TEXT NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tcandidate_id UUID, \n'
 '\tsource_job_id UUID, \n'
 '\tevent_kind TEXT NOT NULL, \n'
 '\ttrim_in_ms INTEGER, \n'
 '\ttrim_out_ms INTEGER, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_working_selection_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_working_selection_versions_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) '
 'REFERENCES shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_working_selection_versions_project_id_candidate_id_b_6234 FOREIGN KEY(project_id, '
 'candidate_id) REFERENCES binding_candidates (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_working_selection_versions_project_id_source_job_id__42ee FOREIGN KEY(project_id, '
 'source_job_id) REFERENCES generation_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_working_selection_versions_project_id_shot_id_output_0530 UNIQUE (project_id, shot_id, '
 'output_kind, version), \n'
 '\tCONSTRAINT uq_working_selection_versions_project_id_shot_id_output_kind_id UNIQUE (project_id, shot_id, '
 'output_kind, id), \n'
 "\tCONSTRAINT ck_working_selection_versions_shape CHECK (output_kind IN ('image','video') AND version>0 AND "
 "event_kind IN ('select','clear','trim','auto_select')), \n"
 "\tCONSTRAINT ck_working_selection_versions_clear_candidate CHECK ((event_kind='clear') = (candidate_id IS "
 'NULL)), \n'
 '\tCONSTRAINT ck_working_selection_versions_trim_range CHECK ((trim_in_ms IS NULL AND trim_out_ms IS NULL) '
 'OR (trim_in_ms>=0 AND trim_out_ms>trim_in_ms)), \n'
 '\tCONSTRAINT ck_working_selection_versions_trim_pair CHECK ((trim_in_ms IS NULL) = (trim_out_ms IS '
 'NULL)), \n'
 '\tCONSTRAINT ck_working_selection_versions_video_trim CHECK ((candidate_id IS NOT NULL AND '
 "output_kind='video') = (trim_in_ms IS NOT NULL AND trim_out_ms IS NOT NULL)), \n"
 "\tCONSTRAINT ck_working_selection_versions_auto_source CHECK (event_kind <> 'auto_select' OR source_job_id "
 'IS NOT NULL), \n'
 '\tCONSTRAINT fk_working_selection_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_working_selection_versions_candidate_id ON working_selection_versions (project_id, '
 'candidate_id)',
 'CREATE INDEX ix_working_selection_versions_shot_id ON working_selection_versions (project_id, shot_id)',
 'CREATE INDEX ix_working_selection_versions_source_job_id ON working_selection_versions (project_id, '
 'source_job_id)',
 '\n'
 'CREATE TABLE current_working_selections (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\toutput_kind TEXT NOT NULL, \n'
 '\tselection_version_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_current_working_selections PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_current_working_selections_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) '
 'REFERENCES shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_current_working_selections_project_id_shot_id_output_kind UNIQUE (project_id, shot_id, '
 'output_kind), \n'
 '\tCONSTRAINT fk_current_working_selections_project_id_shot_id_output_f58f FOREIGN KEY(project_id, shot_id, '
 'output_kind, selection_version_id) REFERENCES working_selection_versions (project_id, shot_id, '
 'output_kind, id), \n'
 '\tCONSTRAINT fk_current_working_selections_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_current_working_selections_selection_version_id ON current_working_selections (project_id, '
 'selection_version_id)',
 'CREATE INDEX ix_current_working_selections_shot_id ON current_working_selections (project_id, shot_id)',
 '\n'
 'CREATE TABLE edit_revision_working_selections (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tedit_version_id UUID NOT NULL, \n'
 '\tclip_key TEXT NOT NULL, \n'
 '\tselection_version_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_edit_revision_working_selections PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_revision_working_selections_project_id_edit_ver_4483 FOREIGN KEY(project_id, '
 'edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_working_selections_project_id_selectio_d811 FOREIGN KEY(project_id, '
 'selection_version_id) REFERENCES working_selection_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_working_selections_project_id_edit_ver_541b FOREIGN KEY(project_id, '
 'edit_version_id, clip_key) REFERENCES edit_revision_media (project_id, edit_version_id, clip_key), \n'
 '\tCONSTRAINT uq_edit_revision_working_selections_project_id_edit_ver_dafa UNIQUE (project_id, '
 'edit_version_id, clip_key), \n'
 '\tCONSTRAINT fk_edit_revision_working_selections_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_revision_working_selections_edit_version_id ON edit_revision_working_selections '
 '(project_id, edit_version_id)',
 'CREATE INDEX ix_edit_revision_working_selections_selection_version_id ON edit_revision_working_selections '
 '(project_id, selection_version_id)',
 '\n'
 'CREATE TABLE workbench_run_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\trun_version_id UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\tdraft_version_id UUID NOT NULL, \n'
 '\tdraft_sha256 VARCHAR(64) NOT NULL, \n'
 '\toutput_kind TEXT NOT NULL, \n'
 '\tbase_selection_version_id UUID, \n'
 '\tCONSTRAINT pk_workbench_run_inputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_workbench_run_inputs_project_id_run_version_id_artif_1b35 FOREIGN KEY(project_id, '
 'run_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_workbench_run_inputs_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_workbench_run_inputs_project_id_draft_version_id_dra_d1a8 FOREIGN KEY(project_id, '
 'draft_version_id, draft_sha256) REFERENCES artifact_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT fk_workbench_run_inputs_project_id_shot_id_output_kind__8aca FOREIGN KEY(project_id, shot_id, '
 'output_kind, base_selection_version_id) REFERENCES working_selection_versions (project_id, shot_id, '
 'output_kind, id), \n'
 "\tCONSTRAINT ck_workbench_run_inputs_output_kind CHECK (output_kind IN ('image','video','audio') AND "
 "(output_kind<>'audio' OR base_selection_version_id IS NULL)), \n"
 '\tCONSTRAINT uq_workbench_run_inputs_project_id_run_version_id_shot_id UNIQUE (project_id, run_version_id, '
 'shot_id), \n'
 '\tCONSTRAINT fk_workbench_run_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_workbench_run_inputs_draft_sha256_format CHECK (draft_sha256 IS NULL OR draft_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_workbench_run_inputs_base_selection_version_id ON workbench_run_inputs (project_id, '
 'base_selection_version_id)',
 'CREATE INDEX ix_workbench_run_inputs_draft_version_id ON workbench_run_inputs (project_id, '
 'draft_version_id)',
 'CREATE INDEX ix_workbench_run_inputs_run_version_id ON workbench_run_inputs (project_id, run_version_id)',
 'CREATE INDEX ix_workbench_run_inputs_shot_id ON workbench_run_inputs (project_id, shot_id)',
 'ALTER TABLE episode_asset_forms ADD CONSTRAINT fk_episode_form_current_version FOREIGN KEY(project_id, id, '
 'current_version_id) REFERENCES episode_asset_form_versions (project_id, form_id, id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON working_selection_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON episode_asset_form_versions FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON classic_draft_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON workbench_run_inputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_revision_working_selections FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 'ALTER TABLE intelligent_assets ADD COLUMN episode_asset_form_version_id UUID',
 'ALTER TABLE intelligent_assets ADD CONSTRAINT fk_intelligent_assets_project_id_episode_asset_form_ver_6369 '
 'FOREIGN KEY(project_id, episode_asset_form_version_id) REFERENCES episode_asset_form_versions (project_id, '
 'id)',
 'CREATE INDEX ix_intelligent_assets_episode_form ON intelligent_assets (project_id, '
 'episode_asset_form_version_id)',
 'ALTER TABLE intelligent_media ADD COLUMN working_selection_version_id UUID',
 'ALTER TABLE intelligent_media ADD CONSTRAINT fk_intelligent_media_project_id_working_selection_versi_8054 '
 'FOREIGN KEY(project_id, working_selection_version_id) REFERENCES working_selection_versions (project_id, '
 'id)',
 'CREATE INDEX ix_intelligent_media_working_selection ON intelligent_media (project_id, '
 'working_selection_version_id)',
 'ALTER TABLE intelligent_media ADD COLUMN episode_asset_form_version_id UUID',
 'ALTER TABLE intelligent_media ADD CONSTRAINT fk_intelligent_media_project_id_episode_asset_form_vers_597c '
 'FOREIGN KEY(project_id, episode_asset_form_version_id) REFERENCES episode_asset_form_versions (project_id, '
 'id)',
 'CREATE INDEX ix_intelligent_media_episode_form ON intelligent_media (project_id, '
 'episode_asset_form_version_id)',
 'ALTER TABLE intelligent_media ALTER COLUMN decision_id DROP NOT NULL',
 'ALTER TABLE intelligent_media ADD CONSTRAINT ck_intelligent_media_working_media_source CHECK '
 '(num_nonnulls(decision_id,working_selection_version_id,episode_asset_form_version_id)<=1 AND (decision_id '
 'IS NOT NULL OR working_selection_version_id IS NOT NULL OR episode_asset_form_version_id IS NOT NULL OR '
 'spatial_export_id IS NOT NULL))']

GUARDS = r"""
CREATE FUNCTION vsc_working_selection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid; modality text; duration integer; prior integer;
BEGIN
 PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
 SELECT coalesce(max(version),0) INTO prior FROM working_selection_versions
 WHERE project_id=NEW.project_id AND shot_id=NEW.shot_id AND output_kind=NEW.output_kind;
 IF NEW.version<>prior+1 THEN RAISE EXCEPTION 'working selection version conflict' USING ERRCODE='23514'; END IF;
 IF NEW.candidate_id IS NOT NULL THEN
  SELECT s.target_object_id,m.modality,b.duration_ms INTO target,modality,duration
  FROM binding_candidates c JOIN binding_slots s ON s.project_id=c.project_id AND s.id=c.slot_id
  JOIN media_items m ON m.project_id=c.project_id AND m.id=c.media_id
  JOIN media_blobs b ON b.id=m.blob_id WHERE c.project_id=NEW.project_id AND c.id=NEW.candidate_id;
  IF target IS DISTINCT FROM NEW.shot_id OR modality IS DISTINCT FROM NEW.output_kind THEN
   RAISE EXCEPTION 'working candidate must belong to this shot and output kind' USING ERRCODE='23514'; END IF;
  IF modality='video' AND (duration IS NULL OR NEW.trim_out_ms>duration) THEN
   RAISE EXCEPTION 'working trim requires known source duration' USING ERRCODE='23514'; END IF;
  IF NEW.source_job_id IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM job_outputs o JOIN generation_jobs j ON j.project_id=o.project_id AND j.id=o.job_id
   JOIN binding_candidates c ON c.project_id=o.project_id AND c.media_id=o.media_id
   WHERE o.project_id=NEW.project_id AND o.job_id=NEW.source_job_id AND c.id=NEW.candidate_id AND j.shot_id=NEW.shot_id) THEN
   RAISE EXCEPTION 'automatic choice must originate from this job output' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER working_selection_guard BEFORE INSERT ON working_selection_versions
FOR EACH ROW EXECUTE FUNCTION vsc_working_selection_guard();

CREATE FUNCTION vsc_working_selection_head() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected uuid; actual uuid;
BEGIN
 SELECT id INTO expected FROM working_selection_versions WHERE project_id=NEW.project_id
 AND shot_id=NEW.shot_id AND output_kind=NEW.output_kind ORDER BY version DESC LIMIT 1;
 SELECT selection_version_id INTO actual FROM current_working_selections WHERE project_id=NEW.project_id
 AND shot_id=NEW.shot_id AND output_kind=NEW.output_kind;
 IF expected IS DISTINCT FROM actual THEN RAISE EXCEPTION 'working head must reference latest version' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER working_selection_head AFTER INSERT ON working_selection_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_working_selection_head();
CREATE CONSTRAINT TRIGGER working_selection_head AFTER INSERT OR UPDATE ON current_working_selections
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_working_selection_head();
CREATE TRIGGER working_head_no_delete BEFORE DELETE ON current_working_selections
FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();

CREATE FUNCTION vsc_classic_draft_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; doc jsonb; refs jsonb; member record; expected jsonb; shot uuid; episode uuid; source_episode uuid;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='artifact_versions' THEN
  IF NEW.artifact_type<>'classic-production-draft' THEN RETURN NEW; END IF;
  a:=NEW.id;
 ELSE a:=NEW.draft_version_id; END IF;
 SELECT convert_from(document,'UTF8')::jsonb INTO doc FROM artifact_versions
 WHERE project_id=p AND id=a AND artifact_type='classic-production-draft';
 IF doc IS NULL THEN RAISE EXCEPTION 'classic references require a classic draft' USING ERRCODE='23514'; END IF;
 refs:=coalesce(doc->'references','[]'::jsonb);
 IF jsonb_typeof(refs)<>'array' OR jsonb_array_length(refs)<>(SELECT count(*) FROM classic_draft_media WHERE project_id=p AND draft_version_id=a) THEN
  RAISE EXCEPTION 'classic draft fixed reference set is incomplete' USING ERRCODE='23514'; END IF;
 shot:=(doc->>'shot_id')::uuid;
 SELECT sc.parent_id INTO episode FROM shots sh JOIN sequences sq ON sq.project_id=sh.project_id AND sq.id=sh.parent_id
 JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sh.project_id=p AND sh.id=shot;
 IF episode IS NULL THEN RAISE EXCEPTION 'classic draft shot missing' USING ERRCODE='23514'; END IF;
 FOR member IN SELECT * FROM classic_draft_media WHERE project_id=p AND draft_version_id=a LOOP
  expected:=refs->member.ordinal;
  IF expected IS NULL OR member.media_id::text IS DISTINCT FROM expected->>'media_id'
   OR member.role IS DISTINCT FROM expected->>'role' OR member.blob_sha256 IS DISTINCT FROM expected->>'sha256'
   OR member.reference_key IS DISTINCT FROM coalesce(expected->>'reference_key',member.role||':'||member.media_id::text)
   OR member.annotation_artifact_id::text IS DISTINCT FROM expected->>'annotation_id'
   OR member.episode_asset_form_version_id::text IS DISTINCT FROM expected->>'episode_asset_form_version_id'
   OR (expected ? 'display_name' AND member.display_name IS DISTINCT FROM expected->>'display_name') THEN
    RAISE EXCEPTION 'classic draft reference differs from fixed document' USING ERRCODE='23514'; END IF;
  IF member.episode_asset_form_version_id IS NOT NULL THEN
   SELECT ea.episode_id INTO source_episode FROM episode_asset_form_versions v
   JOIN episode_asset_forms f ON f.project_id=v.project_id AND f.id=v.form_id
   JOIN episode_assets ea ON ea.project_id=f.project_id AND ea.id=f.episode_asset_id
   WHERE v.project_id=p AND v.id=member.episode_asset_form_version_id AND v.media_id=member.media_id;
   IF source_episode IS DISTINCT FROM episode THEN RAISE EXCEPTION 'classic reference belongs to another episode or media' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER classic_draft_members AFTER INSERT ON artifact_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_classic_draft_members();
CREATE CONSTRAINT TRIGGER classic_draft_members AFTER INSERT ON classic_draft_media
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_classic_draft_members();

CREATE FUNCTION vsc_working_links() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE doc jsonb; draft jsonb; source_episode uuid; target_episode uuid; selected record; clip record; formrow record;
BEGIN
 IF TG_TABLE_NAME='workbench_run_inputs' THEN
  SELECT convert_from(document,'UTF8')::jsonb INTO doc FROM artifact_versions
   WHERE project_id=NEW.project_id AND id=NEW.run_version_id AND artifact_type='workbench-generation-run';
  SELECT convert_from(document,'UTF8')::jsonb INTO draft FROM artifact_versions
   WHERE project_id=NEW.project_id AND id=NEW.draft_version_id AND artifact_type='classic-production-draft';
  IF doc IS NULL OR draft IS NULL OR (draft->>'shot_id')::uuid IS DISTINCT FROM NEW.shot_id THEN
   RAISE EXCEPTION 'workbench run requires a same-shot classic draft' USING ERRCODE='23514'; END IF;
  IF NEW.output_kind IS DISTINCT FROM (CASE WHEN draft->>'mode' LIKE 'image%' THEN 'image' WHEN draft->>'mode' LIKE 'audio%' THEN 'audio' ELSE 'video' END) THEN
   RAISE EXCEPTION 'working run output kind differs from draft' USING ERRCODE='23514'; END IF;
  IF doc ? 'workbench_draft' AND (doc->'workbench_draft'->>'id' IS DISTINCT FROM NEW.draft_version_id::text
   OR doc->'workbench_draft'->>'sha256' IS DISTINCT FROM NEW.draft_sha256) THEN
   RAISE EXCEPTION 'workbench run document/input mismatch' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='intelligent_assets' THEN
  IF NEW.episode_asset_form_version_id IS NULL THEN RETURN NEW; END IF;
  SELECT ea.episode_id,v.source_asset_id,v.spec_id INTO formrow FROM episode_asset_form_versions v
   JOIN episode_asset_forms f ON f.project_id=v.project_id AND f.id=v.form_id
   JOIN episode_assets ea ON ea.project_id=f.project_id AND ea.id=f.episode_asset_id
   WHERE v.project_id=NEW.project_id AND v.id=NEW.episode_asset_form_version_id;
  SELECT w.episode_id INTO target_episode FROM intelligent_versions v JOIN intelligent_workflows w ON w.project_id=v.project_id AND w.id=v.workflow_id
   WHERE v.project_id=NEW.project_id AND v.id=NEW.version_id;
  IF formrow.episode_id IS DISTINCT FROM target_episode OR formrow.source_asset_id IS DISTINCT FROM NEW.asset_id OR formrow.spec_id IS DISTINCT FROM NEW.spec_id THEN
   RAISE EXCEPTION 'workflow asset must match fixed episode form' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='edit_revision_working_selections' THEN
  SELECT v.*,c.media_id INTO selected FROM working_selection_versions v JOIN binding_candidates c
   ON c.project_id=v.project_id AND c.id=v.candidate_id WHERE v.project_id=NEW.project_id AND v.id=NEW.selection_version_id;
  SELECT * INTO clip FROM edit_revision_media WHERE project_id=NEW.project_id AND edit_version_id=NEW.edit_version_id AND clip_key=NEW.clip_key;
  IF selected.id IS NULL OR selected.output_kind<>'video' OR clip.media_id IS DISTINCT FROM selected.media_id OR clip.shot_id IS DISTINCT FROM selected.shot_id OR clip.track<>'clips' THEN
   RAISE EXCEPTION 'edit clip must match fixed working selection' USING ERRCODE='23514'; END IF;
  SELECT w.episode_id INTO target_episode FROM edit_revisions r JOIN edit_workspaces w ON w.project_id=r.project_id AND w.id=r.workspace_id
   WHERE r.project_id=NEW.project_id AND r.id=NEW.edit_version_id;
  SELECT sc.parent_id INTO source_episode FROM shots sh JOIN sequences sq ON sq.project_id=sh.project_id AND sq.id=sh.parent_id
   JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sh.project_id=NEW.project_id AND sh.id=selected.shot_id;
  IF target_episode IS DISTINCT FROM source_episode THEN RAISE EXCEPTION 'working edit belongs to another episode' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER working_links BEFORE INSERT ON workbench_run_inputs FOR EACH ROW EXECUTE FUNCTION vsc_working_links();
CREATE TRIGGER working_episode_asset BEFORE INSERT ON intelligent_assets FOR EACH ROW EXECUTE FUNCTION vsc_working_links();
CREATE TRIGGER working_edit_input BEFORE INSERT ON edit_revision_working_selections FOR EACH ROW EXECUTE FUNCTION vsc_working_links();

CREATE FUNCTION vsc_working_edit_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; doc jsonb; expected integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='edit_revisions' THEN a:=NEW.id; ELSE a:=NEW.edit_version_id; END IF;
 SELECT document INTO doc FROM edit_revisions WHERE project_id=p AND id=a;
 SELECT count(*) INTO expected FROM jsonb_array_elements(doc->'clips') c WHERE c->>'working_selection_version_id' IS NOT NULL;
 IF expected<>(SELECT count(*) FROM edit_revision_working_selections WHERE project_id=p AND edit_version_id=a)
 OR EXISTS(SELECT 1 FROM edit_revision_working_selections r WHERE r.project_id=p AND r.edit_version_id=a AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(doc->'clips') c WHERE c->>'id'=r.clip_key AND c->>'working_selection_version_id'=r.selection_version_id::text)) THEN
  RAISE EXCEPTION 'edit working selection sources must equal fixed clip document' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER working_edit_members AFTER INSERT ON edit_revisions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_working_edit_members();
CREATE CONSTRAINT TRIGGER working_edit_members AFTER INSERT ON edit_revision_working_selections
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_working_edit_members();

CREATE FUNCTION vsc_workbench_input_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; doc jsonb; expected integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='artifact_versions' THEN
  IF NEW.artifact_type<>'workbench-generation-run' THEN RETURN NEW; END IF;
  a:=NEW.id;
 ELSE a:=NEW.run_version_id; END IF;
 SELECT convert_from(document,'UTF8')::jsonb INTO doc FROM artifact_versions
 WHERE project_id=p AND id=a AND artifact_type='workbench-generation-run';
 IF jsonb_typeof(doc->'workbench_draft')='object' THEN expected:=1;
 ELSE RAISE EXCEPTION 'workbench run requires fixed input declaration' USING ERRCODE='23514'; END IF;
 IF expected<>(SELECT count(*) FROM workbench_run_inputs WHERE project_id=p AND run_version_id=a) THEN
  RAISE EXCEPTION 'workbench run input set incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER workbench_input_members AFTER INSERT ON artifact_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_workbench_input_members();
CREATE CONSTRAINT TRIGGER workbench_input_members AFTER INSERT ON workbench_run_inputs
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_workbench_input_members();

CREATE FUNCTION vsc_episode_asset_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE kind text; actual text;
BEGIN
 IF TG_TABLE_NAME='episode_assets' THEN
  IF (NEW.episode_id,NEW.asset_key,NEW.asset_kind) IS DISTINCT FROM (OLD.episode_id,OLD.asset_key,OLD.asset_kind) THEN
   RAISE EXCEPTION 'episode asset identity cannot change' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='episode_asset_forms' THEN
  IF (NEW.episode_asset_id,NEW.form_key) IS DISTINCT FROM (OLD.episode_asset_id,OLD.form_key) THEN
   RAISE EXCEPTION 'episode form identity cannot change' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT a.asset_kind INTO kind FROM episode_assets a JOIN episode_asset_forms f ON f.project_id=a.project_id AND f.episode_asset_id=a.id
  WHERE f.project_id=NEW.project_id AND f.id=NEW.form_id;
  IF NEW.source_asset_id IS NOT NULL THEN
   SELECT asset_kind INTO actual FROM asset_identities WHERE project_id=NEW.project_id AND id=NEW.source_asset_id;
   IF actual IS DISTINCT FROM kind THEN RAISE EXCEPTION 'episode source asset kind mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.media_id IS NOT NULL THEN
   SELECT modality INTO actual FROM media_items WHERE project_id=NEW.project_id AND id=NEW.media_id;
   IF actual IS DISTINCT FROM (CASE WHEN kind='voice' THEN 'audio' ELSE 'image' END) THEN
    RAISE EXCEPTION 'episode form media kind mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER episode_asset_identity BEFORE UPDATE ON episode_assets FOR EACH ROW EXECUTE FUNCTION vsc_episode_asset_guard();
CREATE TRIGGER episode_form_identity BEFORE UPDATE ON episode_asset_forms FOR EACH ROW EXECUTE FUNCTION vsc_episode_asset_guard();
CREATE TRIGGER episode_form_source BEFORE INSERT ON episode_asset_form_versions FOR EACH ROW EXECUTE FUNCTION vsc_episode_asset_guard();
"""


INTELLIGENT_GUARD = r"""
CREATE OR REPLACE FUNCTION vsc_intelligent_links() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; wanted uuid; target_episode uuid; source_episode uuid; unitrow record; chosen record;
BEGIN
 IF TG_TABLE_NAME='intelligent_assets' THEN
  SELECT asset_id INTO actual FROM asset_spec_versions WHERE project_id=NEW.project_id AND id=NEW.spec_id;
  IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION 'asset/spec mismatch' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='intelligent_dependencies' THEN
  SELECT workflow_id INTO actual FROM intelligent_versions WHERE project_id=NEW.project_id AND id=NEW.version_id;
  SELECT workflow_id INTO wanted FROM intelligent_versions WHERE project_id=NEW.project_id AND id=NEW.source_version_id;
  IF actual IS DISTINCT FROM wanted THEN RAISE EXCEPTION 'cross workflow dependency' USING ERRCODE='23514'; END IF;
  IF EXISTS(WITH RECURSIVE edges(v,k) AS (
   SELECT NEW.source_version_id,NEW.source_unit_key UNION
   SELECT d.source_version_id,d.source_unit_key FROM intelligent_dependencies d JOIN edges e
   ON d.version_id=e.v AND d.unit_key=e.k WHERE d.project_id=NEW.project_id
  ) SELECT 1 FROM edges WHERE v=NEW.version_id AND k=NEW.unit_key) THEN
   RAISE EXCEPTION 'cyclic workflow dependency' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='intelligent_media' THEN
  SELECT * INTO unitrow FROM intelligent_units WHERE project_id=NEW.project_id AND version_id=NEW.version_id AND unit_key=NEW.unit_key;
  SELECT w.episode_id INTO target_episode FROM intelligent_versions v JOIN intelligent_workflows w ON w.project_id=v.project_id AND w.id=v.workflow_id
   WHERE v.project_id=NEW.project_id AND v.id=NEW.version_id;
  IF NEW.decision_id IS NOT NULL THEN
   SELECT c.media_id INTO actual FROM binding_decisions d JOIN binding_candidates c ON d.project_id=c.project_id AND d.candidate_id=c.id
    WHERE d.project_id=NEW.project_id AND d.id=NEW.decision_id AND d.outcome='select';
   IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'media must match original selection decision' USING ERRCODE='23514'; END IF;
  ELSIF NEW.working_selection_version_id IS NOT NULL THEN
   SELECT s.shot_id,s.output_kind,c.media_id INTO chosen FROM working_selection_versions s JOIN binding_candidates c ON c.project_id=s.project_id AND c.id=s.candidate_id
    WHERE s.project_id=NEW.project_id AND s.id=NEW.working_selection_version_id;
   IF chosen.media_id IS DISTINCT FROM NEW.media_id OR chosen.output_kind IS DISTINCT FROM 'image'
    OR (unitrow.shot_id IS NOT NULL AND chosen.shot_id IS DISTINCT FROM unitrow.shot_id) THEN
    RAISE EXCEPTION 'working image must match unit shot and media' USING ERRCODE='23514'; END IF;
   SELECT sc.parent_id INTO source_episode FROM shots sh JOIN sequences sq ON sq.project_id=sh.project_id AND sq.id=sh.parent_id
    JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sh.project_id=NEW.project_id AND sh.id=chosen.shot_id;
   IF source_episode IS DISTINCT FROM target_episode THEN RAISE EXCEPTION 'working reference crosses episode' USING ERRCODE='23514'; END IF;
  ELSIF NEW.episode_asset_form_version_id IS NOT NULL THEN
   SELECT a.episode_id INTO source_episode FROM episode_asset_form_versions v JOIN episode_asset_forms f ON f.project_id=v.project_id AND f.id=v.form_id
    JOIN episode_assets a ON a.project_id=f.project_id AND a.id=f.episode_asset_id
    WHERE v.project_id=NEW.project_id AND v.id=NEW.episode_asset_form_version_id AND v.media_id=NEW.media_id;
   IF source_episode IS DISTINCT FROM target_episode THEN RAISE EXCEPTION 'episode form reference must match episode and media' USING ERRCODE='23514'; END IF;
  END IF;
  IF NEW.spatial_export_id IS NOT NULL THEN
   SELECT o.media_id INTO actual FROM spatial_export_outputs o JOIN spatial_exports e ON e.project_id=o.project_id AND e.id=o.export_id
    JOIN media_items m ON m.project_id=o.project_id AND m.id=o.media_id JOIN media_blobs b ON b.id=m.blob_id
    WHERE o.project_id=NEW.project_id AND o.export_id=NEW.spatial_export_id AND e.format='png' AND e.status='succeeded'
    AND e.version_id=unitrow.spatial_version_id AND o.sha256=b.sha256;
   IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'spatial screenshot mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF NOT EXISTS(SELECT 1 FROM media_items WHERE project_id=NEW.project_id AND id=NEW.media_id AND modality='image') THEN
   RAISE EXCEPTION 'intelligent reference must be an image' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade():
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARDS)
    op.execute(INTELLIGENT_GUARD)


# Frozen pre-0034 guard, used only when no working facts exist.
LEGACY_INTELLIGENT_GUARD = "CREATE OR REPLACE FUNCTION vsc_intelligent_links() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE actual uuid; wanted uuid;\nBEGIN\n IF TG_TABLE_NAME='intelligent_assets' THEN\n SELECT asset_id INTO actual FROM asset_spec_versions WHERE project_id=NEW.project_id AND id=NEW.spec_id;\n IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION 'asset/spec mismatch' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME='intelligent_dependencies' THEN\n SELECT workflow_id INTO actual FROM intelligent_versions WHERE project_id=NEW.project_id AND id=NEW.version_id;\n SELECT workflow_id INTO wanted FROM intelligent_versions WHERE project_id=NEW.project_id AND id=NEW.source_version_id;\n IF actual IS DISTINCT FROM wanted THEN RAISE EXCEPTION 'cross workflow dependency' USING ERRCODE='23514'; END IF;\n IF EXISTS(WITH RECURSIVE edges(v,k) AS (\n SELECT NEW.source_version_id,NEW.source_unit_key UNION\n SELECT d.source_version_id,d.source_unit_key FROM intelligent_dependencies d JOIN edges e ON d.version_id=e.v AND d.unit_key=e.k WHERE d.project_id=NEW.project_id\n ) SELECT 1 FROM edges WHERE v=NEW.version_id AND k=NEW.unit_key) THEN RAISE EXCEPTION 'cyclic workflow dependency' USING ERRCODE='23514'; END IF;\n ELSIF TG_TABLE_NAME='intelligent_media' THEN\n SELECT c.media_id INTO actual FROM binding_decisions d JOIN binding_candidates c ON d.project_id=c.project_id AND d.candidate_id=c.id WHERE d.project_id=NEW.project_id AND d.id=NEW.decision_id AND d.outcome='select';\n IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'media must match original selection decision' USING ERRCODE='23514'; END IF;\n IF NEW.spatial_export_id IS NOT NULL THEN\n SELECT media_id INTO actual FROM spatial_export_outputs WHERE project_id=NEW.project_id AND export_id=NEW.spatial_export_id;\n IF actual IS DISTINCT FROM NEW.media_id THEN RAISE EXCEPTION 'spatial screenshot mismatch' USING ERRCODE='23514'; END IF;\n END IF;\n END IF;\n RETURN NEW;\nEND $$"


def downgrade():
    tables=('episode_assets','episode_asset_forms','episode_asset_form_versions','classic_draft_media','working_selection_versions','current_working_selections','workbench_run_inputs','edit_revision_working_selections')
    # Lock out concurrent writers before checking; never discard a working fact.
    op.execute('LOCK TABLE '+', '.join(tables)+', intelligent_assets, intelligent_media, artifact_versions, edit_revisions IN ACCESS EXCLUSIVE MODE')
    predicates=['EXISTS(SELECT 1 FROM '+table+')' for table in tables]
    predicates+=['EXISTS(SELECT 1 FROM intelligent_assets WHERE episode_asset_form_version_id IS NOT NULL)', 'EXISTS(SELECT 1 FROM intelligent_media WHERE decision_id IS NULL OR working_selection_version_id IS NOT NULL OR episode_asset_form_version_id IS NOT NULL)', "EXISTS(SELECT 1 FROM artifact_versions WHERE artifact_type='workbench-generation-run')"]
    op.execute("DO $$ BEGIN IF "+' OR '.join(predicates)+" THEN RAISE EXCEPTION 'working history exists; restore a backup or forward repair instead' USING ERRCODE='23514'; END IF; END $$")
    op.execute(LEGACY_INTELLIGENT_GUARD)
    for trigger,table in (('classic_draft_members','artifact_versions'),('working_edit_members','edit_revisions'),('workbench_input_members','artifact_versions'),('working_episode_asset','intelligent_assets')):
        op.execute('DROP TRIGGER '+trigger+' ON '+table)
    op.execute('ALTER TABLE intelligent_assets DROP COLUMN episode_asset_form_version_id')
    op.execute('ALTER TABLE intelligent_media DROP CONSTRAINT ck_intelligent_media_working_media_source')
    op.execute('ALTER TABLE intelligent_media DROP COLUMN working_selection_version_id, DROP COLUMN episode_asset_form_version_id, ALTER COLUMN decision_id SET NOT NULL')
    op.execute('ALTER TABLE episode_asset_forms DROP CONSTRAINT fk_episode_form_current_version')
    for table in ('edit_revision_working_selections','workbench_run_inputs','current_working_selections','working_selection_versions','classic_draft_media','episode_asset_form_versions','episode_asset_forms','episode_assets'):
        op.execute('DROP TABLE '+table)
    for function in ('vsc_working_selection_guard','vsc_working_selection_head','vsc_classic_draft_members','vsc_working_links','vsc_working_edit_members','vsc_workbench_input_members','vsc_episode_asset_guard'):
        op.execute('DROP FUNCTION '+function+'()')
