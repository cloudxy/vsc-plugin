"""Director-stage canvas nodes, panorama and capture ports, local recognition records."""
from alembic import op

revision = "0065_canvas_director_stage"
down_revision = "0064_canvas_agent_stream"
branch_labels = None
depends_on = None

NODE_TYPE = (
    "ALTER TABLE creative_canvas_nodes ADD CONSTRAINT ck_creative_canvas_nodes_type CHECK "
    "(node_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing','director-stage','3d-preview'))"
)
PORT_TYPE = (
    "ALTER TABLE creative_canvas_edges ADD CONSTRAINT ck_creative_canvas_edges_port_type CHECK "
    "((port = 'prompt' AND source_type = 'text' AND target_type IN ('image','video','audio','spatial','director','music_mix','processing')) OR "
    "(port = 'reference' AND source_type = 'image' AND target_type IN ('image','spatial','director')) OR "
    "(port IN ('first_frame','last_frame','reference_image') AND source_type = 'image' AND target_type = 'video') OR "
    "(port = 'reference_video' AND source_type = 'video' AND target_type = 'video') OR "
    "(port = 'reference_audio' AND source_type = 'audio' AND target_type IN ('video','audio')) OR "
    "(port='visual' AND source_type IN ('image','video') AND target_type='edit') OR "
    "(port='sound' AND source_type='audio' AND target_type IN ('edit','music_mix')) OR "
    "(port='source_video' AND source_type='video' AND target_type IN ('music_mix','processing')) OR "
    "(port='derived_from' AND source_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing','director-stage','3d-preview') AND target_type IN ('text','image','video','audio')) OR "
    "(port = 'panorama_image' AND source_type = 'image' AND target_type = 'director-stage') OR "
    "(port = 'directorStageCapture' AND source_type IN ('director-stage','director') AND target_type = 'image'))"
)
PREVIOUS_NODE_TYPE = (
    "ALTER TABLE creative_canvas_nodes ADD CONSTRAINT ck_creative_canvas_nodes_type CHECK "
    "(node_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing'))"
)
PREVIOUS_PORT_TYPE = (
    "ALTER TABLE creative_canvas_edges ADD CONSTRAINT ck_creative_canvas_edges_port_type CHECK "
    "((port = 'prompt' AND source_type = 'text' AND target_type IN ('image','video','audio','spatial','director','music_mix','processing')) OR "
    "(port = 'reference' AND source_type = 'image' AND target_type IN ('image','spatial','director')) OR "
    "(port IN ('first_frame','last_frame','reference_image') AND source_type = 'image' AND target_type = 'video') OR "
    "(port = 'reference_video' AND source_type = 'video' AND target_type = 'video') OR "
    "(port = 'reference_audio' AND source_type = 'audio' AND target_type IN ('video','audio')) OR "
    "(port='visual' AND source_type IN ('image','video') AND target_type='edit') OR "
    "(port='sound' AND source_type='audio' AND target_type IN ('edit','music_mix')) OR "
    "(port='source_video' AND source_type='video' AND target_type IN ('music_mix','processing')) OR "
    "(port='derived_from' AND source_type IN ('text','image','video','audio','spatial','director','edit','music_mix','processing') AND target_type IN ('text','image','video','audio')))"
)


def upgrade():
    op.execute("ALTER TABLE creative_canvas_nodes DROP CONSTRAINT ck_creative_canvas_nodes_type")
    op.execute(NODE_TYPE)
    op.execute("ALTER TABLE creative_canvas_edges DROP CONSTRAINT ck_creative_canvas_edges_port_type")
    op.execute(PORT_TYPE)
    op.execute("""
CREATE TABLE canvas_director_records (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	node_key TEXT NOT NULL, 
	kind TEXT NOT NULL, 
	status INTEGER NOT NULL, 
	media_id UUID, 
	result JSONB NOT NULL, 
	deleted BOOLEAN DEFAULT false NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_director_records PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_director_records_project_id_canvas_id_creativ_433c FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id), 
	CONSTRAINT fk_canvas_director_records_project_id_media_id_media_items FOREIGN KEY(project_id, media_id) REFERENCES media_items (project_id, id), 
	CONSTRAINT ck_canvas_director_records_kind CHECK (kind IN ('recognize','panorama')), 
	CONSTRAINT ck_canvas_director_records_status CHECK (status IN (2, 3)), 
	CONSTRAINT ck_canvas_director_records_node_key CHECK (char_length(node_key) BETWEEN 1 AND 100), 
	CONSTRAINT fk_canvas_director_records_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""")
    op.execute("CREATE INDEX ix_canvas_director_records_canvas_id ON canvas_director_records (project_id, canvas_id, kind)")


def downgrade():
    op.execute("ALTER TABLE creative_canvas_nodes DROP CONSTRAINT ck_creative_canvas_nodes_type")
    op.execute(PREVIOUS_NODE_TYPE)
    op.execute("ALTER TABLE creative_canvas_edges DROP CONSTRAINT ck_creative_canvas_edges_port_type")
    op.execute(PREVIOUS_PORT_TYPE)
    op.execute("DROP TABLE IF EXISTS canvas_director_records")
