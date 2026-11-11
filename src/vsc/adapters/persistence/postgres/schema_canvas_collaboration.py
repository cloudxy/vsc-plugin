"""Canvas collaboration policy, ticket, active session, node lease lock, and immutable op log tables."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, String, Table,
    Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

CANVAS_COLLAB_IMMUTABLE = ("canvas_collaboration_decisions", "canvas_collab_ops")


def declare_canvas_collaboration(metadata, project_table, ref, uid, stamp):
    creative_canvases = metadata.tables["creative_canvases"]
    creative_canvases.append_column(
        Column("collaboration_enabled", Boolean, nullable=False, server_default=text("false"))
    )
    creative_canvases.append_column(
        Column("collab_seq", BigInteger, nullable=False, server_default=text("1"))
    )
    creative_canvases.append_column(
        Column("fencing_seq", BigInteger, nullable=False, server_default=text("0"))
    )
    creative_canvases.append_constraint(
        CheckConstraint("collab_seq >= 1 AND fencing_seq >= 0", name="collab_counters")
    )

    canvas_collaboration_decisions = project_table(
        "canvas_collaboration_decisions",
        *ref("creative_canvases", "canvas_id"),
        Column("collaboration_enabled", Boolean, nullable=False),
        Column("actor", Text, nullable=False),
        Column("identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("command_key", Text, nullable=False),
        stamp(),
        ForeignKeyConstraint(
            ["project_id", "command_key"],
            ["command_receipts.project_id", "command_receipts.idempotency_key"],
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("project_id", "command_key"),
        CheckConstraint("btrim(actor) <> '' AND btrim(command_key) <> ''", name="actor_command"),
    )
    Index(
        "ix_canvas_collab_decisions_canvas",
        canvas_collaboration_decisions.c.project_id,
        canvas_collaboration_decisions.c.canvas_id,
        canvas_collaboration_decisions.c.created_at,
    )

    canvas_collab_tickets = project_table(
        "canvas_collab_tickets",
        *ref("creative_canvases", "canvas_id"),
        Column("identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("actor", Text, nullable=False),
        Column("mode", Text, nullable=False),
        Column("page_session_id", Text, nullable=False),
        Column("token_sha256", String(64), nullable=False, unique=True),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("consumed_at", DateTime(timezone=True)),
        stamp(),
        UniqueConstraint("project_id", "canvas_id", "id"),
        CheckConstraint(
            "mode IN ('edit', 'presence') AND btrim(actor) <> '' AND btrim(page_session_id) <> ''",
            name="valid_ticket_mode",
        ),
    )
    Index(
        "ix_canvas_collab_tickets_canvas",
        canvas_collab_tickets.c.project_id,
        canvas_collab_tickets.c.canvas_id,
        canvas_collab_tickets.c.expires_at,
    )

    canvas_collab_sessions = project_table(
        "canvas_collab_sessions",
        uid("canvas_id", nullable=False),
        uid("ticket_id", nullable=False),
        Column("identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("actor", Text, nullable=False),
        Column("display_name", Text, nullable=False),
        Column("color", Text, nullable=False),
        Column("mode", Text, nullable=False),
        Column("page_session_id", Text, nullable=False),
        Column("sync_protocol", Integer, nullable=False, server_default=text("2")),
        Column("status", Text, nullable=False, server_default=text("'active'")),
        Column("kicked_reason", Text),
        Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        stamp(),
        ForeignKeyConstraint(
            ["project_id", "canvas_id"],
            ["creative_canvases.project_id", "creative_canvases.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "canvas_id", "ticket_id"],
            [
                "canvas_collab_tickets.project_id",
                "canvas_collab_tickets.canvas_id",
                "canvas_collab_tickets.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("project_id", "ticket_id"),
        UniqueConstraint("project_id", "canvas_id", "id"),
        CheckConstraint(
            "mode IN ('edit', 'presence') AND sync_protocol = 2 "
            "AND status IN ('active', 'kicked', 'closed') "
            "AND btrim(actor) <> '' AND btrim(page_session_id) <> '' AND btrim(color) <> ''",
            name="valid_collab_session",
        ),
    )
    Index(
        "ix_canvas_collab_sessions_active",
        canvas_collab_sessions.c.project_id,
        canvas_collab_sessions.c.canvas_id,
        canvas_collab_sessions.c.status,
    )

    canvas_node_locks = Table(
        "canvas_node_locks",
        metadata,
        Column("project_id", UUID(as_uuid=False), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        uid("canvas_id", nullable=False),
        Column("node_key", Text, nullable=False),
        uid("session_id", nullable=False),
        Column("identity_id", UUID(as_uuid=False), ForeignKey("access_identities.id", ondelete="RESTRICT")),
        Column("owner_actor", Text, nullable=False),
        Column("owner_name", Text, nullable=False),
        Column("color", Text, nullable=False),
        Column("intent", Text, nullable=False),
        Column("fencing_token", BigInteger, nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        PrimaryKeyConstraint("project_id", "canvas_id", "node_key"),
        ForeignKeyConstraint(
            ["project_id", "canvas_id"],
            ["creative_canvases.project_id", "creative_canvases.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "canvas_id", "session_id"],
            [
                "canvas_collab_sessions.project_id",
                "canvas_collab_sessions.canvas_id",
                "canvas_collab_sessions.id",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "btrim(node_key) <> '' AND intent IN ('edit', 'move', 'delete') "
            "AND fencing_token > 0 AND btrim(owner_actor) <> '' AND btrim(color) <> ''",
            name="valid_node_lock",
        ),
    )
    Index("ix_canvas_node_locks_session", canvas_node_locks.c.project_id, canvas_node_locks.c.session_id)
    Index(
        "ix_canvas_node_locks_expires",
        canvas_node_locks.c.project_id,
        canvas_node_locks.c.canvas_id,
        canvas_node_locks.c.expires_at,
    )

    canvas_collab_ops = project_table(
        "canvas_collab_ops",
        *ref("creative_canvases", "canvas_id"),
        Column("seq", BigInteger, nullable=False),
        uid("version_id", nullable=True),
        Column("op_kind", Text, nullable=False),
        Column("ops", JSONB, nullable=False),
        Column("actor", Text, nullable=False),
        uid("session_id", nullable=True),
        Column("client_op_id", Text),
        stamp(),
        ForeignKeyConstraint(
            ["project_id", "canvas_id", "version_id"],
            [
                "creative_canvas_versions.project_id",
                "creative_canvas_versions.canvas_id",
                "creative_canvas_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "canvas_id", "session_id"],
            [
                "canvas_collab_sessions.project_id",
                "canvas_collab_sessions.canvas_id",
                "canvas_collab_sessions.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("project_id", "canvas_id", "seq"),
        CheckConstraint(
            "seq >= 1 AND op_kind IN ('version_saved', 'collaboration_toggled', 'ops_batch', 'recovery_batch') "
            "AND jsonb_typeof(ops) = 'array' AND btrim(actor) <> ''",
            name="valid_collab_op",
        ),
    )
    return {
        "canvas_collaboration_decisions": canvas_collaboration_decisions,
        "canvas_collab_tickets": canvas_collab_tickets,
        "canvas_collab_sessions": canvas_collab_sessions,
        "canvas_node_locks": canvas_node_locks,
        "canvas_collab_ops": canvas_collab_ops,
    }
