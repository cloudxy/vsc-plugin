"""Workspace allocations retain both entries in the original credit ledger."""
from alembic import op
revision="0038_workspace_commerce"
down_revision="0037_text_media_review"
branch_labels=None
depends_on=None
DDL=['\n'
 'CREATE TABLE commerce_workspace_transfers (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tsource_bucket_id UUID NOT NULL, \n'
 '\tsource_entry_id UUID NOT NULL, \n'
 '\ttarget_project_id UUID NOT NULL, \n'
 '\ttarget_bucket_id UUID NOT NULL, \n'
 '\ttarget_entry_id UUID NOT NULL, \n'
 '\tworkspace_id UUID NOT NULL, \n'
 '\treclaim_project_id UUID, \n'
 '\treclaim_of_id UUID, \n'
 '\tcredits BIGINT NOT NULL, \n'
 '\tactor TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_commerce_workspace_transfers PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_project_id_source_bucke_e21e FOREIGN '
 'KEY(project_id, source_bucket_id) REFERENCES commerce_buckets (project_id, id) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_project_id_source_entry_0f33 FOREIGN '
 'KEY(project_id, source_entry_id) REFERENCES commerce_ledger (project_id, id) ON DELETE '
 'RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_2c32 FOREIGN '
 'KEY(target_project_id, target_bucket_id) REFERENCES commerce_buckets (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_target_project_id_targe_6227 FOREIGN '
 'KEY(target_project_id, target_entry_id) REFERENCES commerce_ledger (project_id, id), \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_reclaim_project_id_recl_4823 FOREIGN '
 'KEY(reclaim_project_id, reclaim_of_id) REFERENCES commerce_workspace_transfers (project_id, '
 'id), \n'
 '\tCONSTRAINT ck_commerce_workspace_transfers_amount_scope CHECK (credits>0 AND '
 'project_id<>target_project_id AND (reclaim_project_id IS NULL)=(reclaim_of_id IS NULL)), \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_project_id_projects FOREIGN KEY(project_id) '
 'REFERENCES projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_target_project_id_projects FOREIGN '
 'KEY(target_project_id) REFERENCES projects (id), \n'
 '\tCONSTRAINT fk_commerce_workspace_transfers_workspace_id_access_workspaces FOREIGN '
 'KEY(workspace_id) REFERENCES access_workspaces (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_commerce_workspace_transfers_reclaim_of_id ON commerce_workspace_transfers '
 '(project_id, reclaim_of_id)',
 'CREATE INDEX ix_commerce_workspace_transfers_source_bucket_id ON commerce_workspace_transfers '
 '(project_id, source_bucket_id)',
 'CREATE INDEX ix_commerce_workspace_transfers_source_entry_id ON commerce_workspace_transfers '
 '(project_id, source_entry_id)',
 'CREATE INDEX ix_commerce_workspace_transfers_target ON commerce_workspace_transfers '
 '(target_project_id, target_bucket_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON commerce_workspace_transfers FOR EACH '
 'ROW EXECUTE FUNCTION vsc_reject_mutation()',
 'ALTER TABLE commerce_invoices ADD COLUMN workspace_id UUID CONSTRAINT fk_commerce_invoices_workspace_id_access_workspaces REFERENCES access_workspaces(id)',
 'CREATE INDEX ix_commerce_invoices_workspace_id ON commerce_invoices (project_id,workspace_id)']
GUARD="\nCREATE FUNCTION vsc_commerce_workspace_transfer() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE outgoing commerce_ledger%ROWTYPE; incoming commerce_ledger%ROWTYPE;\n source_bucket commerce_buckets%ROWTYPE; target_bucket commerce_buckets%ROWTYPE; prior commerce_workspace_transfers%ROWTYPE;\nBEGIN\n SELECT * INTO outgoing FROM commerce_ledger WHERE project_id=NEW.project_id AND id=NEW.source_entry_id;\n SELECT * INTO incoming FROM commerce_ledger WHERE project_id=NEW.target_project_id AND id=NEW.target_entry_id;\n IF outgoing.bucket_id IS DISTINCT FROM NEW.source_bucket_id OR incoming.bucket_id IS DISTINCT FROM NEW.target_bucket_id\n OR outgoing.delta IS DISTINCT FROM -NEW.credits OR incoming.delta IS DISTINCT FROM NEW.credits\n OR outgoing.kind NOT IN ('allocate_out','reclaim_out') OR incoming.kind NOT IN ('allocate_in','reclaim_in') THEN\n  RAISE EXCEPTION 'workspace transfer must match both original ledger entries' USING ERRCODE='23514';\n END IF;\n SELECT * INTO source_bucket FROM commerce_buckets WHERE project_id=NEW.project_id AND id=NEW.source_bucket_id;\n SELECT * INTO target_bucket FROM commerce_buckets WHERE project_id=NEW.target_project_id AND id=NEW.target_bucket_id;\n IF (source_bucket.kind,source_bucket.purposes,source_bucket.expires_at) IS DISTINCT FROM\n (target_bucket.kind,target_bucket.purposes,target_bucket.expires_at) THEN\n  RAISE EXCEPTION 'transferred credit retains its type, purposes and expiry' USING ERRCODE='23514';\n END IF;\n IF NEW.reclaim_of_id IS NOT NULL THEN\n  SELECT * INTO prior FROM commerce_workspace_transfers WHERE project_id=NEW.reclaim_project_id AND id=NEW.reclaim_of_id;\n  IF prior.project_id IS DISTINCT FROM NEW.target_project_id OR prior.target_project_id IS DISTINCT FROM NEW.project_id\n   OR prior.source_bucket_id IS DISTINCT FROM NEW.target_bucket_id OR prior.target_bucket_id IS DISTINCT FROM NEW.source_bucket_id\n   OR prior.reclaim_of_id IS NOT NULL THEN\n   RAISE EXCEPTION 'reclaim must return to its original source bucket' USING ERRCODE='23514';\n  END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER commerce_workspace_transfer BEFORE INSERT ON commerce_workspace_transfers FOR EACH ROW EXECUTE FUNCTION vsc_commerce_workspace_transfer();\n"
def upgrade():
    for statement in DDL:op.execute(statement)
    op.execute(GUARD)
def downgrade():
    op.execute('LOCK TABLE commerce_workspace_transfers, commerce_invoices IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM commerce_workspace_transfers) OR EXISTS(SELECT 1 FROM commerce_invoices WHERE workspace_id IS NOT NULL) THEN RAISE EXCEPTION 'workspace financial history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute('ALTER TABLE commerce_invoices DROP COLUMN workspace_id')
    op.execute('DROP TABLE commerce_workspace_transfers')
    op.execute('DROP FUNCTION vsc_commerce_workspace_transfer()')
