"""Recoverable canvas visibility under the original management authority."""
from alembic import op

revision = "0052_canvas_lifecycle"
down_revision = "0051_project_cover_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE management_canvas_states (
    project_id UUID NOT NULL,
    id UUID NOT NULL,
    canvas_id UUID NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_management_canvas_states PRIMARY KEY (project_id, id),
    CONSTRAINT fk_management_canvas_states_project_id_canvas_id_creati_26ca
        FOREIGN KEY (project_id, canvas_id) REFERENCES creative_canvases (project_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_management_canvas_states_state CHECK (state IN ('active','trashed')),
    CONSTRAINT uq_management_canvas_states_project_id_canvas_id UNIQUE (project_id, canvas_id),
    CONSTRAINT fk_management_canvas_states_project_id_projects
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE RESTRICT
)
""")


def downgrade():
    # An old application would expose recycled canvases. Keep the lifecycle facts
    # and require explicit recovery planning after the feature has been used.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM management_canvas_states) THEN
            RAISE EXCEPTION 'canvas lifecycle facts exist; preserve them before application rollback';
        END IF;
    END $$""")
    op.drop_table("management_canvas_states")
