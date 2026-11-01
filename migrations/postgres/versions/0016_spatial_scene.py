"""Versioned blocking and previs scenes with fenced exports to original media."""
from alembic import op

revision="0016_spatial_scene"
down_revision="0015_editor_workspace"
branch_labels=None
depends_on=None

DDL=['\n'
 'CREATE TABLE spatial_scenes (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tmode TEXT NOT NULL, \n'
 '\tscene_id UUID, \n'
 '\tepisode_id UUID, \n'
 '\tcurrent_version_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_scenes PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_scenes_project_id_scene_id_scenes FOREIGN KEY(project_id, scene_id) REFERENCES '
 'scenes (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_scenes_project_id_episode_id_episodes FOREIGN KEY(project_id, episode_id) '
 'REFERENCES episodes (project_id, id), \n'
 "\tCONSTRAINT ck_spatial_scenes_mode_scope CHECK (mode IN ('blocking','previs') AND (mode <> 'blocking' OR "
 'scene_id IS NOT NULL)), \n'
 '\tCONSTRAINT fk_spatial_scenes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_scenes_current_version_id ON spatial_scenes (project_id, current_version_id)',
 'CREATE INDEX ix_spatial_scenes_episode_id ON spatial_scenes (project_id, episode_id)',
 'CREATE INDEX ix_spatial_scenes_scene_id ON spatial_scenes (project_id, scene_id)',
 '\n'
 'CREATE TABLE spatial_scene_versions (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tspatial_scene_id UUID NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\ttitle TEXT NOT NULL, \n'
 '\tdescription TEXT NOT NULL, \n'
 '\tsettings JSONB NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tobject_count INTEGER NOT NULL, \n'
 '\tcamera_count INTEGER NOT NULL, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_scene_versions PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_spatial_scene_versions_project_id_spatial_scene_id_version UNIQUE (project_id, '
 'spatial_scene_id, version), \n'
 '\tCONSTRAINT uq_spatial_scene_versions_project_id_spatial_scene_id_id UNIQUE (project_id, '
 'spatial_scene_id, id), \n'
 '\tCONSTRAINT fk_spatial_scene_versions_project_id_spatial_scene_id_s_7bc3 FOREIGN KEY(project_id, '
 'spatial_scene_id) REFERENCES spatial_scenes (project_id, id), \n'
 '\tCONSTRAINT ck_spatial_scene_versions_counts CHECK (version > 0 AND object_count BETWEEN 0 AND 64 AND '
 'camera_count BETWEEN 1 AND 8), \n'
 '\tCONSTRAINT fk_spatial_scene_versions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id), \n'
 "\tCONSTRAINT ck_spatial_scene_versions_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_scene_versions_spatial_scene_id ON spatial_scene_versions (project_id, '
 'spatial_scene_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON spatial_scene_versions FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 '\n'
 'CREATE TABLE spatial_objects (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tobject_key TEXT NOT NULL, \n'
 '\tkind TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tspec JSONB NOT NULL, \n'
 '\tmedia_id UUID, \n'
 '\tCONSTRAINT pk_spatial_objects PRIMARY KEY (project_id, version_id, object_key), \n'
 '\tCONSTRAINT uq_spatial_objects_project_id_version_id_ordinal UNIQUE (project_id, version_id, ordinal), \n'
 '\tCONSTRAINT fk_spatial_objects_project_id_version_id_spatial_scene_versions FOREIGN KEY(project_id, '
 'version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_objects_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id), \n'
 "\tCONSTRAINT ck_spatial_objects_kind CHECK (kind IN ('box','sphere','actor','light','mesh','reference') "
 'AND ordinal >= 0), \n'
 '\tCONSTRAINT fk_spatial_objects_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_objects_media_id ON spatial_objects (project_id, media_id)',
 'CREATE INDEX ix_spatial_objects_version_id ON spatial_objects (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON spatial_objects FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE spatial_cameras (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tcamera_key TEXT NOT NULL, \n'
 '\tordinal INTEGER NOT NULL, \n'
 '\tspec JSONB NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_cameras PRIMARY KEY (project_id, version_id, camera_key), \n'
 '\tCONSTRAINT uq_spatial_cameras_project_id_version_id_ordinal UNIQUE (project_id, version_id, ordinal), \n'
 '\tCONSTRAINT fk_spatial_cameras_project_id_version_id_spatial_scene_versions FOREIGN KEY(project_id, '
 'version_id) REFERENCES spatial_scene_versions (project_id, id), \n'
 '\tCONSTRAINT ck_spatial_cameras_ordinal CHECK (ordinal >= 0), \n'
 '\tCONSTRAINT fk_spatial_cameras_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_cameras_version_id ON spatial_cameras (project_id, version_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON spatial_cameras FOR EACH ROW EXECUTE FUNCTION '
 'vsc_reject_mutation()',
 '\n'
 'CREATE TABLE spatial_exports (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tcamera_key TEXT NOT NULL, \n'
 '\tformat TEXT NOT NULL, \n'
 '\ttime_seconds FLOAT NOT NULL, \n'
 '\tduration_seconds FLOAT NOT NULL, \n'
 '\tfps INTEGER NOT NULL, \n'
 '\ttotal_frames INTEGER NOT NULL, \n'
 "\tprogress_frames INTEGER DEFAULT '0' NOT NULL, \n"
 '\tstatus TEXT NOT NULL, \n'
 "\tattempt INTEGER DEFAULT '0' NOT NULL, \n"
 '\tclaim_token TEXT, \n'
 '\tclaim_until TIMESTAMP WITH TIME ZONE, \n'
 "\tcancel_requested BOOLEAN DEFAULT 'false' NOT NULL, \n"
 '\terror TEXT, \n'
 '\tcreated_by TEXT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_exports PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_exports_project_id_version_id_camera_key_spa_5d09 FOREIGN KEY(project_id, '
 'version_id, camera_key) REFERENCES spatial_cameras (project_id, version_id, camera_key), \n'
 "\tCONSTRAINT ck_spatial_exports_format CHECK (format IN ('png','glb','mp4')), \n"
 '\tCONSTRAINT ck_spatial_exports_status CHECK (status IN '
 "('queued','running','succeeded','failed','cancelled') AND attempt >= 0), \n"
 '\tCONSTRAINT ck_spatial_exports_bounds CHECK (time_seconds >= 0 AND duration_seconds >= 0 AND fps IN '
 '(12,24) AND total_frames BETWEEN 1 AND 360 AND progress_frames BETWEEN 0 AND total_frames), \n'
 '\tCONSTRAINT fk_spatial_exports_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_exports_version_id ON spatial_exports (project_id, version_id)',
 '\n'
 'CREATE TABLE spatial_export_outputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\texport_id UUID NOT NULL, \n'
 '\tmedia_id UUID NOT NULL, \n'
 '\tsha256 VARCHAR(64) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_spatial_export_outputs PRIMARY KEY (project_id, id), \n'
 '\tCONSTRAINT uq_spatial_export_outputs_project_id_export_id UNIQUE (project_id, export_id), \n'
 '\tCONSTRAINT fk_spatial_export_outputs_project_id_export_id_spatial_exports FOREIGN KEY(project_id, '
 'export_id) REFERENCES spatial_exports (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_export_outputs_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) '
 'REFERENCES media_items (project_id, id), \n'
 '\tCONSTRAINT fk_spatial_export_outputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id), \n'
 "\tCONSTRAINT ck_spatial_export_outputs_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_spatial_export_outputs_export_id ON spatial_export_outputs (project_id, export_id)',
 'CREATE INDEX ix_spatial_export_outputs_media_id ON spatial_export_outputs (project_id, media_id)',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON spatial_export_outputs FOR EACH ROW EXECUTE '
 'FUNCTION vsc_reject_mutation()',
 'ALTER TABLE spatial_scenes ADD CONSTRAINT fk_spatial_scene_current FOREIGN KEY(project_id, id, '
 'current_version_id) REFERENCES spatial_scene_versions (project_id, spatial_scene_id, id)']

DDL += ["""
CREATE FUNCTION vsc_spatial_members() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p uuid; v uuid; n integer; c integer;
BEGIN
 p:=NEW.project_id;
 IF TG_TABLE_NAME='spatial_scene_versions' THEN v:=NEW.id; ELSE v:=NEW.version_id; END IF;
 SELECT object_count,camera_count INTO n,c FROM spatial_scene_versions WHERE project_id=p AND id=v;
 IF n IS DISTINCT FROM (SELECT count(*)::integer FROM spatial_objects WHERE project_id=p AND version_id=v)
    OR c IS DISTINCT FROM (SELECT count(*)::integer FROM spatial_cameras WHERE project_id=p AND version_id=v) THEN
   RAISE EXCEPTION 'spatial version members are incomplete or already sealed' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$
""", """
CREATE FUNCTION vsc_spatial_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'spatial identity is immutable' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='spatial_scenes' THEN
   IF (to_jsonb(NEW)-'current_version_id') IS DISTINCT FROM (to_jsonb(OLD)-'current_version_id') THEN
     RAISE EXCEPTION 'spatial identity is immutable' USING ERRCODE='23514'; END IF;
 ELSE
   IF (to_jsonb(NEW)-ARRAY['status','attempt','progress_frames','claim_token','claim_until','cancel_requested','error'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','attempt','progress_frames','claim_token','claim_until','cancel_requested','error']) THEN
     RAISE EXCEPTION 'spatial export request is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$
""", """
CREATE FUNCTION vsc_spatial_output() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job spatial_exports%ROWTYPE; output spatial_export_outputs%ROWTYPE; modality text; sha text;
BEGIN
 IF TG_TABLE_NAME='spatial_exports' THEN job:=NEW;
 ELSE SELECT * INTO job FROM spatial_exports WHERE project_id=NEW.project_id AND id=NEW.export_id; END IF;
 SELECT * INTO output FROM spatial_export_outputs WHERE project_id=job.project_id AND export_id=job.id;
 IF job.status='succeeded' AND output.id IS NULL OR output.id IS NOT NULL AND job.status<>'succeeded' THEN
   RAISE EXCEPTION 'spatial success and immutable output must agree' USING ERRCODE='23514'; END IF;
 IF output.id IS NOT NULL THEN
   SELECT m.modality,b.sha256 INTO modality,sha FROM media_items m JOIN media_blobs b ON b.id=m.blob_id
     WHERE m.project_id=output.project_id AND m.id=output.media_id;
   IF sha IS DISTINCT FROM output.sha256 OR
       (job.format='png' AND modality<>'image') OR (job.format='mp4' AND modality<>'video') OR
       (job.format='glb' AND modality NOT IN ('document','other')) THEN
     RAISE EXCEPTION 'spatial output must pin matching original media bytes and type' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $$
"""]
for _table in ('spatial_scene_versions','spatial_objects','spatial_cameras'):
    DDL.append('CREATE CONSTRAINT TRIGGER spatial_members AFTER INSERT ON '+_table+
        ' DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_spatial_members()')
for _table in ('spatial_scenes','spatial_exports'):
    DDL.append('CREATE TRIGGER spatial_identity BEFORE UPDATE OR DELETE ON '+_table+
        ' FOR EACH ROW EXECUTE FUNCTION vsc_spatial_identity()')
DDL += ['CREATE CONSTRAINT TRIGGER spatial_output AFTER INSERT OR UPDATE ON spatial_exports DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_spatial_output()',
        'CREATE CONSTRAINT TRIGGER spatial_output AFTER INSERT ON spatial_export_outputs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vsc_spatial_output()']


def upgrade():
    for sql in DDL:op.execute(sql)


def downgrade():
    op.drop_constraint('fk_spatial_scene_current','spatial_scenes',type_='foreignkey')
    for name in ('spatial_export_outputs','spatial_exports','spatial_cameras','spatial_objects','spatial_scene_versions','spatial_scenes'):
        op.drop_table(name)
    for name in ('vsc_spatial_members','vsc_spatial_identity','vsc_spatial_output'):
        op.execute('DROP FUNCTION '+name+'()')
