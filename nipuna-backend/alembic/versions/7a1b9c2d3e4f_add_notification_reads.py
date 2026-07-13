"""add notification_reads

Persist per-user read-state for synthetic notifications (e.g.
TEAM_INVITATION) that don't have an `alerts` row to attach `read_at`
to. Keyed by `(user_id, synthetic_id)` — `synthetic_id` is the
deterministic UUID the notifications router derives for each
(placeholder, org) pair (see `_SYNTHETIC_TEAM_INVITATION_NS` in
`app/routers/notifications.py`).

Revision ID: 7a1b9c2d3e4f
Revises: 13397d83e0a9
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7a1b9c2d3e4f"
down_revision = "13397d83e0a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "synthetic_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "synthetic_id", name="uq_notification_reads_user_synth"
        ),
    )
    op.create_index(
        "ix_notification_reads_user_id", "notification_reads", ["user_id"]
    )
    op.create_index(
        "ix_notification_reads_synthetic_id",
        "notification_reads",
        ["synthetic_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_reads_synthetic_id", table_name="notification_reads"
    )
    op.drop_index("ix_notification_reads_user_id", table_name="notification_reads")
    op.drop_table("notification_reads")
