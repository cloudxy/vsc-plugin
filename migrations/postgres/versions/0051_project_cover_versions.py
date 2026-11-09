"""Preserve explicit project cover selections without copying media or approvals."""
from alembic import op

revision = "0051_project_cover_versions"
down_revision = "0050_classic_frame_media"
branch_labels = None
depends_on = None

DDL = r"""
CREATE TABLE project_cover_versions (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	version INTEGER NOT NULL,
	media_id UUID,
	blob_id UUID,
	sha256 VARCHAR(64),
	created_by TEXT NOT NULL,
	command_key TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_project_cover_versions PRIMARY KEY (project_id, id),
	CONSTRAINT uq_project_cover_versions_project_id_version UNIQUE (project_id, version),
	CONSTRAINT uq_project_cover_versions_project_id_command_key UNIQUE (project_id, command_key),
	CONSTRAINT fk_project_cover_versions_project_id_media_id_blob_id_m_14f9 FOREIGN KEY(project_id, media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON DELETE RESTRICT,
	CONSTRAINT fk_project_cover_versions_blob_id_sha256_media_blobs FOREIGN KEY(blob_id, sha256) REFERENCES media_blobs (id, sha256) ON DELETE RESTRICT,
	CONSTRAINT fk_project_cover_receipt FOREIGN KEY(project_id, command_key) REFERENCES command_receipts (project_id, idempotency_key) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_project_cover_versions_positive_version CHECK (version > 0),
	CONSTRAINT ck_project_cover_versions_media_tuple CHECK ((media_id IS NULL) = (blob_id IS NULL) AND (media_id IS NULL) = (sha256 IS NULL)),
	CONSTRAINT ck_project_cover_versions_actor_command CHECK (length(btrim(created_by)) BETWEEN 1 AND 200 AND length(btrim(command_key)) BETWEEN 1 AND 200),
	CONSTRAINT fk_project_cover_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT,
	CONSTRAINT ck_project_cover_versions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_project_cover_blob ON project_cover_versions (blob_id, sha256);
CREATE INDEX ix_project_cover_media ON project_cover_versions (project_id, media_id);

CREATE FUNCTION vsc_project_cover_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE next_version integer;
BEGIN
 PERFORM 1 FROM projects WHERE id=NEW.project_id FOR UPDATE;
 SELECT coalesce(max(version),0)+1 INTO next_version FROM project_cover_versions WHERE project_id=NEW.project_id;
 IF NEW.version<>next_version THEN
  RAISE EXCEPTION 'project cover version must follow its project history' USING ERRCODE='23514'; END IF;
 IF NEW.media_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM media_items m JOIN media_blobs b ON b.id=m.blob_id
  WHERE m.project_id=NEW.project_id AND m.id=NEW.media_id AND m.blob_id=NEW.blob_id AND b.sha256=NEW.sha256
   AND m.modality='image' AND b.size_bytes BETWEEN 1 AND 5242880
 ) THEN RAISE EXCEPTION 'project cover requires a same-project image of at most 5 MiB' USING ERRCODE='23514'; END IF;
 IF NEW.media_id IS NOT NULL AND (SELECT outcome FROM media_lifecycle_decisions
  WHERE project_id=NEW.project_id AND media_id=NEW.media_id ORDER BY decision_sequence DESC LIMIT 1)='deprecate' THEN
  RAISE EXCEPTION 'project cover media is deprecated' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER project_cover_guard BEFORE INSERT ON project_cover_versions
 FOR EACH ROW EXECUTE FUNCTION vsc_project_cover_guard();
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON project_cover_versions
 FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();

CREATE FUNCTION vsc_project_cover_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM command_receipts r JOIN project_revisions rev
   ON rev.project_id=r.project_id AND rev.command_key=r.idempotency_key
  WHERE r.project_id=NEW.project_id AND r.idempotency_key=NEW.command_key
   AND rev.action='set_project_cover' AND rev.actor=NEW.created_by
   AND r.response->>'revision'=rev.revision::text
   AND r.response->'selection'->>'id'=NEW.id::text
   AND r.response->'selection'->>'version'=NEW.version::text
   AND r.response->'selection'->>'created_by'=NEW.created_by
   AND coalesce(r.response->'selection'->>'media_id','')=coalesce(NEW.media_id::text,'')
   AND coalesce(r.response->'selection'->>'blob_id','')=coalesce(NEW.blob_id::text,'')
   AND coalesce(r.response->'selection'->>'sha256','')=coalesce(NEW.sha256,'')
 ) THEN RAISE EXCEPTION 'project cover requires its original command receipt' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER project_cover_receipt_guard AFTER INSERT ON project_cover_versions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_project_cover_receipt_guard();
"""

def upgrade():
    op.execute(DDL)

def downgrade():
    op.execute("LOCK TABLE project_cover_versions IN ACCESS EXCLUSIVE MODE")
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM project_cover_versions) THEN RAISE EXCEPTION 'project cover history exists; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.drop_table("project_cover_versions")
    op.execute("DROP FUNCTION vsc_project_cover_receipt_guard()")
    op.execute("DROP FUNCTION vsc_project_cover_guard()")
