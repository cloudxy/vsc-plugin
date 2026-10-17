"""Script note scopes and per-hunk suggestions with accept/reject/undo decisions.

0007 adds scope binding for script notes (NULL keeps legacy notes as unattributed
history; no name-based migration guess) and the suggestion tables: a suggestion
pins the draft revision it was based on; accepting applies one field change only
while that revision is still current, and undo_accept reverts it only when no
further edit happened. DDL below is frozen for this revision.
"""
from alembic import op
revision = "0007_script_suggestions"
down_revision = "0006_script_workspace"
branch_labels = None
depends_on = None

DDL = [
    "ALTER TABLE script_notes ADD COLUMN scope_key TEXT",
    """CREATE TABLE script_suggestions (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	scope_key TEXT DEFAULT '' NOT NULL,
	base_draft_revision BIGINT NOT NULL,
	scene_id TEXT NOT NULL,
	line_id TEXT,
	kind TEXT NOT NULL,
	field TEXT DEFAULT 'text' NOT NULL,
	before_value TEXT,
	after_value TEXT NOT NULL,
	reason TEXT NOT NULL,
	origin TEXT DEFAULT 'manual' NOT NULL,
	author TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_script_suggestions PRIMARY KEY (project_id, id),
	CONSTRAINT ck_script_suggestions_kind CHECK (kind IN ('action','dialogue','silence')),
	CONSTRAINT ck_script_suggestions_field CHECK (field IN ('text','speaker')),
	CONSTRAINT fk_script_suggestions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_script_suggestions_project_scope_key ON script_suggestions (project_id, scope_key)",
    """CREATE TABLE script_suggestion_decisions (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	suggestion_id UUID NOT NULL,
	outcome TEXT NOT NULL,
	actor TEXT NOT NULL,
	reason TEXT NOT NULL,
	applied_revision BIGINT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_script_suggestion_decisions PRIMARY KEY (project_id, id),
	CONSTRAINT fk_script_suggestion_decisions_project_id_suggestion_id_70ed FOREIGN KEY(project_id, suggestion_id) REFERENCES script_suggestions (project_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_script_suggestion_decisions_outcome CHECK (outcome IN ('accept','reject','undo_accept')),
	CONSTRAINT fk_script_suggestion_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_script_suggestion_decisions_project_suggestion_id ON script_suggestion_decisions (project_id, suggestion_id)",
    "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_suggestions FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()",
    "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_suggestion_decisions FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    op.execute("DROP TRIGGER immutable_record ON script_suggestion_decisions")
    op.execute("DROP TRIGGER immutable_record ON script_suggestions")
    op.drop_table("script_suggestion_decisions")
    op.drop_index("ix_script_suggestions_project_scope_key", table_name="script_suggestions")
    op.drop_table("script_suggestions")
    op.execute("DROP INDEX ix_script_notes_project_scene_id")
    op.execute("ALTER TABLE script_notes DROP COLUMN scope_key")
