"""add alert read_at

Revision ID: 20260619_000003
Revises: 5b3754cf4216
Create Date: 2026-06-19 18:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260619_000003"
down_revision = "5b3754cf4216"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "read_at")
