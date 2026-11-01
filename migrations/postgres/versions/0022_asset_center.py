"""Catalog annotations and fixed library selection/download records."""
from alembic import op
revision="0022_asset_center"
down_revision="0021_commerce"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE library_catalog_edits (\n'
 '\tid UUID NOT NULL, \n'
 '\tentry_id UUID NOT NULL, \n'
 '\tlibrary_version_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tasset_kind TEXT NOT NULL, \n'
 '\tform_name TEXT NOT NULL, \n'
 '\tworkspace_id UUID, \n'
 '\treview_status TEXT NOT NULL, \n'
 '\tnotes TEXT NOT NULL, \n'
 '\ttag_count INTEGER NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcommand_key TEXT NOT NULL, \n'
 '\trequest_sha256 TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_catalog_edits PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_library_catalog_edits_entry_id_library_version_id_li_dda6 FOREIGN KEY(entry_id, '
 'library_version_id) REFERENCES library_entry_versions (entry_id, id), \n'
 '\tCONSTRAINT fk_library_catalog_edits_workspace_id_access_workspaces FOREIGN KEY(workspace_id) REFERENCES '
 'access_workspaces (id), \n'
 '\tCONSTRAINT uq_library_catalog_edits_entry_id_revision UNIQUE (entry_id, revision), \n'
 '\tCONSTRAINT uq_library_catalog_edits_actor_command_key UNIQUE (actor, command_key), \n'
 '\tCONSTRAINT ck_library_catalog_edits_revision CHECK (revision > 0), \n'
 '\tCONSTRAINT ck_library_catalog_edits_tag_count CHECK (tag_count BETWEEN 0 AND 50), \n'
 '\tCONSTRAINT ck_library_catalog_edits_asset_kind CHECK (asset_kind IN '
 "('character','location','prop','voice','blocking','other')), \n"
 '\tCONSTRAINT ck_library_catalog_edits_review_status CHECK (review_status IN '
 "('draft','confirmed','returned')), \n"
 '\tCONSTRAINT ck_library_catalog_edits_request_sha256_format CHECK (request_sha256 IS NULL OR '
 "request_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_library_catalog_edits_browse ON library_catalog_edits (entry_id, revision)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_catalog_edits FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE library_cart_items (\n'
 '\tid UUID NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tlibrary_version_id UUID NOT NULL, \n'
 '\tmember_key TEXT NOT NULL, \n'
 "\tactive BOOLEAN DEFAULT 'true' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_cart_items PRIMARY KEY (id), \n'
 '\tCONSTRAINT fk_library_cart_items_library_version_id_member_key_lib_56fc FOREIGN KEY(library_version_id, '
 'member_key) REFERENCES library_version_media (library_version_id, member_key), \n'
 '\tCONSTRAINT uq_library_cart_items_actor_library_version_id_member_key UNIQUE (actor, library_version_id, '
 'member_key), \n'
 '\tCONSTRAINT uq_library_cart_items_id_actor UNIQUE (id, actor)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_library_cart_items_browse ON library_cart_items (actor, active)',
 '\n'
 'CREATE TABLE library_catalog_tags (\n'
 '\tedit_id UUID NOT NULL, \n'
 '\ttag TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_library_catalog_tags PRIMARY KEY (edit_id, tag), \n'
 '\tCONSTRAINT fk_library_catalog_tags_edit_id_library_catalog_edits FOREIGN KEY(edit_id) REFERENCES '
 'library_catalog_edits (id), \n'
 '\tCONSTRAINT ck_library_catalog_tags_tag CHECK (length(tag) BETWEEN 1 AND 80)\n'
 ')\n'
 '\n',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_catalog_tags FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE library_download_requests (\n'
 '\tid UUID NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tlibrary_version_id UUID NOT NULL, \n'
 '\tmember_key TEXT NOT NULL, \n'
 '\tcommand_key TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_download_requests PRIMARY KEY (id), \n'
 '\tCONSTRAINT uq_library_download_requests_actor_command_key UNIQUE (actor, command_key), \n'
 '\tCONSTRAINT fk_library_download_requests_library_version_id_member__378a FOREIGN KEY(library_version_id, '
 'member_key) REFERENCES library_version_media (library_version_id, member_key)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_library_download_requests_browse ON library_download_requests (actor, created_at)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_download_requests FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE library_cart_imports (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcart_id UUID NOT NULL, \n'
 '\ttarget_object_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tcandidate_id UUID NOT NULL, \n'
 '\trole TEXT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_library_cart_imports PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_library_cart_imports_project_id_target_object_id_cre_8760 FOREIGN KEY(project_id, '
 'target_object_id) REFERENCES creative_objects (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_library_cart_imports_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_library_cart_imports_project_id_candidate_id_binding_5f96 FOREIGN KEY(project_id, '
 'candidate_id) REFERENCES binding_candidates (project_id, id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_library_cart_imports_cart_id_library_cart_items FOREIGN KEY(cart_id) REFERENCES '
 'library_cart_items (id), \n'
 '\tCONSTRAINT fk_library_cart_imports_cart_id_actor_library_cart_items FOREIGN KEY(cart_id, actor) '
 'REFERENCES library_cart_items (id, actor), \n'
 '\tCONSTRAINT uq_library_cart_imports_project_id_cart_id_target_objec_2eda UNIQUE (project_id, cart_id, '
 'target_object_id, role), \n'
 '\tCONSTRAINT fk_library_cart_imports_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_library_cart_imports_browse ON library_cart_imports (project_id, cart_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON library_cart_imports FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'CREATE FUNCTION vsc_library_cart_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n'
 "IF TG_OP='DELETE' OR (to_jsonb(NEW)-'active') IS DISTINCT FROM (to_jsonb(OLD)-'active') THEN RAISE "
 "EXCEPTION 'cart fixed member identity is immutable' USING ERRCODE='23514'; END IF; RETURN NEW; END $$",
 'CREATE TRIGGER library_cart_identity BEFORE UPDATE OR DELETE ON library_cart_items FOR EACH ROW EXECUTE '
 'FUNCTION vsc_library_cart_identity()',
 'CREATE FUNCTION vsc_library_catalog_seal() RETURNS trigger LANGUAGE plpgsql AS $$\n'
 'DECLARE e uuid; wanted integer; actual integer;\n'
 "BEGIN IF TG_TABLE_NAME='library_catalog_edits' THEN e:=NEW.id; ELSE e:=NEW.edit_id; END IF;\n"
 'SELECT tag_count INTO wanted FROM library_catalog_edits WHERE id=e;\n'
 'SELECT count(*) INTO actual FROM library_catalog_tags WHERE edit_id=e;\n'
 "IF wanted IS NULL OR actual<>wanted THEN RAISE EXCEPTION 'catalog tags are incomplete or sealed' USING "
 "ERRCODE='23514'; END IF; RETURN NULL; END $$",
 'CREATE CONSTRAINT TRIGGER library_catalog_seal AFTER INSERT ON library_catalog_edits DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_library_catalog_seal()',
 'CREATE CONSTRAINT TRIGGER library_catalog_seal AFTER INSERT ON library_catalog_tags DEFERRABLE INITIALLY '
 'DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_library_catalog_seal()',
 'CREATE FUNCTION vsc_library_cart_import_fixed() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n'
 'IF NOT EXISTS(SELECT 1 FROM binding_candidates c JOIN binding_slots s ON '
 '(s.project_id,s.id)=(c.project_id,c.slot_id)\n'
 'WHERE (c.project_id,c.id,c.media_id)=(NEW.project_id,NEW.candidate_id,NEW.media_id) AND '
 's.target_object_id=NEW.target_object_id AND s.role=NEW.role)\n'
 'OR NOT EXISTS(SELECT 1 FROM library_cart_items cart JOIN library_reuses reused ON '
 'reused.library_version_id=cart.library_version_id AND reused.member_key=cart.member_key\n'
 'WHERE cart.id=NEW.cart_id AND (reused.project_id,reused.media_id)=(NEW.project_id,NEW.media_id)) THEN\n'
 "RAISE EXCEPTION 'cart imported result does not match fixed member/target' USING ERRCODE='23514'; END IF; "
 'RETURN NEW; END $$',
 'CREATE TRIGGER library_cart_import_fixed BEFORE INSERT ON library_cart_imports FOR EACH ROW EXECUTE '
 'FUNCTION vsc_library_cart_import_fixed()']
def upgrade():
    for statement in DDL:op.execute(statement)
def downgrade():
    op.execute("DROP FUNCTION vsc_library_cart_import_fixed() CASCADE")
    op.execute("DROP FUNCTION vsc_library_catalog_seal() CASCADE")
    op.execute("DROP FUNCTION vsc_library_cart_identity() CASCADE")
    for name in ("library_cart_imports","library_download_requests","library_cart_items","library_catalog_tags","library_catalog_edits"):op.drop_table(name)
