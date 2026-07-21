"""add messages.truncated_at

PR3 introduces the streaming-disconnect path. When the SSE client
disconnects mid-stream the background pipeline catches the signal,
stops the LLM, and persists the partial answer with
``truncated_at = now()`` so the FE can render "…response cut off"
and the user knows the answer isn't complete.

NULL on a normal completion. The flag is a single column, no index —
the per-message write path is the hot one, and a SELECT-by-id with
a NULL check is a single page read.

Revision ID: 20260716_000005
Revises: 20260716_000004
Create Date: 2026-07-16 00:00:05.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260716_000005"
down_revision = "20260716_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("truncated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "truncated_at")
