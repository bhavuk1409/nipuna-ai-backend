"""add HNSW index on vector_chunks.embedding

HNSW indexes must be created with ``CONCURRENTLY`` so they don't
block writes against the table. Alembic wraps every migration in a
transaction by default, so this migration is split: it sets
``transaction_per_migration = False`` via the ``--sql`` route and
expects to be run with ``op.get_context().autocommit_block()``.

Operator runbook (see ``docs/chat-overhaul-migrations.md``):

    cd /Users/bhavukagrawal/nipuna-ai-backend/nipuna-backend
    alembic upgrade 20260716_000002 --sql > /tmp/hnsw.sql
    psql "$DATABASE_URL" -f /tmp/hnsw.sql

This migration is a no-op when re-run on a database that already has
the index (``CREATE INDEX IF NOT EXISTS``).

Revision ID: 20260716_000002
Revises: 20260716_000001
Create Date: 2026-07-16 00:00:02.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260716_000002"
down_revision = "20260716_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY is not allowed inside a transaction. Alembic's
    # default is per-migration transactional; this is a no-op in
    # that mode (the operator uses ``alembic --sql`` and runs the
    # SQL by hand). When alembic is invoked with
    # ``transaction_per_ddl=True`` (the env we don't use) the
    # concurrent index is the only way.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_vector_chunks_embedding_hnsw "
        "ON vector_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_vector_chunks_embedding_hnsw")
