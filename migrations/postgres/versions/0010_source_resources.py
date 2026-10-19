"""Source extraction, design provenance and typed resource vocabulary.

Frozen SQL: historical migrations never import current application metadata.
"""
from alembic import op

revision = "0010_source_resources"
down_revision = "0009_role_memory"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE asset_categories (\n'
 '\tcode TEXT NOT NULL, \n'
 '\tlabel TEXT NOT NULL, \n'
 '\tparent_code TEXT, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_asset_categories PRIMARY KEY (code), \n'
 '\tCONSTRAINT ck_asset_categories_category_code CHECK (length(code) > 0 AND ordinal >= 0), \n'
 '\tCONSTRAINT ck_asset_categories_category_parent CHECK (parent_code IS NULL OR parent_code <> code), \n'
 '\tCONSTRAINT fk_asset_categories_parent_code_asset_categories FOREIGN KEY(parent_code) REFERENCES '
 'asset_categories (code) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE parse_jobs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tparser_version TEXT NOT NULL, \n'
 '\tschema_version TEXT NOT NULL, \n'
 '\tintent TEXT NOT NULL, \n'
 '\tparameters JSONB NOT NULL, \n'
 '\tsignature_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_parse_jobs PRIMARY KEY (project_id, id), \n'
 "\tCONSTRAINT ck_parse_jobs_intent CHECK (intent IN ('screenplay','novel','outline')), \n"
 '\tCONSTRAINT fk_parse_jobs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT ck_parse_jobs_signature_sha256_format CHECK (signature_sha256 IS NULL OR signature_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE artifact_category_links (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tcategory_code TEXT NOT NULL, \n'
 '\tregistered_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_artifact_category_links PRIMARY KEY (project_id, artifact_id, category_code), \n'
 '\tCONSTRAINT fk_artifact_category_links_project_id_artifact_id_artif_265d FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_category_links_category_code_asset_categories FOREIGN KEY(category_code) '
 'REFERENCES asset_categories (code) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE media_category_links (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tcategory_code TEXT NOT NULL, \n'
 '\tregistered_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_media_category_links PRIMARY KEY (project_id, media_id, category_code), \n'
 '\tCONSTRAINT fk_media_category_links_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_media_category_links_category_code_asset_categories FOREIGN KEY(category_code) REFERENCES '
 'asset_categories (code) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE parse_attempts (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tattempt_no INTEGER NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\terror_code TEXT, \n'
 '\terror_message TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_parse_attempts PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_parse_attempts_project_id_job_id_parse_jobs FOREIGN KEY(project_id, job_id) REFERENCES '
 'parse_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_parse_attempts_attempt_no CHECK (attempt_no > 0), \n'
 "\tCONSTRAINT ck_parse_attempts_status CHECK (status IN ('succeeded','failed')), \n"
 '\tCONSTRAINT uq_parse_attempts_project_id_job_id_attempt_no UNIQUE (project_id, job_id, attempt_no), \n'
 '\tCONSTRAINT fk_parse_attempts_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE parse_job_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tsource_id UUID NOT NULL, \n'
 '\tsource_sha256 VARCHAR(64) NOT NULL, \n'
 '\tformat TEXT NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_parse_job_inputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_parse_job_inputs_project_id_job_id_parse_jobs FOREIGN KEY(project_id, job_id) REFERENCES '
 'parse_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_parse_job_inputs_project_id_source_id_source_versions FOREIGN KEY(project_id, source_id) '
 'REFERENCES source_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_parse_job_inputs_project_id_source_id_source_sha256__d21c FOREIGN KEY(project_id, '
 'source_id, source_sha256) REFERENCES source_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT ck_parse_job_inputs_ordinal CHECK (ordinal >= 0), \n'
 '\tCONSTRAINT uq_parse_job_inputs_project_id_job_id_ordinal UNIQUE (project_id, job_id, ordinal), \n'
 '\tCONSTRAINT uq_parse_job_inputs_project_id_job_id_source_id_role UNIQUE (project_id, job_id, source_id, '
 'role), \n'
 '\tCONSTRAINT fk_parse_job_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_parse_job_inputs_source_sha256_format CHECK (source_sha256 IS NULL OR source_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE source_intake_documents (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tsource_id UUID NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tintent TEXT NOT NULL, \n'
 '\tformat TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_source_intake_documents PRIMARY KEY (project_id, source_id), \n'
 '\tCONSTRAINT fk_source_intake_documents_project_id_source_id_source_versions FOREIGN KEY(project_id, '
 'source_id) REFERENCES source_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_source_intake_documents_title CHECK (length(trim(title)) > 0), \n'
 '\tCONSTRAINT ck_source_intake_documents_intent CHECK (intent IN '
 "('screenplay','novel','outline','reference')), \n"
 '\tCONSTRAINT ck_source_intake_documents_format CHECK (format IN '
 "('paste','txt','md','docx','pdf','xlsx','image','audio','video','unknown'))\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE identity_category_links (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tasset_id UUID NOT NULL, \n'
 '\tcategory_code TEXT NOT NULL, \n'
 '\tregistered_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_identity_category_links PRIMARY KEY (project_id, asset_id, category_code), \n'
 '\tCONSTRAINT fk_identity_category_links_project_id_asset_id_asset_identities FOREIGN KEY(project_id, '
 'asset_id) REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_identity_category_links_category_code_asset_categories FOREIGN KEY(category_code) '
 'REFERENCES asset_categories (code) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE source_extractions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tattempt_id UUID NOT NULL, \n'
 '\tsource_id UUID NOT NULL, \n'
 '\tsource_sha256 VARCHAR(64) NOT NULL, \n'
 '\toutput_key TEXT NOT NULL, \n'
 '\ttext TEXT NOT NULL, \n'
 '\ttext_sha256 VARCHAR(64) NOT NULL, \n'
 '\tlayout JSONB NOT NULL, \n'
 '\twarnings JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_source_extractions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_source_extractions_project_id_attempt_id_parse_attempts FOREIGN KEY(project_id, '
 'attempt_id) REFERENCES parse_attempts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_source_extractions_project_id_source_id_source_versions FOREIGN KEY(project_id, source_id) '
 'REFERENCES source_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_source_extractions_project_id_source_id_source_sha25_e553 FOREIGN KEY(project_id, '
 'source_id, source_sha256) REFERENCES source_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT uq_source_extractions_project_id_attempt_id_output_key UNIQUE (project_id, attempt_id, '
 'output_key), \n'
 '\tCONSTRAINT uq_source_extractions_project_id_id_source_id UNIQUE (project_id, id, source_id), \n'
 "\tCONSTRAINT ck_source_extractions_text_sha256 CHECK (encode(sha256(convert_to(text, 'UTF8')), 'hex') = "
 'text_sha256), \n'
 '\tCONSTRAINT fk_source_extractions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_source_extractions_source_sha256_format CHECK (source_sha256 IS NULL OR source_sha256 ~ '
 "'^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_source_extractions_text_sha256_format CHECK (text_sha256 IS NULL OR text_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE source_anchors (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\textraction_id UUID NOT NULL, \n'
 '\tsource_id UUID NOT NULL, \n'
 '\tanchor_key TEXT NOT NULL, \n'
 '\tstart_char INTEGER NOT NULL, \n'
 '\tend_char INTEGER NOT NULL, \n'
 '\tlocator JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_source_anchors PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_source_anchors_project_id_extraction_id_source_extractions FOREIGN KEY(project_id, '
 'extraction_id) REFERENCES source_extractions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_source_anchors_project_id_source_id_source_versions FOREIGN KEY(project_id, source_id) '
 'REFERENCES source_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_source_anchors_project_id_extraction_id_source_id_so_9b31 FOREIGN KEY(project_id, '
 'extraction_id, source_id) REFERENCES source_extractions (project_id, id, source_id), \n'
 '\tCONSTRAINT ck_source_anchors_character_range CHECK (start_char >= 0 AND end_char > start_char), \n'
 '\tCONSTRAINT uq_source_anchors_project_id_extraction_id_anchor_key UNIQUE (project_id, extraction_id, '
 'anchor_key), \n'
 '\tCONSTRAINT fk_source_anchors_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE draft_source_refs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tdraft_id UUID NOT NULL, \n'
 '\tdraft_revision BIGINT NOT NULL, \n'
 '\tscene_key TEXT NOT NULL, \n'
 '\tline_key TEXT NOT NULL, \n'
 '\tanchor_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_draft_source_refs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_draft_source_refs_project_id_draft_id_script_drafts FOREIGN KEY(project_id, draft_id) '
 'REFERENCES script_drafts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_draft_source_refs_project_id_anchor_id_source_anchors FOREIGN KEY(project_id, anchor_id) '
 'REFERENCES source_anchors (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_draft_source_refs_draft_revision CHECK (draft_revision > 0), \n'
 '\tCONSTRAINT uq_draft_source_refs_project_id_draft_id_draft_revision_7a6f UNIQUE (project_id, draft_id, '
 'draft_revision, scene_key, line_key, anchor_id, role), \n'
 '\tCONSTRAINT fk_draft_source_refs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE shot_design_units (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tscene_id UUID, \n'
 '\tsource_sha256 VARCHAR(64) NOT NULL, \n'
 '\tdesign_key TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tcontent JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_shot_design_units PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_shot_design_units_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_units_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) REFERENCES '
 'scenes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_units_project_id_artifact_id_source_sha2_1d08 FOREIGN KEY(project_id, '
 'artifact_id, source_sha256) REFERENCES artifact_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT uq_shot_design_units_project_id_artifact_id_design_key UNIQUE (project_id, artifact_id, '
 'design_key), \n'
 '\tCONSTRAINT uq_shot_design_units_project_id_artifact_id_id UNIQUE (project_id, artifact_id, id), \n'
 '\tCONSTRAINT ck_shot_design_units_design_key CHECK (length(design_key) > 0 AND ordinal >= 0), \n'
 '\tCONSTRAINT fk_shot_design_units_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_shot_design_units_source_sha256_format CHECK (source_sha256 IS NULL OR source_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE script_line_sources (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tline_id UUID NOT NULL, \n'
 '\tanchor_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_script_line_sources PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_script_line_sources_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) '
 'REFERENCES script_lines (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_script_line_sources_project_id_anchor_id_source_anchors FOREIGN KEY(project_id, anchor_id) '
 'REFERENCES source_anchors (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_script_line_sources_project_id_line_id_anchor_id_role UNIQUE (project_id, line_id, '
 'anchor_id, role), \n'
 '\tCONSTRAINT fk_script_line_sources_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE shot_design_line_refs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tdesign_unit_id UUID NOT NULL, \n'
 '\tline_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_shot_design_line_refs PRIMARY KEY (project_id, design_unit_id, line_id), \n'
 '\tCONSTRAINT fk_shot_design_line_refs_project_id_design_unit_id_shot_d909 FOREIGN KEY(project_id, '
 'design_unit_id) REFERENCES shot_design_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_line_refs_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) '
 'REFERENCES script_lines (project_id, id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE shot_design_panels (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tdesign_unit_id UUID NOT NULL, \n'
 '\tmedia_id UUID, \n'
 '\tpanel_key TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tcontent JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_shot_design_panels PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_shot_design_panels_project_id_design_unit_id_shot_de_8631 FOREIGN KEY(project_id, '
 'design_unit_id) REFERENCES shot_design_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_panels_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_shot_design_panels_project_id_design_unit_id_panel_key UNIQUE (project_id, design_unit_id, '
 'panel_key), \n'
 '\tCONSTRAINT uq_shot_design_panels_project_id_design_unit_id_ordinal UNIQUE (project_id, design_unit_id, '
 'ordinal), \n'
 '\tCONSTRAINT ck_shot_design_panels_panel_key CHECK (length(panel_key) > 0 AND ordinal >= 0), \n'
 '\tCONSTRAINT fk_shot_design_panels_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE scene_location_refs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tsource_sha256 VARCHAR(64) NOT NULL, \n'
 '\tscene_id UUID NOT NULL, \n'
 '\tshot_id UUID, \n'
 '\tlocation_id UUID NOT NULL, \n'
 '\tspec_version_id UUID, \n'
 '\trole TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_scene_location_refs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) '
 'REFERENCES scenes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_location_id_asset_identities FOREIGN KEY(project_id, '
 'location_id) REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_spec_version_id_asset_c20f FOREIGN KEY(project_id, '
 'spec_version_id) REFERENCES asset_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_artifact_id_source_sh_e200 FOREIGN KEY(project_id, '
 'artifact_id, source_sha256) REFERENCES artifact_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_location_id_spec_vers_d48e FOREIGN KEY(project_id, '
 'location_id, spec_version_id) REFERENCES asset_spec_versions (project_id, asset_id, id), \n'
 "\tCONSTRAINT ck_scene_location_refs_location_role CHECK (role IN ('primary','secondary','insert') AND "
 'ordinal >= 0), \n'
 '\tCONSTRAINT fk_scene_location_refs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_scene_location_refs_source_sha256_format CHECK (source_sha256 IS NULL OR source_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE shot_design_shots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tdesign_unit_id UUID NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\tscene_id UUID NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_shot_design_shots PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_shot_design_shots_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_shots_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_shots_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) REFERENCES '
 'scenes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_shot_design_shots_project_id_artifact_id_design_unit_c099 FOREIGN KEY(project_id, '
 'artifact_id, design_unit_id) REFERENCES shot_design_units (project_id, artifact_id, id), \n'
 "\tCONSTRAINT ck_shot_design_shots_design_shot_role CHECK (role IN ('primary','alternate','reference') AND "
 'ordinal >= 0 AND length(purpose) > 0), \n'
 '\tCONSTRAINT uq_shot_design_shots_project_id_design_unit_id_shot_id__2f16 UNIQUE (project_id, '
 'design_unit_id, shot_id, purpose, role), \n'
 '\tCONSTRAINT fk_shot_design_shots_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE asset_requirements (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tsource_sha256 VARCHAR(64) NOT NULL, \n'
 '\trequirement_key TEXT NOT NULL, \n'
 '\tcategory_code TEXT NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tdescription TEXT NOT NULL, \n'
 '\tscene_id UUID, \n'
 '\tshot_id UUID, \n'
 '\tasset_id UUID, \n'
 '\tspec_version_id UUID, \n'
 '\tinstance_id UUID, \n'
 '\tCONSTRAINT pk_asset_requirements PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) REFERENCES '
 'scenes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_asset_id_asset_identities FOREIGN KEY(project_id, asset_id) '
 'REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_spec_version_id_asset__9297 FOREIGN KEY(project_id, '
 'spec_version_id) REFERENCES asset_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_instance_id_asset_use__cd67 FOREIGN KEY(project_id, '
 'instance_id) REFERENCES asset_use_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_artifact_id_source_sha_4c67 FOREIGN KEY(project_id, '
 'artifact_id, source_sha256) REFERENCES artifact_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_asset_id_spec_version__996a FOREIGN KEY(project_id, '
 'asset_id, spec_version_id) REFERENCES asset_spec_versions (project_id, asset_id, id), \n'
 '\tCONSTRAINT uq_asset_requirements_project_id_artifact_id_requirement_key UNIQUE (project_id, artifact_id, '
 'requirement_key), \n'
 '\tCONSTRAINT ck_asset_requirements_requirement_text CHECK (length(requirement_key)>0 AND length(purpose)>0 '
 'AND length(description)>0), \n'
 '\tCONSTRAINT ck_asset_requirements_requirement_scope CHECK (shot_id IS NULL OR scene_id IS NOT NULL), \n'
 '\tCONSTRAINT ck_asset_requirements_requirement_spec CHECK (spec_version_id IS NULL OR asset_id IS NOT '
 'NULL), \n'
 '\tCONSTRAINT fk_asset_requirements_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_asset_requirements_category_code_asset_categories FOREIGN KEY(category_code) REFERENCES '
 'asset_categories (code) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_asset_requirements_source_sha256_format CHECK (source_sha256 IS NULL OR source_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE requirement_line_refs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\trequirement_id UUID NOT NULL, \n'
 '\tline_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_requirement_line_refs PRIMARY KEY (project_id, requirement_id, line_id), \n'
 '\tCONSTRAINT fk_requirement_line_refs_project_id_requirement_id_asse_3a36 FOREIGN KEY(project_id, '
 'requirement_id) REFERENCES asset_requirements (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_requirement_line_refs_project_id_line_id_script_lines FOREIGN KEY(project_id, line_id) '
 'REFERENCES script_lines (project_id, id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE requirement_slots (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\trequirement_id UUID NOT NULL, \n'
 '\tslot_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_requirement_slots PRIMARY KEY (project_id, requirement_id, slot_id, role), \n'
 '\tCONSTRAINT fk_requirement_slots_project_id_requirement_id_asset_re_1a2d FOREIGN KEY(project_id, '
 'requirement_id) REFERENCES asset_requirements (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_requirement_slots_project_id_slot_id_binding_slots FOREIGN KEY(project_id, slot_id) '
 'REFERENCES binding_slots (project_id, id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_requirement_slots_requirement_slot_role CHECK (role IN ('fulfills','reference','post'))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_artifact_category_links_category ON artifact_category_links (project_id, category_code)',
 'CREATE INDEX ix_artifact_category_links_project_artifact_id ON artifact_category_links (project_id, '
 'artifact_id)',
 'CREATE INDEX ix_media_category_links_category ON media_category_links (project_id, category_code)',
 'CREATE INDEX ix_media_category_links_project_media_id ON media_category_links (project_id, media_id)',
 'CREATE INDEX ix_parse_inputs_source ON parse_job_inputs (project_id, source_id)',
 'CREATE INDEX ix_identity_category_links_category ON identity_category_links (project_id, category_code)',
 'CREATE INDEX ix_identity_category_links_project_asset_id ON identity_category_links (project_id, asset_id)',
 'CREATE INDEX ix_source_anchor_lookup ON source_anchors (project_id, source_id)',
 'CREATE INDEX ix_shot_design_units_project_artifact_id ON shot_design_units (project_id, artifact_id)',
 'CREATE INDEX ix_shot_design_units_project_scene_id ON shot_design_units (project_id, scene_id)',
 'CREATE INDEX ix_script_line_sources_anchor ON script_line_sources (project_id, anchor_id)',
 'CREATE INDEX ix_shot_design_line_refs_project_design_unit_id ON shot_design_line_refs (project_id, '
 'design_unit_id)',
 'CREATE INDEX ix_shot_design_line_refs_project_line_id ON shot_design_line_refs (project_id, line_id)',
 'CREATE INDEX ix_shot_design_panels_project_design_unit_id ON shot_design_panels (project_id, '
 'design_unit_id)',
 'CREATE INDEX ix_shot_design_panels_project_media_id ON shot_design_panels (project_id, media_id)',
 'CREATE INDEX ix_scene_location_refs_project_artifact_id ON scene_location_refs (project_id, artifact_id)',
 'CREATE INDEX ix_scene_location_refs_project_location_id ON scene_location_refs (project_id, location_id)',
 'CREATE INDEX ix_scene_location_refs_project_scene_id ON scene_location_refs (project_id, scene_id)',
 'CREATE INDEX ix_scene_location_refs_project_shot_id ON scene_location_refs (project_id, shot_id)',
 'CREATE INDEX ix_scene_location_refs_project_spec_version_id ON scene_location_refs (project_id, '
 'spec_version_id)',
 'CREATE UNIQUE INDEX uq_scene_location_refs_primary ON scene_location_refs (project_id, artifact_id, '
 "scene_id, coalesce(shot_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE role = 'primary'",
 'CREATE UNIQUE INDEX uq_scene_location_refs_scope_order ON scene_location_refs (project_id, artifact_id, '
 "scene_id, coalesce(shot_id, '00000000-0000-0000-0000-000000000000'::uuid), role, ordinal)",
 'CREATE INDEX ix_shot_design_shots_project_artifact_id ON shot_design_shots (project_id, artifact_id)',
 'CREATE INDEX ix_shot_design_shots_project_design_unit_id ON shot_design_shots (project_id, design_unit_id)',
 'CREATE INDEX ix_shot_design_shots_project_scene_id ON shot_design_shots (project_id, scene_id)',
 'CREATE INDEX ix_shot_design_shots_project_shot_id ON shot_design_shots (project_id, shot_id)',
 'CREATE UNIQUE INDEX uq_shot_design_shots_primary ON shot_design_shots (project_id, artifact_id, shot_id, '
 "purpose) WHERE role = 'primary'",
 'CREATE INDEX ix_asset_requirements_category ON asset_requirements (project_id, category_code)',
 'CREATE INDEX ix_asset_requirements_project_artifact_id ON asset_requirements (project_id, artifact_id)',
 'CREATE INDEX ix_asset_requirements_project_asset_id ON asset_requirements (project_id, asset_id)',
 'CREATE INDEX ix_asset_requirements_project_instance_id ON asset_requirements (project_id, instance_id)',
 'CREATE INDEX ix_asset_requirements_project_scene_id ON asset_requirements (project_id, scene_id)',
 'CREATE INDEX ix_asset_requirements_project_shot_id ON asset_requirements (project_id, shot_id)',
 'CREATE INDEX ix_asset_requirements_project_spec_version_id ON asset_requirements (project_id, '
 'spec_version_id)',
 'CREATE INDEX ix_requirement_line_refs_project_line_id ON requirement_line_refs (project_id, line_id)',
 'CREATE INDEX ix_requirement_line_refs_project_requirement_id ON requirement_line_refs (project_id, '
 'requirement_id)',
 'CREATE INDEX ix_requirement_slots_project_requirement_id ON requirement_slots (project_id, requirement_id)',
 'CREATE INDEX ix_requirement_slots_project_slot_id ON requirement_slots (project_id, slot_id)',
 'INSERT INTO asset_categories(code,label,parent_code,ordinal) VALUES '
 "('character','人物与角色',NULL,0),('character.identity','人物身份','character',0),('character.face_body','脸与身体','character',1),('character.expression','表情','character',2),('character.makeup_hair','妆发','character',3),('character.costume','服装','character',4),('character.action_lipsync','动作与口型','character',5),('character.age_crowd','年龄与群演','character',6),('character.voiceprint','声纹','character',7),('environment','背景环境',NULL,1),('environment.location','地点母版','environment',0),('environment.views','地点多视角','environment',1),('environment.layout','结构布局地形','environment',2),('environment.sky_weather','天空日夜天气','environment',3),('environment.lighting','灯光','environment',4),('environment.material_depth','材质深度蒙版','environment',5),('prop','道具',NULL,2),('prop.handheld','剧情与手持','prop',0),('prop.furniture','家具','prop',1),('prop.vehicle','车船','prop',2),('prop.weapon_tool','武器工具','prop',3),('prop.food','饮食','prop',4),('prop.electronics','电子','prop',5),('prop.documents','纸张证件','prop',6),('prop.damage','破损状态','prop',7),('creature','生物',NULL,3),('creature.animal','动物','creature',0),('creature.insect','昆虫','creature',1),('creature.pet','宠物','creature',2),('creature.fantasy','幻想生物','creature',3),('creature.crowd','生物群体','creature',4),('plant','植物',NULL,4),('plant.tree_flower','树木花草','plant',0),('plant.vine','藤蔓','plant',1),('plant.crop','农作物','plant',2),('plant.fallen','落叶花瓣','plant',3),('plant.community','植物群落','plant',4),('sound','声音',NULL,5),('sound.voice','声纹与干声','sound',0),('sound.narration','旁白','sound',1),('sound.ambience','环境','sound',2),('sound.sfx','音效与拟音','sound',3),('sound.music','BGM','sound',4),('sound.impulse_response','IR混响','sound',5),('sound.phoneme','音素时码','sound',6),('sound.level','电平规范','sound',7),('text','字幕与文字',NULL,6),('text.subtitle','字幕文本','text',0),('text.style','字幕样式','text',1),('text.title','标题片尾','text',2),('text.screen','屏幕文字','text',3),('text.language','多语言与词库','text',4),('text.font','字体与授权','text',5),('vfx','视觉与动态特效',NULL,7),('vfx.weather','天气粒子','vfx',0),('vfx.magic_explosion','法术爆炸','vfx',1),('vfx.transition','转场','vfx',2),('vfx.alpha','Alpha层','vfx',3),('vfx.screen','屏幕画面','vfx',4),('vfx.sticker','贴纸','vfx',5),('camera_style','镜头与风格控制',NULL,8),('camera_style.camera','相机运镜构图','camera_style',0),('camera_style.style','视觉风格','camera_style',1),('camera_style.lut_grain','LUT与颗粒','camera_style',2),('camera_style.prompt','提示词与负词','camera_style',3),('camera_style.model','模型与LoRA','camera_style',4),('camera_style.control','控制图与蒙版','camera_style',5),('post','后期与包装',NULL,9),('post.opening_ending','片头片尾','post',0),('post.logo','Logo水印','post',1),('post.graphics','花字转场包','post',2),('post.template','混音渲染模板','post',3),('post.cover','封面海报','post',4),('post.delivery','发布包装','post',5),('document','制作文档与规则',NULL,10),('document.script','剧本','document',0),('document.storyboard','分镜','document',1),('document.continuity','场记与连续性','document',2),('document.bible','圣经','document',3),('document.approval','批准凭证','document',4),('document.rights','版权凭证','document',5),('document.dictionary','词库与规则','document',6)",
 'ALTER TABLE asset_identities DROP CONSTRAINT ck_asset_identities_asset_kind',
 'ALTER TABLE asset_identities ADD CONSTRAINT ck_asset_identities_asset_kind CHECK (asset_kind IN '
 "('character','location','prop','voice','style','costume','object','creature','vehicle','plant'))",
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON asset_categories FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON parse_jobs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON artifact_category_links FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON media_category_links FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON parse_attempts FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON parse_job_inputs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON source_intake_documents FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON identity_category_links FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON source_extractions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON source_anchors FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON draft_source_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON shot_design_units FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_line_sources FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON shot_design_line_refs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON shot_design_panels FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON scene_location_refs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON shot_design_shots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON asset_requirements FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON requirement_line_refs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON requirement_slots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '-- Freeze into 0010; no dynamic metadata imports. Alongside append-only triggers.\n'
 'CREATE FUNCTION vsc_resource_category_acyclic() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 '  IF EXISTS (WITH RECURSIVE ancestry(code, parent_code) AS (\n'
 '    SELECT code, parent_code FROM asset_categories WHERE code = NEW.parent_code\n'
 '    UNION SELECT c.code, c.parent_code FROM asset_categories c JOIN ancestry a ON c.code = a.parent_code\n'
 '  ) SELECT 1 FROM ancestry WHERE code = NEW.code) THEN\n'
 "    RAISE EXCEPTION 'resource category cycle' USING ERRCODE = '23514';\n"
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$;\n'
 'CREATE CONSTRAINT TRIGGER resource_category_acyclic AFTER INSERT OR UPDATE ON asset_categories\n'
 'DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION vsc_resource_category_acyclic();\n'
 '\n'
 'CREATE FUNCTION vsc_resource_model_scope() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE actual_scene uuid; expected_scene uuid; use_row record; req record; slot record;\n'
 'BEGIN\n'
 "  IF TG_TABLE_NAME IN ('shot_design_shots', 'scene_location_refs', 'asset_requirements') THEN\n"
 '    IF NEW.shot_id IS NOT NULL THEN\n'
 '      SELECT sq.parent_id INTO actual_scene FROM shots sh JOIN sequences sq\n'
 '        ON sq.project_id=sh.project_id AND sq.id=sh.parent_id\n'
 '        WHERE sh.project_id=NEW.project_id AND sh.id=NEW.shot_id;\n'
 '      IF actual_scene IS DISTINCT FROM NEW.scene_id THEN\n'
 "        RAISE EXCEPTION 'resource shot scene mismatch' USING ERRCODE='23514';\n"
 '      END IF;\n'
 '    END IF;\n'
 '  END IF;\n'
 "  IF TG_TABLE_NAME = 'shot_design_shots' THEN\n"
 '    SELECT scene_id INTO expected_scene FROM shot_design_units WHERE project_id=NEW.project_id AND '
 'id=NEW.design_unit_id;\n'
 '    IF expected_scene IS NOT NULL AND expected_scene IS DISTINCT FROM NEW.scene_id THEN\n'
 "      RAISE EXCEPTION 'design unit scene mismatch' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'shot_design_panels' THEN\n"
 '    IF NEW.media_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_items WHERE\n'
 "      project_id=NEW.project_id AND id=NEW.media_id AND modality='image') THEN\n"
 "      RAISE EXCEPTION 'design panel must be an image' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'scene_location_refs' THEN\n"
 '    IF NOT EXISTS (SELECT 1 FROM asset_identities WHERE project_id=NEW.project_id AND id=NEW.location_id '
 "AND asset_kind='location') THEN\n"
 "      RAISE EXCEPTION 'location reference must use a location identity' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'asset_requirements' THEN\n"
 '    IF NEW.instance_id IS NOT NULL THEN\n'
 '      SELECT * INTO use_row FROM asset_use_instances WHERE project_id=NEW.project_id AND '
 'id=NEW.instance_id;\n'
 '      IF use_row.asset_id IS DISTINCT FROM NEW.asset_id OR\n'
 '        (NEW.scene_id IS NOT NULL AND use_row.scene_id IS DISTINCT FROM NEW.scene_id) OR\n'
 '        (NEW.shot_id IS NOT NULL AND use_row.shot_id IS NOT NULL AND use_row.shot_id <> NEW.shot_id) THEN\n'
 "        RAISE EXCEPTION 'resource requirement instance mismatch' USING ERRCODE='23514';\n"
 '      END IF;\n'
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'requirement_slots' THEN\n"
 '    SELECT * INTO req FROM asset_requirements WHERE project_id=NEW.project_id AND id=NEW.requirement_id;\n'
 '    SELECT * INTO slot FROM binding_slots WHERE project_id=NEW.project_id AND id=NEW.slot_id;\n'
 '    IF NOT (slot.target_object_id = ANY(array_remove(ARRAY[req.asset_id,req.shot_id,req.scene_id],NULL))) '
 'OR\n'
 '       (req.asset_id IS NOT NULL AND slot.identity_asset_id IS NOT NULL AND req.asset_id <> '
 'slot.identity_asset_id) THEN\n'
 "      RAISE EXCEPTION 'resource requirement slot mismatch' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME IN ('requirement_line_refs','shot_design_line_refs') THEN\n"
 "    IF TG_TABLE_NAME = 'requirement_line_refs' THEN\n"
 '      SELECT scene_id INTO expected_scene FROM asset_requirements WHERE project_id=NEW.project_id AND '
 'id=NEW.requirement_id;\n'
 '    ELSE\n'
 '      SELECT scene_id INTO expected_scene FROM shot_design_units WHERE project_id=NEW.project_id AND '
 'id=NEW.design_unit_id;\n'
 '    END IF;\n'
 '    SELECT scene_id INTO actual_scene FROM script_lines WHERE project_id=NEW.project_id AND '
 'id=NEW.line_id;\n'
 '    IF expected_scene IS NOT NULL AND expected_scene IS DISTINCT FROM actual_scene THEN\n'
 "      RAISE EXCEPTION 'resource line scene mismatch' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$;\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON shot_design_shots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON shot_design_panels FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON scene_location_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON asset_requirements FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON requirement_slots FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON requirement_line_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n'
 'CREATE TRIGGER resource_model_scope BEFORE INSERT ON shot_design_line_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_resource_model_scope();\n',
 'CREATE FUNCTION vsc_source_scope() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE\n'
 '  extraction_length integer;\n'
 '  working script_drafts%ROWTYPE;\n'
 '  fixed_line script_lines%ROWTYPE;\n'
 '  scope_episode uuid;\n'
 '  scope_work uuid;\n'
 'BEGIN\n'
 "  IF TG_TABLE_NAME = 'source_anchors' THEN\n"
 '    SELECT char_length(text) INTO extraction_length FROM source_extractions\n'
 '      WHERE project_id=NEW.project_id AND id=NEW.extraction_id AND source_id=NEW.source_id;\n'
 '    IF extraction_length IS NULL OR NEW.end_char > extraction_length THEN\n'
 "      RAISE EXCEPTION 'source anchor outside extraction' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'source_extractions' THEN\n"
 '    IF NOT EXISTS (\n'
 '      SELECT 1 FROM parse_attempts a JOIN parse_job_inputs i\n'
 '        ON i.project_id=a.project_id AND i.job_id=a.job_id\n'
 '      WHERE a.project_id=NEW.project_id AND a.id=NEW.attempt_id\n'
 "        AND a.status='succeeded' AND i.source_id=NEW.source_id AND i.source_sha256=NEW.source_sha256\n"
 '    ) THEN\n'
 "      RAISE EXCEPTION 'extraction not from succeeded fixed job input' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'draft_source_refs' THEN\n"
 '    SELECT * INTO working FROM script_drafts WHERE project_id=NEW.project_id AND id=NEW.draft_id FOR '
 'SHARE;\n'
 '    IF working.draft_revision IS DISTINCT FROM NEW.draft_revision OR NOT EXISTS (\n'
 "      SELECT 1 FROM jsonb_array_elements(COALESCE(working.content->'scenes','[]'::jsonb)) scene,\n"
 "        LATERAL jsonb_array_elements(COALESCE(scene->'actions','[]'::jsonb) ||\n"
 "          COALESCE(scene->'dialogue','[]'::jsonb) || COALESCE(scene->'silence','[]'::jsonb)) unit\n"
 "      WHERE scene->>'id'=NEW.scene_key AND unit->>'id'=NEW.line_key\n"
 '    ) THEN\n'
 "      RAISE EXCEPTION 'draft source ref outside exact working revision' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '    SELECT s.parent_id,e.parent_id INTO scope_episode,scope_work FROM scenes s JOIN episodes e\n'
 '      ON e.project_id=s.project_id AND e.id=s.parent_id\n'
 '      WHERE s.project_id=NEW.project_id AND s.id::text=NEW.scene_key;\n'
 '    IF scope_episode IS NULL OR NOT (working.scope_key IN '
 "('',NEW.scene_key,scope_episode::text,scope_work::text)) THEN\n"
 "      RAISE EXCEPTION 'draft source scene outside scope' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'script_line_sources' THEN\n"
 '    SELECT * INTO fixed_line FROM script_lines WHERE project_id=NEW.project_id AND id=NEW.line_id;\n'
 '    IF NOT EXISTS (\n'
 '      SELECT 1 FROM draft_source_refs r JOIN script_drafts d\n'
 '        ON d.project_id=r.project_id AND d.id=r.draft_id AND d.draft_revision=r.draft_revision,\n'
 "        LATERAL jsonb_array_elements(COALESCE(d.content->'scenes','[]'::jsonb)) scene,\n"
 "        LATERAL jsonb_array_elements(COALESCE(scene->'actions','[]'::jsonb) ||\n"
 "          COALESCE(scene->'dialogue','[]'::jsonb) || COALESCE(scene->'silence','[]'::jsonb)) unit\n"
 '      WHERE r.project_id=NEW.project_id AND r.anchor_id=NEW.anchor_id AND r.role=NEW.role\n'
 '        AND r.scene_key=fixed_line.scene_id::text AND r.line_key=fixed_line.line_key\n'
 "        AND scene->>'id'=r.scene_key AND unit->>'id'=r.line_key\n"
 "        AND COALESCE(unit->>'text',unit->>'purpose','静默')=fixed_line.text\n"
 '    ) THEN\n'
 "      RAISE EXCEPTION 'fixed line provenance not from exact working source ref' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$;\n'
 'CREATE TRIGGER source_scope BEFORE INSERT ON source_anchors FOR EACH ROW EXECUTE FUNCTION '
 'vsc_source_scope();\n'
 'CREATE TRIGGER source_scope BEFORE INSERT ON source_extractions FOR EACH ROW EXECUTE FUNCTION '
 'vsc_source_scope();\n'
 'CREATE TRIGGER source_scope BEFORE INSERT ON draft_source_refs FOR EACH ROW EXECUTE FUNCTION '
 'vsc_source_scope();\n'
 'CREATE TRIGGER source_scope BEFORE INSERT ON script_line_sources FOR EACH ROW EXECUTE FUNCTION '
 'vsc_source_scope();\n']

def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    # Refuse to lose new identity semantics: map identities explicitly first.
    op.execute("ALTER TABLE asset_identities DROP CONSTRAINT ck_asset_identities_asset_kind")
    op.execute("ALTER TABLE asset_identities ADD CONSTRAINT ck_asset_identities_asset_kind CHECK (asset_kind IN ('character','location','prop','voice','style','costume'))")
    op.drop_table('requirement_slots')
    op.drop_table('requirement_line_refs')
    op.drop_table('asset_requirements')
    op.drop_table('shot_design_shots')
    op.drop_table('scene_location_refs')
    op.drop_table('shot_design_panels')
    op.drop_table('shot_design_line_refs')
    op.drop_table('script_line_sources')
    op.drop_table('shot_design_units')
    op.drop_table('draft_source_refs')
    op.drop_table('source_anchors')
    op.drop_table('source_extractions')
    op.drop_table('identity_category_links')
    op.drop_table('source_intake_documents')
    op.drop_table('parse_job_inputs')
    op.drop_table('parse_attempts')
    op.drop_table('media_category_links')
    op.drop_table('artifact_category_links')
    op.drop_table('parse_jobs')
    op.drop_table('asset_categories')
    op.execute("DROP FUNCTION vsc_resource_category_acyclic()")
    op.execute("DROP FUNCTION vsc_resource_model_scope()")
    op.execute("DROP FUNCTION vsc_source_scope()")
