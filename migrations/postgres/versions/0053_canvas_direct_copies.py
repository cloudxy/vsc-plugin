"""Immutable direct canvas-copy roots, typed mappings and provenance closure."""
from alembic import op

revision="0053_canvas_direct_copies"
down_revision="0052_canvas_lifecycle"
branch_labels=None
depends_on=None

DDL = """
CREATE TABLE canvas_direct_copies (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	canvas_version_id UUID NOT NULL, 
	source_project_id UUID NOT NULL, 
	source_canvas_id UUID NOT NULL, 
	source_version_id UUID NOT NULL, 
	command_key TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_direct_copies PRIMARY KEY (project_id, id), 
	CONSTRAINT uq_canvas_direct_copies_project_id_canvas_id UNIQUE (project_id, canvas_id), 
	CONSTRAINT uq_canvas_direct_copies_project_id_command_key UNIQUE (project_id, command_key), 
	CONSTRAINT uq_canvas_direct_copies_project_id_id_source_project_id UNIQUE (project_id, id, source_project_id), 
	CONSTRAINT fk_canvas_direct_copies_project_id_canvas_id_canvas_ver_7c4e FOREIGN KEY(project_id, canvas_id, canvas_version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copies_source_project_id_source_canvas_1f2c FOREIGN KEY(source_project_id, source_canvas_id, source_version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copies_project_id_command_key_command_receipts FOREIGN KEY(project_id, command_key) REFERENCES command_receipts (project_id, idempotency_key) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT ck_canvas_direct_copies_new_identity CHECK (canvas_id<>source_canvas_id AND canvas_version_id<>source_version_id), 
	CONSTRAINT ck_canvas_direct_copies_command_actor CHECK (length(btrim(command_key)) BETWEEN 1 AND 200 AND length(btrim(created_by)) BETWEEN 1 AND 200), 
	CONSTRAINT fk_canvas_direct_copies_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_direct_copy_source_canvas ON canvas_direct_copies (source_project_id, source_canvas_id);
CREATE INDEX ix_direct_copy_source_project ON canvas_direct_copies (project_id, source_project_id);

CREATE TABLE canvas_direct_copy_media (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	copy_id UUID NOT NULL, 
	source_project_id UUID NOT NULL, 
	source_media_id UUID NOT NULL, 
	target_media_id UUID NOT NULL, 
	blob_id UUID NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_canvas_direct_copy_media PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_direct_copy_media_project_id_copy_id_source_p_ca32 FOREIGN KEY(project_id, copy_id, source_project_id) REFERENCES canvas_direct_copies (project_id, id, source_project_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_media_source_project_id_source_me_61d1 FOREIGN KEY(source_project_id, source_media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_media_project_id_target_media_id__2a9a FOREIGN KEY(project_id, target_media_id, blob_id) REFERENCES media_items (project_id, id, blob_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_media_blob_id_sha256_media_blobs FOREIGN KEY(blob_id, sha256) REFERENCES media_blobs (id, sha256) ON DELETE RESTRICT, 
	CONSTRAINT uq_canvas_direct_copy_media_project_id_copy_id_source_media_id UNIQUE (project_id, copy_id, source_media_id), 
	CONSTRAINT uq_canvas_direct_copy_media_project_id_target_media_id UNIQUE (project_id, target_media_id), 
	CONSTRAINT ck_canvas_direct_copy_media_new_identity CHECK (source_media_id<>target_media_id), 
	CONSTRAINT fk_canvas_direct_copy_media_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_canvas_direct_copy_media_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_direct_copy_media_source ON canvas_direct_copy_media (source_project_id, source_media_id);

CREATE TABLE canvas_direct_copy_domains (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	copy_id UUID NOT NULL, 
	source_project_id UUID NOT NULL, 
	source_spatial_version_id UUID, 
	target_spatial_version_id UUID, 
	source_edit_version_id UUID, 
	target_edit_version_id UUID, 
	source_tool_version_id UUID, 
	target_tool_version_id UUID, 
	CONSTRAINT pk_canvas_direct_copy_domains PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_direct_copy_domains_project_id_copy_id_source_9b8e FOREIGN KEY(project_id, copy_id, source_project_id) REFERENCES canvas_direct_copies (project_id, id, source_project_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_source_project_id_source__8198 FOREIGN KEY(source_project_id, source_spatial_version_id) REFERENCES spatial_scene_versions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_project_id_target_spatial_f702 FOREIGN KEY(project_id, target_spatial_version_id) REFERENCES spatial_scene_versions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_source_project_id_source__1cda FOREIGN KEY(source_project_id, source_edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_project_id_target_edit_ve_bce0 FOREIGN KEY(project_id, target_edit_version_id) REFERENCES edit_revisions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_source_project_id_source__aea2 FOREIGN KEY(source_project_id, source_tool_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_direct_copy_domains_project_id_target_tool_ve_53e1 FOREIGN KEY(project_id, target_tool_version_id) REFERENCES artifact_versions (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT ck_canvas_direct_copy_domains_typed_mapping CHECK (num_nonnulls(source_spatial_version_id,source_edit_version_id,source_tool_version_id)=1 AND (source_spatial_version_id IS NULL)=(target_spatial_version_id IS NULL) AND (source_edit_version_id IS NULL)=(target_edit_version_id IS NULL) AND (source_tool_version_id IS NULL)=(target_tool_version_id IS NULL) AND (source_spatial_version_id IS NULL OR source_spatial_version_id<>target_spatial_version_id) AND (source_edit_version_id IS NULL OR source_edit_version_id<>target_edit_version_id) AND (source_tool_version_id IS NULL OR source_tool_version_id<>target_tool_version_id)), 
	CONSTRAINT fk_canvas_direct_copy_domains_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)

;
CREATE UNIQUE INDEX uq_direct_domain_source_edit ON canvas_direct_copy_domains (project_id, copy_id, source_edit_version_id) WHERE source_edit_version_id IS NOT NULL;
CREATE UNIQUE INDEX uq_direct_domain_source_spatial ON canvas_direct_copy_domains (project_id, copy_id, source_spatial_version_id) WHERE source_spatial_version_id IS NOT NULL;
CREATE UNIQUE INDEX uq_direct_domain_source_tool ON canvas_direct_copy_domains (project_id, copy_id, source_tool_version_id) WHERE source_tool_version_id IS NOT NULL;
CREATE UNIQUE INDEX uq_direct_domain_target_edit ON canvas_direct_copy_domains (project_id, target_edit_version_id) WHERE target_edit_version_id IS NOT NULL;
CREATE UNIQUE INDEX uq_direct_domain_target_spatial ON canvas_direct_copy_domains (project_id, target_spatial_version_id) WHERE target_spatial_version_id IS NOT NULL;
CREATE UNIQUE INDEX uq_direct_domain_target_tool ON canvas_direct_copy_domains (project_id, target_tool_version_id) WHERE target_tool_version_id IS NOT NULL;"""

GUARDS = """-- A visible uncommitted row belongs to this transaction, including released
-- savepoints. Normalize 32-bit xmin to the current full-XID epoch before asking
-- PostgreSQL; old/frozen/unavailable transaction status fails closed.
-- Require the immutable creation stamp too: a historical frozen 32-bit xmin
-- must not be mistaken for a reused current-epoch XID after wraparound.
CREATE FUNCTION vsc_direct_copy_new_row(row_xmin xid,row_created_at timestamptz) RETURNS boolean LANGUAGE plpgsql VOLATILE AS $$
DECLARE current_id numeric := pg_current_xact_id()::text::numeric; full_id numeric;
BEGIN
 IF row_created_at IS DISTINCT FROM transaction_timestamp() OR row_xmin::text::numeric < 3 THEN RETURN false; END IF;
 full_id := current_id-mod(current_id,4294967296)+row_xmin::text::numeric;
 IF full_id>current_id AND row_xmin::text::numeric-mod(current_id,4294967296)>2147483648 THEN full_id:=full_id-4294967296; END IF;
 RETURN coalesce(pg_xact_status(full_id::text::xid8)='in progress',false);
END $$;

CREATE FUNCTION vsc_canvas_fixed_domains(p_project_id uuid,p_version_id uuid)
RETURNS TABLE(kind text,version_id uuid) LANGUAGE sql STABLE AS $$
 SELECT 'spatial',spatial_version_id FROM creative_canvas_nodes WHERE project_id=p_project_id AND version_id=p_version_id AND spatial_version_id IS NOT NULL
 UNION SELECT 'edit',edit_version_id FROM creative_canvas_nodes WHERE project_id=p_project_id AND version_id=p_version_id AND edit_version_id IS NOT NULL
 UNION SELECT 'tool',tool_draft_id FROM creative_canvas_nodes WHERE project_id=p_project_id AND version_id=p_version_id AND tool_draft_id IS NOT NULL
$$;
CREATE FUNCTION vsc_canvas_domain_media(p_project_id uuid,p_kind text,p_version_id uuid)
RETURNS TABLE(slot text,media_id uuid) LANGUAGE sql STABLE AS $$
 SELECT 'object:'||o.ordinal::text,o.media_id FROM spatial_objects o WHERE p_kind='spatial' AND o.project_id=p_project_id AND o.version_id=p_version_id AND o.media_id IS NOT NULL
 UNION ALL SELECT m.track||':'||m.ordinal::text,m.media_id FROM edit_revision_media m WHERE p_kind='edit' AND m.project_id=p_project_id AND m.edit_version_id=p_version_id
 UNION ALL SELECT 'pin:'||x.ordinal::text,(x.pin->>'media_id')::uuid FROM artifact_versions a CROSS JOIN LATERAL jsonb_array_elements(convert_from(a.document,'UTF8')::jsonb->'media') WITH ORDINALITY x(pin,ordinal) WHERE p_kind='tool' AND a.project_id=p_project_id AND a.id=p_version_id
 UNION ALL SELECT 'input:'||x.key,nullif(x.value,'')::uuid FROM artifact_versions a CROSS JOIN LATERAL jsonb_each_text(convert_from(a.document,'UTF8')::jsonb->'input') x WHERE p_kind='tool' AND a.project_id=p_project_id AND a.id=p_version_id AND x.key IN ('source_media_id','audio_media_id','voice_media_id','replacement_media_id') AND nullif(x.value,'') IS NOT NULL
 UNION ALL SELECT 'visual:'||x.ordinal::text,x.value::uuid FROM artifact_versions a CROSS JOIN LATERAL jsonb_array_elements_text(convert_from(a.document,'UTF8')::jsonb#>'{input,visual_media_ids}') WITH ORDINALITY x(value,ordinal) WHERE p_kind='tool' AND a.project_id=p_project_id AND a.id=p_version_id
$$;

CREATE FUNCTION vsc_canvas_fixed_media(p_project_id uuid,p_version_id uuid)
RETURNS TABLE(media_id uuid) LANGUAGE sql STABLE AS $$
 SELECT n.media_id FROM creative_canvas_nodes n WHERE n.project_id=p_project_id AND n.version_id=p_version_id AND n.media_id IS NOT NULL
 UNION SELECT o.media_id FROM vsc_canvas_fixed_domains(p_project_id,p_version_id) d JOIN spatial_objects o ON o.project_id=p_project_id AND o.version_id=d.version_id WHERE d.kind='spatial' AND o.media_id IS NOT NULL
 UNION SELECT m.media_id FROM vsc_canvas_fixed_domains(p_project_id,p_version_id) d JOIN edit_revision_media m ON m.project_id=p_project_id AND m.edit_version_id=d.version_id WHERE d.kind='edit'
 UNION SELECT m.media_id FROM vsc_canvas_fixed_domains(p_project_id,p_version_id) d CROSS JOIN LATERAL vsc_canvas_domain_media(p_project_id,d.kind,d.version_id) m
$$;

CREATE FUNCTION vsc_direct_copy_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE root canvas_direct_copies%ROWTYPE; target_xmin xid; target_created_at timestamptz; source_type text; target_type text; target_version bigint; source_object uuid; target_object uuid;
BEGIN
 IF TG_TABLE_NAME='canvas_direct_copies' THEN
  IF EXISTS(SELECT 1 FROM command_receipts WHERE project_id=NEW.project_id AND idempotency_key=NEW.command_key) THEN RAISE EXCEPTION 'direct copy receipt already sealed' USING ERRCODE='23514'; END IF;
  SELECT v.xmin,v.created_at,v.version INTO target_xmin,target_created_at,target_version FROM creative_canvas_versions v WHERE v.project_id=NEW.project_id AND v.canvas_id=NEW.canvas_id AND v.id=NEW.canvas_version_id AND v.created_by=NEW.created_by;
  IF target_version IS DISTINCT FROM 1 OR NOT coalesce(vsc_direct_copy_new_row(target_xmin,target_created_at),false) THEN RAISE EXCEPTION 'direct copy requires a new initial canvas version' USING ERRCODE='23514'; END IF;
  IF NOT EXISTS(SELECT 1 FROM creative_canvases t JOIN creative_canvases s ON s.project_id=NEW.source_project_id AND s.id=NEW.source_canvas_id WHERE t.project_id=NEW.project_id AND t.id=NEW.canvas_id AND t.current_version_id=NEW.canvas_version_id AND t.episode_id IS NOT NULL AND t.created_by=NEW.created_by AND (t.project_id<>s.project_id OR t.episode_id IS DISTINCT FROM s.episode_id)) THEN RAISE EXCEPTION 'direct copy episode or initial canvas mismatch' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO root FROM canvas_direct_copies WHERE project_id=NEW.project_id AND id=NEW.copy_id FOR UPDATE;
 IF NOT FOUND OR root.source_project_id<>NEW.source_project_id THEN RAISE EXCEPTION 'direct copy root scope mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM command_receipts WHERE project_id=root.project_id AND idempotency_key=root.command_key) THEN RAISE EXCEPTION 'direct copy members sealed by receipt' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='canvas_direct_copy_media' THEN
  SELECT modality INTO source_type FROM media_items WHERE project_id=NEW.source_project_id AND id=NEW.source_media_id;
  SELECT m.modality,m.xmin,m.created_at INTO target_type,target_xmin,target_created_at FROM media_items m WHERE m.project_id=NEW.project_id AND m.id=NEW.target_media_id;
  IF source_type IS DISTINCT FROM target_type OR NOT coalesce(vsc_direct_copy_new_row(target_xmin,target_created_at),false) THEN RAISE EXCEPTION 'direct copy requires new media of same modality' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.source_spatial_version_id IS NOT NULL THEN
   SELECT v.spatial_scene_id,s.mode INTO source_object,source_type FROM spatial_scene_versions v JOIN spatial_scenes s ON s.project_id=v.project_id AND s.id=v.spatial_scene_id WHERE v.project_id=NEW.source_project_id AND v.id=NEW.source_spatial_version_id;
   SELECT v.spatial_scene_id,s.mode,v.xmin,v.created_at,v.version INTO target_object,target_type,target_xmin,target_created_at,target_version FROM spatial_scene_versions v JOIN spatial_scenes s ON s.project_id=v.project_id AND s.id=v.spatial_scene_id WHERE v.project_id=NEW.project_id AND v.id=NEW.target_spatial_version_id;
   IF source_type IS DISTINCT FROM target_type OR source_object=target_object THEN RAISE EXCEPTION 'spatial clone identity or mode mismatch' USING ERRCODE='23514'; END IF;
  ELSIF NEW.source_edit_version_id IS NOT NULL THEN
   SELECT workspace_id INTO source_object FROM edit_revisions WHERE project_id=NEW.source_project_id AND id=NEW.source_edit_version_id;
   SELECT v.workspace_id,v.xmin,v.created_at,v.version INTO target_object,target_xmin,target_created_at,target_version FROM edit_revisions v WHERE v.project_id=NEW.project_id AND v.id=NEW.target_edit_version_id;
   IF source_object=target_object THEN RAISE EXCEPTION 'edit clone identity mismatch' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT artifact_type INTO source_type FROM artifact_versions WHERE project_id=NEW.source_project_id AND id=NEW.source_tool_version_id;
   SELECT a.artifact_type,a.xmin,a.created_at,a.version INTO target_type,target_xmin,target_created_at,target_version FROM artifact_versions a WHERE a.project_id=NEW.project_id AND a.id=NEW.target_tool_version_id;
   IF source_type IS DISTINCT FROM 'creative-tool-draft' OR target_type IS DISTINCT FROM 'creative-tool-draft' THEN RAISE EXCEPTION 'tool copy requires creative tool draft' USING ERRCODE='23514'; END IF;
  END IF;
  IF target_version IS DISTINCT FROM 1 OR NOT coalesce(vsc_direct_copy_new_row(target_xmin,target_created_at),false) THEN RAISE EXCEPTION 'direct copy requires new domain initial version' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION vsc_direct_copy_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE media_count bigint; domain_count bigint;
BEGIN
 SELECT count(*) INTO media_count FROM canvas_direct_copy_media WHERE project_id=NEW.project_id AND copy_id=NEW.id;
 SELECT count(*) INTO domain_count FROM canvas_direct_copy_domains WHERE project_id=NEW.project_id AND copy_id=NEW.id;
 IF NOT EXISTS(SELECT 1 FROM command_receipts r JOIN project_revisions rev ON rev.project_id=r.project_id AND rev.command_key=r.idempotency_key WHERE r.project_id=NEW.project_id AND r.idempotency_key=NEW.command_key AND rev.action='copy_direct_canvas' AND rev.actor=NEW.created_by AND r.response->>'revision'=rev.revision::text AND r.response->>'project_id'=NEW.project_id::text AND r.response->>'copy_id'=NEW.id::text AND r.response->>'id'=NEW.canvas_id::text AND r.response->>'version_id'=NEW.canvas_version_id::text AND r.response->>'source_project_id'=NEW.source_project_id::text AND r.response->>'source_canvas_id'=NEW.source_canvas_id::text AND r.response->>'source_version_id'=NEW.source_version_id::text AND r.response->>'media_count'=media_count::text AND r.response->>'domain_count'=domain_count::text) THEN RAISE EXCEPTION 'direct copy receipt mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(
  (SELECT media_id FROM vsc_canvas_fixed_media(NEW.source_project_id,NEW.source_version_id) EXCEPT SELECT source_media_id FROM canvas_direct_copy_media WHERE project_id=NEW.project_id AND copy_id=NEW.id)
  UNION ALL (SELECT source_media_id FROM canvas_direct_copy_media WHERE project_id=NEW.project_id AND copy_id=NEW.id EXCEPT SELECT media_id FROM vsc_canvas_fixed_media(NEW.source_project_id,NEW.source_version_id))
  UNION ALL (SELECT media_id FROM vsc_canvas_fixed_media(NEW.project_id,NEW.canvas_version_id) EXCEPT SELECT target_media_id FROM canvas_direct_copy_media WHERE project_id=NEW.project_id AND copy_id=NEW.id)
  UNION ALL (SELECT target_media_id FROM canvas_direct_copy_media WHERE project_id=NEW.project_id AND copy_id=NEW.id EXCEPT SELECT media_id FROM vsc_canvas_fixed_media(NEW.project_id,NEW.canvas_version_id))
 ) THEN RAISE EXCEPTION 'direct copy media mapping is not exact' USING ERRCODE='23514'; END IF;
 IF EXISTS(
  WITH mapped AS (SELECT k.kind,k.source_id,k.target_id FROM canvas_direct_copy_domains d CROSS JOIN LATERAL (VALUES ('spatial',d.source_spatial_version_id,d.target_spatial_version_id),('edit',d.source_edit_version_id,d.target_edit_version_id),('tool',d.source_tool_version_id,d.target_tool_version_id)) k(kind,source_id,target_id) WHERE d.project_id=NEW.project_id AND d.copy_id=NEW.id AND k.source_id IS NOT NULL)
  (SELECT kind,version_id FROM vsc_canvas_fixed_domains(NEW.source_project_id,NEW.source_version_id) EXCEPT SELECT kind,source_id FROM mapped)
  UNION ALL (SELECT kind,source_id FROM mapped EXCEPT SELECT kind,version_id FROM vsc_canvas_fixed_domains(NEW.source_project_id,NEW.source_version_id))
  UNION ALL (SELECT kind,version_id FROM vsc_canvas_fixed_domains(NEW.project_id,NEW.canvas_version_id) EXCEPT SELECT kind,target_id FROM mapped)
  UNION ALL (SELECT kind,target_id FROM mapped EXCEPT SELECT kind,version_id FROM vsc_canvas_fixed_domains(NEW.project_id,NEW.canvas_version_id))
 ) THEN RAISE EXCEPTION 'direct copy domain mapping is not exact' USING ERRCODE='23514'; END IF;
 IF EXISTS(
  SELECT 1 FROM (SELECT * FROM creative_canvas_nodes WHERE project_id=NEW.source_project_id AND version_id=NEW.source_version_id) s FULL JOIN (SELECT * FROM creative_canvas_nodes WHERE project_id=NEW.project_id AND version_id=NEW.canvas_version_id) t USING(ordinal)
  LEFT JOIN canvas_direct_copy_media m ON m.project_id=NEW.project_id AND m.copy_id=NEW.id AND m.source_media_id=s.media_id
  LEFT JOIN canvas_direct_copy_domains d ON d.project_id=NEW.project_id AND d.copy_id=NEW.id AND (d.source_spatial_version_id=s.spatial_version_id OR d.source_edit_version_id=s.edit_version_id OR d.source_tool_version_id=s.tool_draft_id)
  WHERE s.node_key IS NULL OR t.node_key IS NULL OR s.node_key=t.node_key OR s.node_type<>t.node_type OR t.job_id IS NOT NULL OR t.media_id IS DISTINCT FROM m.target_media_id OR t.spatial_version_id IS DISTINCT FROM d.target_spatial_version_id OR t.edit_version_id IS DISTINCT FROM d.target_edit_version_id OR t.tool_draft_id IS DISTINCT FROM d.target_tool_version_id
 ) THEN RAISE EXCEPTION 'direct copy node mapping mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(
  SELECT 1 FROM canvas_direct_copy_domains d
  CROSS JOIN LATERAL (VALUES ('spatial',d.source_spatial_version_id,d.target_spatial_version_id),('edit',d.source_edit_version_id,d.target_edit_version_id),('tool',d.source_tool_version_id,d.target_tool_version_id)) k(kind,source_id,target_id)
  CROSS JOIN LATERAL (SELECT s.slot AS source_slot,t.slot AS target_slot,s.media_id AS source_media,t.media_id AS target_media FROM vsc_canvas_domain_media(NEW.source_project_id,k.kind,k.source_id) s FULL JOIN vsc_canvas_domain_media(NEW.project_id,k.kind,k.target_id) t USING(slot)) slots
  LEFT JOIN canvas_direct_copy_media m ON m.project_id=NEW.project_id AND m.copy_id=NEW.id AND m.source_media_id=slots.source_media
  WHERE d.project_id=NEW.project_id AND d.copy_id=NEW.id AND k.source_id IS NOT NULL AND (slots.source_slot IS NULL OR slots.target_slot IS NULL OR slots.target_media IS DISTINCT FROM m.target_media_id)
 ) THEN RAISE EXCEPTION 'direct copy domain media mapping mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(
  SELECT 1 FROM (SELECT e.*,s.ordinal AS source_ordinal,t.ordinal AS target_ordinal FROM creative_canvas_edges e JOIN creative_canvas_nodes s ON s.project_id=e.project_id AND s.version_id=e.version_id AND s.node_key=e.source_key JOIN creative_canvas_nodes t ON t.project_id=e.project_id AND t.version_id=e.version_id AND t.node_key=e.target_key WHERE e.project_id=NEW.source_project_id AND e.version_id=NEW.source_version_id) s
  FULL JOIN (SELECT e.*,sn.ordinal AS source_ordinal,tn.ordinal AS target_ordinal FROM creative_canvas_edges e JOIN creative_canvas_nodes sn ON sn.project_id=e.project_id AND sn.version_id=e.version_id AND sn.node_key=e.source_key JOIN creative_canvas_nodes tn ON tn.project_id=e.project_id AND tn.version_id=e.version_id AND tn.node_key=e.target_key WHERE e.project_id=NEW.project_id AND e.version_id=NEW.canvas_version_id) t USING(ordinal)
  WHERE s.edge_key IS NULL OR t.edge_key IS NULL OR s.edge_key=t.edge_key OR s.source_ordinal<>t.source_ordinal OR s.target_ordinal<>t.target_ordinal OR s.port<>t.port OR s.source_type<>t.source_type OR s.target_type<>t.target_type
 ) THEN RAISE EXCEPTION 'direct copy edge mapping mismatch' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;

CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_direct_copies FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
CREATE TRIGGER direct_copy_insert_guard BEFORE INSERT ON canvas_direct_copies FOR EACH ROW EXECUTE FUNCTION vsc_direct_copy_insert_guard();

CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_direct_copy_media FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
CREATE TRIGGER direct_copy_insert_guard BEFORE INSERT ON canvas_direct_copy_media FOR EACH ROW EXECUTE FUNCTION vsc_direct_copy_insert_guard();

CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_direct_copy_domains FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
CREATE TRIGGER direct_copy_insert_guard BEFORE INSERT ON canvas_direct_copy_domains FOR EACH ROW EXECUTE FUNCTION vsc_direct_copy_insert_guard();
CREATE CONSTRAINT TRIGGER direct_copy_complete_guard AFTER INSERT ON canvas_direct_copies DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_direct_copy_complete_guard();
"""

LIBRARY_PRIOR_GUARD = """CREATE OR REPLACE FUNCTION vsc_library_has_imported_ancestor(p_project_id uuid, p_media_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
WITH RECURSIVE edges AS NOT MATERIALIZED (

 SELECT c.project_id AS target_project, t.media_id AS target_media,
        c.source_project_id AS source_project, s.media_id AS source_media
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 WHERE t.media_id IS NOT NULL AND s.media_id IS NOT NULL
 UNION
 SELECT c.project_id, tv.reference_media_id, c.source_project_id, sv.reference_media_id
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 JOIN voice_spec_versions tv ON tv.project_id=t.project_id AND tv.id=t.voice_spec_id
 JOIN voice_spec_versions sv ON sv.project_id=s.project_id AND sv.id=s.voice_spec_id
 WHERE tv.reference_media_id IS NOT NULL AND sv.reference_media_id IS NOT NULL
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM template_copy_media
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM canvas_project_media_links
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM classic_frame_media_links

 UNION ALL
 SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM operation_outputs o JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
 UNION ALL
 SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM job_outputs o JOIN job_input_media i ON i.project_id=o.project_id AND i.job_id=o.job_id
), ancestors(project_id,media_id) AS (
 SELECT p_project_id,p_media_id
 UNION
 SELECT e.source_project,e.source_media FROM ancestors a JOIN edges e ON e.target_project=a.project_id AND e.target_media=a.media_id
)
SELECT EXISTS(SELECT 1 FROM ancestors a JOIN library_reuses r ON r.project_id=a.project_id AND r.media_id=a.media_id WHERE r.library_version_id IS NOT NULL AND r.reuse_mode IN ('reference','derive'))
$$
"""

LIBRARY_NEW_GUARD = """CREATE OR REPLACE FUNCTION vsc_library_has_imported_ancestor(p_project_id uuid, p_media_id uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
WITH RECURSIVE edges AS NOT MATERIALIZED (

 SELECT c.project_id AS target_project, t.media_id AS target_media,
        c.source_project_id AS source_project, s.media_id AS source_media
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 WHERE t.media_id IS NOT NULL AND s.media_id IS NOT NULL
 UNION
 SELECT c.project_id, tv.reference_media_id, c.source_project_id, sv.reference_media_id
 FROM asset_card_copy_sources c
 JOIN asset_card_form_versions t ON t.project_id=c.project_id AND t.id=c.target_form_version_id
 JOIN asset_card_form_versions s ON s.project_id=c.source_project_id AND s.id=c.source_form_version_id
 JOIN voice_spec_versions tv ON tv.project_id=t.project_id AND tv.id=t.voice_spec_id
 JOIN voice_spec_versions sv ON sv.project_id=s.project_id AND sv.id=s.voice_spec_id
 WHERE tv.reference_media_id IS NOT NULL AND sv.reference_media_id IS NOT NULL
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM template_copy_media
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM canvas_direct_copy_media
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM canvas_project_media_links
 UNION
 SELECT project_id,target_media_id,source_project_id,source_media_id FROM classic_frame_media_links

 UNION ALL
 SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM operation_outputs o JOIN operation_inputs i ON i.project_id=o.project_id AND i.operation_id=o.operation_id
 UNION ALL
 SELECT o.project_id,o.media_id,i.project_id,i.media_id FROM job_outputs o JOIN job_input_media i ON i.project_id=o.project_id AND i.job_id=o.job_id
), ancestors(project_id,media_id) AS (
 SELECT p_project_id,p_media_id
 UNION
 SELECT e.source_project,e.source_media FROM ancestors a JOIN edges e ON e.target_project=a.project_id AND e.target_media=a.media_id
)
SELECT EXISTS(SELECT 1 FROM ancestors a JOIN library_reuses r ON r.project_id=a.project_id AND r.media_id=a.media_id WHERE r.library_version_id IS NOT NULL AND r.reuse_mode IN ('reference','derive'))
$$
"""

def upgrade():
    op.execute(DDL)
    op.execute(GUARDS)
    op.execute(LIBRARY_NEW_GUARD)


def downgrade():
    op.execute("LOCK TABLE canvas_direct_copies,canvas_direct_copy_media,canvas_direct_copy_domains IN ACCESS EXCLUSIVE MODE")
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM canvas_direct_copies) OR EXISTS(SELECT 1 FROM canvas_direct_copy_media) OR EXISTS(SELECT 1 FROM canvas_direct_copy_domains) THEN RAISE EXCEPTION 'direct copy facts exist; use forward recovery' USING ERRCODE='23514'; END IF; END $$")
    op.execute(LIBRARY_PRIOR_GUARD)
    for name in ('canvas_direct_copy_domains','canvas_direct_copy_media','canvas_direct_copies'):op.drop_table(name)
    for signature in ('vsc_direct_copy_complete_guard()','vsc_direct_copy_insert_guard()','vsc_canvas_fixed_media(uuid,uuid)','vsc_canvas_fixed_domains(uuid,uuid)','vsc_canvas_domain_media(uuid,text,uuid)','vsc_direct_copy_new_row(xid,timestamptz)'):op.execute('DROP FUNCTION '+signature)
