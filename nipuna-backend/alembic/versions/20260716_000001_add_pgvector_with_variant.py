"""enable pgvector + create vector_chunks

Adds the ``vector`` Postgres extension and a new ``vector_chunks``
table that stores per-chunk text + 1536-dim embedding. The existing
``vector_documents`` table keeps its opensearch-shaped content_hash /
opensearch_id columns — we don't drop those in this PR so the legacy
ingest path can keep running during the cutover.

The HNSW index is intentionally NOT created here. ``CREATE INDEX
CONCURRENTLY`` is not allowed inside an Alembic transaction, and a
plain ``CREATE INDEX`` would block writes on a populated table. The
operator runs the HNSW index migration separately
(``20260716_000002_add_vector_chunks_hnsw``) and the full sequence
is documented in ``docs/chat-overhaul-migrations.md``.

The embedding column is typed via ``with_variant`` so the SQLite
test path (``Base.metadata.create_all`` in conftest) treats it as
``TEXT`` and doesn't blow up. Postgres sees ``vector(1536)`` at
migration time, so the type round-trips through ``pg_dump``/``pg_restore``
cleanly.

Revision ID: 20260716_000001
Revises: e32ecbc54f42
Create Date: 2026-07-16 00:00:01.000000

The original `down_revision = "20260713_000001"` would have placed
this chain on an orphaned branch (the prod DB is at `e32ecbc54f42`,
not `7a8b3c1d4e2f`). Rebased onto the live prod head so `alembic
upgrade head` from prod applies pgvector + the rest of PR1 in order.
The orphaned `20260713_000001_organization_membership` migration is
left in place for dev environments that branched from
`7a8b3c1d4e2f`; its effects are already on prod via a prior apply.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260716_000001"
down_revision = "e32ecbc54f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Enable the vector extension. `IF NOT EXISTS` so re-running this
    # migration (e.g. on a partially-applied DB) is a no-op.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Per-chunk vector store. The application chunks documents on
    # write and stores one row per chunk; search runs the HNSW query
    # against the embedding column and joins back to the document
    # metadata.
    op.create_table(
        "vector_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "embedding",
            sa.Text().with_variant(
                postgresql.ARRAY(sa.Float()),
                "postgresql",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["vector_documents.id"],
            name=op.f("fk_vector_chunks_document_id_vector_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_vector_chunks_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vector_chunks")),
    )
    op.create_index(
        op.f("ix_vector_chunks_org_id"),
        "vector_chunks",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_vector_chunks_document_id"),
        "vector_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_vector_chunks_source"),
        "vector_chunks",
        ["source"],
        unique=False,
    )

    # Now upgrade the `embedding` column from the array fallback to
    # a real ``vector(1536)`` *if* we're on Postgres. We use raw SQL
    # because `pgvector.sqlalchemy.Vector` isn't in requirements yet
    # and we don't want a hard import on a module that might be
    # missing on a dev machine. The cast is a no-op if the column is
    # already ``vector(1536)``.
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE vector_chunks "
            "ALTER COLUMN embedding TYPE vector(1536) "
            "USING embedding::vector(1536)"
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_vector_chunks_source"), table_name="vector_chunks")
    op.drop_index(op.f("ix_vector_chunks_document_id"), table_name="vector_chunks")
    op.drop_index(op.f("ix_vector_chunks_org_id"), table_name="vector_chunks")
    op.drop_table("vector_chunks")
    # Do NOT drop the `vector` extension — other tables may use it
    # and dropping the extension is destructive.
