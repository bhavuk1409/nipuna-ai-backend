"""add tool_call_audit table

Dedicated audit log for AI tool invocations. Distinct from
``audit_log`` (which is for human-driven org events like
``workspace.deleted``) because:

  - access pattern is "show me every tool call between t1 and t2
    for this org" — high volume, high write rate
  - per-tool and per-user timelines want their own indexes
  - the ``params_hash`` + ``result_hash`` columns are specific to
    tool-call semantics and don't belong on the human-event log

Every ``node_execute_tools`` invocation writes one row. The unique
partial index on ``(message_id, tool_name, tool_action, params_hash)``
makes ``record_tool_call`` idempotent so a retry of the same
turn doesn't double-write the audit.

Revision ID: 20260716_000008
Revises: 20260716_000007
Create Date: 2026-07-16 00:00:08.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260716_000008"
down_revision = "20260716_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_call_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("tool_action", sa.String(length=128), nullable=False),
        sa.Column("params_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_tool_call_audit_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_tool_call_audit_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_tool_call_audit_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tool_call_audit_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_call_audit")),
    )
    op.create_index(
        op.f("ix_tool_call_audit_org_created"),
        "tool_call_audit",
        ["org_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_call_audit_tool_created"),
        "tool_call_audit",
        ["tool_name", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_call_audit_user_created"),
        "tool_call_audit",
        ["user_id", "created_at"],
        unique=False,
    )
    # Idempotency on the (message_id, tool_name, tool_action, params_hash)
    # tuple. Partial: message_id is NULL for some pre-persist tool
    # calls (credit-deduct rows) and we don't want the unique to
    # collide there.
    op.create_index(
        op.f("uq_tool_call_audit_idempotency"),
        "tool_call_audit",
        ["message_id", "tool_name", "tool_action", "params_hash"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("uq_tool_call_audit_idempotency"),
        table_name="tool_call_audit",
    )
    op.drop_index(
        op.f("ix_tool_call_audit_user_created"),
        table_name="tool_call_audit",
    )
    op.drop_index(
        op.f("ix_tool_call_audit_tool_created"),
        table_name="tool_call_audit",
    )
    op.drop_index(
        op.f("ix_tool_call_audit_org_created"),
        table_name="tool_call_audit",
    )
    op.drop_table("tool_call_audit")
