"""Bind new notes to a real draft revision/hash and optional exact frozen version.

Historical notes remain NULL: earlier mutable draft bytes cannot be recovered
from command hashes. No inferred backfill or production data update is used.
"""
from alembic import op

revision = "0008_script_note_baselines"
down_revision = "0007_script_suggestions"
branch_labels = None
depends_on = None

DDL = [
    "ALTER TABLE script_notes ADD COLUMN base_draft_revision BIGINT",
    "ALTER TABLE script_notes ADD COLUMN base_content_sha256 VARCHAR(64)",
    "ALTER TABLE script_notes ADD COLUMN base_artifact_id UUID",
    """ALTER TABLE script_notes ADD CONSTRAINT fk_script_notes_base_artifact
       FOREIGN KEY(project_id, base_artifact_id) REFERENCES artifact_versions(project_id, id) ON DELETE RESTRICT""",
    """ALTER TABLE script_notes ADD CONSTRAINT ck_script_notes_baseline CHECK (
       (base_draft_revision IS NULL AND base_content_sha256 IS NULL AND base_artifact_id IS NULL) OR
       (base_draft_revision IS NOT NULL AND base_draft_revision >= 1 AND base_content_sha256 IS NOT NULL AND base_content_sha256 ~ '^[0-9a-f]{64}$'))""",
    "CREATE INDEX ix_script_notes_project_base_artifact_id ON script_notes (project_id, base_artifact_id)",
]


def upgrade():
    for sql in DDL:
        op.execute(sql)


def downgrade():
    op.drop_index("ix_script_notes_project_base_artifact_id", table_name="script_notes")
    op.drop_constraint(op.f("fk_script_notes_base_artifact"), "script_notes", type_="foreignkey")
    op.drop_constraint(op.f("ck_script_notes_baseline"), "script_notes", type_="check")
    op.drop_column("script_notes", "base_artifact_id")
    op.drop_column("script_notes", "base_content_sha256")
    op.drop_column("script_notes", "base_draft_revision")
