"""Leased local edit previews, production fencing and reversible media recycle.

Frozen DDL; historical migrations never import live application metadata.
"""
from alembic import op

revision = "0012_assisted_workflow"
down_revision = "0011_review_feedback"
branch_labels = None
depends_on = None

DDL = ['ALTER TABLE media_lifecycle_decisions ADD CONSTRAINT uq_media_lifecycle_decisions_project_id_media_id_id '
 'UNIQUE (project_id, media_id, id)',
 'ALTER TABLE generation_jobs ADD COLUMN claim_epoch INTEGER DEFAULT 0 NOT NULL',
 'ALTER TABLE generation_jobs ADD COLUMN next_attempt_at TIMESTAMP WITH TIME ZONE',
 'ALTER TABLE generation_jobs ADD CONSTRAINT ck_generation_jobs_claim_epoch CHECK (claim_epoch >= 0)',
 '\n'
 'CREATE TABLE media_recycle_actions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tdecision_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_media_recycle_actions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_media_recycle_actions_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_media_recycle_actions_project_id_decision_id_media_l_17ed FOREIGN KEY(project_id, '
 'decision_id) REFERENCES media_lifecycle_decisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_media_recycle_actions_project_id_decision_id UNIQUE (project_id, decision_id), \n'
 '\tCONSTRAINT fk_media_recycle_actions_project_id_media_id_decision_i_8e21 FOREIGN KEY(project_id, '
 'media_id, decision_id) REFERENCES media_lifecycle_decisions (project_id, media_id, id), \n'
 '\tCONSTRAINT fk_media_recycle_actions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_media_recycle_actions_project_decision_id ON media_recycle_actions (project_id, '
 'decision_id)',
 'CREATE INDEX ix_media_recycle_actions_project_media_id ON media_recycle_actions (project_id, media_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON media_recycle_actions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE render_caption_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\trender_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tblob_sha256 VARCHAR(64) NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_render_caption_inputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_render_caption_inputs_project_id_render_id_render_versions FOREIGN KEY(project_id, '
 'render_id) REFERENCES render_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_render_caption_inputs_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_render_caption_inputs_project_id_media_id_blob_id_me_7a8e FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_render_caption_inputs_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_render_caption_inputs_project_id_render_id_role UNIQUE (project_id, render_id, role), \n'
 "\tCONSTRAINT ck_render_caption_inputs_role CHECK (role IN ('clean_master','subtitle_font')), \n"
 '\tCONSTRAINT fk_render_caption_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_render_caption_inputs_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_render_caption_inputs_project_blob_id ON render_caption_inputs (project_id, blob_id)',
 'CREATE INDEX ix_render_caption_inputs_project_media_id ON render_caption_inputs (project_id, media_id)',
 'CREATE INDEX ix_render_caption_inputs_project_render_id ON render_caption_inputs (project_id, render_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON render_caption_inputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE edit_preview_jobs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tnote_id UUID NOT NULL, \n'
 '\trender_id UUID NOT NULL, \n'
 '\tsource_artifact_id UUID NOT NULL, \n'
 '\tdraft_artifact_id UUID, \n'
 '\tdispatch_id UUID, \n'
 '\trequest_sha256 VARCHAR(64) NOT NULL, \n'
 '\trecipe_version TEXT NOT NULL, \n'
 '\ttool_version TEXT NOT NULL, \n'
 '\tcaption_id TEXT NOT NULL, \n'
 '\toperation TEXT NOT NULL, \n'
 '\tlayout JSONB NOT NULL, \n'
 '\tdiff JSONB NOT NULL, \n'
 '\tstart_frame INTEGER NOT NULL, \n'
 '\tend_frame INTEGER NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 "\tattempt INTEGER DEFAULT '0' NOT NULL, \n"
 '\tclaim_owner TEXT, \n'
 '\tclaim_until TIMESTAMP WITH TIME ZONE, \n'
 '\terror TEXT, \n'
 '\texplanation TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_edit_preview_jobs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_note_id_artifact_review_notes FOREIGN KEY(project_id, '
 'note_id) REFERENCES artifact_review_notes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_render_id_render_versions FOREIGN KEY(project_id, render_id) '
 'REFERENCES render_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_source_artifact_id_arti_2b00 FOREIGN KEY(project_id, '
 'source_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_draft_artifact_id_artif_ab4c FOREIGN KEY(project_id, '
 'draft_artifact_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_dispatch_id_role_dispatches FOREIGN KEY(project_id, '
 'dispatch_id) REFERENCES role_dispatches (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_edit_preview_jobs_project_id_note_id_request_sha256 UNIQUE (project_id, note_id, '
 'request_sha256), \n'
 '\tCONSTRAINT uq_edit_preview_jobs_project_id_dispatch_id UNIQUE (project_id, dispatch_id), \n'
 '\tCONSTRAINT ck_edit_preview_jobs_status CHECK (status IN '
 "('queued','running','succeeded','failed','blocked','stale')), \n"
 '\tCONSTRAINT ck_edit_preview_jobs_range_attempt CHECK (start_frame >= 0 AND end_frame > start_frame AND '
 'attempt >= 0), \n'
 '\tCONSTRAINT fk_edit_preview_jobs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_edit_preview_jobs_request_sha256_format CHECK (request_sha256 IS NULL OR request_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_preview_jobs_project_caption_id ON edit_preview_jobs (project_id, caption_id)',
 'CREATE INDEX ix_edit_preview_jobs_project_dispatch_id ON edit_preview_jobs (project_id, dispatch_id)',
 'CREATE INDEX ix_edit_preview_jobs_project_draft_artifact_id ON edit_preview_jobs (project_id, '
 'draft_artifact_id)',
 'CREATE INDEX ix_edit_preview_jobs_project_note_id ON edit_preview_jobs (project_id, note_id)',
 'CREATE INDEX ix_edit_preview_jobs_project_render_id ON edit_preview_jobs (project_id, render_id)',
 'CREATE INDEX ix_edit_preview_jobs_project_source_artifact_id ON edit_preview_jobs (project_id, '
 'source_artifact_id)',
 'CREATE UNIQUE INDEX uq_edit_preview_active_note ON edit_preview_jobs (project_id, note_id) WHERE status IN '
 "('queued','running')",
 '\n'
 'CREATE TABLE edit_preview_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\ttimeline_item_id UUID, \n'
 '\tbinding_decision_id UUID, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tblob_sha256 VARCHAR(64) NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tstart_frame INTEGER NOT NULL, \n'
 '\tend_frame INTEGER NOT NULL, \n'
 "\tsource_path TEXT DEFAULT '' NOT NULL, \n"
 '\tCONSTRAINT pk_edit_preview_inputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_job_id_edit_preview_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES edit_preview_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_timeline_item_id_time_914f FOREIGN KEY(project_id, '
 'timeline_item_id) REFERENCES timeline_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_binding_decision_id_b_2fa9 FOREIGN KEY(project_id, '
 'binding_decision_id) REFERENCES binding_decisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_media_id_blob_id_media_items FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_edit_preview_inputs_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_edit_preview_inputs_project_id_job_id_role_source_pa_28f7 UNIQUE NULLS NOT DISTINCT '
 '(project_id, job_id, role, source_path, timeline_item_id), \n'
 '\tCONSTRAINT ck_edit_preview_inputs_role CHECK (role IN '
 "('clean_master','subtitle_font','subtitle_audio')), \n"
 "\tCONSTRAINT ck_edit_preview_inputs_audio_binding CHECK ((role='subtitle_audio' AND timeline_item_id IS "
 "NOT NULL AND binding_decision_id IS NOT NULL AND length(source_path)>0) OR (role<>'subtitle_audio' AND "
 "timeline_item_id IS NULL AND binding_decision_id IS NULL AND source_path='')), \n"
 '\tCONSTRAINT ck_edit_preview_inputs_range CHECK (start_frame >= 0 AND end_frame > start_frame), \n'
 '\tCONSTRAINT fk_edit_preview_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_edit_preview_inputs_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_preview_inputs_project_binding_decision_id ON edit_preview_inputs (project_id, '
 'binding_decision_id)',
 'CREATE INDEX ix_edit_preview_inputs_project_blob_id ON edit_preview_inputs (project_id, blob_id)',
 'CREATE INDEX ix_edit_preview_inputs_project_job_id ON edit_preview_inputs (project_id, job_id)',
 'CREATE INDEX ix_edit_preview_inputs_project_media_id ON edit_preview_inputs (project_id, media_id)',
 'CREATE INDEX ix_edit_preview_inputs_project_timeline_item_id ON edit_preview_inputs (project_id, '
 'timeline_item_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_preview_inputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE edit_preview_attempts (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tattempt INTEGER NOT NULL, \n'
 '\tworker_id TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 "\treceipt JSONB DEFAULT '{}' NOT NULL, \n"
 '\terror TEXT, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tfinished_at TIMESTAMP WITH TIME ZONE, \n'
 '\tCONSTRAINT pk_edit_preview_attempts PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_preview_attempts_project_id_job_id_edit_preview_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES edit_preview_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_edit_preview_attempts_project_id_job_id_attempt UNIQUE (project_id, job_id, attempt), \n'
 '\tCONSTRAINT ck_edit_preview_attempts_attempt CHECK (attempt > 0), \n'
 '\tCONSTRAINT ck_edit_preview_attempts_status CHECK (status IN '
 "('running','succeeded','failed','stale','expired')), \n"
 '\tCONSTRAINT fk_edit_preview_attempts_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_preview_attempts_project_job_id ON edit_preview_attempts (project_id, job_id)',
 'CREATE INDEX ix_edit_preview_attempts_project_worker_id ON edit_preview_attempts (project_id, worker_id)',
 '\n'
 'CREATE TABLE edit_preview_outputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tjob_id UUID NOT NULL, \n'
 '\tattempt_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tblob_sha256 VARCHAR(64) NOT NULL, \n'
 '\tstart_frame INTEGER NOT NULL, \n'
 '\tend_frame INTEGER NOT NULL, \n'
 '\tduration_ms INTEGER NOT NULL, \n'
 '\treceipt JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_edit_preview_outputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_preview_outputs_project_id_job_id_edit_preview_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES edit_preview_jobs (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_outputs_project_id_attempt_id_edit_prev_7959 FOREIGN KEY(project_id, '
 'attempt_id) REFERENCES edit_preview_attempts (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_preview_outputs_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_edit_preview_outputs_project_id_attempt_id UNIQUE (project_id, attempt_id), \n'
 '\tCONSTRAINT ck_edit_preview_outputs_range CHECK (start_frame >= 0 AND end_frame > start_frame AND '
 'duration_ms > 0), \n'
 '\tCONSTRAINT fk_edit_preview_outputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_edit_preview_outputs_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_preview_outputs_project_attempt_id ON edit_preview_outputs (project_id, attempt_id)',
 'CREATE INDEX ix_edit_preview_outputs_project_blob_id ON edit_preview_outputs (project_id, blob_id)',
 'CREATE INDEX ix_edit_preview_outputs_project_job_id ON edit_preview_outputs (project_id, job_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_preview_outputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']

DDL += ["CREATE INDEX ix_generation_jobs_provider_lease ON generation_jobs (provider_id,claim_until)",
        "CREATE INDEX ix_generation_jobs_due ON generation_jobs (status,next_attempt_at,claim_until)", """
CREATE FUNCTION vsc_edit_preview_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job edit_preview_jobs%ROWTYPE; note artifact_review_notes%ROWTYPE; source artifact_versions%ROWTYPE;
        draft artifact_versions%ROWTYPE; attempt edit_preview_attempts%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME = 'edit_preview_jobs' THEN
    SELECT * INTO note FROM artifact_review_notes WHERE project_id=NEW.project_id AND id=NEW.note_id;
    IF note.category IS DISTINCT FROM 'subtitle' OR note.render_id IS DISTINCT FROM NEW.render_id OR
       note.artifact_id IS DISTINCT FROM NEW.source_artifact_id OR
       NOT EXISTS (SELECT 1 FROM render_versions WHERE project_id=NEW.project_id AND id=NEW.render_id AND artifact_id=NEW.source_artifact_id) THEN
      RAISE EXCEPTION 'edit preview outside original note baseline' USING ERRCODE='23514';
    END IF;
    IF TG_OP = 'UPDATE' AND
       (to_jsonb(NEW)-ARRAY['status','attempt','claim_owner','claim_until','error','updated_at','draft_artifact_id','dispatch_id']) IS DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['status','attempt','claim_owner','claim_until','error','updated_at','draft_artifact_id','dispatch_id']) THEN
      RAISE EXCEPTION 'edit preview fixed intent is immutable' USING ERRCODE='23514';
    END IF;
    IF TG_OP = 'UPDATE' AND ((OLD.draft_artifact_id IS NOT NULL AND NEW.draft_artifact_id IS DISTINCT FROM OLD.draft_artifact_id) OR
       (OLD.dispatch_id IS NOT NULL AND NEW.dispatch_id IS DISTINCT FROM OLD.dispatch_id)) THEN
      RAISE EXCEPTION 'edit preview result identity is immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.draft_artifact_id IS NOT NULL THEN
      SELECT * INTO source FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.source_artifact_id;
      SELECT * INTO draft FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.draft_artifact_id;
      IF draft.supersedes_id IS DISTINCT FROM source.id OR draft.artifact_type IS DISTINCT FROM source.artifact_type THEN
        RAISE EXCEPTION 'edit preview draft does not revise its original type' USING ERRCODE='23514';
      END IF;
    END IF;
    IF NEW.dispatch_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM role_dispatches d JOIN dispatch_inputs i ON i.project_id=d.project_id AND i.dispatch_id=d.id
       WHERE d.project_id=NEW.project_id AND d.id=NEW.dispatch_id AND d.role_id='remotion-composer'
       AND i.artifact_id=NEW.source_artifact_id AND d.packet->'execution'->>'job_id'=NEW.id::text) THEN
      RAISE EXCEPTION 'edit preview dispatch outside fixed operation' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO job FROM edit_preview_jobs WHERE project_id=NEW.project_id AND id=NEW.job_id;
    IF TG_TABLE_NAME = 'edit_preview_inputs' THEN
      IF NEW.role='subtitle_audio' THEN
        IF NOT EXISTS (SELECT 1 FROM timeline_item_media m JOIN timeline_items i ON i.project_id=m.project_id AND i.id=m.item_id
            JOIN render_versions r ON r.project_id=i.project_id AND r.timeline_id=i.timeline_id
            WHERE m.project_id=NEW.project_id AND r.id=job.render_id AND m.item_id=NEW.timeline_item_id
              AND m.media_id=NEW.media_id AND m.binding_decision_id=NEW.binding_decision_id
              AND m.blob_id=NEW.blob_id AND m.blob_sha256=NEW.blob_sha256
              AND m.source_in_frame=NEW.start_frame AND m.source_out_frame=NEW.end_frame) THEN
          RAISE EXCEPTION 'edit preview audio outside frozen timeline binding' USING ERRCODE='23514';
        END IF;
      ELSIF NOT EXISTS (SELECT 1 FROM render_caption_inputs WHERE project_id=NEW.project_id AND render_id=job.render_id
                     AND media_id=NEW.media_id AND role=NEW.role) THEN
        RAISE EXCEPTION 'edit preview input is not a fixed render source' USING ERRCODE='23514';
      END IF;
    ELSIF TG_TABLE_NAME = 'edit_preview_outputs' THEN
      SELECT * INTO attempt FROM edit_preview_attempts WHERE project_id=NEW.project_id AND id=NEW.attempt_id;
      IF attempt.job_id IS DISTINCT FROM NEW.job_id OR NEW.start_frame <> job.start_frame OR NEW.end_frame <> job.end_frame THEN
        RAISE EXCEPTION 'edit preview output outside fixed attempt or interval' USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER edit_preview_scope BEFORE INSERT OR UPDATE ON edit_preview_jobs FOR EACH ROW EXECUTE FUNCTION vsc_edit_preview_scope();
CREATE TRIGGER edit_preview_scope BEFORE INSERT ON edit_preview_inputs FOR EACH ROW EXECUTE FUNCTION vsc_edit_preview_scope();
CREATE TRIGGER edit_preview_scope BEFORE INSERT ON edit_preview_outputs FOR EACH ROW EXECUTE FUNCTION vsc_edit_preview_scope();
CREATE FUNCTION vsc_edit_attempt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'edit execution evidence is immutable' USING ERRCODE='23514'; END IF;
  IF (to_jsonb(NEW)-ARRAY['status','receipt','error','finished_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','receipt','error','finished_at'])
      OR (OLD.receipt <> '{}'::jsonb AND NEW.receipt IS DISTINCT FROM OLD.receipt) THEN
    RAISE EXCEPTION 'edit execution evidence is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER edit_attempt_immutable BEFORE UPDATE OR DELETE ON edit_preview_attempts FOR EACH ROW EXECUTE FUNCTION vsc_edit_attempt_immutable();
"""]

def upgrade():
    for sql in DDL:
        op.execute(sql)

def downgrade():
    op.drop_index("ix_generation_jobs_due", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_provider_lease", table_name="generation_jobs")
    op.drop_table('edit_preview_outputs')
    op.drop_table('edit_preview_attempts')
    op.drop_table('edit_preview_inputs')
    op.drop_table('edit_preview_jobs')
    op.drop_table('render_caption_inputs')
    op.drop_table('media_recycle_actions')
    op.drop_column("generation_jobs", "next_attempt_at")
    op.drop_column("generation_jobs", "claim_epoch")
    op.drop_constraint("uq_media_lifecycle_decisions_project_id_media_id_id", "media_lifecycle_decisions", type_="unique")
    op.execute("DROP FUNCTION vsc_edit_preview_scope()")
    op.execute("DROP FUNCTION vsc_edit_attempt_immutable()")
