"""add_last_active_at_to_users

Revision ID: 7a8b3c1d4e2f
Revises: 6c52f40cb7c2
Create Date: 2026-07-12 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "7a8b3c1d4e2f"
down_revision = "6c52f40cb7c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable `last_active_at` column to the users table.

    The team router maintains this column opportunistically on every
    list call (debounced inside the route). The column is nullable
    so existing rows don't need a backfill value.
    """
    op.add_column(
        "users",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index helps the team router's "oldest active admin" query
    # (org_id, role, created_at) by keeping last_active_at lookups cheap
    # when we later add an activity-based ordering. Cheap to add now.
    op.create_index(
        "ix_users_last_active_at",
        "users",
        ["last_active_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_active_at", table_name="users")
    op.drop_column("users", "last_active_at")
