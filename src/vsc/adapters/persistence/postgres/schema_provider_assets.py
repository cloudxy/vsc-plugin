"""Provider registration is a typed request and receipt, separate from image URLs."""
from sqlalchemy import Column,Text,CheckConstraint,ForeignKeyConstraint,Index
from sqlalchemy.dialects.postgresql import JSONB


def declare_provider_assets(project_table,ref,uid,stamp):
    registrations=project_table('provider_asset_registrations',*ref('text_tool_units','unit_id'),*ref('artifact_versions','source_version_id'),
        Column('entity_key',Text,nullable=False),*ref('asset_identities','asset_id',nullable=True),*ref('media_items','media_id'),
        uid('blob_id',nullable=False),Column('media_sha256',Text,nullable=False),Column('provider',Text,nullable=False),Column('account_scope',Text,nullable=False),
        Column('status',Text,nullable=False),Column('remote_asset_id',Text),Column('receipt',JSONB),Column('error_code',Text),Column('created_by',Text,nullable=False),stamp(),
        CheckConstraint("status IN ('running','submission_unknown','completed','failed')",name='status'),
        CheckConstraint("(status='completed') = (remote_asset_id IS NOT NULL AND receipt IS NOT NULL)",name='receipt'),
        CheckConstraint("length(entity_key)>0 AND length(provider)>0 AND length(account_scope)>0 AND media_sha256 ~ '^[0-9a-f]{64}$'",name='identity'),
        ForeignKeyConstraint(['project_id','media_id','blob_id'],['media_items.project_id','media_items.id','media_items.blob_id'],ondelete='RESTRICT'),
        ForeignKeyConstraint(['blob_id','media_sha256'],['media_blobs.id','media_blobs.sha256'],ondelete='RESTRICT'))
    for key in ('unit_id','source_version_id','asset_id','media_id'):Index('ix_provider_asset_registrations_'+key,registrations.c.project_id,registrations.c[key])
    Index('ix_provider_asset_registrations_blob',registrations.c.blob_id,registrations.c.media_sha256)
    return {'provider_asset_registrations':registrations}


PROVIDER_ASSET_GUARD="""
CREATE FUNCTION vsc_provider_asset_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v artifact_versions%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'provider registration history cannot be deleted' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-ARRAY['status','remote_asset_id','receipt','error_code']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','remote_asset_id','receipt','error_code']) OR OLD.status IN ('completed','failed')) THEN
  RAISE EXCEPTION 'provider request and terminal receipt are fixed' USING ERRCODE='23514'; END IF;
 SELECT * INTO v FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.source_version_id;
 IF v.artifact_type IS DISTINCT FROM 'text-tool-draft' OR v.artifact_key IS DISTINCT FROM 'text-tool:'||NEW.unit_id::text OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(convert_from(v.document,'UTF8')::jsonb->'entities') e WHERE e->>'key'=NEW.entity_key AND e->>'media_id'=NEW.media_id::text AND nullif(e->>'asset_id','')::uuid IS NOT DISTINCT FROM NEW.asset_id) THEN
  RAISE EXCEPTION 'provider asset must pin its original entity and media' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER provider_asset_guard BEFORE INSERT OR UPDATE OR DELETE ON provider_asset_registrations FOR EACH ROW EXECUTE FUNCTION vsc_provider_asset_guard();
"""
