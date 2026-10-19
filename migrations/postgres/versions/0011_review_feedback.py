"""Immutable original-review responses and typed execution links.

Revision ID: 0011_review_feedback
Revises: 0010_source_resources
"""
from alembic import op
revision = "0011_review_feedback"
down_revision = "0010_source_resources"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE artifact_review_notes (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tartifact_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcategory TEXT NOT NULL, \n'
 '\tbody TEXT NOT NULL, \n'
 '\tauthor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tdesign_unit_id UUID, \n'
 '\tspec_version_id UUID, \n'
 '\tinstance_id UUID, \n'
 '\trender_id UUID, \n'
 '\trender_output_id UUID, \n'
 '\tmedia_sha256 VARCHAR(64), \n'
 '\tstart_frame INTEGER, \n'
 '\tend_frame INTEGER, \n'
 '\tCONSTRAINT pk_artifact_review_notes PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_design_unit_id_shot_8ed9 FOREIGN KEY(project_id, '
 'design_unit_id) REFERENCES shot_design_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_spec_version_id_ass_2571 FOREIGN KEY(project_id, '
 'spec_version_id) REFERENCES asset_spec_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_instance_id_asset_u_23a3 FOREIGN KEY(project_id, '
 'instance_id) REFERENCES asset_use_instances (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_render_id_render_versions FOREIGN KEY(project_id, '
 'render_id) REFERENCES render_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_render_output_id_re_ca63 FOREIGN KEY(project_id, '
 'render_output_id) REFERENCES render_outputs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_artifact_id_artifac_7658 FOREIGN KEY(project_id, '
 'artifact_id, artifact_sha256) REFERENCES artifact_versions (project_id, id, sha256), \n'
 '\tCONSTRAINT ck_artifact_review_notes_body CHECK (length(body) BETWEEN 1 AND 4000), \n'
 "\tCONSTRAINT ck_artifact_review_notes_typed_target CHECK ((category='director' AND design_unit_id IS NOT "
 "NULL AND spec_version_id IS NULL AND instance_id IS NULL AND render_id IS NULL) OR (category='asset' AND "
 'num_nonnulls(spec_version_id,instance_id)=1 AND design_unit_id IS NULL AND render_id IS NULL) OR (category '
 "IN ('subtitle','edit') AND render_id IS NOT NULL AND render_output_id IS NOT NULL AND media_sha256 IS NOT "
 'NULL AND start_frame IS NOT NULL AND end_frame IS NOT NULL AND start_frame >= 0 AND end_frame > start_frame AND design_unit_id IS NULL AND spec_version_id IS '
 'NULL AND instance_id IS NULL)), \n'
 '\tCONSTRAINT ck_artifact_review_notes_render_range CHECK ((render_id IS NOT NULL) OR (render_output_id IS '
 'NULL AND media_sha256 IS NULL AND start_frame IS NULL AND end_frame IS NULL)), \n'
 '\tCONSTRAINT fk_artifact_review_notes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_artifact_review_notes_artifact_sha256_format CHECK (artifact_sha256 IS NULL OR '
 "artifact_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_artifact_review_notes_media_sha256_format CHECK (media_sha256 IS NULL OR media_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_artifact_review_notes_project_artifact_id ON artifact_review_notes (project_id, '
 'artifact_id)',
 'CREATE INDEX ix_artifact_review_notes_project_design_unit_id ON artifact_review_notes (project_id, '
 'design_unit_id)',
 'CREATE INDEX ix_artifact_review_notes_project_instance_id ON artifact_review_notes (project_id, '
 'instance_id)',
 'CREATE INDEX ix_artifact_review_notes_project_render_id ON artifact_review_notes (project_id, render_id)',
 'CREATE INDEX ix_artifact_review_notes_project_render_output_id ON artifact_review_notes (project_id, '
 'render_output_id)',
 'CREATE INDEX ix_artifact_review_notes_project_spec_version_id ON artifact_review_notes (project_id, '
 'spec_version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON artifact_review_notes FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE script_note_anchors (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tnote_id UUID NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tfield TEXT NOT NULL, \n'
 '\texcerpt TEXT NOT NULL, \n'
 '\tstart_char INTEGER NOT NULL, \n'
 '\tend_char INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_script_note_anchors PRIMARY KEY (project_id, note_id), \n'
 '\tCONSTRAINT fk_script_note_anchors_project_id_note_id_script_notes FOREIGN KEY(project_id, note_id) '
 'REFERENCES script_notes (project_id, id) ON DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_script_note_anchors_kind CHECK (kind IN ('scene','action','dialogue','silence')), \n"
 "\tCONSTRAINT ck_script_note_anchors_field CHECK (field IN ('text','speaker','scene')), \n"
 '\tCONSTRAINT ck_script_note_anchors_character_range CHECK (start_char >= 0 AND end_char >= start_char AND '
 'end_char <= length(excerpt))\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_script_note_anchors_project_note_id ON script_note_anchors (project_id, note_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_note_anchors FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE review_responses (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tscript_note_id UUID, \n'
 '\tmedia_review_id UUID, \n'
 '\tartifact_note_id UUID, \n'
 '\taction TEXT NOT NULL, \n'
 '\texplanation TEXT NOT NULL, \n'
 '\tpreserve TEXT NOT NULL, \n'
 '\tlimitations TEXT NOT NULL, \n'
 '\tauthor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_review_responses PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_review_responses_project_id_script_note_id_script_notes FOREIGN KEY(project_id, '
 'script_note_id) REFERENCES script_notes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_review_responses_project_id_media_review_id_media_reviews FOREIGN KEY(project_id, '
 'media_review_id) REFERENCES media_reviews (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_review_responses_project_id_artifact_note_id_artifac_763a FOREIGN KEY(project_id, '
 'artifact_note_id) REFERENCES artifact_review_notes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_review_responses_one_source CHECK '
 '(num_nonnulls(script_note_id,media_review_id,artifact_note_id)=1), \n'
 '\tCONSTRAINT ck_review_responses_action CHECK (action IN '
 "('script_suggestions','redo_sound','resample','replace_instance','professional')), \n"
 '\tCONSTRAINT fk_review_responses_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_review_responses_project_artifact_note_id ON review_responses (project_id, '
 'artifact_note_id)',
 'CREATE INDEX ix_review_responses_project_media_review_id ON review_responses (project_id, media_review_id)',
 'CREATE INDEX ix_review_responses_project_script_note_id ON review_responses (project_id, script_note_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON review_responses FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE review_script_runs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tresponse_id UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_review_script_runs PRIMARY KEY (project_id, response_id, run_id), \n'
 '\tCONSTRAINT fk_review_script_runs_project_id_response_id_review_responses FOREIGN KEY(project_id, '
 'response_id) REFERENCES review_responses (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_review_script_runs_project_id_run_id_script_suggestion_runs FOREIGN KEY(project_id, '
 'run_id) REFERENCES script_suggestion_runs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_review_script_runs_project_id_run_id UNIQUE (project_id, run_id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_review_script_runs_project_response_id ON review_script_runs (project_id, response_id)',
 'CREATE INDEX ix_review_script_runs_project_run_id ON review_script_runs (project_id, run_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON review_script_runs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE script_run_suggestions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\tsuggestion_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_script_run_suggestions PRIMARY KEY (project_id, run_id, suggestion_id), \n'
 '\tCONSTRAINT fk_script_run_suggestions_project_id_run_id_script_sugg_717e FOREIGN KEY(project_id, run_id) '
 'REFERENCES script_suggestion_runs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_script_run_suggestions_project_id_suggestion_id_scri_d86c FOREIGN KEY(project_id, '
 'suggestion_id) REFERENCES script_suggestions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_script_run_suggestions_project_id_suggestion_id UNIQUE (project_id, suggestion_id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_script_run_suggestions_project_run_id ON script_run_suggestions (project_id, run_id)',
 'CREATE INDEX ix_script_run_suggestions_project_suggestion_id ON script_run_suggestions (project_id, '
 'suggestion_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_run_suggestions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE review_proposals (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tresponse_id UUID NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_review_proposals PRIMARY KEY (project_id, response_id, artifact_id), \n'
 '\tCONSTRAINT fk_review_proposals_project_id_response_id_review_responses FOREIGN KEY(project_id, '
 'response_id) REFERENCES review_responses (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_review_proposals_project_id_artifact_id_artifact_versions FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_review_proposals_project_id_artifact_id UNIQUE (project_id, artifact_id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_review_proposals_project_artifact_id ON review_proposals (project_id, artifact_id)',
 'CREATE INDEX ix_review_proposals_project_response_id ON review_proposals (project_id, response_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON review_proposals FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE review_dispatches (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tresponse_id UUID NOT NULL, \n'
 '\tdispatch_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_review_dispatches PRIMARY KEY (project_id, response_id, dispatch_id), \n'
 '\tCONSTRAINT fk_review_dispatches_project_id_response_id_review_responses FOREIGN KEY(project_id, '
 'response_id) REFERENCES review_responses (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_review_dispatches_project_id_dispatch_id_role_dispatches FOREIGN KEY(project_id, '
 'dispatch_id) REFERENCES role_dispatches (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_review_dispatches_project_id_dispatch_id UNIQUE (project_id, dispatch_id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_review_dispatches_project_dispatch_id ON review_dispatches (project_id, dispatch_id)',
 'CREATE INDEX ix_review_dispatches_project_response_id ON review_dispatches (project_id, response_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON review_dispatches FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 'CREATE FUNCTION vsc_review_target() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE target_artifact uuid; actual_sha text; duration integer; working script_drafts%ROWTYPE; original '
 'script_notes%ROWTYPE; unit jsonb;\n'
 'BEGIN\n'
 "  IF TG_TABLE_NAME = 'artifact_review_notes' THEN\n"
 '    IF NEW.design_unit_id IS NOT NULL THEN\n'
 '      SELECT artifact_id INTO target_artifact FROM shot_design_units WHERE project_id=NEW.project_id AND '
 'id=NEW.design_unit_id;\n'
 '    ELSIF NEW.spec_version_id IS NOT NULL THEN\n'
 '      SELECT artifact_id INTO target_artifact FROM asset_spec_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.spec_version_id;\n'
 '    ELSIF NEW.instance_id IS NOT NULL THEN\n'
 '      SELECT artifact_id INTO target_artifact FROM asset_use_instances WHERE project_id=NEW.project_id AND '
 'id=NEW.instance_id;\n'
 '    ELSE\n'
 '      SELECT artifact_id INTO target_artifact FROM render_versions WHERE project_id=NEW.project_id AND '
 'id=NEW.render_id;\n'
 '      SELECT b.sha256 INTO actual_sha FROM render_outputs o JOIN media_items m ON '
 'm.project_id=o.project_id AND m.id=o.media_id\n'
 '        JOIN media_blobs b ON b.id=m.blob_id WHERE o.project_id=NEW.project_id AND '
 'o.id=NEW.render_output_id AND o.render_id=NEW.render_id;\n'
 '      SELECT max(i.offset_frame+i.duration_frames) INTO duration FROM timeline_items i JOIN '
 'render_versions r\n'
 '        ON r.project_id=i.project_id AND r.timeline_id=i.timeline_id WHERE r.project_id=NEW.project_id AND '
 'r.id=NEW.render_id;\n'
 '      IF actual_sha IS DISTINCT FROM NEW.media_sha256 OR duration IS NULL OR NEW.end_frame > duration '
 'THEN\n'
 "        RAISE EXCEPTION 'review render output sha or range mismatch' USING ERRCODE='23514';\n"
 '      END IF;\n'
 '    END IF;\n'
 '    IF target_artifact IS DISTINCT FROM NEW.artifact_id THEN\n'
 "      RAISE EXCEPTION 'review target outside fixed artifact' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "  ELSIF TG_TABLE_NAME = 'script_note_anchors' THEN\n"
 '    SELECT * INTO original FROM script_notes WHERE project_id=NEW.project_id AND id=NEW.note_id;\n'
 '    SELECT * INTO working FROM script_drafts WHERE project_id=NEW.project_id AND '
 'scope_key=original.scope_key FOR SHARE;\n'
 '    IF working.id IS NULL OR working.draft_revision IS DISTINCT FROM original.base_draft_revision THEN\n'
 "      RAISE EXCEPTION 'review anchor draft revision mismatch' USING ERRCODE='23514';\n"
 '    END IF;\n'
 "    IF NEW.kind <> 'scene' THEN\n"
 "      SELECT candidate INTO unit FROM jsonb_array_elements(working.content->'scenes') scene,\n"
 "        LATERAL jsonb_array_elements(scene->CASE NEW.kind WHEN 'action' THEN 'actions' WHEN 'dialogue' "
 "THEN 'dialogue' ELSE 'silence' END) candidate\n"
 "        WHERE scene->>'id'=original.scene_id AND candidate->>'id'=original.line_id;\n"
 "      IF unit IS NULL OR COALESCE(unit->>'text',unit->>'purpose','') IS DISTINCT FROM NEW.excerpt THEN\n"
 "        RAISE EXCEPTION 'review anchor excerpt mismatch' USING ERRCODE='23514';\n"
 '      END IF;\n'
 "    ELSIF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(working.content->'scenes') scene WHERE "
 "scene->>'id'=original.scene_id) THEN\n"
 "      RAISE EXCEPTION 'review anchor scene missing' USING ERRCODE='23514';\n"
 '    END IF;\n'
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER review_target BEFORE INSERT ON artifact_review_notes FOR EACH ROW EXECUTE FUNCTION '
 'vsc_review_target()',
 'CREATE TRIGGER review_target BEFORE INSERT ON script_note_anchors FOR EACH ROW EXECUTE FUNCTION '
 'vsc_review_target()']

DDL += ["""ALTER TABLE review_responses ADD CONSTRAINT ck_review_responses_source_action CHECK (
    (script_note_id IS NULL OR action='script_suggestions') AND
    (media_review_id IS NULL OR action IN ('redo_sound','resample')) AND
    (artifact_note_id IS NULL OR action='professional'))""", """
CREATE FUNCTION vsc_review_execution_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE response review_responses%ROWTYPE; note script_notes%ROWTYPE; run script_suggestion_runs%ROWTYPE;
        suggestion script_suggestions%ROWTYPE; target artifact_review_notes%ROWTYPE; role_name text;
BEGIN
  IF TG_TABLE_NAME = 'review_script_runs' THEN
    SELECT * INTO response FROM review_responses WHERE project_id=NEW.project_id AND id=NEW.response_id;
    SELECT * INTO note FROM script_notes WHERE project_id=NEW.project_id AND id=response.script_note_id;
    SELECT * INTO run FROM script_suggestion_runs WHERE project_id=NEW.project_id AND id=NEW.run_id;
    IF response.action <> 'script_suggestions' OR note.id IS NULL OR
       run.scope_key IS DISTINCT FROM note.scope_key OR run.base_draft_revision IS DISTINCT FROM note.base_draft_revision OR
       run.base_content_sha256 IS DISTINCT FROM note.base_content_sha256 THEN
      RAISE EXCEPTION 'review run does not match original note baseline' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'script_run_suggestions' THEN
    SELECT * INTO run FROM script_suggestion_runs WHERE project_id=NEW.project_id AND id=NEW.run_id;
    SELECT * INTO suggestion FROM script_suggestions WHERE project_id=NEW.project_id AND id=NEW.suggestion_id;
    IF run.scope_key IS DISTINCT FROM suggestion.scope_key OR run.base_draft_revision IS DISTINCT FROM suggestion.base_draft_revision THEN
      RAISE EXCEPTION 'suggestion outside fixed run' USING ERRCODE='23514';
    END IF;
    SELECT n.* INTO note FROM script_notes n JOIN review_responses r ON r.project_id=n.project_id AND r.script_note_id=n.id
      JOIN review_script_runs l ON l.project_id=r.project_id AND l.response_id=r.id
      WHERE l.project_id=NEW.project_id AND l.run_id=NEW.run_id;
    IF note.id IS NOT NULL AND (suggestion.scene_id IS DISTINCT FROM note.scene_id OR suggestion.line_id IS DISTINCT FROM note.line_id OR
        NOT EXISTS (SELECT 1 FROM script_note_anchors a WHERE a.project_id=NEW.project_id AND a.note_id=note.id
                    AND a.kind=suggestion.kind AND a.field=suggestion.field)) THEN
      RAISE EXCEPTION 'suggestion outside original note anchor' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'review_dispatches' THEN
    SELECT * INTO response FROM review_responses WHERE project_id=NEW.project_id AND id=NEW.response_id;
    SELECT * INTO target FROM artifact_review_notes WHERE project_id=NEW.project_id AND id=response.artifact_note_id;
    SELECT role_id INTO role_name FROM role_dispatches WHERE project_id=NEW.project_id AND id=NEW.dispatch_id;
    IF target.id IS NULL OR role_name IS DISTINCT FROM (CASE target.category WHEN 'director' THEN 'director'
        WHEN 'asset' THEN 'asset-director' WHEN 'subtitle' THEN 'remotion-composer' ELSE 'editor' END) OR
        NOT EXISTS (SELECT 1 FROM dispatch_inputs WHERE project_id=NEW.project_id AND dispatch_id=NEW.dispatch_id AND artifact_id=target.artifact_id) THEN
      RAISE EXCEPTION 'review dispatch role or fixed input mismatch' USING ERRCODE='23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'review_proposals' THEN
    SELECT * INTO response FROM review_responses WHERE project_id=NEW.project_id AND id=NEW.response_id;
    IF response.media_review_id IS NULL OR NOT EXISTS (SELECT 1 FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.artifact_id
        AND artifact_type IN ('production-run','vsc.production_run') AND convert_from(document,'UTF8')::jsonb->>'local_action'=response.action) THEN
      RAISE EXCEPTION 'review proposal does not match registered local action' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER review_execution_link BEFORE INSERT ON review_script_runs FOR EACH ROW EXECUTE FUNCTION vsc_review_execution_link();
CREATE TRIGGER review_execution_link BEFORE INSERT ON script_run_suggestions FOR EACH ROW EXECUTE FUNCTION vsc_review_execution_link();
CREATE TRIGGER review_execution_link BEFORE INSERT ON review_dispatches FOR EACH ROW EXECUTE FUNCTION vsc_review_execution_link();
CREATE TRIGGER review_execution_link BEFORE INSERT ON review_proposals FOR EACH ROW EXECUTE FUNCTION vsc_review_execution_link();
"""]

def upgrade():
    for sql in DDL:
        op.execute(sql)

def downgrade():
    op.drop_table('review_dispatches')
    op.drop_table('review_proposals')
    op.drop_table('script_run_suggestions')
    op.drop_table('review_script_runs')
    op.drop_table('review_responses')
    op.drop_table('script_note_anchors')
    op.drop_table('artifact_review_notes')
    op.execute("DROP FUNCTION vsc_review_target()")
    op.execute("DROP FUNCTION vsc_review_execution_link()")
