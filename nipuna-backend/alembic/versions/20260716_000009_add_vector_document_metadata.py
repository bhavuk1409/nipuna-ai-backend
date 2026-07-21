"""add vector_documents.title and last_indexed_at

The /knowledge/status endpoint (PR4) reports ``last_indexed_at`` so
the FE can render "Last indexed 2 minutes ago" without an extra
round-trip. ``title`` is the human-readable filename (or first line
of the source) used in the documents list view.

Both columns are nullable. Existing rows are backfilled to NULL on
the way up; reads use ``updated_at`` as a sensible substitute until
the next re-index populates ``last_indexed_at``.

Also adds ``updated_at`` to the table so the index is stable for
the /knowledge/status query — without it, callers can't tell which
documents are "stale" relative to their content.

Revision ID: 20260716_000009
Revises: 20260716_000008
Create Date: 2026-07-16 00:00:09.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260716_000009"
down_revision = "20260716_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vector_documents",
        sa.Column("title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "vector_documents",
        sa.Column(
            "last_indexed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "vector_documents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("vector_documents", "updated_at")
    op.drop_column("vector_documents", "last_indexed_at")
    op.drop_column("vector_documents", "title")
