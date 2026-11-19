"""Canvas agent SSE events, session pointer, preferences and stream records.

Events are append-only. Session rows stay immutable; delete is a logical archive.
"""
from alembic import op

revision = "0064_canvas_agent_stream"
down_revision = "0063_guide_boards"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE canvas_agent_events (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	session_id UUID, 
	seq BIGINT NOT NULL, 
	kind TEXT NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_events PRIMARY KEY (project_id, id), 
	CONSTRAINT uq_canvas_agent_events_project_id_canvas_id_seq UNIQUE (project_id, canvas_id, seq), 
	CONSTRAINT fk_canvas_agent_events_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id), 
	CONSTRAINT fk_canvas_agent_events_project_id_session_id_canvas_age_3d6a FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT ck_canvas_agent_events_event_bounds CHECK (seq > 0 AND btrim(kind) <> '' AND char_length(kind) <= 80), 
	CONSTRAINT fk_canvas_agent_events_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
)""")
    op.execute("CREATE INDEX ix_canvas_agent_events_canvas_id ON canvas_agent_events (project_id, canvas_id)")
    op.execute("CREATE INDEX ix_canvas_agent_events_session_id ON canvas_agent_events (project_id, session_id)")
    op.execute("CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_agent_events FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()")
    op.execute("""
CREATE TABLE canvas_agent_stream_records (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	session_id UUID, 
	turn_id UUID, 
	record_kind TEXT NOT NULL, 
	status TEXT NOT NULL, 
	payload JSONB NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	updated_by TEXT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_stream_records PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_agent_stream_records_project_id_canvas_id_cre_10eb FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id), 
	CONSTRAINT fk_canvas_agent_stream_records_project_id_session_id_ca_28ec FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT fk_canvas_agent_stream_records_project_id_turn_id_canva_ba51 FOREIGN KEY(project_id, turn_id) REFERENCES canvas_agent_turns (project_id, id), 
	CONSTRAINT ck_canvas_agent_stream_records_record_bounds CHECK (record_kind IN ('question_batch','authorization','feedback','queue_context','action_receipt') AND btrim(status) <> '' AND char_length(status) <= 40 AND version >= 1 AND btrim(updated_by) <> ''), 
	CONSTRAINT fk_canvas_agent_stream_records_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
)""")
    op.execute("CREATE INDEX ix_canvas_agent_stream_records_turn_id ON canvas_agent_stream_records (project_id, turn_id)")
    op.execute("CREATE INDEX ix_canvas_agent_stream_records_canvas_id ON canvas_agent_stream_records (project_id, canvas_id)")
    op.execute("CREATE INDEX ix_canvas_agent_stream_records_session_id ON canvas_agent_stream_records (project_id, session_id)")
    op.execute("""
CREATE TABLE canvas_agent_session_prefs (
	project_id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	chat_model TEXT DEFAULT 'grok' NOT NULL, 
	reasoning_effort TEXT DEFAULT 'medium' NOT NULL, 
	selected_skill TEXT DEFAULT 'vsc-script' NOT NULL, 
	preferred_model_ids JSONB DEFAULT '[]'::jsonb NOT NULL, 
	tier_seen BOOLEAN DEFAULT false NOT NULL, 
	updated_by TEXT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_session_prefs PRIMARY KEY (project_id, session_id), 
	CONSTRAINT fk_canvas_agent_session_prefs_project_id_session_id_can_1736 FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT ck_canvas_agent_session_prefs_pref_bounds CHECK (chat_model IN ('grok','grok-fast') AND reasoning_effort IN ('low','medium','high') AND btrim(selected_skill) <> '' AND char_length(selected_skill) <= 80 AND btrim(updated_by) <> ''), 
	CONSTRAINT fk_canvas_agent_session_prefs_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
)""")
    op.execute("""
CREATE TABLE canvas_agent_current_sessions (
	project_id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	updated_by TEXT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_agent_current_sessions PRIMARY KEY (project_id, canvas_id), 
	CONSTRAINT fk_canvas_agent_current_sessions_project_id_canvas_id_c_da32 FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id), 
	CONSTRAINT fk_canvas_agent_current_sessions_project_id_session_id__abc6 FOREIGN KEY(project_id, session_id) REFERENCES canvas_agent_sessions (project_id, id), 
	CONSTRAINT ck_canvas_agent_current_sessions_current_bounds CHECK (btrim(updated_by) <> ''), 
	CONSTRAINT fk_canvas_agent_current_sessions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id)
)""")
    op.execute("CREATE INDEX ix_canvas_agent_current_sessions_session_id ON canvas_agent_current_sessions (project_id, session_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS canvas_agent_current_sessions")
    op.execute("DROP TABLE IF EXISTS canvas_agent_session_prefs")
    op.execute("DROP TABLE IF EXISTS canvas_agent_stream_records")
    op.execute("DROP TABLE IF EXISTS canvas_agent_events")
