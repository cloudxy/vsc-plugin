"""Project display-cover choices are immutable references to existing media."""
from sqlalchemy import Column, Integer, Text, String, CheckConstraint, ForeignKeyConstraint, UniqueConstraint, Index


def declare_project_cover(project_table, uid, stamp):
    versions = project_table('project_cover_versions', Column('version', Integer, nullable=False),
        uid('media_id', nullable=True), uid('blob_id', nullable=True), Column('sha256', String(64)),
        Column('created_by', Text, nullable=False), Column('command_key', Text, nullable=False), stamp(),
        UniqueConstraint('project_id', 'version'), UniqueConstraint('project_id', 'command_key'),
        ForeignKeyConstraint(['project_id', 'media_id', 'blob_id'],
            ['media_items.project_id', 'media_items.id', 'media_items.blob_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['blob_id', 'sha256'], ['media_blobs.id', 'media_blobs.sha256'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['project_id', 'command_key'], ['command_receipts.project_id', 'command_receipts.idempotency_key'],
            name='fk_project_cover_receipt', ondelete='RESTRICT', deferrable=True, initially='DEFERRED'),
        CheckConstraint('version > 0', name='positive_version'),
        CheckConstraint('(media_id IS NULL) = (blob_id IS NULL) AND (media_id IS NULL) = (sha256 IS NULL)', name='media_tuple'),
        CheckConstraint('length(btrim(created_by)) BETWEEN 1 AND 200 AND length(btrim(command_key)) BETWEEN 1 AND 200', name='actor_command'))
    Index('ix_project_cover_media', versions.c.project_id, versions.c.media_id)
    Index('ix_project_cover_blob', versions.c.blob_id, versions.c.sha256)
    return {'project_cover_versions': versions}


PROJECT_COVER_GUARD_DDL = r'''
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
'''
