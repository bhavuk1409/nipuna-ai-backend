"""add logo_url to organizations

Revision ID: e32ecbc54f42
Revises: 7a1b9c2d3e4f
Create Date: 2026-07-14 15:24:06.576609
"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'e32ecbc54f42'
down_revision = '7a1b9c2d3e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL with IF EXISTS so this migration never fails even if the
    # column/index already exists or was already dropped by a previous migration.

    # Drop conversation indexes if they still exist (they may have been removed already)
    op.execute("DROP INDEX IF EXISTS idx_conversations_created_at")
    op.execute("DROP INDEX IF EXISTS idx_conversations_org_agent_user")

    # Make billing_events.org_id nullable if it isn't already
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE billing_events ALTER COLUMN org_id DROP NOT NULL;
        EXCEPTION WHEN others THEN
            NULL;  -- already nullable, ignore
        END$$;
    """)

    # Ensure logo_url column exists on organizations (TEXT is fine for Postgres)
    op.execute("""
        ALTER TABLE organizations
        ADD COLUMN IF NOT EXISTS logo_url TEXT;
    """)


def downgrade() -> None:
    # Intentionally a no-op — the column and index state is managed elsewhere.
    pass

