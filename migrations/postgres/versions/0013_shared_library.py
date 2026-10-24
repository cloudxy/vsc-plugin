"""Workspace shared library with immutable fixed versions and local registrations."""
from alembic import op

revision = "0013_shared_library"
down_revision = "0012_assisted_workflow"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE library_entries (\n'
 '\tid UUID NOT NULL, \n'
 '\tlibrary_key TEXT NOT NULL, \n'
 '\tcategory TEXT NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 "\tvisibility TEXT DEFAULT 'workspace' NOT NULL, \n"
 "\tstatus TEXT DEFAULT 'active' NOT NULL, \n"
 "\trights_status TEXT DEFAULT 'active' NOT NULL, \n"
 '\tcurrent_version_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_entries PRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_library_entries_visibility CHECK (visibility = 'workspace'), \n"
 "\tCONSTRAINT ck_library_entries_status CHECK (status IN ('active','retired')), \n"
 "\tCONSTRAINT ck_library_entries_rights_status CHECK (rights_status IN ('active','revoked')), \n"
 '\tCONSTRAINT uq_library_entries_library_key UNIQUE (library_key)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_library_entries_browse ON library_entries (visibility, status, category)',
 '\n'
 'CREATE TABLE library_entry_versions (\n'
 '\tid UUID NOT NULL, \n'
 '\tentry_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tcategory TEXT NOT NULL, \n'
 '\tdescription TEXT NOT NULL, \n'
 '\tspecification JSONB NOT NULL, \n'
 '\tmember_count INTEGER NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\timport_key TEXT, \n'
 '\trequest_sha256 VARCHAR(64) NOT NULL, \n'
 '\tlicense JSONB NOT NULL, \n'
 '\tallowed_purposes JSONB NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE, \n'
 '\tpublished_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_entry_versions PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_library_entry_versions_entry_id_library_entries FOREIGN KEY(entry_id) REFERENCES '
 'library_entries (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_library_entry_versions_entry_id_version UNIQUE (entry_id, version), \n'
 '\tCONSTRAINT uq_library_entry_versions_entry_id_id UNIQUE (entry_id, id), \n'
 '\tCONSTRAINT ck_library_entry_versions_version CHECK (version > 0), \n'
 '\tCONSTRAINT ck_library_entry_versions_member_count CHECK (member_count >= 0 AND member_count <= 32), \n'
 '\tCONSTRAINT ck_library_entry_versions_allowed_purposes CHECK (jsonb_typeof(allowed_purposes) = '
 "'array'), \n"
 '\tCONSTRAINT uq_library_entry_versions_import_key UNIQUE (import_key), \n'
 '\tCONSTRAINT ck_library_entry_versions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '
 "'^[0-9a-f]{64}$'), \n"
 '\tCONSTRAINT ck_library_entry_versions_request_sha256_format CHECK (request_sha256 IS NULL OR '
 "request_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_library_versions_entry ON library_entry_versions (entry_id, version)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_entry_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE library_version_media (\n'
 '\tlibrary_version_id UUID NOT NULL, \n'
 '\tmember_key TEXT NOT NULL, \n'
 '\tblob_id UUID NOT NULL, \n'
 '\tmodality TEXT NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tCONSTRAINT pk_library_version_media PRIMARY KEY (library_version_id, member_key), \n'
 '\tCONSTRAINT fk_library_version_media_library_version_id_library_ent_6022 FOREIGN KEY(library_version_id) '
 'REFERENCES library_entry_versions (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_library_version_media_blob_id_media_blobs FOREIGN KEY(blob_id) REFERENCES media_blobs (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_library_version_media_library_version_id_member_key_blob_id UNIQUE (library_version_id, '
 'member_key, blob_id), \n'
 '\tCONSTRAINT uq_library_version_media_library_version_id_ordinal UNIQUE (library_version_id, ordinal), \n'
 '\tCONSTRAINT ck_library_version_media_ordinal CHECK (ordinal >= 0), \n'
 '\tCONSTRAINT ck_library_version_media_modality CHECK (modality IN '
 "('image','video','audio','text','document','other'))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_library_version_media_blob ON library_version_media (blob_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_version_media FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE library_entry_decisions (\n'
 '\tid UUID NOT NULL, \n'
 '\tentry_id UUID NOT NULL, \n'
 '\toutcome TEXT NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tidempotency_key TEXT NOT NULL, \n'
 '\trequest_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_entry_decisions PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_library_entry_decisions_entry_id_library_entries FOREIGN KEY(entry_id) REFERENCES '
 'library_entries (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT uq_library_entry_decisions_entry_id_idempotency_key UNIQUE (entry_id, idempotency_key), \n'
 "\tCONSTRAINT ck_library_entry_decisions_outcome CHECK (outcome IN ('retire','revoke_rights')), \n"
 '\tCONSTRAINT ck_library_entry_decisions_request_sha256_format CHECK (request_sha256 IS NULL OR '
 "request_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_entry_decisions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'ALTER TABLE library_entries ADD CONSTRAINT fk_library_entries_current_version FOREIGN KEY(id, '
 'current_version_id) REFERENCES library_entry_versions (entry_id, id) ON DELETE RESTRICT',
 'ALTER TABLE library_reuses ADD COLUMN library_version_id UUID',
 'ALTER TABLE library_reuses ADD COLUMN member_key TEXT',
 'ALTER TABLE library_reuses ADD COLUMN blob_id UUID',
 'ALTER TABLE library_reuses ADD COLUMN rights_decision_id UUID',
 'ALTER TABLE library_reuses ADD CONSTRAINT ck_library_reuses_fixed_library_reference CHECK '
 '((library_version_id IS NULL AND member_key IS NULL AND blob_id IS NULL AND rights_decision_id IS NULL) OR '
 '(library_version_id IS NOT NULL AND member_key IS NOT NULL AND blob_id IS NOT NULL AND rights_decision_id '
 "IS NOT NULL AND reuse_mode IN ('publish','reference','derive')))",
 'ALTER TABLE library_reuses ADD CONSTRAINT fk_library_reuses_library_version_id_member_key_blob_id_5161 '
 'FOREIGN KEY(library_version_id, member_key, blob_id) REFERENCES library_version_media (library_version_id, '
 'member_key, blob_id)',
 'ALTER TABLE library_reuses ADD CONSTRAINT fk_library_reuses_project_id_media_id_blob_id_media_items '
 'FOREIGN KEY(project_id, media_id, blob_id) REFERENCES media_items (project_id, id, blob_id)',
 'ALTER TABLE library_reuses ADD CONSTRAINT fk_library_reuses_project_id_rights_decision_id_rights__c5ff '
 'FOREIGN KEY(project_id, rights_decision_id) REFERENCES rights_decisions (project_id, id) ON DELETE '
 'RESTRICT',
 'CREATE INDEX ix_library_reuses_fixed_member ON library_reuses (library_version_id, member_key, reuse_mode)',
 'CREATE FUNCTION vsc_library_reuse_scope() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE member library_version_media%ROWTYPE; version library_entry_versions%ROWTYPE;\n'
 '        rights rights_decisions%ROWTYPE; item media_items%ROWTYPE; entry library_entries%ROWTYPE;\n'
 'BEGIN\n'
 '  IF NEW.library_version_id IS NULL THEN RETURN NEW; END IF;\n'
 '  IF NEW.reuse_mode = \'publish\' AND vsc_library_has_imported_ancestor(NEW.project_id, NEW.media_id) THEN\n'
 '    RAISE EXCEPTION \'library sourced media cannot be republished\' USING ERRCODE=\'23514\';\n'
 '  END IF;\n'
 '  SELECT * INTO member FROM library_version_media WHERE library_version_id=NEW.library_version_id AND '
 'member_key=NEW.member_key;\n'
 '  SELECT * INTO version FROM library_entry_versions WHERE id=NEW.library_version_id;\n'
 '  SELECT * INTO entry FROM library_entries WHERE id=version.entry_id;\n'
 '  SELECT * INTO rights FROM rights_decisions WHERE project_id=NEW.project_id AND '
 'id=NEW.rights_decision_id;\n'
 '  SELECT * INTO item FROM media_items WHERE project_id=NEW.project_id AND id=NEW.media_id;\n'
 '  IF rights.media_id IS DISTINCT FROM NEW.media_id OR rights.source_id IS DISTINCT FROM NEW.source_id\n'
 '     OR item.modality IS DISTINCT FROM member.modality OR NEW.library_key IS DISTINCT FROM '
 'entry.library_key\n'
 '     OR NEW.library_version IS DISTINCT FROM version.version::text THEN\n'
 "    RAISE EXCEPTION 'library reuse must pin its own media, source, rights and fixed member' USING "
 "ERRCODE='23514';\n"
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER library_reuse_scope BEFORE INSERT ON library_reuses FOR EACH ROW EXECUTE FUNCTION '
 'vsc_library_reuse_scope()',
 'CREATE FUNCTION vsc_library_entry_identity() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'BEGIN\n'
 "  IF TG_OP='DELETE' OR "
 "(to_jsonb(NEW)-ARRAY['title','category','status','rights_status','current_version_id']) IS DISTINCT FROM\n"
 '                      '
 "(to_jsonb(OLD)-ARRAY['title','category','status','rights_status','current_version_id']) THEN\n"
 "    RAISE EXCEPTION 'library identity is immutable' USING ERRCODE='23514';\n"
 '  END IF;\n'
 '  RETURN NEW;\n'
 'END $$',
 'CREATE TRIGGER library_entry_identity BEFORE UPDATE OR DELETE ON library_entries FOR EACH ROW EXECUTE '
 'FUNCTION vsc_library_entry_identity()']

# A fixed version declares its complete set cardinality. Since both the version
# and every member are append-only, verifying the count at commit permits the
# creating transaction and permanently prevents later member INSERTs.
DDL += ["""
CREATE FUNCTION vsc_library_has_imported_ancestor(p_project_id uuid, p_media_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
WITH RECURSIVE edges AS NOT MATERIALIZED (
  SELECT o.media_id AS child, i.media_id AS parent
    FROM operation_outputs o JOIN operation_inputs i
      ON i.project_id=o.project_id AND i.operation_id=o.operation_id
    WHERE o.project_id=p_project_id
  UNION ALL
  SELECT o.media_id AS child, i.media_id AS parent
    FROM job_outputs o JOIN job_input_media i
      ON i.project_id=o.project_id AND i.job_id=o.job_id
    WHERE o.project_id=p_project_id
), ancestors(media_id) AS (
  SELECT p_media_id
  UNION
  SELECT edges.parent FROM ancestors JOIN edges ON edges.child=ancestors.media_id
)
SELECT EXISTS (
  SELECT 1 FROM ancestors a JOIN library_reuses r
    ON r.project_id=p_project_id AND r.media_id=a.media_id
    WHERE r.library_version_id IS NOT NULL AND r.reuse_mode IN ('reference','derive')
)
$$
""", """
CREATE FUNCTION vsc_library_member_set() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_id uuid; expected integer; actual bigint;
BEGIN
  IF TG_TABLE_NAME='library_entry_versions' THEN version_id:=NEW.id;
  ELSE version_id:=NEW.library_version_id; END IF;
  SELECT member_count INTO expected FROM library_entry_versions WHERE id=version_id;
  SELECT count(*) INTO actual FROM library_version_media WHERE library_version_id=version_id;
  IF expected IS NULL OR actual <> expected THEN
    RAISE EXCEPTION 'fixed library member set is incomplete or already sealed' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END $$
""", """
CREATE CONSTRAINT TRIGGER library_version_member_set AFTER INSERT ON library_entry_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_library_member_set()
""", """
CREATE CONSTRAINT TRIGGER library_media_member_set AFTER INSERT ON library_version_media
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_library_member_set()
"""]

def upgrade():
    for sql in DDL:
        op.execute(sql)

def downgrade():
    op.execute("DROP TRIGGER library_version_member_set ON library_entry_versions")
    op.execute("DROP TRIGGER library_media_member_set ON library_version_media")
    op.execute("DROP FUNCTION vsc_library_member_set()")
    op.execute("DROP TRIGGER library_reuse_scope ON library_reuses")
    op.execute("DROP FUNCTION vsc_library_reuse_scope()")
    op.execute("DROP FUNCTION vsc_library_has_imported_ancestor(uuid,uuid)")
    op.execute("DROP FUNCTION vsc_library_entry_identity() CASCADE")
    op.drop_constraint("fk_library_entries_current_version", "library_entries", type_="foreignkey")
    op.drop_constraint(op.f('ck_library_reuses_fixed_library_reference'), "library_reuses")
    op.drop_constraint(op.f('fk_library_reuses_library_version_id_member_key_blob_id_library_version_media'), "library_reuses")
    op.drop_constraint(op.f('fk_library_reuses_project_id_media_id_blob_id_media_items'), "library_reuses")
    op.drop_constraint(op.f('fk_library_reuses_project_id_rights_decision_id_rights_decisions'), "library_reuses")
    op.drop_column("library_reuses", 'rights_decision_id')
    op.drop_column("library_reuses", 'blob_id')
    op.drop_column("library_reuses", 'member_key')
    op.drop_column("library_reuses", 'library_version_id')
    op.drop_table("library_entry_decisions")
    op.drop_table("library_version_media")
    op.drop_table("library_entry_versions")
    op.drop_table("library_entries")
