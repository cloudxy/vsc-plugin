"""Guide document tables: workspace manuals with nested sections and image refs.

Companion migration for schema_guide.install_guide_schema; completes the
creation-guide feature whose schema registration landed without a migration.
Downgrade refuses once any guide row exists.
"""
from alembic import op

revision = "0061_guide_documents"
down_revision = "0060_official_asset_classes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE guide_documents (
	id UUID NOT NULL,
	slug TEXT NOT NULL,
	title TEXT NOT NULL,
	description TEXT NOT NULL DEFAULT '',
	cover_media TEXT NOT NULL DEFAULT '',
	version INTEGER NOT NULL DEFAULT 1,
	created_by TEXT NOT NULL DEFAULT '',
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_guide_documents PRIMARY KEY (id),
	CONSTRAINT uq_guide_documents_slug UNIQUE (slug)
)""")
    op.execute("""
CREATE TABLE guide_sections (
	id UUID NOT NULL,
	document_id UUID NOT NULL REFERENCES guide_documents (id) ON DELETE CASCADE,
	parent_id UUID REFERENCES guide_sections (id) ON DELETE SET NULL,
	section_key TEXT NOT NULL,
	level INTEGER NOT NULL DEFAULT 2,
	title TEXT NOT NULL,
	body TEXT NOT NULL DEFAULT '',
	callout TEXT NOT NULL DEFAULT '',
	sort_order INTEGER NOT NULL DEFAULT 0,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_guide_sections PRIMARY KEY (id),
	CONSTRAINT uq_guide_sections_key UNIQUE (document_id, section_key)
)""")
    op.execute("CREATE INDEX ix_guide_sections_doc_sort ON guide_sections (document_id, sort_order)")
    op.execute("""
CREATE TABLE guide_images (
	id UUID NOT NULL,
	document_id UUID NOT NULL REFERENCES guide_documents (id) ON DELETE CASCADE,
	section_id UUID REFERENCES guide_sections (id) ON DELETE SET NULL,
	filename TEXT NOT NULL,
	alt_text TEXT NOT NULL DEFAULT '',
	media_url TEXT NOT NULL,
	sort_order INTEGER NOT NULL DEFAULT 0,
	metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
	CONSTRAINT pk_guide_images PRIMARY KEY (id)
)""")
    op.execute("CREATE INDEX ix_guide_images_doc_sort ON guide_images (document_id, sort_order)")


def downgrade():
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM guide_documents)
     OR EXISTS (SELECT 1 FROM guide_sections)
     OR EXISTS (SELECT 1 FROM guide_images) THEN
    RAISE EXCEPTION 'guide documents exist; use forward recovery' USING ERRCODE = '23514';
  END IF;
END $$""")
    op.execute("DROP INDEX IF EXISTS ix_guide_images_doc_sort")
    op.execute("DROP INDEX IF EXISTS ix_guide_sections_doc_sort")
    op.execute("DROP TABLE IF EXISTS guide_images")
    op.execute("DROP TABLE IF EXISTS guide_sections")
    op.execute("DROP TABLE IF EXISTS guide_documents")
