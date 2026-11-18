"""Guide boards and replies: the plaza can hold more than one reading list.

Existing manuals stay on the 操作说明 board. Replies attach to a document and
start empty. Downgrade refuses once a reply exists.
"""
from alembic import op

revision = "0063_guide_boards"
down_revision = "0062_character_studio_generations"
branch_labels = None
depends_on = None

GUIDES_BOARD = "a0e8c3b2-7c1d-4f0a-9b6e-1d2c3b4a5e01"
PLAZA_BOARD = "b1f9d4c3-8d2e-4a1b-8c7f-2e3d4c5b6f02"


def upgrade():
    op.execute("""
CREATE TABLE guide_boards (
	id UUID NOT NULL,
	slug TEXT NOT NULL,
	title TEXT NOT NULL,
	summary TEXT NOT NULL DEFAULT '',
	sort_order INTEGER NOT NULL DEFAULT 0,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_guide_boards PRIMARY KEY (id),
	CONSTRAINT uq_guide_boards_slug UNIQUE (slug)
)""")
    op.execute("ALTER TABLE guide_documents ADD COLUMN board_id UUID")
    op.execute("""
ALTER TABLE guide_documents
	ADD CONSTRAINT fk_guide_documents_board_id_guide_boards
	FOREIGN KEY (board_id) REFERENCES guide_boards (id) ON DELETE SET NULL
""")
    op.execute("""
CREATE TABLE guide_replies (
	id UUID NOT NULL,
	document_id UUID NOT NULL REFERENCES guide_documents (id) ON DELETE CASCADE,
	body TEXT NOT NULL,
	author_label TEXT NOT NULL DEFAULT '',
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_guide_replies PRIMARY KEY (id)
)""")
    op.execute("CREATE INDEX ix_guide_replies_doc ON guide_replies (document_id, created_at)")
    op.execute(f"""
INSERT INTO guide_boards (id, slug, title, summary, sort_order) VALUES
('{GUIDES_BOARD}', 'guides', '操作说明', '已经收入的说明。打开一篇后按章节阅读，讨论接在正文下面。', 0),
('{PLAZA_BOARD}', 'plaza', '学习广场', '教程和讨论按主题放在这里。板块已经留好，有可保存的来源时再填入内容。', 1)
""")
    op.execute(f"""
UPDATE guide_documents SET board_id = '{GUIDES_BOARD}' WHERE board_id IS NULL
""")


def downgrade():
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM guide_replies) THEN
    RAISE EXCEPTION 'guide replies exist; use forward recovery' USING ERRCODE = '23514';
  END IF;
END $$""")
    op.execute("DROP INDEX IF EXISTS ix_guide_replies_doc")
    op.execute("DROP TABLE IF EXISTS guide_replies")
    op.execute("ALTER TABLE guide_documents DROP CONSTRAINT IF EXISTS fk_guide_documents_board_id_guide_boards")
    op.execute("ALTER TABLE guide_documents DROP COLUMN IF EXISTS board_id")
    op.execute("DROP TABLE IF EXISTS guide_boards")
