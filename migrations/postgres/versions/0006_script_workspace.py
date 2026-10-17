"""Script working copy, anchored notes and note decisions for human confirmation.

script_drafts is the only mutable project table: autosave updates content in place
and never creates artifact versions or project revisions; freezing happens through
the existing immutable artifact system on submit. Notes and note decisions stay
append-only. DDL below is frozen for this revision and never imports live models.
"""
from alembic import op
revision = "0006_script_workspace"
down_revision = "0005_creative_relations"
branch_labels = None
depends_on = None

DDL = [
    """CREATE TABLE script_drafts (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	scope_key TEXT DEFAULT '' NOT NULL,
	content JSONB NOT NULL,
	base_artifact_id UUID,
	submitted_artifact_id UUID,
	draft_revision BIGINT DEFAULT '1' NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_script_drafts PRIMARY KEY (project_id, id),
	CONSTRAINT fk_script_drafts_project_id_base_artifact_id_artifact_versions FOREIGN KEY(project_id, base_artifact_id) REFERENCES artifact_versions (project_id, id),
	CONSTRAINT fk_script_drafts_project_id_submitted_artifact_id_artif_9629 FOREIGN KEY(project_id, submitted_artifact_id) REFERENCES artifact_versions (project_id, id),
	CONSTRAINT ck_script_drafts_draft_revision CHECK (draft_revision >= 1),
	CONSTRAINT uq_script_drafts_project_id_scope_key UNIQUE (project_id, scope_key),
	CONSTRAINT fk_script_drafts_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE script_notes (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	scene_id TEXT NOT NULL,
	line_id TEXT,
	body TEXT NOT NULL,
	author TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_script_notes PRIMARY KEY (project_id, id),
	CONSTRAINT fk_script_notes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_script_notes_project_scene_id ON script_notes (project_id, scene_id)",
    """CREATE TABLE script_note_decisions (
	project_id UUID NOT NULL,
	id UUID NOT NULL,
	note_id UUID NOT NULL,
	outcome TEXT NOT NULL,
	actor TEXT NOT NULL,
	reason TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_script_note_decisions PRIMARY KEY (project_id, id),
	CONSTRAINT fk_script_note_decisions_project_id_note_id_script_notes FOREIGN KEY(project_id, note_id) REFERENCES script_notes (project_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_script_note_decisions_outcome CHECK (outcome IN ('resolve','dismiss','reopen')),
	CONSTRAINT fk_script_note_decisions_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_script_note_decisions_project_note_id ON script_note_decisions (project_id, note_id)",
    "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_notes FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()",
    "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON script_note_decisions FOR EACH ROW EXECUTE FUNCTION vsc_reject_mutation()",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    op.execute("DROP TRIGGER immutable_record ON script_note_decisions")
    op.execute("DROP TRIGGER immutable_record ON script_notes")
    op.drop_table("script_note_decisions")
    op.drop_index("ix_script_notes_project_scene_id", table_name="script_notes")
    op.drop_table("script_notes")
    op.drop_table("script_drafts")
