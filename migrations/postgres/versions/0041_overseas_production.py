"""Typed provider asset receipts and original overseas understanding attempts."""
from alembic import op
revision='0041_overseas_production'
down_revision='0040_canvas_sound_completion'
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE provider_asset_registrations (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tunit_id UUID NOT NULL, \n'
 '\tsource_version_id UUID NOT NULL, \n'
 '\tentity_key TEXT NOT NULL, \n'
 '\tasset_id UUID, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tmedia_sha256 TEXT NOT NULL, \n'
 '\tprovider TEXT NOT NULL, \n'
 '\taccount_scope TEXT NOT NULL, \n'
 '\tstatus TEXT NOT NULL, \n'
 '\tremote_asset_id TEXT, \n'
 '\treceipt JSONB, \n'
 '\terror_code TEXT, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_provider_asset_registrations PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_unit_id_text_e9be FOREIGN KEY(project_id, unit_id) '
 'REFERENCES text_tool_units (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_source_versi_e72a FOREIGN KEY(project_id, '
 'source_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_asset_id_ass_6fd3 FOREIGN KEY(project_id, '
 'asset_id) REFERENCES asset_identities (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_media_id_media_items FOREIGN KEY(project_id, '
 'media_id) REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_provider_asset_registrations_status CHECK (status IN '
 "('running','submission_unknown','completed','failed')), \n"
 "\tCONSTRAINT ck_provider_asset_registrations_receipt CHECK ((status='completed') = (remote_asset_id IS NOT "
 'NULL AND receipt IS NOT NULL)), \n'
 '\tCONSTRAINT ck_provider_asset_registrations_identity CHECK (length(entity_key)>0 AND length(provider)>0 '
 "AND length(account_scope)>0 AND media_sha256 ~ '^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_media_id_blo_15fb FOREIGN KEY(project_id, '
 'media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_provider_asset_registrations_blob_id_media_sha256_me_4450 FOREIGN KEY(blob_id, '
 'media_sha256) REFERENCES media_blobs (id, sha256) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_provider_asset_registrations_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_provider_asset_registrations_media_sha256_format CHECK (media_sha256 IS NULL OR '
 "media_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_provider_asset_registrations_asset_id ON provider_asset_registrations (project_id, '
 'asset_id)',
 'CREATE INDEX ix_provider_asset_registrations_blob ON provider_asset_registrations (blob_id, media_sha256)',
 'CREATE INDEX ix_provider_asset_registrations_media_id ON provider_asset_registrations (project_id, '
 'media_id)',
 'CREATE INDEX ix_provider_asset_registrations_source_version_id ON provider_asset_registrations '
 '(project_id, source_version_id)',
 'CREATE INDEX ix_provider_asset_registrations_unit_id ON provider_asset_registrations (project_id, unit_id)']
GUARD="\nCREATE FUNCTION vsc_provider_asset_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE v artifact_versions%ROWTYPE;\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'provider registration history cannot be deleted' USING ERRCODE='23514'; END IF;\n IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-ARRAY['status','remote_asset_id','receipt','error_code']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','remote_asset_id','receipt','error_code']) OR OLD.status IN ('completed','failed')) THEN\n  RAISE EXCEPTION 'provider request and terminal receipt are fixed' USING ERRCODE='23514'; END IF;\n SELECT * INTO v FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.source_version_id;\n IF v.artifact_type IS DISTINCT FROM 'text-tool-draft' OR v.artifact_key IS DISTINCT FROM 'text-tool:'||NEW.unit_id::text OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(convert_from(v.document,'UTF8')::jsonb->'entities') e WHERE e->>'key'=NEW.entity_key AND e->>'media_id'=NEW.media_id::text AND nullif(e->>'asset_id','')::uuid IS NOT DISTINCT FROM NEW.asset_id) THEN\n  RAISE EXCEPTION 'provider asset must pin its original entity and media' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER provider_asset_guard BEFORE INSERT OR UPDATE OR DELETE ON provider_asset_registrations FOR EACH ROW EXECUTE FUNCTION vsc_provider_asset_guard();\n"
BINDING="\nCREATE OR REPLACE FUNCTION vsc_text_tool_binding() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE u text_tool_units%ROWTYPE; a artifact_versions%ROWTYPE; r text_tool_attempts%ROWTYPE;\nBEGIN\n IF TG_TABLE_NAME='text_tool_units' THEN\n  SELECT * INTO u FROM text_tool_units WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=u.project_id AND id=u.current_version_id;\n  IF a.id IS NULL OR a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'format' IS DISTINCT FROM 'vsc.text-tool/'||u.tool||'/v1' THEN\n   RAISE EXCEPTION 'text unit must point to its own typed fixed draft' USING ERRCODE='23514'; END IF;\n ELSE\n  SELECT * INTO r FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO u FROM text_tool_units WHERE project_id=r.project_id AND id=r.unit_id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.input_version_id;\n  IF a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text THEN\n   RAISE EXCEPTION 'text attempt input belongs to another unit' USING ERRCODE='23514'; END IF;\n  IF NOT ((u.tool='novel' AND r.action IN ('synopsis','characters','outline','scenes','body','qa_notes')) OR (u.tool='translation' AND r.action IN ('translate','terms')) OR (u.tool='scoring' AND r.action IN ('score','analyze')) OR (u.tool='breakdown' AND r.action='observe') OR (u.tool='qc' AND r.action='check') OR (u.tool='overseas' AND r.action IN ('localize','understand'))) THEN\n   RAISE EXCEPTION 'text action does not belong to tool' USING ERRCODE='23514'; END IF;\n  IF r.result_version_id IS NOT NULL THEN\n   SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.result_version_id;\n   IF a.artifact_type<>'text-tool-result' OR convert_from(a.document,'UTF8')::jsonb->>'unit_id' IS DISTINCT FROM u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'input_version_id' IS DISTINCT FROM r.input_version_id::text OR convert_from(a.document,'UTF8')::jsonb->>'action' IS DISTINCT FROM r.action THEN\n    RAISE EXCEPTION 'text result must pin its own input and action' USING ERRCODE='23514'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND $$\n"
LEGACY_BINDING="\nCREATE OR REPLACE FUNCTION vsc_text_tool_binding() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE u text_tool_units%ROWTYPE; a artifact_versions%ROWTYPE; r text_tool_attempts%ROWTYPE;\nBEGIN\n IF TG_TABLE_NAME='text_tool_units' THEN\n  SELECT * INTO u FROM text_tool_units WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=u.project_id AND id=u.current_version_id;\n  IF a.id IS NULL OR a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'format' IS DISTINCT FROM 'vsc.text-tool/'||u.tool||'/v1' THEN\n   RAISE EXCEPTION 'text unit must point to its own typed fixed draft' USING ERRCODE='23514'; END IF;\n ELSE\n  SELECT * INTO r FROM text_tool_attempts WHERE project_id=NEW.project_id AND id=NEW.id;\n  SELECT * INTO u FROM text_tool_units WHERE project_id=r.project_id AND id=r.unit_id;\n  SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.input_version_id;\n  IF a.artifact_type<>'text-tool-draft' OR a.artifact_key<>'text-tool:'||u.id::text THEN\n   RAISE EXCEPTION 'text attempt input belongs to another unit' USING ERRCODE='23514'; END IF;\n  IF NOT ((u.tool='novel' AND r.action IN ('synopsis','characters','outline','scenes','body','qa_notes')) OR (u.tool='translation' AND r.action IN ('translate','terms')) OR (u.tool='scoring' AND r.action IN ('score','analyze')) OR (u.tool='breakdown' AND r.action='observe') OR (u.tool='qc' AND r.action='check') OR (u.tool='overseas' AND r.action='localize')) THEN\n   RAISE EXCEPTION 'text action does not belong to tool' USING ERRCODE='23514'; END IF;\n  IF r.result_version_id IS NOT NULL THEN\n   SELECT * INTO a FROM artifact_versions WHERE project_id=r.project_id AND id=r.result_version_id;\n   IF a.artifact_type<>'text-tool-result' OR convert_from(a.document,'UTF8')::jsonb->>'unit_id' IS DISTINCT FROM u.id::text OR convert_from(a.document,'UTF8')::jsonb->>'input_version_id' IS DISTINCT FROM r.input_version_id::text OR convert_from(a.document,'UTF8')::jsonb->>'action' IS DISTINCT FROM r.action THEN\n    RAISE EXCEPTION 'text result must pin its own input and action' USING ERRCODE='23514'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND $$\n"
def upgrade():
    for sql in DDL:op.execute(sql)
    op.execute(GUARD)
    op.execute('ALTER TABLE text_tool_attempts DROP CONSTRAINT ck_text_tool_attempts_action')
    op.execute("ALTER TABLE text_tool_attempts ADD CONSTRAINT ck_text_tool_attempts_action CHECK (action IN ('synopsis','characters','outline','scenes','body','qa_notes','translate','terms','analyze','score','observe','understand','localize','check'))")
    op.execute(BINDING)
def downgrade():
    op.execute('LOCK TABLE provider_asset_registrations, text_tool_attempts, artifact_versions IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM provider_asset_registrations) OR EXISTS(SELECT 1 FROM text_tool_attempts WHERE action='understand') OR EXISTS(SELECT 1 FROM artifact_versions WHERE artifact_type='overseas-asset-image-draft') THEN RAISE EXCEPTION 'overseas production history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute('DROP TABLE provider_asset_registrations')
    op.execute('DROP FUNCTION vsc_provider_asset_guard()')
    op.execute('ALTER TABLE text_tool_attempts DROP CONSTRAINT ck_text_tool_attempts_action')
    op.execute("ALTER TABLE text_tool_attempts ADD CONSTRAINT ck_text_tool_attempts_action CHECK (action IN ('synopsis','characters','outline','scenes','body','qa_notes','translate','terms','analyze','score','observe','localize','check'))")
    op.execute(LEGACY_BINDING)
