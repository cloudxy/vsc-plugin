"""Add canvas collaboration policy, one-time tickets, active sessions, node lease locks, and immutable ops."""
from alembic import op

revision = "0054_canvas_collaboration"
down_revision = "0053_canvas_direct_copies"
branch_labels = None
depends_on = None

SCHEMA_DDL = """ALTER TABLE creative_canvases
	ADD COLUMN collaboration_enabled BOOLEAN DEFAULT false NOT NULL,
	ADD COLUMN collab_seq BIGINT DEFAULT 1 NOT NULL,
	ADD COLUMN fencing_seq BIGINT DEFAULT 0 NOT NULL,
	ADD CONSTRAINT ck_creative_canvases_collab_counters CHECK (collab_seq >= 1 AND fencing_seq >= 0);

CREATE TABLE canvas_collaboration_decisions (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	collaboration_enabled BOOLEAN NOT NULL, 
	actor TEXT NOT NULL, 
	identity_id UUID, 
	command_key TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_collaboration_decisions PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_collaboration_decisions_project_id_canvas_id__4bb5 FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collaboration_decisions_project_id_command_ke_167c FOREIGN KEY(project_id, command_key) REFERENCES command_receipts (project_id, idempotency_key) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT uq_canvas_collaboration_decisions_project_id_command_key UNIQUE (project_id, command_key), 
	CONSTRAINT ck_canvas_collaboration_decisions_actor_command CHECK (btrim(actor) <> '' AND btrim(command_key) <> ''), 
	CONSTRAINT fk_canvas_collaboration_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collaboration_decisions_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT
);
CREATE INDEX ix_canvas_collab_decisions_canvas ON canvas_collaboration_decisions (project_id, canvas_id, created_at);

CREATE TABLE canvas_collab_tickets (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	identity_id UUID, 
	actor TEXT NOT NULL, 
	mode TEXT NOT NULL, 
	page_session_id TEXT NOT NULL, 
	token_sha256 VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_collab_tickets PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_collab_tickets_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_canvas_collab_tickets_project_id_canvas_id_id UNIQUE (project_id, canvas_id, id), 
	CONSTRAINT ck_canvas_collab_tickets_valid_ticket_mode CHECK (mode IN ('edit', 'presence') AND btrim(actor) <> '' AND btrim(page_session_id) <> ''), 
	CONSTRAINT fk_canvas_collab_tickets_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collab_tickets_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_canvas_collab_tickets_token_sha256 UNIQUE (token_sha256), 
	CONSTRAINT ck_canvas_collab_tickets_token_sha256_format CHECK (token_sha256 IS NULL OR token_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX ix_canvas_collab_tickets_canvas ON canvas_collab_tickets (project_id, canvas_id, expires_at);

CREATE TABLE canvas_collab_sessions (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	ticket_id UUID NOT NULL, 
	identity_id UUID, 
	actor TEXT NOT NULL, 
	display_name TEXT NOT NULL, 
	color TEXT NOT NULL, 
	mode TEXT NOT NULL, 
	page_session_id TEXT NOT NULL, 
	sync_protocol INTEGER DEFAULT 2 NOT NULL, 
	status TEXT DEFAULT 'active' NOT NULL, 
	kicked_reason TEXT, 
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_collab_sessions PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_collab_sessions_project_id_canvas_id_creative_3ae5 FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collab_sessions_project_id_canvas_id_ticket_i_905b FOREIGN KEY(project_id, canvas_id, ticket_id) REFERENCES canvas_collab_tickets (project_id, canvas_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_canvas_collab_sessions_project_id_ticket_id UNIQUE (project_id, ticket_id), 
	CONSTRAINT uq_canvas_collab_sessions_project_id_canvas_id_id UNIQUE (project_id, canvas_id, id), 
	CONSTRAINT ck_canvas_collab_sessions_valid_collab_session CHECK (mode IN ('edit', 'presence') AND sync_protocol = 2 AND status IN ('active', 'kicked', 'closed') AND btrim(actor) <> '' AND btrim(page_session_id) <> '' AND btrim(color) <> ''), 
	CONSTRAINT fk_canvas_collab_sessions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collab_sessions_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT
);
CREATE INDEX ix_canvas_collab_sessions_active ON canvas_collab_sessions (project_id, canvas_id, status);

CREATE TABLE canvas_node_locks (
	project_id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	node_key TEXT NOT NULL, 
	session_id UUID NOT NULL, 
	identity_id UUID, 
	owner_actor TEXT NOT NULL, 
	owner_name TEXT NOT NULL, 
	color TEXT NOT NULL, 
	intent TEXT NOT NULL, 
	fencing_token BIGINT NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_node_locks PRIMARY KEY (project_id, canvas_id, node_key), 
	CONSTRAINT fk_canvas_node_locks_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE CASCADE, 
	CONSTRAINT fk_canvas_node_locks_project_id_canvas_id_session_id_ca_e6a8 FOREIGN KEY(project_id, canvas_id, session_id) REFERENCES canvas_collab_sessions (project_id, canvas_id, id) ON DELETE CASCADE, 
	CONSTRAINT ck_canvas_node_locks_valid_node_lock CHECK (btrim(node_key) <> '' AND intent IN ('edit', 'move', 'delete') AND fencing_token > 0 AND btrim(owner_actor) <> '' AND btrim(color) <> ''), 
	CONSTRAINT fk_canvas_node_locks_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_node_locks_identity_id_access_identities FOREIGN KEY(identity_id) REFERENCES access_identities (id) ON DELETE RESTRICT
);
CREATE INDEX ix_canvas_node_locks_expires ON canvas_node_locks (project_id, canvas_id, expires_at);
CREATE INDEX ix_canvas_node_locks_session ON canvas_node_locks (project_id, session_id);

CREATE TABLE canvas_collab_ops (
	project_id UUID NOT NULL, 
	id UUID NOT NULL, 
	canvas_id UUID NOT NULL, 
	seq BIGINT NOT NULL, 
	version_id UUID, 
	op_kind TEXT NOT NULL, 
	ops JSONB NOT NULL, 
	actor TEXT NOT NULL, 
	session_id UUID, 
	client_op_id TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_canvas_collab_ops PRIMARY KEY (project_id, id), 
	CONSTRAINT fk_canvas_collab_ops_project_id_canvas_id_creative_canvases FOREIGN KEY(project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collab_ops_project_id_canvas_id_version_id_cr_5920 FOREIGN KEY(project_id, canvas_id, version_id) REFERENCES creative_canvas_versions (project_id, canvas_id, id) ON DELETE RESTRICT, 
	CONSTRAINT fk_canvas_collab_ops_project_id_canvas_id_session_id_ca_b754 FOREIGN KEY(project_id, canvas_id, session_id) REFERENCES canvas_collab_sessions (project_id, canvas_id, id) ON DELETE RESTRICT, 
	CONSTRAINT uq_canvas_collab_ops_project_id_canvas_id_seq UNIQUE (project_id, canvas_id, seq), 
	CONSTRAINT ck_canvas_collab_ops_valid_collab_op CHECK (seq >= 1 AND op_kind IN ('version_saved', 'collaboration_toggled', 'ops_batch', 'recovery_batch') AND jsonb_typeof(ops) = 'array' AND btrim(actor) <> ''), 
	CONSTRAINT fk_canvas_collab_ops_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);

CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_collaboration_decisions
	FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON canvas_collab_ops
	FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation();

CREATE OR REPLACE FUNCTION vsc_canvas_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-'current_version_id'-'collaboration_enabled'-'collab_seq'-'fencing_seq')
     IS DISTINCT FROM (to_jsonb(OLD)-'current_version_id'-'collaboration_enabled'-'collab_seq'-'fencing_seq') THEN
    RAISE EXCEPTION 'canvas identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
"""

DOWNGRADE_DDL = """DO $$
BEGIN
	IF EXISTS (SELECT 1 FROM canvas_collaboration_decisions)
	   OR EXISTS (SELECT 1 FROM canvas_collab_ops WHERE op_kind <> 'version_saved')
	   OR EXISTS (SELECT 1 FROM creative_canvases WHERE collaboration_enabled = true) THEN
		RAISE EXCEPTION 'cannot downgrade 0054_canvas_collaboration with recorded collaboration facts'
			USING ERRCODE = '23514';
	END IF;
END $$;

DROP TRIGGER IF EXISTS immutable_record ON canvas_collab_ops;
DROP TRIGGER IF EXISTS immutable_record ON canvas_collaboration_decisions;
DROP TABLE canvas_collab_ops;
DROP TABLE canvas_node_locks;
DROP TABLE canvas_collab_sessions;
DROP TABLE canvas_collab_tickets;
DROP TABLE canvas_collaboration_decisions;
ALTER TABLE creative_canvases
	DROP CONSTRAINT ck_creative_canvases_collab_counters,
	DROP COLUMN fencing_seq,
	DROP COLUMN collab_seq,
	DROP COLUMN collaboration_enabled;

CREATE OR REPLACE FUNCTION vsc_canvas_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-'current_version_id') IS DISTINCT FROM (to_jsonb(OLD)-'current_version_id') THEN
    RAISE EXCEPTION 'canvas identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade():
    op.execute(SCHEMA_DDL)


def downgrade():
    op.execute(DOWNGRADE_DDL)
