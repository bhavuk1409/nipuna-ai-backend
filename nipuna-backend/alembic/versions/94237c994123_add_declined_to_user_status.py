"""add_declined_to_user_status

Revision ID: 94237c994123
Revises: 20260619_000003
Create Date: 2026-06-24 16:15:12.018283
"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '94237c994123'
down_revision = '20260619_000003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE user_status_enum ADD VALUE 'declined'")


def downgrade() -> None:
    pass
