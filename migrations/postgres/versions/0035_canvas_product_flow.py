"""Typed canvas domain references and original working-generation provenance."""
from alembic import op
revision="0035_canvas_product_flow"
down_revision="0034_working_state"
branch_labels=None
depends_on=None
DDL=['ALTER TABLE creative_canvas_nodes ADD COLUMN spatial_scene_id UUID',
 'ALTER TABLE creative_canvas_nodes ADD COLUMN spatial_version_id UUID',
 'ALTER TABLE creative_canvas_nodes ADD COLUMN edit_workspace_id UUID',
 'ALTER TABLE creative_canvas_nodes ADD COLUMN edit_version_id UUID',
 'ALTER TABLE creative_canvas_nodes ADD COLUMN tool_draft_id UUID',
 'ALTER TABLE creative_canvas_nodes DROP CONSTRAINT ck_creative_canvas_nodes_type',
 'ALTER TABLE creative_canvas_edges DROP CONSTRAINT ck_creative_canvas_edges_port_type',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT ck_creative_canvas_nodes_domain_shape CHECK '
 '((spatial_scene_id IS NULL) = (spatial_version_id IS NULL) AND (edit_workspace_id IS NULL) = '
 "(edit_version_id IS NULL) AND (spatial_scene_id IS NULL OR node_type IN ('spatial','director')) AND "
 "(edit_workspace_id IS NULL OR node_type='edit') AND (tool_draft_id IS NULL OR node_type IN "
 "('music_mix','processing')) AND (node_type IN ('text','image','video','audio') OR (media_id IS NULL AND "
 'job_id IS NULL)))',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT ck_creative_canvas_nodes_type CHECK (node_type IN '
 "('text','image','video','audio','spatial','director','edit','music_mix','processing'))",
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT '
 'fk_creative_canvas_nodes_project_id_edit_workspace_id_e_a3e0 FOREIGN KEY(project_id, edit_workspace_id, '
 'edit_version_id) REFERENCES edit_revisions (project_id, workspace_id, id)',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT '
 'fk_creative_canvas_nodes_project_id_edit_workspace_id_e_a7d8 FOREIGN KEY(project_id, edit_workspace_id) '
 'REFERENCES edit_workspaces (project_id, id)',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT '
 'fk_creative_canvas_nodes_project_id_spatial_scene_id_sp_a4ab FOREIGN KEY(project_id, spatial_scene_id) '
 'REFERENCES spatial_scenes (project_id, id)',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT '
 'fk_creative_canvas_nodes_project_id_spatial_scene_id_sp_125c FOREIGN KEY(project_id, spatial_scene_id, '
 'spatial_version_id) REFERENCES spatial_scene_versions (project_id, spatial_scene_id, id)',
 'ALTER TABLE creative_canvas_nodes ADD CONSTRAINT '
 'fk_creative_canvas_nodes_project_id_tool_draft_id_artif_81cf FOREIGN KEY(project_id, tool_draft_id) '
 'REFERENCES artifact_versions (project_id, id)',
 'ALTER TABLE creative_canvas_edges ADD CONSTRAINT ck_creative_canvas_edges_port_type CHECK ((port = '
 "'prompt' AND source_type = 'text' AND target_type IN "
 "('image','video','audio','spatial','director','music_mix','processing')) OR (port = 'reference' AND "
 "source_type = 'image' AND target_type IN ('image','spatial','director')) OR (port IN "
 "('first_frame','last_frame','reference_image') AND source_type = 'image' AND target_type = 'video') OR "
 "(port = 'reference_video' AND source_type = 'video' AND target_type = 'video') OR (port = "
 "'reference_audio' AND source_type = 'audio' AND target_type IN ('video','audio')) OR (port='visual' AND "
 "source_type IN ('image','video') AND target_type='edit') OR (port='sound' AND source_type='audio' AND "
 "target_type IN ('edit','music_mix')) OR (port='source_video' AND source_type='video' AND target_type IN "
 "('music_mix','processing')) OR (port='derived_from' AND source_type IN "
 "('text','image','video','audio','spatial','director','edit','music_mix','processing') AND target_type IN "
 "('text','image','video','audio')))",
 '\n'
 'CREATE TABLE canvas_generation_inputs (\n'
 '\tproject_id UUID NOT NULL, \n'
 '\tdraft_version_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\tnode_key TEXT NOT NULL, \n'
 '\tshot_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tCONSTRAINT pk_canvas_generation_inputs PRIMARY KEY (project_id, draft_version_id), \n'
 '\tCONSTRAINT fk_canvas_generation_inputs_project_id_draft_version_id_0b4e FOREIGN KEY(project_id, '
 'draft_version_id) REFERENCES artifact_versions (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_generation_inputs_project_id_version_id_node__e986 FOREIGN KEY(project_id, '
 'version_id, node_key) REFERENCES creative_canvas_nodes (project_id, version_id, node_key), \n'
 '\tCONSTRAINT fk_canvas_generation_inputs_project_id_shot_id_shots FOREIGN KEY(project_id, shot_id) '
 'REFERENCES shots (project_id, id), \n'
 '\tCONSTRAINT fk_canvas_generation_inputs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects '
 '(id) ON DELETE RESTRICT\n'
 ')\n'
 '\n',
 'CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_generation_inputs FOR '
 'EACH ROW EXECUTE FUNCTION vsc_reject_mutation()']

DDL.append("CREATE OR REPLACE FUNCTION vsc_canvas_execution_links() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE old_step record; actual uuid; kind text;\nBEGIN\nIF NEW.spec_id IS NOT NULL THEN SELECT asset_id INTO actual FROM asset_spec_versions WHERE project_id=NEW.project_id AND id=NEW.spec_id; IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION 'execution asset/spec mismatch' USING ERRCODE='23514'; END IF; END IF;\nSELECT artifact_type INTO kind FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.run_artifact_id;\nIF kind NOT IN ('production-run','vsc.production_run','workbench-generation-run') THEN RAISE EXCEPTION 'execution must reference original run' USING ERRCODE='23514'; END IF;\nIF NEW.source_step_id IS NOT NULL THEN SELECT * INTO old_step FROM canvas_execution_steps WHERE project_id=NEW.project_id AND id=NEW.source_step_id; IF (NEW.version_id,NEW.node_key,NEW.shot_id,NEW.asset_id,NEW.spec_id) IS DISTINCT FROM (old_step.version_id,old_step.node_key,old_step.shot_id,old_step.asset_id,old_step.spec_id) THEN RAISE EXCEPTION 'fallback target changed' USING ERRCODE='23514'; END IF; END IF;\nRETURN NEW; END $$")

DDL += ['CREATE INDEX ix_creative_canvas_nodes_spatial_scene_id ON creative_canvas_nodes (project_id, spatial_scene_id)', 'CREATE INDEX ix_creative_canvas_nodes_spatial_version_id ON creative_canvas_nodes (project_id, spatial_version_id)', 'CREATE INDEX ix_creative_canvas_nodes_edit_workspace_id ON creative_canvas_nodes (project_id, edit_workspace_id)', 'CREATE INDEX ix_creative_canvas_nodes_edit_version_id ON creative_canvas_nodes (project_id, edit_version_id)', 'CREATE INDEX ix_creative_canvas_nodes_tool_draft_id ON creative_canvas_nodes (project_id, tool_draft_id)']

def upgrade():
    for statement in DDL:op.execute(statement)

# These statements reproduce the pre-0035 contract; no current metadata is imported.
LEGACY_NODE_TYPE = "ALTER TABLE creative_canvas_nodes ADD CONSTRAINT ck_creative_canvas_nodes_type CHECK (node_type IN ('text','image','video','audio'))"
LEGACY_PORT_TYPE = "ALTER TABLE creative_canvas_edges ADD CONSTRAINT ck_creative_canvas_edges_port_type CHECK ((port='prompt' AND source_type='text' AND target_type IN ('image','video','audio')) OR (port='reference' AND source_type='image' AND target_type='image') OR (port IN ('first_frame','last_frame','reference_image') AND source_type='image' AND target_type='video') OR (port='reference_video' AND source_type='video' AND target_type='video') OR (port='reference_audio' AND source_type='audio' AND target_type IN ('video','audio')))"
LEGACY_EXECUTION_LINKS = "CREATE OR REPLACE FUNCTION vsc_canvas_execution_links() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE old_step record; actual uuid; kind text;\nBEGIN\nIF NEW.spec_id IS NOT NULL THEN SELECT asset_id INTO actual FROM asset_spec_versions WHERE project_id=NEW.project_id AND id=NEW.spec_id; IF actual IS DISTINCT FROM NEW.asset_id THEN RAISE EXCEPTION 'execution asset/spec mismatch' USING ERRCODE='23514'; END IF; END IF;\nSELECT artifact_type INTO kind FROM artifact_versions WHERE project_id=NEW.project_id AND id=NEW.run_artifact_id;\nIF kind NOT IN ('production-run','vsc.production_run') THEN RAISE EXCEPTION 'execution must reference original run' USING ERRCODE='23514'; END IF;\nIF NEW.source_step_id IS NOT NULL THEN SELECT * INTO old_step FROM canvas_execution_steps WHERE project_id=NEW.project_id AND id=NEW.source_step_id; IF (NEW.version_id,NEW.node_key,NEW.shot_id,NEW.asset_id,NEW.spec_id) IS DISTINCT FROM (old_step.version_id,old_step.node_key,old_step.shot_id,old_step.asset_id,old_step.spec_id) THEN RAISE EXCEPTION 'fallback target changed' USING ERRCODE='23514'; END IF; END IF;\nRETURN NEW; END $$"

def downgrade():
    # An empty new domain may roll back. A single new fact prevents any DDL.
    op.execute('LOCK TABLE canvas_generation_inputs, creative_canvas_nodes, creative_canvas_edges, canvas_execution_steps, artifact_versions IN ACCESS EXCLUSIVE MODE')
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM canvas_generation_inputs) OR EXISTS(SELECT 1 FROM creative_canvas_nodes WHERE node_type NOT IN ('text','image','video','audio') OR spatial_scene_id IS NOT NULL OR spatial_version_id IS NOT NULL OR edit_workspace_id IS NOT NULL OR edit_version_id IS NOT NULL OR tool_draft_id IS NOT NULL) OR EXISTS(SELECT 1 FROM creative_canvas_edges WHERE port NOT IN ('prompt','reference','first_frame','last_frame','reference_image','reference_video','reference_audio')) OR EXISTS(SELECT 1 FROM canvas_execution_steps s JOIN artifact_versions a ON a.project_id=s.project_id AND a.id=s.run_artifact_id WHERE a.artifact_type='workbench-generation-run') THEN RAISE EXCEPTION 'canvas product history exists; restore a backup or forward repair instead' USING ERRCODE='23514'; END IF; END $$")
    op.execute(LEGACY_EXECUTION_LINKS)
    op.execute('DROP TABLE canvas_generation_inputs')
    op.execute('ALTER TABLE creative_canvas_edges DROP CONSTRAINT ck_creative_canvas_edges_port_type')
    op.execute(LEGACY_PORT_TYPE)
    op.execute('ALTER TABLE creative_canvas_nodes DROP CONSTRAINT ck_creative_canvas_nodes_type, DROP CONSTRAINT ck_creative_canvas_nodes_domain_shape')
    op.execute(LEGACY_NODE_TYPE)
    op.execute('ALTER TABLE creative_canvas_nodes DROP COLUMN tool_draft_id, DROP COLUMN edit_version_id, DROP COLUMN edit_workspace_id, DROP COLUMN spatial_version_id, DROP COLUMN spatial_scene_id')
