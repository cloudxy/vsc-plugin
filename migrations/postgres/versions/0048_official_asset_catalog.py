"""Publish typed official classifications of original fixed shared-library versions."""
from alembic import op

revision = "0048_official_asset_catalog"
down_revision = "0047_professional_inputs"
branch_labels = None
depends_on = None

DDL = ["\nCREATE TABLE official_asset_publications (\n\tid UUID NOT NULL, \n\tentry_id UUID NOT NULL, \n\tlibrary_version_id UUID NOT NULL, \n\tasset_kind TEXT NOT NULL, \n\trole_level TEXT NOT NULL, \n\trole_tag TEXT NOT NULL, \n\tgender TEXT NOT NULL, \n\tage_band TEXT NOT NULL, \n\tpublisher TEXT NOT NULL, \n\tnotes TEXT NOT NULL, \n\tcommand_key TEXT NOT NULL, \n\trequest_sha256 TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_official_asset_publications PRIMARY KEY (id), \n\tCONSTRAINT fk_official_asset_publications_entry_id_library_version_ee88 FOREIGN KEY(entry_id, library_version_id) REFERENCES library_entry_versions (entry_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_official_asset_publications_library_version_id UNIQUE (library_version_id), \n\tCONSTRAINT uq_official_asset_publications_publisher_command_key UNIQUE (publisher, command_key), \n\tCONSTRAINT ck_official_asset_publications_asset_kind CHECK (asset_kind IN ('character','location','prop','voice','blocking','other')), \n\tCONSTRAINT ck_official_asset_publications_role_level CHECK (role_level IN ('lead','supporting','extra','unspecified')), \n\tCONSTRAINT ck_official_asset_publications_gender CHECK (gender IN ('female','male','other','unspecified')), \n\tCONSTRAINT ck_official_asset_publications_age_band CHECK (age_band IN ('child','teen','young_adult','middle_aged','senior','unspecified')), \n\tCONSTRAINT ck_official_asset_publications_character_dimensions CHECK (asset_kind='character' OR (role_level='unspecified' AND gender='unspecified' AND age_band='unspecified')), \n\tCONSTRAINT ck_official_asset_publications_text_fields CHECK (length(btrim(role_tag)) BETWEEN 1 AND 80 AND length(btrim(notes)) BETWEEN 1 AND 4000 AND length(btrim(publisher)) BETWEEN 1 AND 200 AND length(btrim(command_key)) BETWEEN 1 AND 200), \n\tCONSTRAINT ck_official_asset_publications_request_sha256_format CHECK (request_sha256 IS NULL OR request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n", 'CREATE INDEX ix_official_asset_publications_browse ON official_asset_publications (asset_kind, role_level, gender, age_band)', 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON official_asset_publications FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()']

def upgrade():
    for statement in DDL:
        op.execute(statement)

def downgrade():
    op.execute("LOCK TABLE official_asset_publications IN ACCESS EXCLUSIVE MODE")
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM official_asset_publications) THEN RAISE EXCEPTION 'official publications exist; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.drop_table("official_asset_publications")
