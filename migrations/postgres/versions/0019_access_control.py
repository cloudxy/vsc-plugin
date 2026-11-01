"""Persistent identities, scoped grants and revocable fixed sharing."""
from alembic import op
revision="0019_access_control"
down_revision="0018_text_tools"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE access_state (\n'
 '\tid SERIAL NOT NULL, \n'
 "\trevision BIGINT DEFAULT '0' NOT NULL, \n"
 '\tCONSTRAINT pk_access_state PRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_access_state_singleton CHECK (id=1 AND revision>=0)\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE access_identities (\n'
 '\tid UUID NOT NULL, \n'
 '\tsubject_key TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tdisplay_name TEXT NOT NULL, \n'
 '\tpreferences JSONB NOT NULL, \n'
 "\tactive BOOLEAN DEFAULT 'true' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_identities PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_access_identities_subject_key UNIQUE (subject_key), \n'
 '\tCONSTRAINT uq_access_identities_actor UNIQUE (actor)\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE access_credentials (\n'
 '\tid UUID NOT NULL, \n'
 '\tidentity_id UUID NOT NULL, \n'
 '\tsecret_sha256 TEXT NOT NULL, \n'
 "\trevoked BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_credentials PRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_access_credentials_sha256 CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT fk_access_credentials_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_access_credentials_secret_sha256 UNIQUE (secret_sha256)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_credentials_identity_id ON access_credentials (identity_id)',
 '\n'
 'CREATE TABLE access_workspaces (\n'
 '\tid UUID NOT NULL, \n'
 '\tname TEXT NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tparent_id UUID, \n'
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_workspaces PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_access_workspaces_parent_id_access_workspaces FOREIGN KEY(parent_id) REFERENCES '
 'access_workspaces (id), \n'
 "\tCONSTRAINT ck_access_workspaces_kind CHECK (kind IN ('personal','studio','substudio') AND "
 "((kind='substudio')=(parent_id IS NOT NULL))), \n"
 '\tCONSTRAINT fk_access_workspaces_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_workspaces_created_by ON access_workspaces (created_by)',
 'CREATE INDEX ix_access_workspaces_parent_id ON access_workspaces (parent_id)',
 "CREATE UNIQUE INDEX uq_access_personal_workspace ON access_workspaces (created_by) WHERE kind='personal'",
 '\n'
 'CREATE TABLE access_workspace_members (\n'
 '\tworkspace_id UUID NOT NULL, \n'
 '\tidentity_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tactive BOOLEAN NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_workspace_members PRIMARY KEY (workspace_id, identity_id), \n'
 "\tCONSTRAINT ck_access_workspace_members_role CHECK (role IN ('owner','editor','reviewer','viewer')), \n"
 '\tCONSTRAINT fk_access_workspace_members_workspace_id_access_workspaces FOREIGN KEY(workspace_id) '
 'REFERENCES access_workspaces (id), \n'
 '\tCONSTRAINT fk_access_workspace_members_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES '
 'access_identities (id)\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE access_projects (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tworkspace_id UUID NOT NULL, \n'
 '\treview_lanes JSONB NOT NULL, \n'
 '\tassigned_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_projects PRIMARY KEY (project_id), \n'
 '\tCONSTRAINT fk_access_projects_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id), \n'
 '\tCONSTRAINT fk_access_projects_workspace_id_access_workspaces FOREIGN KEY(workspace_id) REFERENCES '
 'access_workspaces (id), \n'
 '\tCONSTRAINT fk_access_projects_assigned_by_access_identities FOREIGN KEY(assigned_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_projects_assigned_by ON access_projects (assigned_by)',
 'CREATE INDEX ix_access_projects_workspace_id ON access_projects (workspace_id)',
 '\n'
 'CREATE TABLE access_project_members (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tidentity_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tactive BOOLEAN NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_project_members PRIMARY KEY (project_id, identity_id), \n'
 "\tCONSTRAINT ck_access_project_members_role CHECK (role IN ('owner','editor','reviewer','viewer')), \n"
 '\tCONSTRAINT fk_access_project_members_project_id_access_projects FOREIGN KEY(project_id) REFERENCES '
 'access_projects (project_id), \n'
 '\tCONSTRAINT fk_access_project_members_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES '
 'access_identities (id)\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE access_invitations (\n'
 '\tid UUID NOT NULL, \n'
 '\tworkspace_id UUID, \n'
 '\tproject_id UUID, \n'
 '\trole TEXT NOT NULL, \n'
 '\tsecret_sha256 TEXT NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 "\trevoked BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tcreated_by UUID NOT NULL, \n'
 '\taccepted_by UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_invitations PRIMARY KEY (id), \n'
 '\tCONSTRAINT ck_access_invitations_one_scope CHECK ((workspace_id IS NULL) <> (project_id IS NULL)), \n'
 "\tCONSTRAINT ck_access_invitations_role CHECK (role IN ('editor','reviewer','viewer')), \n"
 "\tCONSTRAINT ck_access_invitations_sha256 CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT fk_access_invitations_workspace_id_access_workspaces FOREIGN KEY(workspace_id) REFERENCES '
 'access_workspaces (id), \n'
 '\tCONSTRAINT fk_access_invitations_project_id_access_projects FOREIGN KEY(project_id) REFERENCES '
 'access_projects (project_id), \n'
 '\tCONSTRAINT uq_access_invitations_secret_sha256 UNIQUE (secret_sha256), \n'
 '\tCONSTRAINT fk_access_invitations_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_access_invitations_accepted_by_access_identities FOREIGN KEY(accepted_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_invitations_accepted_by ON access_invitations (accepted_by)',
 'CREATE INDEX ix_access_invitations_created_by ON access_invitations (created_by)',
 'CREATE INDEX ix_access_invitations_project_id ON access_invitations (project_id)',
 'CREATE INDEX ix_access_invitations_workspace_id ON access_invitations (workspace_id)',
 '\n'
 'CREATE TABLE access_shares (\n'
 '\tid UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tcanvas_id UUID NOT NULL, \n'
 '\tcanvas_version_id UUID NOT NULL, \n'
 '\tmode TEXT NOT NULL, \n'
 '\tsecret_sha256 TEXT NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 "\trevoked BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\tcreated_by UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_shares PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_access_shares_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, canvas_id) '
 'REFERENCES creative_canvases (project_id, id), \n'
 '\tCONSTRAINT fk_access_shares_project_id_canvas_id_canvas_version_id_5a54 FOREIGN KEY(project_id, '
 'canvas_id, canvas_version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id), \n'
 '\tCONSTRAINT uq_access_shares_project_id_id UNIQUE (project_id, id), \n'
 "\tCONSTRAINT ck_access_shares_mode CHECK (mode IN ('view','edit')), \n"
 "\tCONSTRAINT ck_access_shares_sha256 CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT fk_access_shares_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_access_shares_secret_sha256 UNIQUE (secret_sha256), \n'
 '\tCONSTRAINT fk_access_shares_created_by_access_identities FOREIGN KEY(created_by) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_shares_canvas_id ON access_shares (canvas_id)',
 'CREATE INDEX ix_access_shares_canvas_version_id ON access_shares (canvas_version_id)',
 'CREATE INDEX ix_access_shares_created_by ON access_shares (created_by)',
 'CREATE INDEX ix_access_shares_project_id ON access_shares (project_id)',
 '\n'
 'CREATE TABLE access_share_media (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tshare_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tCONSTRAINT pk_access_share_media PRIMARY KEY (project_id, share_id, media_id), \n'
 '\tCONSTRAINT fk_access_share_media_project_id_share_id_access_shares FOREIGN KEY(project_id, share_id) '
 'REFERENCES access_shares (project_id, id), \n'
 '\tCONSTRAINT fk_access_share_media_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id)\n'
 ')\n'
 '\n',
 '\n'
 'CREATE TABLE access_commands (\n'
 '\tkey TEXT NOT NULL, \n'
 '\tidentity_id UUID, \n'
 '\taction TEXT NOT NULL, \n'
 '\trequest_sha256 TEXT NOT NULL, \n'
 '\trevision BIGINT NOT NULL, \n'
 '\tresponse JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_commands PRIMARY KEY (key), \n'
 '\tCONSTRAINT fk_access_commands_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES '
 'access_identities (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_access_commands_revision UNIQUE (revision)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_commands_identity_id ON access_commands (identity_id)',
 '\n'
 'CREATE TABLE access_review_submissions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcandidate_id UUID NOT NULL, \n'
 '\tlane TEXT NOT NULL, \n'
 '\tsupersedes_id UUID, \n'
 '\tsubmitted_by UUID NOT NULL, \n'
 '\treview_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_access_review_submissions PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_access_review_submissions_project_id_id UNIQUE (project_id, id), \n'
 '\tCONSTRAINT fk_access_review_submissions_project_id_candidate_id_bi_ee83 FOREIGN KEY(project_id, '
 'candidate_id) REFERENCES binding_candidates (project_id, id), \n'
 '\tCONSTRAINT fk_access_review_submissions_project_id_candidate_id_re_a4f6 FOREIGN KEY(project_id, '
 'candidate_id, review_id) REFERENCES media_reviews (project_id, candidate_id, id), \n'
 '\tCONSTRAINT fk_access_review_submissions_project_id_supersedes_id_a_4e38 FOREIGN KEY(project_id, '
 'supersedes_id) REFERENCES access_review_submissions (project_id, id), \n'
 "\tCONSTRAINT ck_access_review_submissions_lane CHECK (lane IN ('character','storyboard','video')), \n"
 '\tCONSTRAINT fk_access_review_submissions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_access_review_submissions_submitted_by_access_identities FOREIGN KEY(submitted_by) '
 'REFERENCES access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_access_review_submissions_candidate_id ON access_review_submissions (candidate_id)',
 'CREATE INDEX ix_access_review_submissions_project_id ON access_review_submissions (project_id)',
 'CREATE INDEX ix_access_review_submissions_review_id ON access_review_submissions (review_id)',
 'CREATE INDEX ix_access_review_submissions_submitted_by ON access_review_submissions (submitted_by)',
 'CREATE INDEX ix_access_review_submissions_supersedes_id ON access_review_submissions (supersedes_id)',
 'CREATE UNIQUE INDEX uq_access_review_pending ON access_review_submissions (project_id, candidate_id) WHERE '
 'review_id IS NULL',
 'INSERT INTO access_state(id,revision) VALUES(1,0)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON access_commands FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE FUNCTION vsc_access_identity() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN RAISE EXCEPTION 'access history is retained' USING ERRCODE='23514'; END IF;\n"
 " IF TG_TABLE_NAME='access_identities' AND (to_jsonb(NEW)-ARRAY['display_name','preferences','active']) IS "
 "DISTINCT FROM (to_jsonb(OLD)-ARRAY['display_name','preferences','active']) THEN\n"
 "  RAISE EXCEPTION 'identity and audit actor are immutable' USING ERRCODE='23514';\n"
 " ELSIF TG_TABLE_NAME='access_workspaces' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN\n"
 "  RAISE EXCEPTION 'workspace ancestry is immutable' USING ERRCODE='23514';\n"
 " ELSIF TG_TABLE_NAME='access_credentials' AND ((to_jsonb(NEW)-'revoked') IS DISTINCT FROM "
 "(to_jsonb(OLD)-'revoked') OR (to_jsonb(OLD)->>'revoked')::boolean AND NOT "
 "(to_jsonb(NEW)->>'revoked')::boolean) THEN\n"
 "  RAISE EXCEPTION 'credential identity and revocation are final' USING ERRCODE='23514';\n"
 " ELSIF TG_TABLE_NAME='access_invitations' AND ((to_jsonb(NEW)-ARRAY['revoked','accepted_by']) IS DISTINCT "
 "FROM (to_jsonb(OLD)-ARRAY['revoked','accepted_by']) OR (to_jsonb(OLD)->>'accepted_by') IS NOT NULL AND "
 "(to_jsonb(NEW)->>'accepted_by') IS DISTINCT FROM (to_jsonb(OLD)->>'accepted_by') OR "
 "(to_jsonb(OLD)->>'revoked')::boolean AND NOT (to_jsonb(NEW)->>'revoked')::boolean) THEN\n"
 "  RAISE EXCEPTION 'invitation scope and acceptance are fixed' USING ERRCODE='23514';\n"
 " ELSIF TG_TABLE_NAME='access_shares' AND ((to_jsonb(NEW)-'revoked') IS DISTINCT FROM "
 "(to_jsonb(OLD)-'revoked') OR (to_jsonb(OLD)->>'revoked')::boolean AND NOT "
 "(to_jsonb(NEW)->>'revoked')::boolean) THEN\n"
 "  RAISE EXCEPTION 'share scope and revocation are fixed' USING ERRCODE='23514';\n"
 " ELSIF TG_TABLE_NAME='access_review_submissions' AND ((to_jsonb(NEW)-'review_id') IS DISTINCT FROM "
 "(to_jsonb(OLD)-'review_id') OR (to_jsonb(OLD)->>'review_id') IS NOT NULL) THEN\n"
 "  RAISE EXCEPTION 'review submissions pin candidate and original decision' USING ERRCODE='23514';\n"
 ' END IF;\n'
 ' RETURN NEW;\n'
 'END $$\n',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_identities FOR EACH ROW EXECUTE FUNCTION '
 'vsc_access_identity()',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_workspaces FOR EACH ROW EXECUTE FUNCTION '
 'vsc_access_identity()',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_credentials FOR EACH ROW EXECUTE FUNCTION '
 'vsc_access_identity()',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_invitations FOR EACH ROW EXECUTE FUNCTION '
 'vsc_access_identity()',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_shares FOR EACH ROW EXECUTE FUNCTION '
 'vsc_access_identity()',
 'CREATE TRIGGER access_identity BEFORE UPDATE OR DELETE ON access_review_submissions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_access_identity()',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON access_share_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()']

def upgrade():
    for statement in DDL:op.execute(statement)

def downgrade():
    op.drop_table('access_review_submissions')
    op.drop_table('access_commands')
    op.drop_table('access_share_media')
    op.drop_table('access_shares')
    op.drop_table('access_invitations')
    op.drop_table('access_project_members')
    op.drop_table('access_projects')
    op.drop_table('access_workspace_members')
    op.drop_table('access_workspaces')
    op.drop_table('access_credentials')
    op.drop_table('access_identities')
    op.drop_table('access_state')
    op.execute("DROP FUNCTION vsc_access_identity()")
