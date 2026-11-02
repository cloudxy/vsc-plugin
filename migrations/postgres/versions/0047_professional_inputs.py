"""Seal professional draft/workflow inputs and original audio cue provenance."""
from alembic import op
revision = '0047_professional_inputs'
down_revision = '0046_classic_preferences'
branch_labels = None
depends_on = None
DDL = ['ALTER TABLE edit_revision_media ADD COLUMN source_cue_id UUID',
 'ALTER TABLE edit_revision_media ADD COLUMN source_binding_decision_id UUID',
 'ALTER TABLE edit_revision_media ADD CONSTRAINT ck_edit_revision_media_cue_source CHECK '
 '((source_cue_id IS NULL) = (source_binding_decision_id IS NULL) AND (source_cue_id IS NULL OR '
 "track='audio'))",
 'ALTER TABLE edit_revision_media ADD CONSTRAINT '
 'fk_edit_revision_media_project_id_source_binding_decisi_1c38 FOREIGN KEY(project_id, '
 'source_binding_decision_id) REFERENCES binding_decisions (project_id, id) ON DELETE RESTRICT',
 'ALTER TABLE edit_revision_media ADD CONSTRAINT '
 'fk_edit_revision_media_project_id_source_cue_id_sound_cues FOREIGN KEY(project_id, source_cue_id) '
 'REFERENCES sound_cues (project_id, id) ON DELETE RESTRICT',
 'CREATE INDEX ix_edit_revision_media_source_cue_id ON edit_revision_media (project_id, source_cue_id)',
 'CREATE INDEX ix_edit_revision_media_source_binding_decision_id ON edit_revision_media (project_id, '
 'source_binding_decision_id)',
 '\n'
 'CREATE TABLE classic_draft_workflows (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tdraft_version_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tartifact_sha256 VARCHAR(64) NOT NULL, \n'
 '\tstate_sha256 VARCHAR(64) NOT NULL, \n'
 '\tunit_key TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_classic_draft_workflows PRIMARY KEY (project_id, draft_version_id), \n'
 '\tCONSTRAINT fk_classic_draft_workflows_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_workflows_project_id_draft_version_id__3bbe FOREIGN KEY(project_id, '
 'draft_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_workflows_project_id_artifact_id_artif_873c FOREIGN KEY(project_id, '
 'artifact_id, artifact_sha256) REFERENCES artifact_versions (project_id, id, sha256) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT fk_classic_draft_workflows_project_id_version_id_unit_k_9b49 FOREIGN KEY(project_id, '
 'version_id, unit_key) REFERENCES intelligent_units (project_id, version_id, unit_key) ON DELETE '
 'RESTRICT, \n'
 "\tCONSTRAINT ck_classic_draft_workflows_unit_key CHECK (unit_key ~ '^[A-Za-z0-9_-]{1,100}$'), \n"
 '\tCONSTRAINT ck_classic_draft_workflows_artifact_sha256_format CHECK (artifact_sha256 IS NULL OR '
 "artifact_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_classic_draft_workflows_state_sha256_format CHECK (state_sha256 IS NULL OR '
 "state_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_classic_draft_workflows_artifact ON classic_draft_workflows (project_id, artifact_id)',
 'CREATE INDEX ix_classic_draft_workflows_version ON classic_draft_workflows (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON classic_draft_workflows FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE edit_revision_professional_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tedit_version_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tartifact_sha256 VARCHAR(64) NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_edit_revision_professional_inputs PRIMARY KEY (project_id, edit_version_id, '
 'ordinal), \n'
 '\tCONSTRAINT fk_edit_revision_professional_inputs_project_id_projects FOREIGN KEY(project_id) '
 'REFERENCES projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_professional_inputs_project_id_edit_ve_db58 FOREIGN KEY(project_id, '
 'edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_professional_inputs_project_id_artifac_202c FOREIGN KEY(project_id, '
 'artifact_id, artifact_sha256) REFERENCES artifact_versions (project_id, id, sha256) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT uq_edit_revision_professional_inputs_project_id_edit_ve_9f0e UNIQUE (project_id, '
 'edit_version_id, artifact_id), \n'
 '\tCONSTRAINT ck_edit_revision_professional_inputs_shape CHECK (ordinal BETWEEN 0 AND 23 AND kind IN '
 "('screenplay','shot_plan','scene_state','sequence_links','sound_plan','creative_rules','continuity','workflow')), \n"
 '\tCONSTRAINT ck_edit_revision_professional_inputs_artifact_sha256_format CHECK (artifact_sha256 IS '
 "NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_professional_artifact ON edit_revision_professional_inputs (project_id, '
 'artifact_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_revision_professional_inputs FOR EACH '
 'ROW EXECUTE FUNCTION vsc_reject_mutation()',
 'ALTER TABLE text_tool_batches ADD COLUMN materials_artifact_id UUID',
 'ALTER TABLE text_tool_batches ADD CONSTRAINT ck_text_tool_batches_materials_tool CHECK '
 "(materials_artifact_id IS NULL OR tool='novel')",
 'ALTER TABLE text_tool_batches ADD CONSTRAINT '
 'fk_text_tool_batches_project_id_materials_artifact_id_a_5f20 FOREIGN KEY(project_id, '
 'materials_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT',
 'CREATE INDEX ix_text_tool_batches_materials_artifact_id ON text_tool_batches (project_id, '
 'materials_artifact_id)',
 'ALTER TABLE edit_revision_media ADD COLUMN source_job_id UUID',
 'ALTER TABLE edit_revision_media ADD CONSTRAINT ck_edit_revision_media_job_source CHECK (source_job_id '
 "IS NULL OR track='clips')",
 'ALTER TABLE edit_revision_media ADD CONSTRAINT '
 'fk_edit_revision_media_project_id_source_job_id_generation_jobs FOREIGN KEY(project_id, '
 'source_job_id) REFERENCES generation_jobs (project_id, id) ON DELETE RESTRICT',
 'ALTER TABLE edit_revision_media ADD CONSTRAINT '
 'fk_edit_revision_media_project_id_source_job_id_media_i_5be0 FOREIGN KEY(project_id, source_job_id, '
 'media_id) REFERENCES job_outputs (project_id, job_id, media_id) ON DELETE RESTRICT',
 'CREATE INDEX ix_edit_revision_media_source_job_id ON edit_revision_media (project_id, source_job_id)']
GUARD = "\nCREATE FUNCTION vsc_professional_document(raw_document bytea) RETURNS jsonb\nLANGUAGE plpgsql IMMUTABLE AS $$\nBEGIN\n RETURN convert_from(raw_document,'UTF8')::jsonb;\nEXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN RETURN NULL;\nEND $$;\n\nCREATE FUNCTION vsc_professional_input_type(input_kind text, actual_type text, with_workflow boolean)\nRETURNS boolean LANGUAGE sql IMMUTABLE AS $$\n SELECT coalesce(CASE input_kind\n  WHEN 'screenplay' THEN actual_type IN ('vsc.screenplay','screenplay','script','script-workspace')\n  WHEN 'shot_plan' THEN actual_type IN ('vsc.shot_plan','shot-plan')\n  WHEN 'scene_state' THEN actual_type IN ('vsc.scene_state','scene-state')\n  WHEN 'sequence_links' THEN actual_type IN ('vsc.sequence_links','sequence-links')\n  WHEN 'sound_plan' THEN actual_type IN ('vsc.sound_plan','sound-plan','vsc.sound_cue_sheet','sound-cue-sheet','creative-relations')\n  WHEN 'creative_rules' THEN actual_type IN ('vsc.creative_brief','creative-brief','vsc.creative_rules','creative-rules')\n  WHEN 'continuity' THEN actual_type IN ('vsc.continuity_plan','continuity-plan')\n  WHEN 'workflow' THEN with_workflow AND actual_type='intelligent-workflow-state'\n  ELSE false END, false)\n$$;\n\nCREATE FUNCTION vsc_professional_object_episode(p uuid, object_id uuid) RETURNS uuid\nLANGUAGE sql STABLE AS $$\n SELECT id FROM episodes WHERE project_id=p AND id=object_id\n UNION ALL SELECT parent_id FROM scenes WHERE project_id=p AND id=object_id\n UNION ALL SELECT sc.parent_id FROM sequences sq JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sq.project_id=p AND sq.id=object_id\n UNION ALL SELECT sc.parent_id FROM shots sh JOIN sequences sq ON sq.project_id=sh.project_id AND sq.id=sh.parent_id\n JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sh.project_id=p AND sh.id=object_id\n$$;\n\nCREATE FUNCTION vsc_artifact_professional_inputs() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE p uuid; a uuid; doc jsonb; refs jsonb; item jsonb;\nBEGIN\n p:=NEW.project_id;\n IF TG_TABLE_NAME='artifact_versions' THEN a:=NEW.id; ELSE a:=NEW.artifact_id; END IF;\n SELECT vsc_professional_document(document) INTO doc FROM artifact_versions WHERE project_id=p AND id=a;\n IF doc IS NULL OR jsonb_typeof(doc)<>'object' OR NOT (doc ? 'professional_inputs') THEN RETURN NULL; END IF;\n refs:=doc->'professional_inputs';\n IF jsonb_typeof(refs) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'professional inputs must be an array' USING ERRCODE='23514'; END IF;\n IF jsonb_array_length(refs)>24 THEN RAISE EXCEPTION 'professional input limit exceeded' USING ERRCODE='23514'; END IF;\n FOR item IN SELECT value FROM jsonb_array_elements(refs) LOOP\n  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN\n   RAISE EXCEPTION 'professional input must be an object' USING ERRCODE='23514'; END IF;\n  IF NOT (item ?& ARRAY['id','sha256','kind']) OR (item-ARRAY['id','sha256','kind'])<>'{}'::jsonb THEN\n   RAISE EXCEPTION 'professional input fields must be fixed' USING ERRCODE='23514'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM artifact_dependencies d JOIN artifact_versions source\n   ON source.project_id=d.project_id AND source.id=d.dependency_id\n   WHERE d.project_id=p AND d.artifact_id=a AND source.id::text=item->>'id'\n    AND source.sha256=item->>'sha256' AND vsc_professional_input_type(item->>'kind',source.artifact_type,false)) THEN\n   RAISE EXCEPTION 'professional input must match its typed original dependency and SHA' USING ERRCODE='23514'; END IF;\n END LOOP;\n IF (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(refs))<>jsonb_array_length(refs) THEN\n  RAISE EXCEPTION 'professional input identity repeated' USING ERRCODE='23514'; END IF;\n RETURN NULL;\nEND $$;\nCREATE CONSTRAINT TRIGGER artifact_professional_inputs AFTER INSERT ON artifact_versions\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_artifact_professional_inputs();\nCREATE CONSTRAINT TRIGGER artifact_professional_inputs AFTER INSERT ON artifact_dependencies\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_artifact_professional_inputs();\n\nCREATE FUNCTION vsc_edit_professional_inputs() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE p uuid; a uuid; doc jsonb; refs jsonb; member record; expected jsonb; target_episode uuid;\nBEGIN\n p:=NEW.project_id;\n IF TG_TABLE_NAME='edit_revisions' THEN a:=NEW.id; ELSE a:=NEW.edit_version_id; END IF;\n SELECT r.document,w.episode_id INTO doc,target_episode FROM edit_revisions r JOIN edit_workspaces w\n ON w.project_id=r.project_id AND w.id=r.workspace_id WHERE r.project_id=p AND r.id=a;\n IF doc IS NULL THEN RAISE EXCEPTION 'professional inputs require an edit revision' USING ERRCODE='23514'; END IF;\n refs:=coalesce(doc->'professional_inputs','[]'::jsonb);\n IF jsonb_typeof(refs) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'edit professional inputs must be an array' USING ERRCODE='23514'; END IF;\n IF jsonb_array_length(refs)>24 OR jsonb_array_length(refs)<>(SELECT count(*) FROM edit_revision_professional_inputs WHERE project_id=p AND edit_version_id=a) THEN\n  RAISE EXCEPTION 'edit professional input membership is incomplete or sealed' USING ERRCODE='23514'; END IF;\n FOR member IN SELECT * FROM edit_revision_professional_inputs WHERE project_id=p AND edit_version_id=a LOOP\n  expected:=jsonb_build_object('id',member.artifact_id::text,'sha256',member.artifact_sha256,'kind',member.kind);\n  IF refs->member.ordinal IS DISTINCT FROM expected OR NOT EXISTS(SELECT 1 FROM artifact_versions source\n   WHERE source.project_id=p AND source.id=member.artifact_id AND source.sha256=member.artifact_sha256\n    AND vsc_professional_input_type(member.kind,source.artifact_type,true)) THEN\n   RAISE EXCEPTION 'edit professional input differs from fixed typed source' USING ERRCODE='23514'; END IF;\n END LOOP;\n FOR member IN SELECT * FROM edit_revision_media WHERE project_id=p AND edit_version_id=a LOOP\n  SELECT value INTO expected FROM jsonb_array_elements(doc->member.track) WHERE value->>'id'=member.clip_key;\n  IF member.source_job_id::text IS DISTINCT FROM expected->>'source_job_id' THEN\n   RAISE EXCEPTION 'edit job provenance differs from the fixed clip document' USING ERRCODE='23514'; END IF;\n  IF member.source_job_id IS NOT NULL THEN\n   IF member.shot_id::text IS DISTINCT FROM expected->>'shot_id'\n    OR member.media_id::text IS DISTINCT FROM expected->>'media_id'\n    OR NOT EXISTS(SELECT 1 FROM generation_jobs j WHERE j.project_id=p AND j.id=member.source_job_id\n     AND j.status='succeeded' AND j.shot_id=member.shot_id AND j.modality IN ('image','video') AND j.purpose<>'depth'\n     AND vsc_professional_object_episode(p,j.shot_id)=target_episode) THEN\n    RAISE EXCEPTION 'clip job must match its successful original output shot and episode' USING ERRCODE='23514'; END IF;\n  END IF;\n  IF member.source_cue_id::text IS DISTINCT FROM expected->>'cue_id'\n   OR member.source_binding_decision_id::text IS DISTINCT FROM expected->>'binding_decision_id' THEN\n   RAISE EXCEPTION 'edit cue provenance differs from the fixed audio document' USING ERRCODE='23514'; END IF;\n  IF member.source_cue_id IS NOT NULL THEN\n   IF NOT EXISTS(SELECT 1 FROM sound_cues cue\n    JOIN edit_revision_professional_inputs input ON input.project_id=cue.project_id AND input.artifact_id=cue.artifact_id\n     AND input.edit_version_id=a AND input.kind='sound_plan'\n    JOIN cue_slots cs ON cs.project_id=cue.project_id AND cs.cue_id=cue.id\n    JOIN binding_decisions d ON d.project_id=cs.project_id AND d.slot_id=cs.slot_id\n    JOIN binding_candidates c ON c.project_id=d.project_id AND c.id=d.candidate_id\n    WHERE cue.project_id=p AND cue.id=member.source_cue_id AND d.id=member.source_binding_decision_id\n     AND d.outcome='select' AND c.media_id=member.media_id\n     AND vsc_professional_object_episode(p,cue.scope_object_id)=target_episode) THEN\n    RAISE EXCEPTION 'audio cue must match fixed sound plan, episode, slot and selected media' USING ERRCODE='23514'; END IF;\n   IF EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id\n    AND vsc_professional_object_episode(p,cs.shot_id) IS DISTINCT FROM target_episode) THEN\n    RAISE EXCEPTION 'audio cue shot belongs to another episode' USING ERRCODE='23514'; END IF;\n   IF member.shot_id IS NOT NULL AND EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id)\n    AND NOT EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id AND cs.shot_id=member.shot_id) THEN\n    RAISE EXCEPTION 'audio cue does not cover the fixed source shot' USING ERRCODE='23514'; END IF;\n  END IF;\n END LOOP;\n RETURN NULL;\nEND $$;\nCREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revisions\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();\nCREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revision_professional_inputs\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();\nCREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revision_media\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();\n\nCREATE FUNCTION vsc_text_batch_materials() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE p uuid; batch_id uuid; artifact_id uuid; batch text_tool_batches%ROWTYPE;\n        material artifact_versions%ROWTYPE; doc jsonb;\nBEGIN\n p:=NEW.project_id;\n IF TG_TABLE_NAME='text_tool_batches' THEN batch_id:=NEW.id;\n ELSIF TG_TABLE_NAME='text_tool_batch_items' THEN batch_id:=NEW.batch_id;\n ELSE\n  artifact_id:=NEW.artifact_id;\n  -- Serialize attaching a batch with a concurrent dependency insert. This\n  -- row lock does not mutate immutable evidence or conflict with FK key locks.\n  PERFORM 1 FROM artifact_versions v WHERE v.project_id=p AND v.id=artifact_id\n   AND v.artifact_type='text-tool-role-materials' FOR NO KEY UPDATE;\n  IF NOT FOUND THEN RETURN NULL; END IF;\n END IF;\n FOR batch IN SELECT b.* FROM text_tool_batches b WHERE b.project_id=p\n   AND (b.id=batch_id OR b.materials_artifact_id=artifact_id)\n LOOP\n  IF batch.materials_artifact_id IS NULL THEN CONTINUE; END IF;\n  SELECT * INTO material FROM artifact_versions v WHERE v.project_id=p\n   AND v.id=batch.materials_artifact_id FOR NO KEY UPDATE;\n  doc:=vsc_professional_document(material.document);\n  IF batch.tool<>'novel' OR material.artifact_type IS DISTINCT FROM 'text-tool-role-materials'\n    OR jsonb_typeof(doc) IS DISTINCT FROM 'object'\n    OR doc->>'format' IS DISTINCT FROM 'vsc.text-tool-role-materials/v1'\n    OR doc->>'tool' IS DISTINCT FROM 'novel'\n    OR jsonb_typeof(doc->'actions') IS DISTINCT FROM 'object' THEN\n   RAISE EXCEPTION 'batch materials must be a fixed novel role-materials artifact' USING ERRCODE='23514';\n  END IF;\n  IF EXISTS(SELECT 1 FROM jsonb_each(doc->'actions') e WHERE jsonb_typeof(e.value)<>'object')\n    OR EXISTS(SELECT jsonb_object_keys(doc->'actions') EXCEPT\n      SELECT i.action FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id)\n    OR EXISTS(SELECT i.action FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id EXCEPT\n      SELECT jsonb_object_keys(doc->'actions')) THEN\n   RAISE EXCEPTION 'batch materials actions must match the fixed item actions' USING ERRCODE='23514';\n  END IF;\n  IF EXISTS(SELECT d.dependency_id FROM artifact_dependencies d WHERE d.project_id=p AND d.artifact_id=material.id EXCEPT\n      SELECT i.input_version_id FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id)\n    OR EXISTS(SELECT i.input_version_id FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id EXCEPT\n      SELECT d.dependency_id FROM artifact_dependencies d WHERE d.project_id=p AND d.artifact_id=material.id) THEN\n   RAISE EXCEPTION 'batch materials dependencies must match every fixed item input' USING ERRCODE='23514';\n  END IF;\n END LOOP;\n RETURN NULL;\nEND $$;\nCREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON text_tool_batches\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();\nCREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON text_tool_batch_items\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();\nCREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON artifact_dependencies\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();\n\nCREATE FUNCTION vsc_classic_workflow_inputs() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE p uuid; a uuid; doc jsonb; source jsonb; member record; expected jsonb; target_episode uuid;\nBEGIN\n p:=NEW.project_id;\n IF TG_TABLE_NAME='artifact_versions' THEN\n  IF NEW.artifact_type<>'classic-production-draft' THEN RETURN NULL; END IF;\n  a:=NEW.id;\n ELSE a:=NEW.draft_version_id; END IF;\n SELECT vsc_professional_document(document) INTO doc FROM artifact_versions\n WHERE project_id=p AND id=a AND artifact_type='classic-production-draft';\n IF doc IS NULL THEN RAISE EXCEPTION 'workflow source requires a classic draft' USING ERRCODE='23514'; END IF;\n source:=doc->'source_workflow';\n IF source IS NULL OR source='null'::jsonb THEN\n  IF EXISTS(SELECT 1 FROM classic_draft_workflows WHERE project_id=p AND draft_version_id=a) THEN\n   RAISE EXCEPTION 'workflow source cannot be appended to a sealed draft' USING ERRCODE='23514'; END IF;\n  RETURN NULL;\n END IF;\n SELECT * INTO member FROM classic_draft_workflows WHERE project_id=p AND draft_version_id=a;\n IF NOT FOUND THEN RAISE EXCEPTION 'classic workflow projection is incomplete' USING ERRCODE='23514'; END IF;\n expected:=jsonb_build_object('version_id',member.version_id::text,'artifact_id',member.artifact_id::text,\n  'artifact_sha256',member.artifact_sha256,'state_sha256',member.state_sha256,'unit_key',member.unit_key);\n IF source IS DISTINCT FROM expected THEN RAISE EXCEPTION 'classic workflow source differs from fixed document' USING ERRCODE='23514'; END IF;\n target_episode:=vsc_professional_object_episode(p,(doc->>'shot_id')::uuid);\n IF target_episode IS NULL OR NOT EXISTS(SELECT 1 FROM intelligent_versions v\n  JOIN intelligent_workflows w ON w.project_id=v.project_id AND w.id=v.workflow_id\n  JOIN intelligent_units u ON u.project_id=v.project_id AND u.version_id=v.id\n  JOIN artifact_versions av ON av.project_id=v.project_id AND av.id=v.artifact_id\n  WHERE v.project_id=p AND v.id=member.version_id AND v.artifact_id=member.artifact_id\n   AND av.sha256=member.artifact_sha256 AND av.artifact_type='intelligent-workflow-state'\n   AND u.unit_key=member.unit_key AND u.shot_id::text=doc->>'shot_id' AND w.episode_id=target_episode) THEN\n  RAISE EXCEPTION 'classic workflow must match original artifact, unit, shot and episode' USING ERRCODE='23514'; END IF;\n RETURN NULL;\nEND $$;\nCREATE CONSTRAINT TRIGGER classic_workflow_inputs AFTER INSERT ON artifact_versions\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_classic_workflow_inputs();\nCREATE CONSTRAINT TRIGGER classic_workflow_inputs AFTER INSERT ON classic_draft_workflows\nDEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_classic_workflow_inputs();\n"
CUE_INDEXES = ['ix_edit_revision_media_source_binding_decision_id', 'ix_edit_revision_media_source_cue_id']
CUE_CONSTRAINTS = ['ck_edit_revision_media_cue_source', 'fk_edit_revision_media_project_id_source_binding_decisi_1c38', 'fk_edit_revision_media_project_id_source_cue_id_sound_cues']

MATERIAL_CONSTRAINTS = ['ck_text_tool_batches_materials_tool', 'fk_text_tool_batches_project_id_materials_artifact_id_a_5f20']

SOURCE_JOB_CONSTRAINTS = ['ck_edit_revision_media_job_source', 'fk_edit_revision_media_project_id_source_job_id_generation_jobs', 'fk_edit_revision_media_project_id_source_job_id_media_i_5be0']

def upgrade():
    for statement in DDL: op.execute(statement)
    op.execute(GUARD)


def downgrade():
    op.execute('LOCK TABLE classic_draft_workflows,edit_revision_professional_inputs,edit_revision_media,edit_revisions,artifact_versions,artifact_dependencies,text_tool_batches,text_tool_batch_items IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM classic_draft_workflows)
 OR EXISTS(SELECT 1 FROM edit_revision_professional_inputs)
 OR EXISTS(SELECT 1 FROM edit_revision_media WHERE source_cue_id IS NOT NULL OR source_binding_decision_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM edit_revision_media WHERE source_job_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM text_tool_batches WHERE materials_artifact_id IS NOT NULL)
 OR EXISTS(SELECT 1 FROM artifact_versions WHERE artifact_type='text-tool-role-materials')
 OR EXISTS(SELECT 1 FROM artifact_versions WHERE coalesce(vsc_professional_document(document)->'professional_inputs','[]'::jsonb)<>'[]'::jsonb OR coalesce(vsc_professional_document(document)->'source_workflow','null'::jsonb)<>'null'::jsonb)
 OR EXISTS(SELECT 1 FROM edit_revisions WHERE coalesce(document->'professional_inputs','[]'::jsonb)<>'[]'::jsonb)
 THEN RAISE EXCEPTION 'professional input facts exist; use forward recovery' USING ERRCODE='23514'; END IF;
END $$""")
    for trigger,table in (('artifact_professional_inputs','artifact_versions'),('artifact_professional_inputs','artifact_dependencies'),('classic_workflow_inputs','artifact_versions'),('edit_professional_inputs','edit_revisions'),('edit_professional_inputs','edit_revision_media'),('text_batch_materials','text_tool_batches'),('text_batch_materials','text_tool_batch_items'),('text_batch_materials','artifact_dependencies')):
        op.execute('DROP TRIGGER '+trigger+' ON '+table)
    op.drop_table('edit_revision_professional_inputs')
    op.drop_table('classic_draft_workflows')
    for name in CUE_INDEXES: op.execute('DROP INDEX '+name)
    for name in CUE_CONSTRAINTS: op.execute('ALTER TABLE edit_revision_media DROP CONSTRAINT '+name)
    op.drop_column('edit_revision_media','source_binding_decision_id')
    op.drop_column('edit_revision_media','source_cue_id')
    op.execute('DROP INDEX ix_edit_revision_media_source_job_id')
    for name in SOURCE_JOB_CONSTRAINTS: op.execute('ALTER TABLE edit_revision_media DROP CONSTRAINT '+name)
    op.drop_column('edit_revision_media','source_job_id')
    op.execute('DROP INDEX ix_text_tool_batches_materials_artifact_id')
    for name in MATERIAL_CONSTRAINTS: op.execute('ALTER TABLE text_tool_batches DROP CONSTRAINT '+name)
    op.drop_column('text_tool_batches','materials_artifact_id')
    for signature in ('vsc_text_batch_materials()','vsc_classic_workflow_inputs()','vsc_edit_professional_inputs()','vsc_artifact_professional_inputs()','vsc_professional_object_episode(uuid,uuid)','vsc_professional_input_type(text,text,boolean)','vsc_professional_document(bytea)'):
        op.execute('DROP FUNCTION '+signature)
