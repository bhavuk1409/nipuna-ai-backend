"""add template/icon/color to agents

The chat overhaul (PR1-PR5) introduces per-domain agent templates
(see ``app/services/ai/agent_templates.py``). Templates own the
agent's name, domain, objective, icon, and color, so a new agent
created from a template stores its ``template_id`` here for later
identification.

Nullable on purpose: legacy agents (created before this migration)
have no template; readers treat NULL as ``general_assistant``.

Revision ID: 20260716_000003
Revises: 20260716_000002
Create Date: 2026-07-16 00:00:03.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260716_000003"
down_revision = "20260716_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("template_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("icon", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("color", sa.String(length=16), nullable=True),
    )
    op.create_index(
        op.f("ix_agents_template_id"),
        "agents",
        ["template_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_template_id"), table_name="agents")
    op.drop_column("agents", "color")
    op.drop_column("agents", "icon")
    op.drop_column("agents", "template_id")
