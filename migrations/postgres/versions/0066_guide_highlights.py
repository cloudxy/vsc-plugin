"""Guide highlight features: video cards introducing creation features on the plaza.

Each row is one feature video card (title, description, local video, optional
experience link) grouped by the platform version it shipped with. Rows are
seeded from captured feature-news data and hold no user state, so downgrade
only drops the table.
"""
from alembic import op

revision = "0066_guide_highlights"
down_revision = "0065_canvas_director_stage"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE guide_highlights (
	id UUID NOT NULL,
	slug TEXT NOT NULL,
	title TEXT NOT NULL,
	description TEXT NOT NULL DEFAULT '',
	video_media TEXT NOT NULL DEFAULT '',
	link_url TEXT NOT NULL DEFAULT '',
	button_text TEXT NOT NULL DEFAULT '',
	version_no TEXT NOT NULL DEFAULT '',
	online_date DATE,
	sort_order INTEGER NOT NULL DEFAULT 0,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_guide_highlights PRIMARY KEY (id),
	CONSTRAINT uq_guide_highlights_slug UNIQUE (slug)
)""")
    op.execute(
        "CREATE INDEX ix_guide_highlights_order ON guide_highlights (online_date DESC, sort_order)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_guide_highlights_order")
    op.execute("DROP TABLE IF EXISTS guide_highlights")
