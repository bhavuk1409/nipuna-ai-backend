"""drop uq_conversations_org_agent_user

Revision ID: 5b3754cf4216
Revises: e9d6a28b89a5
Create Date: 2026-06-19 18:14:39.439032
"""
from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '5b3754cf4216'
down_revision = 'e9d6a28b89a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uq_conversations_org_agent_user', 'conversations', type_='unique')


def downgrade() -> None:
    op.create_unique_constraint('uq_conversations_org_agent_user', 'conversations', ['org_id', 'agent_id', 'user_id'])
