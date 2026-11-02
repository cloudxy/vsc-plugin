"""Cross-project allocation records point at both entries in the original ledger."""
from sqlalchemy import Column, Text, BigInteger, ForeignKey, ForeignKeyConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID

WORKSPACE_COMMERCE_IMMUTABLE=('commerce_workspace_transfers',)


def declare_workspace_commerce(project_table,ref,uid,stamp):
    transfers=project_table('commerce_workspace_transfers',
        *ref('commerce_buckets','source_bucket_id'),
        *ref('commerce_ledger','source_entry_id'),
        Column('target_project_id',UUID(as_uuid=False),ForeignKey('projects.id'),nullable=False),
        uid('target_bucket_id',nullable=False),uid('target_entry_id',nullable=False),
        Column('workspace_id',UUID(as_uuid=False),ForeignKey('access_workspaces.id'),nullable=False),
        uid('reclaim_project_id'),uid('reclaim_of_id'),
        Column('credits',BigInteger,nullable=False),Column('actor',Text,nullable=False),stamp(),
        ForeignKeyConstraint(['target_project_id','target_bucket_id'],['commerce_buckets.project_id','commerce_buckets.id']),
        ForeignKeyConstraint(['target_project_id','target_entry_id'],['commerce_ledger.project_id','commerce_ledger.id']),
        ForeignKeyConstraint(['reclaim_project_id','reclaim_of_id'],['commerce_workspace_transfers.project_id','commerce_workspace_transfers.id']),
        CheckConstraint('credits>0 AND project_id<>target_project_id AND (reclaim_project_id IS NULL)=(reclaim_of_id IS NULL)',name='amount_scope'))
    for name in ('source_bucket_id','source_entry_id','reclaim_of_id'):
        Index('ix_commerce_workspace_transfers_'+name,transfers.c.project_id,transfers.c[name])
    Index('ix_commerce_workspace_transfers_target',transfers.c.target_project_id,transfers.c.target_bucket_id)
    return {transfers.name:transfers}


WORKSPACE_TRANSFER_GUARD="""
CREATE FUNCTION vsc_commerce_workspace_transfer() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE outgoing commerce_ledger%ROWTYPE; incoming commerce_ledger%ROWTYPE;
 source_bucket commerce_buckets%ROWTYPE; target_bucket commerce_buckets%ROWTYPE; prior commerce_workspace_transfers%ROWTYPE;
BEGIN
 SELECT * INTO outgoing FROM commerce_ledger WHERE project_id=NEW.project_id AND id=NEW.source_entry_id;
 SELECT * INTO incoming FROM commerce_ledger WHERE project_id=NEW.target_project_id AND id=NEW.target_entry_id;
 IF outgoing.bucket_id IS DISTINCT FROM NEW.source_bucket_id OR incoming.bucket_id IS DISTINCT FROM NEW.target_bucket_id
 OR outgoing.delta IS DISTINCT FROM -NEW.credits OR incoming.delta IS DISTINCT FROM NEW.credits
 OR outgoing.kind NOT IN ('allocate_out','reclaim_out') OR incoming.kind NOT IN ('allocate_in','reclaim_in') THEN
  RAISE EXCEPTION 'workspace transfer must match both original ledger entries' USING ERRCODE='23514';
 END IF;
 SELECT * INTO source_bucket FROM commerce_buckets WHERE project_id=NEW.project_id AND id=NEW.source_bucket_id;
 SELECT * INTO target_bucket FROM commerce_buckets WHERE project_id=NEW.target_project_id AND id=NEW.target_bucket_id;
 IF (source_bucket.kind,source_bucket.purposes,source_bucket.expires_at) IS DISTINCT FROM
 (target_bucket.kind,target_bucket.purposes,target_bucket.expires_at) THEN
  RAISE EXCEPTION 'transferred credit retains its type, purposes and expiry' USING ERRCODE='23514';
 END IF;
 IF NEW.reclaim_of_id IS NOT NULL THEN
  SELECT * INTO prior FROM commerce_workspace_transfers WHERE project_id=NEW.reclaim_project_id AND id=NEW.reclaim_of_id;
  IF prior.project_id IS DISTINCT FROM NEW.target_project_id OR prior.target_project_id IS DISTINCT FROM NEW.project_id
   OR prior.source_bucket_id IS DISTINCT FROM NEW.target_bucket_id OR prior.target_bucket_id IS DISTINCT FROM NEW.source_bucket_id
   OR prior.reclaim_of_id IS NOT NULL THEN
   RAISE EXCEPTION 'reclaim must return to its original source bucket' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER commerce_workspace_transfer BEFORE INSERT ON commerce_workspace_transfers FOR EACH ROW EXECUTE FUNCTION vsc_commerce_workspace_transfer();
"""
