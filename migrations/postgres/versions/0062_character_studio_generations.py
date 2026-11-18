"""Character studio generation catalog: relative file paths, prompts and exact provenance.

Stores relative image/prompt paths under ``assets/ai-generate-image/<YYYY-MM-DD>/``
with database-level checks forbidding inline Base64 image data.
Downgrade refuses once any generation row exists.
"""
from alembic import op

revision = "0062_character_studio_generations"
down_revision = "0061_guide_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    op.execute("""
CREATE TABLE character_studio_generations (
	id UUID NOT NULL,
	image_path TEXT NOT NULL,
	prompt_path TEXT NOT NULL DEFAULT '',
	sha256 TEXT NOT NULL,
	mime_type TEXT NOT NULL,
	size_bytes BIGINT NOT NULL,
	provider TEXT NOT NULL,
	model TEXT NOT NULL,
	upstream_model TEXT NOT NULL DEFAULT '',
	method TEXT NOT NULL,
	method_label TEXT NOT NULL,
	endpoint TEXT NOT NULL DEFAULT '',
	prompt TEXT NOT NULL DEFAULT '',
	recipe_summary TEXT NOT NULL DEFAULT '',
	snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
	publication JSONB NOT NULL DEFAULT '{}'::jsonb,
	created_by TEXT NOT NULL DEFAULT '',
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_character_studio_generations PRIMARY KEY (id),
	CONSTRAINT uq_character_studio_generations_image_path UNIQUE (image_path),
	CONSTRAINT ck_character_studio_generations_image_path_relative_no_base64 CHECK (length(btrim(image_path)) BETWEEN 1 AND 512 AND image_path !~* '^data:' AND image_path !~ '^/' AND position('..' in image_path) = 0),
	CONSTRAINT ck_character_studio_generations_prompt_path_relative_no_base64 CHECK (prompt_path = '' OR (length(btrim(prompt_path)) BETWEEN 1 AND 512 AND prompt_path !~* '^data:' AND prompt_path !~ '^/' AND position('..' in prompt_path) = 0)),
	CONSTRAINT ck_character_studio_generations_size_bytes_positive CHECK (size_bytes > 0),
	CONSTRAINT ck_character_studio_generations_provider_nonempty CHECK (length(btrim(provider)) BETWEEN 1 AND 64),
	CONSTRAINT ck_character_studio_generations_model_nonempty CHECK (length(btrim(model)) BETWEEN 1 AND 160),
	CONSTRAINT ck_character_studio_generations_method_nonempty CHECK (length(btrim(method)) BETWEEN 1 AND 120),
	CONSTRAINT ck_character_studio_generations_snapshot_no_base64 CHECK (snapshot::text !~* 'data:image/'),
	CONSTRAINT ck_character_studio_generations_publication_no_base64 CHECK (publication::text !~* 'data:image/'),
	CONSTRAINT ck_character_studio_generations_sha256_format CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
)""")
    op.execute("CREATE INDEX ix_character_studio_generations_created_at ON character_studio_generations (created_at, id)")
    op.execute("CREATE INDEX ix_character_studio_generations_model_method ON character_studio_generations (provider, model, method)")


def downgrade():
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM character_studio_generations) THEN
    RAISE EXCEPTION 'character studio generations exist; use forward recovery' USING ERRCODE = '23514';
  END IF;
END $$""")
    op.execute("DROP INDEX IF EXISTS ix_character_studio_generations_model_method")
    op.execute("DROP INDEX IF EXISTS ix_character_studio_generations_created_at")
    op.execute("DROP TABLE IF EXISTS character_studio_generations")
