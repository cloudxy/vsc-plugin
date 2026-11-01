"""Typed versioned creative canvases, sealed members and original-job bindings."""
from alembic import op

revision = "0014_creative_canvas"
down_revision = "0013_shared_library"
branch_labels = None
depends_on = None

DDL = ['\n'
 'CREATE TABLE creative_canvases (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tepisode_id UUID, \n'
 '\tcurrent_version_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_creative_canvases PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvases_project_id_episode_id_episodes FOREIGN KEY(project_id, episode_id) '
 'REFERENCES episodes (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvases_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON '
 'DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_canvases_current_version_id ON creative_canvases (project_id, current_version_id)',
 'CREATE INDEX ix_creative_canvases_episode_id ON creative_canvases (project_id, episode_id)',
 '\n'
 'CREATE TABLE creative_canvas_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tcanvas_id UUID NOT NULL, \n'
 '\tversion BIGINT NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tviewport JSONB NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tnode_count INTEGER NOT NULL, \n'
 '\tedge_count INTEGER NOT NULL, \n'
 '\tparent_version_id UUID, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_creative_canvas_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_creative_canvas_versions_project_id_canvas_id_id UNIQUE (project_id, canvas_id, id), \n'
 '\tCONSTRAINT uq_creative_canvas_versions_project_id_canvas_id_version UNIQUE (project_id, canvas_id, '
 'version), \n'
 '\tCONSTRAINT fk_creative_canvas_versions_project_id_canvas_id_creati_992b FOREIGN KEY(project_id, '
 'canvas_id) REFERENCES creative_canvases (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_versions_project_id_canvas_id_parent_a3c6 FOREIGN KEY(project_id, '
 'canvas_id, parent_version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id), \n'
 '\tCONSTRAINT ck_creative_canvas_versions_counts CHECK (version > 0 AND node_count BETWEEN 0 AND 200 AND '
 'edge_count BETWEEN 0 AND 800), \n'
 '\tCONSTRAINT fk_creative_canvas_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_creative_canvas_versions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '
 "'^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_canvas_versions_canvas_id ON creative_canvas_versions (project_id, canvas_id)',
 'CREATE INDEX ix_creative_canvas_versions_parent_version_id ON creative_canvas_versions (project_id, '
 'parent_version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_canvas_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE creative_canvas_nodes (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tnode_type TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tx FLOAT NOT NULL, \n'
 '\ty FLOAT NOT NULL, \n'
 '\tcontent TEXT NOT NULL, \n'
 '\tparams JSONB NOT NULL, \n'
 '\tgroup_name TEXT NOT NULL, \n'
 '\tmedia_id UUID, \n'
 '\tjob_id UUID, \n'
 '\tCONSTRAINT pk_creative_canvas_nodes PRIMARY KEY (project_id, version_id, node_key), \n'
 '\tCONSTRAINT uq_creative_canvas_nodes_project_id_version_id_ordinal UNIQUE (project_id, version_id, '
 'ordinal), \n'
 '\tCONSTRAINT uq_creative_canvas_nodes_project_id_version_id_node_key_d0bd UNIQUE (project_id, version_id, '
 'node_key, node_type), \n'
 '\tCONSTRAINT fk_creative_canvas_nodes_project_id_version_id_creative_2fce FOREIGN KEY(project_id, '
 'version_id) REFERENCES creative_canvas_versions (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_nodes_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_nodes_project_id_job_id_generation_jobs FOREIGN KEY(project_id, job_id) '
 'REFERENCES generation_jobs (project_id, id), \n'
 "\tCONSTRAINT ck_creative_canvas_nodes_type CHECK (node_type IN ('text','image','video','audio')), \n"
 "\tCONSTRAINT ck_creative_canvas_nodes_text_reference CHECK (node_type <> 'text' OR (media_id IS NULL AND "
 'job_id IS NULL)), \n'
 '\tCONSTRAINT ck_creative_canvas_nodes_position CHECK (ordinal >= 0 AND x BETWEEN -100000 AND 100000 AND y '
 'BETWEEN -100000 AND 100000), \n'
 '\tCONSTRAINT fk_creative_canvas_nodes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_canvas_nodes_job_id ON creative_canvas_nodes (project_id, job_id)',
 'CREATE INDEX ix_creative_canvas_nodes_media_id ON creative_canvas_nodes (project_id, media_id)',
 'CREATE INDEX ix_creative_canvas_nodes_version_id ON creative_canvas_nodes (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_canvas_nodes FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE creative_canvas_edges (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tedge_key TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tsource_key TEXT NOT NULL, \n'
 '\ttarget_key TEXT NOT NULL, \n'
 '\tsource_type TEXT NOT NULL, \n'
 '\ttarget_type TEXT NOT NULL, \n'
 '\tport TEXT NOT NULL, \n'
 '\tCONSTRAINT pk_creative_canvas_edges PRIMARY KEY (project_id, version_id, edge_key), \n'
 '\tCONSTRAINT uq_creative_canvas_edges_project_id_version_id_ordinal UNIQUE (project_id, version_id, '
 'ordinal), \n'
 '\tCONSTRAINT uq_creative_canvas_edges_project_id_version_id_source_k_017f UNIQUE (project_id, version_id, '
 'source_key, target_key, port), \n'
 '\tCONSTRAINT fk_creative_canvas_edges_project_id_version_id_source_k_61d4 FOREIGN KEY(project_id, '
 'version_id, source_key, source_type) REFERENCES creative_canvas_nodes (project_id, version_id, node_key, '
 'node_type), \n'
 '\tCONSTRAINT fk_creative_canvas_edges_project_id_version_id_target_k_2bbb FOREIGN KEY(project_id, '
 'version_id, target_key, target_type) REFERENCES creative_canvas_nodes (project_id, version_id, node_key, '
 'node_type), \n'
 '\tCONSTRAINT ck_creative_canvas_edges_endpoints CHECK (source_key <> target_key AND ordinal >= 0), \n'
 "\tCONSTRAINT ck_creative_canvas_edges_port_type CHECK ((port = 'prompt' AND source_type = 'text' AND "
 "target_type IN ('image','video','audio')) OR (port = 'reference' AND source_type = 'image' AND target_type "
 "= 'image') OR (port IN ('first_frame','last_frame','reference_image') AND source_type = 'image' AND "
 "target_type = 'video') OR (port = 'reference_video' AND source_type = 'video' AND target_type = 'video') "
 "OR (port = 'reference_audio' AND source_type = 'audio' AND target_type IN ('video','audio'))), \n"
 '\tCONSTRAINT fk_creative_canvas_edges_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE UNIQUE INDEX uq_canvas_single_frame ON creative_canvas_edges (project_id, version_id, target_key, '
 "port) WHERE port IN ('first_frame','last_frame')",
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_canvas_edges FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE creative_canvas_preparations (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tjob_id UUID, \n'
 '\tinput_sha256 VARCHAR(64) NOT NULL, \n'
 '\tprompt TEXT NOT NULL, \n'
 '\tparams JSONB NOT NULL, \n'
 '\tgaps JSONB NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_creative_canvas_preparations PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_preparations_project_id_version_id_n_4dbb FOREIGN KEY(project_id, '
 'version_id, node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_creative_canvas_preparations_project_id_job_id_gener_81cb FOREIGN KEY(project_id, job_id) '
 'REFERENCES generation_jobs (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_preparations_project_id_projects FOREIGN KEY(project_id) REFERENCES '
 'projects (id) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_creative_canvas_preparations_input_sha256_format CHECK (input_sha256 IS NULL OR '
 "input_sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_canvas_preparations_job_id ON creative_canvas_preparations (project_id, job_id)',
 'CREATE INDEX ix_creative_canvas_preparations_version_id ON creative_canvas_preparations (project_id, '
 'version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_canvas_preparations FOR EACH ROW '
 'EXECUTE FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE creative_canvas_runs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tartifact_id UUID NOT NULL, \n'
 '\tpreview_sha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_creative_canvas_runs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_creative_canvas_runs_project_id_artifact_id UNIQUE (project_id, artifact_id), \n'
 '\tCONSTRAINT fk_creative_canvas_runs_project_id_version_id_node_key__20e2 FOREIGN KEY(project_id, '
 'version_id, node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_creative_canvas_runs_project_id_artifact_id_artifact_ffbd FOREIGN KEY(project_id, '
 'artifact_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_creative_canvas_runs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) '
 'ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_creative_canvas_runs_preview_sha256_format CHECK (preview_sha256 IS NULL OR preview_sha256 '
 "~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_creative_canvas_runs_artifact_id ON creative_canvas_runs (project_id, artifact_id)',
 'CREATE INDEX ix_creative_canvas_runs_version_id ON creative_canvas_runs (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON creative_canvas_runs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'ALTER TABLE creative_canvases ADD CONSTRAINT fk_creative_canvases_current_version FOREIGN KEY(project_id, '
 'id, current_version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id)']

DDL += ["""
CREATE FUNCTION vsc_canvas_member_set() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; v uuid; n integer; e integer;
BEGIN
  p:=NEW.project_id;
  IF TG_TABLE_NAME='creative_canvas_versions' THEN v:=NEW.id; ELSE v:=NEW.version_id; END IF;
  SELECT node_count,edge_count INTO n,e FROM creative_canvas_versions WHERE project_id=p AND id=v;
  IF n IS DISTINCT FROM (SELECT count(*)::integer FROM creative_canvas_nodes WHERE project_id=p AND version_id=v)
     OR e IS DISTINCT FROM (SELECT count(*)::integer FROM creative_canvas_edges WHERE project_id=p AND version_id=v) THEN
    RAISE EXCEPTION 'canvas members are incomplete or already sealed' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME='creative_canvas_versions' AND EXISTS (
    WITH RECURSIVE walk(source_key,target_key) AS (
      SELECT source_key,target_key FROM creative_canvas_edges WHERE project_id=p AND version_id=v
      UNION
      SELECT w.source_key,e.target_key FROM walk w JOIN creative_canvas_edges e ON e.source_key=w.target_key
        WHERE e.project_id=p AND e.version_id=v
    ) SELECT 1 FROM walk WHERE source_key=target_key
  ) THEN RAISE EXCEPTION 'canvas reference cycle' USING ERRCODE='23514'; END IF;
  RETURN NULL;
END $$
""", """
CREATE FUNCTION vsc_canvas_reference_type() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE kind text; original_job uuid;
BEGIN
  IF TG_TABLE_NAME='creative_canvas_nodes' THEN
    IF NEW.media_id IS NOT NULL THEN
      SELECT modality INTO kind FROM media_items WHERE project_id=NEW.project_id AND id=NEW.media_id;
      IF kind IS DISTINCT FROM NEW.node_type THEN
        RAISE EXCEPTION 'canvas media modality mismatch' USING ERRCODE='23514';
      END IF;
    END IF;
    IF NEW.job_id IS NOT NULL THEN
      SELECT modality INTO kind FROM generation_jobs WHERE project_id=NEW.project_id AND id=NEW.job_id;
      IF kind IS DISTINCT FROM NEW.node_type THEN
        RAISE EXCEPTION 'canvas job modality mismatch' USING ERRCODE='23514';
      END IF;
    END IF;
  ELSE
    SELECT job_id INTO original_job FROM creative_canvas_nodes
      WHERE project_id=NEW.project_id AND version_id=NEW.version_id AND node_key=NEW.node_key;
    IF NEW.job_id IS DISTINCT FROM original_job THEN
      RAISE EXCEPTION 'canvas preparation must reference its fixed node job' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$
""", """
CREATE FUNCTION vsc_canvas_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-'current_version_id') IS DISTINCT FROM (to_jsonb(OLD)-'current_version_id') THEN
    RAISE EXCEPTION 'canvas identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$
"""]

for _table in ('creative_canvas_versions', 'creative_canvas_nodes', 'creative_canvas_edges'):
    DDL.append('CREATE CONSTRAINT TRIGGER canvas_member_set AFTER INSERT ON ' + _table +
        ' DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_canvas_member_set()')
for _table in ('creative_canvas_nodes', 'creative_canvas_preparations'):
    DDL.append('CREATE TRIGGER canvas_reference_type BEFORE INSERT ON ' + _table +
        ' FOR EACH ROW EXECUTE FUNCTION vsc_canvas_reference_type()')
DDL.append('CREATE TRIGGER canvas_identity BEFORE UPDATE OR DELETE ON creative_canvases '
    'FOR EACH ROW EXECUTE FUNCTION vsc_canvas_identity()')


def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    op.drop_constraint('fk_creative_canvases_current_version', 'creative_canvases', type_='foreignkey')
    for table in ('creative_canvas_runs', 'creative_canvas_preparations', 'creative_canvas_edges', 'creative_canvas_nodes',
                  'creative_canvas_versions', 'creative_canvases'):
        op.drop_table(table)
    for function in ('vsc_canvas_member_set', 'vsc_canvas_reference_type', 'vsc_canvas_identity'):
        op.execute('DROP FUNCTION ' + function + '()')
