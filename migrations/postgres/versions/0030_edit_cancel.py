from alembic import op
revision="0030_edit_cancel"
down_revision="0029_text_tool_receipts"
branch_labels=None
depends_on=None

IDENTITY = """CREATE OR REPLACE FUNCTION vsc_edit_job_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY[MUTABLE_FIELDS]) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY[MUTABLE_FIELDS]) OR OLD.status='succeeded' THEN
  RAISE EXCEPTION 'edit export identity or successful output is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$"""
FIELDS="'status','attempt','claim_owner','claim_until','error','output_blob_id','output_sha256','receipt'"

def upgrade():
    op.execute(IDENTITY.replace("MUTABLE_FIELDS",FIELDS+",'cancel_requested'"))
    op.execute("ALTER TABLE edit_render_jobs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE edit_render_jobs DROP CONSTRAINT ck_edit_render_jobs_status")
    op.execute("ALTER TABLE edit_render_jobs ADD CONSTRAINT ck_edit_render_jobs_status CHECK (status IN ('queued','running','succeeded','failed','cancelled') AND attempt >= 0)")

def downgrade():
    # An old worker cannot safely interpret cancelled requests. Preserve them.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM edit_render_jobs WHERE status='cancelled' OR cancel_requested) THEN RAISE EXCEPTION 'cancelled edit history requires current schema'; END IF; END $$")
    op.execute("ALTER TABLE edit_render_jobs DROP CONSTRAINT ck_edit_render_jobs_status")
    op.execute("ALTER TABLE edit_render_jobs ADD CONSTRAINT ck_edit_render_jobs_status CHECK (status IN ('queued','running','succeeded','failed') AND attempt >= 0)")
    op.execute("ALTER TABLE edit_render_jobs DROP COLUMN cancel_requested")
    op.execute(IDENTITY.replace("MUTABLE_FIELDS",FIELDS))
