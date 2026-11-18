"""Guide document tables: workspace-level operation manuals with nested sections and image refs."""
from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer,
    PrimaryKeyConstraint, Table, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID

GUIDE_TABLES = ("guide_boards", "guide_documents", "guide_sections", "guide_images", "guide_replies")


def install_guide_schema(metadata):
    boards = Table("guide_boards", metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("slug", Text, nullable=False),
        Column("title", Text, nullable=False),
        Column("summary", Text, nullable=False, server_default=text("''")),
        Column("sort_order", Integer, nullable=False, server_default=text("0")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("id"),
        UniqueConstraint("slug", name="uq_guide_boards_slug"))

    documents = Table("guide_documents", metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("slug", Text, nullable=False),
        Column("title", Text, nullable=False),
        Column("description", Text, nullable=False, server_default=text("''")),
        Column("cover_media", Text, nullable=False, server_default=text("''")),
        Column("board_id", UUID(as_uuid=False),
            ForeignKey("guide_boards.id", ondelete="SET NULL"), nullable=True),
        Column("version", Integer, nullable=False, server_default=text("1")),
        Column("created_by", Text, nullable=False, server_default=text("''")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("id"),
        UniqueConstraint("slug", name="uq_guide_documents_slug"))

    sections = Table("guide_sections", metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("document_id", UUID(as_uuid=False),
            ForeignKey("guide_documents.id", ondelete="CASCADE"), nullable=False),
        Column("parent_id", UUID(as_uuid=False),
            ForeignKey("guide_sections.id", ondelete="SET NULL"), nullable=True),
        Column("section_key", Text, nullable=False),
        Column("level", Integer, nullable=False, server_default=text("2")),
        Column("title", Text, nullable=False),
        Column("body", Text, nullable=False, server_default=text("''")),
        Column("callout", Text, nullable=False, server_default=text("''")),
        Column("sort_order", Integer, nullable=False, server_default=text("0")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("id"),
        UniqueConstraint("document_id", "section_key", name="uq_guide_sections_key"),
        Index("ix_guide_sections_doc_sort", "document_id", "sort_order"))

    images = Table("guide_images", metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("document_id", UUID(as_uuid=False),
            ForeignKey("guide_documents.id", ondelete="CASCADE"), nullable=False),
        Column("section_id", UUID(as_uuid=False),
            ForeignKey("guide_sections.id", ondelete="SET NULL"), nullable=True),
        Column("filename", Text, nullable=False),
        Column("alt_text", Text, nullable=False, server_default=text("''")),
        Column("media_url", Text, nullable=False),
        Column("sort_order", Integer, nullable=False, server_default=text("0")),
        Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        PrimaryKeyConstraint("id"),
        Index("ix_guide_images_doc_sort", "document_id", "sort_order"))

    replies = Table("guide_replies", metadata,
        Column("id", UUID(as_uuid=False), nullable=False),
        Column("document_id", UUID(as_uuid=False),
            ForeignKey("guide_documents.id", ondelete="CASCADE"), nullable=False),
        Column("body", Text, nullable=False),
        Column("author_label", Text, nullable=False, server_default=text("''")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("id"),
        Index("ix_guide_replies_doc", "document_id", "created_at"))

    return {"guide_boards": boards, "guide_documents": documents, "guide_sections": sections,
            "guide_images": images, "guide_replies": replies}
