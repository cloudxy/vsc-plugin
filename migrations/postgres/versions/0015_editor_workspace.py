"""Persistent editorial drafts and recoverable first-cut exports."""
from alembic import op

revision = "0015_editor_workspace"
down_revision = "0014_creative_canvas"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE edit_workspaces (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tcurrent_version_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_edit_workspaces PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_workspaces_project_id_episode_id_episodes FOREIGN KEY(project_id, episode_id) '
 'REFERENCES episodes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_edit_workspaces_project_id_episode_id UNIQUE (project_id, episode_id), \n'
 '\tCONSTRAINT ck_edit_workspaces_revision CHECK (revision >= 0), \n'
 '\tCONSTRAINT fk_edit_workspaces_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_workspaces_current_version_id ON edit_workspaces (project_id, current_version_id)',
 'CREATE INDEX ix_edit_workspaces_episode_id ON edit_workspaces (project_id, episode_id)',
 '\n'
 'CREATE TABLE edit_revisions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tworkspace_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tdocument JSONB NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tmember_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_edit_revisions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_revisions_project_id_workspace_id_edit_workspaces FOREIGN KEY(project_id, '
 'workspace_id) REFERENCES edit_workspaces (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_edit_revisions_project_id_workspace_id_version UNIQUE (project_id, workspace_id, '
 'version), \n'
 '\tCONSTRAINT uq_edit_revisions_project_id_workspace_id_id UNIQUE (project_id, workspace_id, id), \n'
 '\tCONSTRAINT ck_edit_revisions_version_members CHECK (version > 0 AND member_count >= 0 AND member_count '
 '<= 1000), \n'
 '\tCONSTRAINT fk_edit_revisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_edit_revisions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_revisions_workspace_id ON edit_revisions (project_id, workspace_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_revisions FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE edit_revision_media (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tedit_version_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tshot_id UUID, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tblob_sha256 VARCHAR(64) NOT NULL, \n'
 '\tclip_key TEXT NOT NULL, \n'
 '\ttrack TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tsource_in_frame INTEGER NOT NULL, \n'
 '\tsource_out_frame INTEGER NOT NULL, \n'
 '\toffset_frame INTEGER NOT NULL, \n'
 '\tmodality TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_edit_revision_media PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_revision_media_project_id_edit_version_id_edit__3240 FOREIGN KEY(project_id, '
 'edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_media_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_media_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) REFERENCES '
 'shots (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_revision_media_project_id_media_id_blob_id_media_items FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id), \n'
 '\tCONSTRAINT fk_edit_revision_media_blob_id_blob_sha256_media_blobs FOREIGN KEY(blob_id, blob_sha256) '
 'REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_edit_revision_media_project_id_edit_version_id_clip_key UNIQUE (project_id, '
 'edit_version_id, clip_key), \n'
 '\tCONSTRAINT uq_edit_revision_media_project_id_edit_version_id_track_ordinal UNIQUE (project_id, '
 'edit_version_id, track, ordinal), \n'
 "\tCONSTRAINT ck_edit_revision_media_track CHECK (track IN ('clips','audio')), \n"
 "\tCONSTRAINT ck_edit_revision_media_modality CHECK ((track='clips' AND modality IN ('video','image')) OR "
 "(track='audio' AND modality IN ('audio','video'))), \n"
 '\tCONSTRAINT ck_edit_revision_media_range CHECK (ordinal >= 0 AND offset_frame >= 0 AND source_in_frame '
 '>= 0 AND source_out_frame > source_in_frame), \n'
 '\tCONSTRAINT fk_edit_revision_media_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_edit_revision_media_blob_sha256_format CHECK (blob_sha256 IS NULL OR blob_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_revision_media_blob_id ON edit_revision_media (project_id, blob_id)',
 'CREATE INDEX ix_edit_revision_media_edit_version_id ON edit_revision_media (project_id, edit_version_id)',
 'CREATE INDEX ix_edit_revision_media_media_id ON edit_revision_media (project_id, media_id)',
 'CREATE INDEX ix_edit_revision_media_shot_id ON edit_revision_media (project_id, shot_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON edit_revision_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE edit_render_jobs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tedit_version_id UUID NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tattempt INTEGER NOT NULL, \n'
 '\tclaim_owner TEXT, \n'
 '\tclaim_until TIMESTAMP WITH TIME ZONE, \n'
 '\terror TEXT, \n'
 '\toutput_blob_id UUID, \n'
 '\toutput_sha256 VARCHAR(64), \n'
 '\treceipt JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_edit_render_jobs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_edit_render_jobs_project_id_edit_version_id_edit_revisions FOREIGN KEY(project_id, '
 'edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_edit_render_jobs_output_blob_id_output_sha256_media_blobs FOREIGN KEY(output_blob_id, '
 'output_sha256) REFERENCES media_blobs (id, sha256), \n'
 '\tCONSTRAINT uq_edit_render_jobs_project_id_edit_version_id UNIQUE (project_id, edit_version_id), \n'
 "\tCONSTRAINT ck_edit_render_jobs_status CHECK (status IN ('queued','running','succeeded','failed') AND "
 'attempt >= 0), \n'
 '\tCONSTRAINT ck_edit_render_jobs_output_pair CHECK ((output_blob_id IS NULL) = (output_sha256 IS '
 'NULL)), \n'
 "\tCONSTRAINT ck_edit_render_jobs_successful_output CHECK (status <> 'succeeded' OR output_blob_id IS NOT "
 'NULL), \n'
 '\tCONSTRAINT fk_edit_render_jobs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_edit_render_jobs_output_sha256_format CHECK (output_sha256 IS NULL OR output_sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_edit_render_jobs_edit_version_id ON edit_render_jobs (project_id, edit_version_id)',
 'CREATE INDEX ix_edit_render_jobs_output_blob_id ON edit_render_jobs (project_id, output_blob_id)',
 'CREATE INDEX ix_edit_render_queue ON edit_render_jobs (status, created_at)',
 'ALTER TABLE edit_workspaces ADD CONSTRAINT fk_edit_workspace_current_version FOREIGN KEY(project_id, id, '
 'current_version_id) REFERENCES edit_revisions (project_id, workspace_id, id)',
 'CREATE FUNCTION vsc_edit_member_set() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE v uuid; p uuid; wanted integer; actual bigint; doc jsonb;\n'
 'BEGIN\n'
 ' p:=NEW.project_id;\n'
 " IF TG_TABLE_NAME='edit_revisions' THEN v:=NEW.id; ELSE v:=NEW.edit_version_id; END IF;\n"
 ' SELECT member_count,document INTO wanted,doc FROM edit_revisions WHERE project_id=p AND id=v;\n'
 ' SELECT count(*) INTO actual FROM edit_revision_media WHERE project_id=p AND edit_version_id=v;\n'
 ' IF wanted IS NULL OR wanted<>actual OR '
 "wanted<>jsonb_array_length(doc->'clips')+jsonb_array_length(COALESCE(doc->'audio','[]'::jsonb)) THEN\n"
 "  RAISE EXCEPTION 'edit media membership is incomplete or sealed' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' IF EXISTS(SELECT 1 FROM edit_revision_media m WHERE m.project_id=p AND m.edit_version_id=v AND NOT '
 'EXISTS(\n'
 "  SELECT 1 FROM jsonb_array_elements(doc->m.track) item WHERE item->>'id'=m.clip_key AND "
 "item->>'media_id'=m.media_id::text\n"
 "  AND (item->>'in_frame')::integer=m.source_in_frame AND "
 "(item->>'out_frame')::integer=m.source_out_frame)) THEN\n"
 "  RAISE EXCEPTION 'edit media does not match fixed document' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NULL;\n'
 'END $$',
 'CREATE CONSTRAINT TRIGGER edit_member_set AFTER INSERT ON edit_revisions DEFERRABLE INITIALLY DEFERRED '
 'FOR EACH ROW EXECUTE FUNCTION vsc_edit_member_set()',
 'CREATE CONSTRAINT TRIGGER edit_member_set AFTER INSERT ON edit_revision_media DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_edit_member_set()',
 'CREATE FUNCTION vsc_edit_job_identity() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' OR "
 "(to_jsonb(NEW)-ARRAY['status','attempt','claim_owner','claim_until','error','output_blob_id','output_sha256','receipt']) "
 'IS DISTINCT FROM '
 "(to_jsonb(OLD)-ARRAY['status','attempt','claim_owner','claim_until','error','output_blob_id','output_sha256','receipt']) "
 "OR OLD.status='succeeded' THEN\n"
 "  RAISE EXCEPTION 'edit export identity or successful output is immutable' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER edit_job_identity BEFORE UPDATE OR DELETE ON edit_render_jobs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_edit_job_identity()']

def upgrade():
    for sql in DDL:
        op.execute(sql)

def downgrade():
    op.execute("DROP FUNCTION vsc_edit_job_identity() CASCADE")
    op.execute("DROP FUNCTION vsc_edit_member_set() CASCADE")
    op.drop_constraint("fk_edit_workspace_current_version", "edit_workspaces", type_="foreignkey")
    for name in ("edit_render_jobs", "edit_revision_media", "edit_revisions", "edit_workspaces"):
        op.drop_table(name)
