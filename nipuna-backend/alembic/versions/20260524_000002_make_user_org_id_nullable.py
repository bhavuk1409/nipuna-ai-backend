"""make_user_org_id_nullable

Revision ID: 20260524_000002
Revises: 20260524_000001
Create Date: 2026-05-24 00:00:02.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260524_000002"
down_revision = "20260524_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make org_id nullable so users can be created before their org is set up.
    # Clerk fires user.created BEFORE organizationMembership.created, so the
    # webhook handler must be able to insert a User row with org_id = NULL.
    op.alter_column("users", "org_id", nullable=True)


def downgrade() -> None:
    # WARNING: this will fail if any rows have org_id = NULL
    op.alter_column("users", "org_id", nullable=False)
