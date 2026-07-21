"""add conversation metadata (title, archived_at, legacy_client_id, last_message_at)

PR4 introduces server-backed conversations. The ``title`` column is
filled fire-and-forget from the first user message (truncated, no
LLM call). ``archived_at`` is the soft-delete flag for the sidebar's
"archive" action. ``legacy_client_id`` is the client-side UUID the
FE used while conversations were localStorage-only; the import
migration dedups on (org_id, legacy_client_id) so re-running the
import is safe. ``last_message_at`` is denormalised for the
cursor-paginated /chat/conversations list — saving a message touches
both rows in the same transaction.

All four columns are nullable. Existing rows are backfilled to NULL
on the way up; the FE only sees a title once PR4 is shipped and the
titler runs on the next conversation.

Revision ID: 20260716_000004
Revises: 20260716_000003
Create Date: 2026-07-16 00:00:04.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260716_000004"
down_revision = "20260716_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("legacy_client_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_conversations_org_id_legacy_client_id"),
        "conversations",
        ["org_id", "legacy_client_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_conversations_org_last_message"),
        "conversations",
        ["org_id", "last_message_at"],
        unique=False,
    )

    # Backfill last_message_at from the messages table so the
    # conversation list query can use the new index without a slow
    # path on legacy data. One-shot UPDATE, no WHERE — this is a
    # small table.
    op.execute(
        """
        UPDATE conversations c
        SET last_message_at = (
            SELECT MAX(m.created_at)
            FROM messages m
            WHERE m.conversation_id = c.id
        )
        WHERE last_message_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_org_last_message"), table_name="conversations")
    op.drop_index(
        op.f("ix_conversations_org_id_legacy_client_id"),
        table_name="conversations",
    )
    op.drop_column("conversations", "last_message_at")
    op.drop_column("conversations", "legacy_client_id")
    op.drop_column("conversations", "archived_at")
    op.drop_column("conversations", "title")
