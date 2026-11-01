"""Fixed import manifests and resumable per-file outcomes."""
from alembic import op
revision="0017_media_imports"
down_revision="0016_spatial_scene"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE media_import_batches (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tasset_kind TEXT, \n'
 '\trights TEXT NOT NULL, \n'
 '\trights_scope JSONB NOT NULL, \n'
 '\tsource_evidence TEXT NOT NULL, \n'
 '\tmember_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_media_import_batches PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_media_import_batches_project_id_episode_id_episodes FOREIGN KEY(project_id, episode_id) '
 'REFERENCES episodes (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_media_import_batches_member_count CHECK (member_count BETWEEN 1 AND 200), \n'
 '\tCONSTRAINT ck_media_import_batches_asset_kind CHECK (asset_kind IS NULL OR asset_kind IN '
 "('character','location','prop','voice')), \n"
 "\tCONSTRAINT ck_media_import_batches_rights CHECK (rights IN ('owned','licensed','unknown')), \n"
 '\tCONSTRAINT fk_media_import_batches_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_media_import_batches_episode_id ON media_import_batches (project_id, episode_id)',
 '\n'
 'CREATE TABLE media_import_items (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tbatch_id UUID NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tfilename TEXT NOT NULL, \n'
 '\tsize_bytes BIGINT NOT NULL, \n'
 '\texpected_sha256 VARCHAR(64) NOT NULL, \n'
 '\tupload_key VARCHAR(48) NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tuploaded_metadata JSONB, \n'
 '\terror TEXT, \n'
 '\tmedia_id UUID, \n'
 '\tasset_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_media_import_items PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_media_import_items_project_id_batch_id_media_import_batches FOREIGN KEY(project_id, '
 'batch_id) REFERENCES media_import_batches (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_media_import_items_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_media_import_items_project_id_asset_id_asset_identities FOREIGN KEY(project_id, asset_id) '
 'REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_media_import_items_project_id_batch_id_ordinal UNIQUE (project_id, batch_id, ordinal), \n'
 '\tCONSTRAINT uq_media_import_items_upload_key UNIQUE (upload_key), \n'
 '\tCONSTRAINT ck_media_import_items_size CHECK (ordinal >= 0 AND size_bytes BETWEEN 1 AND 1073741824), \n'
 '\tCONSTRAINT ck_media_import_items_status CHECK (status IN '
 "('awaiting_upload','uploaded','completed','failed','cancelled')), \n"
 "\tCONSTRAINT ck_media_import_items_completed_media CHECK (status <> 'completed' OR media_id IS NOT "
 'NULL), \n'
 '\tCONSTRAINT fk_media_import_items_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT, \n'
 "\tCONSTRAINT ck_media_import_items_upload_key_format CHECK (upload_key ~ '^[0-9a-f]{48}$'), \n"
 '\tCONSTRAINT ck_media_import_items_expected_sha256_format CHECK (expected_sha256 IS NULL OR '
 "expected_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_media_import_items_asset_id ON media_import_items (project_id, asset_id)',
 'CREATE INDEX ix_media_import_items_batch_id ON media_import_items (project_id, batch_id)',
 'CREATE INDEX ix_media_import_items_media_id ON media_import_items (project_id, media_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON media_import_batches FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE FUNCTION vsc_import_manifest_members() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE p uuid; b uuid; wanted integer; actual integer; last_order integer;\n'
 'BEGIN\n'
 "p:=NEW.project_id; IF TG_TABLE_NAME='media_import_batches' THEN b:=NEW.id; ELSE b:=NEW.batch_id; END IF;\n"
 'SELECT member_count INTO wanted FROM media_import_batches WHERE project_id=p AND id=b;\n'
 'SELECT count(*),max(ordinal) INTO actual,last_order FROM media_import_items WHERE project_id=p AND '
 'batch_id=b;\n'
 "IF wanted IS NULL OR actual<>wanted OR last_order<>wanted-1 THEN RAISE EXCEPTION 'import manifest is "
 "incomplete or sealed' USING ERRCODE='23514'; END IF;\n"
 'RETURN NULL; END $$',
 'CREATE CONSTRAINT TRIGGER import_manifest_members AFTER INSERT ON media_import_batches DEFERRABLE '
 'INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_import_manifest_members()',
 'CREATE CONSTRAINT TRIGGER import_manifest_members AFTER INSERT ON media_import_items DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_import_manifest_members()',
 'CREATE FUNCTION vsc_import_item_identity() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 "IF TG_OP='INSERT' THEN\n"
 " IF NEW.status<>'awaiting_upload' OR NEW.uploaded_metadata IS NOT NULL OR NEW.media_id IS NOT NULL OR "
 "NEW.asset_id IS NOT NULL THEN RAISE EXCEPTION 'import must begin from fixed manifest' USING "
 "ERRCODE='23514'; END IF; RETURN NEW; END IF;\n"
 "IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['status','uploaded_metadata','error','media_id','asset_id']) IS "
 "DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','uploaded_metadata','error','media_id','asset_id']) OR "
 "OLD.status='completed' OR (OLD.status='cancelled' AND NEW IS DISTINCT FROM OLD) THEN\n"
 " RAISE EXCEPTION 'import identity or completed outcome is immutable' USING ERRCODE='23514'; END IF;\n"
 'IF OLD.uploaded_metadata IS NOT NULL AND NEW.uploaded_metadata IS DISTINCT FROM OLD.uploaded_metadata THEN '
 "RAISE EXCEPTION 'uploaded bytes are fixed' USING ERRCODE='23514'; END IF;\n"
 "IF NEW.uploaded_metadata IS NOT NULL AND ((NEW.uploaded_metadata->>'sha256') IS DISTINCT FROM "
 "NEW.expected_sha256 OR (NEW.uploaded_metadata->>'size_bytes')::bigint IS DISTINCT FROM NEW.size_bytes) "
 "THEN RAISE EXCEPTION 'uploaded manifest mismatch' USING ERRCODE='23514'; END IF;\n"
 "IF NEW.status IN ('uploaded','completed') AND NEW.uploaded_metadata IS NULL THEN RAISE EXCEPTION 'uploaded "
 "receipt missing' USING ERRCODE='23514'; END IF;\n"
 "IF NEW.status='completed' AND NOT EXISTS(SELECT 1 FROM media_items m JOIN media_blobs b ON b.id=m.blob_id "
 'WHERE m.project_id=NEW.project_id AND m.id=NEW.media_id AND b.sha256=NEW.expected_sha256) THEN RAISE '
 "EXCEPTION 'registered media differs from manifest' USING ERRCODE='23514'; END IF;\n"
 'RETURN NEW; END $$',
 'CREATE TRIGGER import_item_identity BEFORE INSERT OR UPDATE OR DELETE ON media_import_items FOR EACH ROW '
 'EXECUTE FUNCTION vsc_import_item_identity()']

def upgrade():
    for statement in DDL: op.execute(statement)

def downgrade():
    op.execute("DROP FUNCTION vsc_import_item_identity() CASCADE")
    op.execute("DROP FUNCTION vsc_import_manifest_members() CASCADE")
    op.drop_table("media_import_items")
    op.drop_table("media_import_batches")
