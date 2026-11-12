"""Add canvas agent session state projections, message queue items, and custom camera motion templates."""
from alembic import op

revision = "0055_canvas_core_runtime"
down_revision = "0054_canvas_collaboration"
branch_labels = None
depends_on = None

SCHEMA_DDL = """CREATE TABLE canvas_agent_session_states (
	project_id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	title TEXT NOT NULL, 
	archived BOOLEAN DEFAULT false NOT NULL, 
	auto_approve BOOLEAN DEFAULT false NOT NULL, 
	updated_by TEXT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_session_states PRIMARY KEY (project_id, session_id), 
	CONSTRAINT fk_canvas_agent_session_states_project_id_session_id_ca_9fd3 FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT ck_canvas_agent_session_states_session_state_bounds CHECK (btrim(title) <> '' AND char_length(title) <= 200 AND btrim(updated_by) <> ''), 
	CONSTRAINT fk_canvas_agent_session_states_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
);

CREATE TABLE canvas_agent_queue_items (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	ordinal INTEGER NOT NULL, 
	message TEXT NOT NULL, 
	skill_id TEXT NOT NULL, 
	mode TEXT NOT NULL, 
	status TEXT DEFAULT 'queued' NOT NULL, 
	dispatched_turn_id UUID, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_queue_items PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_agent_queue_items_project_id_session_id_canva_e566 FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT fk_canvas_agent_queue_items_project_id_dispatched_turn__f1a8 FOREIGN KEY(project_id, dispatched_turn_id) REFERENCES canvas_agent_turns (project_id, id), 
	CONSTRAINT ck_canvas_agent_queue_items_queue_item_state CHECK (ordinal >= 0 AND btrim(message) <> '' AND char_length(message) <= 6000 AND btrim(skill_id) <> '' AND mode IN ('manual','auto_drafts') AND status IN ('queued','steered','editing','dispatched','cancelled') AND btrim(created_by) <> ''), 
	CONSTRAINT fk_canvas_agent_queue_items_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
);
CREATE INDEX ix_canvas_agent_queue_items_dispatched_turn_id ON canvas_agent_queue_items (project_id, dispatched_turn_id);
CREATE INDEX ix_canvas_agent_queue_items_session_id ON canvas_agent_queue_items (project_id, session_id);
CREATE INDEX ix_canvas_agent_queue_items_skill_id ON canvas_agent_queue_items (project_id, skill_id);

CREATE TABLE canvas_camera_motion_templates (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	name TEXT NOT NULL, 
	prompt_fragment TEXT NOT NULL, 
	horizontal_pan INTEGER DEFAULT 0 NOT NULL, 
	vertical_tilt INTEGER DEFAULT 0 NOT NULL, 
	zoom_delta INTEGER DEFAULT 0 NOT NULL, 
	roll_deg INTEGER DEFAULT 0 NOT NULL, 
	speed_preset TEXT DEFAULT 'normal' NOT NULL, 
	favorite BOOLEAN DEFAULT false NOT NULL, 
	archived BOOLEAN DEFAULT false NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_camera_motion_templates PRIMARY KEY (project_id, id), 
	CONSTRAINT ck_canvas_camera_motion_templates_camera_motion_bounds CHECK (btrim(name) <> '' AND char_length(name) <= 100 AND char_length(prompt_fragment) <= 1000 AND horizontal_pan BETWEEN -100 AND 100 AND vertical_tilt BETWEEN -100 AND 100 AND zoom_delta BETWEEN -100 AND 100 AND roll_deg BETWEEN -45 AND 45 AND speed_preset IN ('slow','normal','fast') AND btrim(created_by) <> ''), 
	CONSTRAINT fk_canvas_camera_motion_templates_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
);
CREATE INDEX ix_canvas_camera_motion_templates_active ON canvas_camera_motion_templates (project_id, archived, favorite);
"""

DOWNGRADE_DDL = """DO $$
BEGIN
	IF EXISTS (SELECT 1 FROM canvas_agent_session_states)
	   OR EXISTS (SELECT 1 FROM canvas_agent_queue_items)
	   OR EXISTS (SELECT 1 FROM canvas_camera_motion_templates) THEN
		RAISE EXCEPTION 'cannot downgrade 0055_canvas_core_runtime with recorded canvas runtime facts'
			USING ERRCODE = '23514';
	END IF;
END $$;

DROP TABLE canvas_camera_motion_templates;
DROP TABLE canvas_agent_queue_items;
DROP TABLE canvas_agent_session_states;
"""


def upgrade():
    op.execute(SCHEMA_DDL)


def downgrade():
    op.execute(DOWNGRADE_DDL)
