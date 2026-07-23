"""add org industry team_size and invite token fields

Revision ID: 20260723_000001
Revises: 20260716_000009_add_vector_document_metadata
Create Date: 2026-07-23

Adds:
  organizations:
    - industry       VARCHAR(120) NULLABLE
    - team_size      VARCHAR(50)  NULLABLE

  organization_members:
    - invite_token           VARCHAR(64) NULLABLE UNIQUE
    - invite_expires_at      TIMESTAMPTZ NULLABLE
    - invited_by_user_id     UUID NULLABLE FK -> users.id ON DELETE SET NULL
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260723_000001"
down_revision = "20260716_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # organizations
    op.add_column(
        "organizations",
        sa.Column("industry", sa.String(120), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("team_size", sa.String(50), nullable=True),
    )

    # organization_members
    op.add_column(
        "organization_members",
        sa.Column("invite_token", sa.String(64), nullable=True),
    )
    op.add_column(
        "organization_members",
        sa.Column(
            "invite_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "organization_members",
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_organization_members_invite_token",
        "organization_members",
        ["invite_token"],
        unique=True,
    )
    op.create_index(
        "ix_organization_members_invited_by_user_id",
        "organization_members",
        ["invited_by_user_id"],
    )
    op.create_foreign_key(
        "fk_org_members_invited_by_user_id",
        "organization_members",
        "users",
        ["invited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_org_members_invited_by_user_id",
        "organization_members",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_organization_members_invited_by_user_id",
        table_name="organization_members",
    )
    op.drop_index(
        "ix_organization_members_invite_token",
        table_name="organization_members",
    )
    op.drop_column("organization_members", "invited_by_user_id")
    op.drop_column("organization_members", "invite_expires_at")
    op.drop_column("organization_members", "invite_token")
    op.drop_column("organizations", "team_size")
    op.drop_column("organizations", "industry")
