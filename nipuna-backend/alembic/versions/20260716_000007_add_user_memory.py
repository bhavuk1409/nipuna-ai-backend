"""add user_memories table

Per-user, per-org key-value facts the AI extracts from conversations
("user is a CFO at Acme", "user prefers INR", "user works with
Tally"). The PR1 read path doesn't use this table — the manager /
extractor land in PR4. PR1 ships the schema and a no-op manager
stub so PR4 can layer on without a second migration.

The ``value`` column stays ``TEXT`` for the existing app to read
without disruption; ``value_encrypted`` is the Fernet-encrypted
mirror (``app/utils/encryption.py``) for the PII-safe read path.
A follow-up migration in PR2 will make the encrypted column the
source of truth and drop the plaintext column.

Revision ID: 20260716_000007
Revises: 20260716_000006
Create Date: 2026-07-16 00:00:07.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260716_000007"
down_revision = "20260716_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "confidence",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("70"),
        ),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_user_memories_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_user_memories_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversations.id"],
            name=op.f("fk_user_memories_source_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_memories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_memories")),
        sa.UniqueConstraint("user_id", "key", name="uq_user_memories_user_key"),
    )
    op.create_index(
        op.f("ix_user_memories_user_org"),
        "user_memories",
        ["user_id", "org_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_memories_user_active"),
        "user_memories",
        ["user_id", "archived"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_memories_user_active"), table_name="user_memories")
    op.drop_index(op.f("ix_user_memories_user_org"), table_name="user_memories")
    op.drop_table("user_memories")
