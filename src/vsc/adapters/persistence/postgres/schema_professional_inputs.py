"""Typed, sealed projections of fixed professional working inputs."""
from sqlalchemy import (Table, Column, Text, String, Integer, ForeignKeyConstraint,
                        PrimaryKeyConstraint, UniqueConstraint, CheckConstraint, Index)
from sqlalchemy.dialects.postgresql import UUID

PROFESSIONAL_INPUT_IMMUTABLE = ('classic_draft_workflows', 'edit_revision_professional_inputs')


def declare_professional_inputs(metadata):
    def uid(name): return Column(name, UUID(as_uuid=False), nullable=False)
    workflows = Table('classic_draft_workflows', metadata,
        uid('project_id'), uid('draft_version_id'), uid('version_id'), uid('artifact_id'),
        Column('artifact_sha256', String(64), nullable=False),
        Column('state_sha256', String(64), nullable=False), Column('unit_key', Text, nullable=False),
        PrimaryKeyConstraint('project_id', 'draft_version_id'),
        ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'draft_version_id'], ['artifact_versions.project_id', 'artifact_versions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'artifact_id', 'artifact_sha256'], ['artifact_versions.project_id', 'artifact_versions.id', 'artifact_versions.sha256'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'version_id', 'unit_key'], ['intelligent_units.project_id', 'intelligent_units.version_id', 'intelligent_units.unit_key'], ondelete='RESTRICT'),
        CheckConstraint("unit_key ~ '^[A-Za-z0-9_-]{1,100}$'", name='unit_key'))
    edits = Table('edit_revision_professional_inputs', metadata,
        uid('project_id'), uid('edit_version_id'), Column('ordinal', Integer, nullable=False),
        uid('artifact_id'), Column('artifact_sha256', String(64), nullable=False),
        Column('kind', Text, nullable=False), PrimaryKeyConstraint('project_id', 'edit_version_id', 'ordinal'),
        ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'edit_version_id'], ['edit_revisions.project_id', 'edit_revisions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'artifact_id', 'artifact_sha256'], ['artifact_versions.project_id', 'artifact_versions.id', 'artifact_versions.sha256'], ondelete='RESTRICT'),
        UniqueConstraint('project_id', 'edit_version_id', 'artifact_id'),
        CheckConstraint("ordinal BETWEEN 0 AND 23 AND kind IN ('screenplay','shot_plan','scene_state','sequence_links','sound_plan','creative_rules','continuity','workflow')", name='shape'))
    Index('ix_classic_draft_workflows_version', workflows.c.project_id, workflows.c.version_id)
    Index('ix_classic_draft_workflows_artifact', workflows.c.project_id, workflows.c.artifact_id)
    Index('ix_edit_professional_artifact', edits.c.project_id, edits.c.artifact_id)
    return {t.name: t for t in (workflows, edits)}


# SQL aliases mirror production.professional_inputs.KIND_TYPES; the dedicated
# schema test compares every alias. Migrations freeze this specification.
PROFESSIONAL_INPUT_GUARD_DDL = r'''
CREATE FUNCTION vsc_professional_document(raw_document bytea) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 RETURN convert_from(raw_document,'UTF8')::jsonb;
EXCEPTION WHEN invalid_text_representation OR character_not_in_repertoire THEN RETURN NULL;
END $$;

CREATE FUNCTION vsc_professional_input_type(input_kind text, actual_type text, with_workflow boolean)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(CASE input_kind
  WHEN 'screenplay' THEN actual_type IN ('vsc.screenplay','screenplay','script','script-workspace')
  WHEN 'shot_plan' THEN actual_type IN ('vsc.shot_plan','shot-plan')
  WHEN 'scene_state' THEN actual_type IN ('vsc.scene_state','scene-state')
  WHEN 'sequence_links' THEN actual_type IN ('vsc.sequence_links','sequence-links')
  WHEN 'sound_plan' THEN actual_type IN ('vsc.sound_plan','sound-plan','vsc.sound_cue_sheet','sound-cue-sheet','creative-relations')
  WHEN 'creative_rules' THEN actual_type IN ('vsc.creative_brief','creative-brief','vsc.creative_rules','creative-rules')
  WHEN 'continuity' THEN actual_type IN ('vsc.continuity_plan','continuity-plan')
  WHEN 'workflow' THEN with_workflow AND actual_type='intelligent-workflow-state'
  ELSE false END, false)
$$;

CREATE FUNCTION vsc_professional_object_episode(p uuid, object_id uuid) RETURNS uuid
LANGUAGE sql STABLE AS $$
 SELECT id FROM episodes WHERE project_id=p AND id=object_id
 UNION ALL SELECT parent_id FROM scenes WHERE project_id=p AND id=object_id
 UNION ALL SELECT sc.parent_id FROM sequences sq JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sq.project_id=p AND sq.id=object_id
 UNION ALL SELECT sc.parent_id FROM shots sh JOIN sequences sq ON sq.project_id=sh.project_id AND sq.id=sh.parent_id
 JOIN scenes sc ON sc.project_id=sq.project_id AND sc.id=sq.parent_id WHERE sh.project_id=p AND sh.id=object_id
$$;

CREATE FUNCTION vsc_artifact_professional_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; doc jsonb; refs jsonb; item jsonb;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='artifact_versions' THEN a:=NEW.id; ELSE a:=NEW.artifact_id; END IF;
 SELECT vsc_professional_document(document) INTO doc FROM artifact_versions WHERE project_id=p AND id=a;
 IF doc IS NULL OR jsonb_typeof(doc)<>'object' OR NOT (doc ? 'professional_inputs') THEN RETURN NULL; END IF;
 refs:=doc->'professional_inputs';
 IF jsonb_typeof(refs) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'professional inputs must be an array' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(refs)>24 THEN RAISE EXCEPTION 'professional input limit exceeded' USING ERRCODE='23514'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(refs) LOOP
  IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'professional input must be an object' USING ERRCODE='23514'; END IF;
  IF NOT (item ?& ARRAY['id','sha256','kind']) OR (item-ARRAY['id','sha256','kind'])<>'{}'::jsonb THEN
   RAISE EXCEPTION 'professional input fields must be fixed' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM artifact_dependencies d JOIN artifact_versions source
   ON source.project_id=d.project_id AND source.id=d.dependency_id
   WHERE d.project_id=p AND d.artifact_id=a AND source.id::text=item->>'id'
    AND source.sha256=item->>'sha256' AND vsc_professional_input_type(item->>'kind',source.artifact_type,false)) THEN
   RAISE EXCEPTION 'professional input must match its typed original dependency and SHA' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(refs))<>jsonb_array_length(refs) THEN
  RAISE EXCEPTION 'professional input identity repeated' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER artifact_professional_inputs AFTER INSERT ON artifact_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_artifact_professional_inputs();
CREATE CONSTRAINT TRIGGER artifact_professional_inputs AFTER INSERT ON artifact_dependencies
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_artifact_professional_inputs();

CREATE FUNCTION vsc_edit_professional_inputs() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; a uuid; doc jsonb; refs jsonb; member record; expected jsonb; target_episode uuid;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='edit_revisions' THEN a:=NEW.id; ELSE a:=NEW.edit_version_id; END IF;
 SELECT r.document,w.episode_id INTO doc,target_episode FROM edit_revisions r JOIN edit_workspaces w
 ON w.project_id=r.project_id AND w.id=r.workspace_id WHERE r.project_id=p AND r.id=a;
 IF doc IS NULL THEN RAISE EXCEPTION 'professional inputs require an edit revision' USING ERRCODE='23514'; END IF;
 refs:=coalesce(doc->'professional_inputs','[]'::jsonb);
 IF jsonb_typeof(refs) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'edit professional inputs must be an array' USING ERRCODE='23514'; END IF;
 IF jsonb_array_length(refs)>24 OR jsonb_array_length(refs)<>(SELECT count(*) FROM edit_revision_professional_inputs WHERE project_id=p AND edit_version_id=a) THEN
  RAISE EXCEPTION 'edit professional input membership is incomplete or sealed' USING ERRCODE='23514'; END IF;
 FOR member IN SELECT * FROM edit_revision_professional_inputs WHERE project_id=p AND edit_version_id=a LOOP
  expected:=jsonb_build_object('id',member.artifact_id::text,'sha256',member.artifact_sha256,'kind',member.kind);
  IF refs->member.ordinal IS DISTINCT FROM expected OR NOT EXISTS(SELECT 1 FROM artifact_versions source
   WHERE source.project_id=p AND source.id=member.artifact_id AND source.sha256=member.artifact_sha256
    AND vsc_professional_input_type(member.kind,source.artifact_type,true)) THEN
   RAISE EXCEPTION 'edit professional input differs from fixed typed source' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR member IN SELECT * FROM edit_revision_media WHERE project_id=p AND edit_version_id=a LOOP
  SELECT value INTO expected FROM jsonb_array_elements(doc->member.track) WHERE value->>'id'=member.clip_key;
  IF member.source_job_id::text IS DISTINCT FROM expected->>'source_job_id' THEN
   RAISE EXCEPTION 'edit job provenance differs from the fixed clip document' USING ERRCODE='23514'; END IF;
  IF member.source_job_id IS NOT NULL THEN
   IF member.shot_id::text IS DISTINCT FROM expected->>'shot_id'
    OR member.media_id::text IS DISTINCT FROM expected->>'media_id'
    OR NOT EXISTS(SELECT 1 FROM generation_jobs j WHERE j.project_id=p AND j.id=member.source_job_id
     AND j.status='succeeded' AND j.shot_id=member.shot_id AND j.modality IN ('image','video') AND j.purpose<>'depth'
     AND vsc_professional_object_episode(p,j.shot_id)=target_episode) THEN
    RAISE EXCEPTION 'clip job must match its successful original output shot and episode' USING ERRCODE='23514'; END IF;
  END IF;
  IF member.source_cue_id::text IS DISTINCT FROM expected->>'cue_id'
   OR member.source_binding_decision_id::text IS DISTINCT FROM expected->>'binding_decision_id' THEN
   RAISE EXCEPTION 'edit cue provenance differs from the fixed audio document' USING ERRCODE='23514'; END IF;
  IF member.source_cue_id IS NOT NULL THEN
   IF NOT EXISTS(SELECT 1 FROM sound_cues cue
    JOIN edit_revision_professional_inputs input ON input.project_id=cue.project_id AND input.artifact_id=cue.artifact_id
     AND input.edit_version_id=a AND input.kind='sound_plan'
    JOIN cue_slots cs ON cs.project_id=cue.project_id AND cs.cue_id=cue.id
    JOIN binding_decisions d ON d.project_id=cs.project_id AND d.slot_id=cs.slot_id
    JOIN binding_candidates c ON c.project_id=d.project_id AND c.id=d.candidate_id
    WHERE cue.project_id=p AND cue.id=member.source_cue_id AND d.id=member.source_binding_decision_id
     AND d.outcome='select' AND c.media_id=member.media_id
     AND vsc_professional_object_episode(p,cue.scope_object_id)=target_episode) THEN
    RAISE EXCEPTION 'audio cue must match fixed sound plan, episode, slot and selected media' USING ERRCODE='23514'; END IF;
   IF EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id
    AND vsc_professional_object_episode(p,cs.shot_id) IS DISTINCT FROM target_episode) THEN
    RAISE EXCEPTION 'audio cue shot belongs to another episode' USING ERRCODE='23514'; END IF;
   IF member.shot_id IS NOT NULL AND EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id)
    AND NOT EXISTS(SELECT 1 FROM cue_shots cs WHERE cs.project_id=p AND cs.cue_id=member.source_cue_id AND cs.shot_id=member.shot_id) THEN
    RAISE EXCEPTION 'audio cue does not cover the fixed source shot' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revisions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();
CREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revision_professional_inputs
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();
CREATE CONSTRAINT TRIGGER edit_professional_inputs AFTER INSERT ON edit_revision_media
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_professional_inputs();

CREATE FUNCTION vsc_text_batch_materials() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; batch_id uuid; artifact_id uuid; batch text_tool_batches%ROWTYPE;
        material artifact_versions%ROWTYPE; doc jsonb;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='text_tool_batches' THEN batch_id:=NEW.id;
 ELSIF TG_TABLE_NAME='text_tool_batch_items' THEN batch_id:=NEW.batch_id;
 ELSE
  artifact_id:=NEW.artifact_id;
  -- Serialize attaching a batch with a concurrent dependency insert. This
  -- row lock does not mutate immutable evidence or conflict with FK key locks.
  PERFORM 1 FROM artifact_versions v WHERE v.project_id=p AND v.id=artifact_id
   AND v.artifact_type='text-tool-role-materials' FOR NO KEY UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
 END IF;
 FOR batch IN SELECT b.* FROM text_tool_batches b WHERE b.project_id=p
   AND (b.id=batch_id OR b.materials_artifact_id=artifact_id)
 LOOP
  IF batch.materials_artifact_id IS NULL THEN CONTINUE; END IF;
  SELECT * INTO material FROM artifact_versions v WHERE v.project_id=p
   AND v.id=batch.materials_artifact_id FOR NO KEY UPDATE;
  doc:=vsc_professional_document(material.document);
  IF batch.tool<>'novel' OR material.artifact_type IS DISTINCT FROM 'text-tool-role-materials'
    OR jsonb_typeof(doc) IS DISTINCT FROM 'object'
    OR doc->>'format' IS DISTINCT FROM 'vsc.text-tool-role-materials/v1'
    OR doc->>'tool' IS DISTINCT FROM 'novel'
    OR jsonb_typeof(doc->'actions') IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'batch materials must be a fixed novel role-materials artifact' USING ERRCODE='23514';
  END IF;
  IF EXISTS(SELECT 1 FROM jsonb_each(doc->'actions') e WHERE jsonb_typeof(e.value)<>'object')
    OR EXISTS(SELECT jsonb_object_keys(doc->'actions') EXCEPT
      SELECT i.action FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id)
    OR EXISTS(SELECT i.action FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id EXCEPT
      SELECT jsonb_object_keys(doc->'actions')) THEN
   RAISE EXCEPTION 'batch materials actions must match the fixed item actions' USING ERRCODE='23514';
  END IF;
  IF EXISTS(SELECT d.dependency_id FROM artifact_dependencies d WHERE d.project_id=p AND d.artifact_id=material.id EXCEPT
      SELECT i.input_version_id FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id)
    OR EXISTS(SELECT i.input_version_id FROM text_tool_batch_items i WHERE i.project_id=p AND i.batch_id=batch.id EXCEPT
      SELECT d.dependency_id FROM artifact_dependencies d WHERE d.project_id=p AND d.artifact_id=material.id) THEN
   RAISE EXCEPTION 'batch materials dependencies must match every fixed item input' USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON text_tool_batches
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();
CREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON text_tool_batch_items
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();
CREATE CONSTRAINT TRIGGER text_batch_materials AFTER INSERT ON artifact_dependencies
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_text_batch_materials();
'''
