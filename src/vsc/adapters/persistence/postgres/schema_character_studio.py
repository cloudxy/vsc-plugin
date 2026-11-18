"""Workspace AI character studio generation catalog: file paths, prompts and provenance.

Generated image bytes and prompt sidecar files live on disk under
``assets/ai-generate-image/<YYYY-MM-DD>/``; PostgreSQL stores relative paths,
checksums, exact model/method provenance, prompts and non-base64 snapshots.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, Index,
    PrimaryKeyConstraint, Table, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

CHARACTER_STUDIO_TABLES = ("character_studio_generations",)


def install_character_studio_schema(metadata):
    generations = Table(
        "character_studio_generations",
        metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("image_path", Text, nullable=False),
        Column("prompt_path", Text, nullable=False, server_default=text("''")),
        Column("sha256", Text, nullable=False),
        Column("mime_type", Text, nullable=False),
        Column("size_bytes", BigInteger, nullable=False),
        Column("provider", Text, nullable=False),
        Column("model", Text, nullable=False),
        Column("upstream_model", Text, nullable=False, server_default=text("''")),
        Column("method", Text, nullable=False),
        Column("method_label", Text, nullable=False),
        Column("endpoint", Text, nullable=False, server_default=text("''")),
        Column("prompt", Text, nullable=False, server_default=text("''")),
        Column("recipe_summary", Text, nullable=False, server_default=text("''")),
        Column("snapshot", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("publication", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("created_by", Text, nullable=False, server_default=text("''")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("id"),
        UniqueConstraint("image_path", name="uq_character_studio_generations_image_path"),
        CheckConstraint(
            "length(btrim(image_path)) BETWEEN 1 AND 512 "
            "AND image_path !~* '^data:' "
            "AND image_path !~ '^/' "
            "AND position('..' in image_path) = 0",
            name="image_path_relative_no_base64",
        ),
        CheckConstraint(
            "prompt_path = '' OR (length(btrim(prompt_path)) BETWEEN 1 AND 512 "
            "AND prompt_path !~* '^data:' "
            "AND prompt_path !~ '^/' "
            "AND position('..' in prompt_path) = 0)",
            name="prompt_path_relative_no_base64",
        ),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("length(btrim(provider)) BETWEEN 1 AND 64", name="provider_nonempty"),
        CheckConstraint("length(btrim(model)) BETWEEN 1 AND 160", name="model_nonempty"),
        CheckConstraint("length(btrim(method)) BETWEEN 1 AND 120", name="method_nonempty"),
        CheckConstraint("snapshot::text !~* 'data:image/'", name="snapshot_no_base64"),
        CheckConstraint("publication::text !~* 'data:image/'", name="publication_no_base64"),
        Index("ix_character_studio_generations_created_at", "created_at", "id"),
        Index("ix_character_studio_generations_model_method", "provider", "model", "method"),
    )
    return {"character_studio_generations": generations}
