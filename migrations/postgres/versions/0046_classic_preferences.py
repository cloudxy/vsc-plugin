"""Personal classic favorites preserve original identity and project-media ownership."""
from alembic import op
revision = '0046_classic_preferences'
down_revision = '0045_auth_challenges'
branch_labels = None
depends_on = None
DDL = ['\n'
 'CREATE TABLE classic_media_favorites (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tidentity_id UUID NOT NULL, \n'
 '\tactive BOOLEAN NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_classic_media_favorites PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_classic_media_favorites_project_id_media_id_media_items FOREIGN KEY(project_id, '
 'media_id) REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_classic_media_favorites_project_id_identity_id_media_id UNIQUE (project_id, '
 'identity_id, media_id), \n'
 '\tCONSTRAINT ck_classic_media_favorites_version CHECK (version > 0), \n'
 '\tCONSTRAINT fk_classic_media_favorites_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_classic_media_favorites_identity_id_access_identities FOREIGN KEY(identity_id) '
 'REFERENCES access_identities (id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_classic_media_favorites_identity_active ON classic_media_favorites (identity_id, '
 'project_id, active)']
GUARD = "\nCREATE FUNCTION vsc_classic_favorite_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'favorite history must be retained' USING ERRCODE='23514'; END IF;\n IF ROW(NEW.id,NEW.project_id,NEW.identity_id,NEW.media_id,NEW.created_at) IS DISTINCT FROM ROW(OLD.id,OLD.project_id,OLD.identity_id,OLD.media_id,OLD.created_at) OR NEW.version<>OLD.version+1 THEN\n  RAISE EXCEPTION 'favorite identity is fixed and version must advance once' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER classic_favorite_guard BEFORE UPDATE OR DELETE ON classic_media_favorites FOR EACH ROW EXECUTE FUNCTION vsc_classic_favorite_guard();\n"

def upgrade():
    for sql in DDL: op.execute(sql)
    op.execute(GUARD)

def downgrade():
    op.execute('LOCK TABLE classic_media_favorites IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM classic_media_favorites) THEN RAISE EXCEPTION 'favorite facts exist; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute('DROP FUNCTION vsc_classic_favorite_guard() CASCADE')
    op.drop_table('classic_media_favorites')
