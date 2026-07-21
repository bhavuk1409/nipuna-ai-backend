"""pgvector-backed vector store for RAG.

This is the primary RAG path going forward. Replaces the dead
OpenSearch Serverless code in ``app/services/ai/vector_store.py``.

We use:
  - ``pgvector``'s ``vector(1536)`` column on the existing
    ``vector_documents`` table (added in migration
    ``*_add_pgvector_with_variant.py``).
  - HNSW index for cosine-distance nearest-neighbour search
    (added in the follow-up ``*_add_pgvector_hnsw_index.py`` migration
    that must be run **outside** a transaction — see
    ``docs/chat-overhaul-migrations.md``).
  - One "row per document" in the existing ``vector_documents`` table.
    We store the chunk-level vectors in a parallel ``vector_chunks``
    table (added in the same migration) so the search query is
    a single ``SELECT ... ORDER BY embedding <=> :q LIMIT :k``.

Why a separate chunks table? The existing ``vector_documents`` table
tracks "we have a document" (id, source, content_hash) but doesn't
have a vector column. The new ``vector_chunks`` table has the
per-chunk vectors. A search joins ``vector_chunks`` back to
``vector_documents`` for the source path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin

logger = logging.getLogger(__name__)


# Model lives here (not under ``app/models/``) because it's a
# private implementation detail of this module. Migration targets
# ``vector_chunks`` by table name explicitly.
class VectorChunk(Base, TimestampMixin):
    __tablename__ = "vector_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_vector_chunks_doc_chunk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # FK to vector_documents; we declare via raw SQL because the
        # model in app/models/vector_doc.py owns the table.
        nullable=False,
        index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # The 1536-d embedding. We declare as Text on SQLite (so the
    # table can be created by `Base.metadata.create_all` in tests)
    # and as a vector type on Postgres (see the migration).
    embedding: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False, server_default="0")


# The HNSW index is created in a separate migration that runs
# OUTSIDE a transaction. Declared here as documentation; the actual
# CREATE INDEX is in ``*_add_pgvector_hnsw_index.py``.
_HNSW_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_vector_chunks_embedding_hnsw "
    "ON vector_chunks USING hnsw (embedding::vector(1536) vector_cosine_ops) "
    "WHERE org_id IS NOT NULL"
)


@dataclass
class SearchHit:
    doc_id: str
    chunk_id: str
    text: str
    score: float


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _serialize_embedding(embedding: list[float]) -> str:
    """Encode an embedding as a JSON array string for storage.

    Postgres pgvector accepts the string form ``'[0.1, 0.2, ...]'``
    directly when we cast to ``::vector``. Using JSON keeps the
    ``Text`` column happy on SQLite too.
    """
    return json.dumps(embedding)


def _is_postgres(db: AsyncSession) -> bool:
    return db.get_bind().dialect.name == "postgresql"


async def ensure_schema(db: AsyncSession) -> None:
    """No-op — the schema is created by the migration. Kept for the
    test-time ``Base.metadata.create_all`` path so the table exists
    in the SQLite test DB.
    """
    pass


async def upsert(
    db: AsyncSession,
    *,
    org_id: str | UUID,
    source: str,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> str:
    """Upsert a document. Returns the document id (UUID string).

    If the same content hash already exists for this org, the
    existing document id is returned and the chunks are not re-embedded.

    This signature accepts a single ``content`` string and a single
    ``embedding``; multi-chunk ingestion is left to the caller
    (the API endpoint in PR4). For the test infra we only need the
    happy-path single-chunk flow.
    """
    from app.models.vector_doc import VectorDocument

    org_uuid = UUID(str(org_id))
    content_hash = _hash_text(content)

    # Find existing doc.
    existing = await db.execute(
        text("SELECT id FROM vector_documents WHERE org_id = :org_id AND content_hash = :h")
        if _is_postgres(db) else
        text("SELECT id FROM vector_documents WHERE org_id = :org_id AND content_hash = :h"),
        {"org_id": str(org_uuid), "h": content_hash},
    )
    row = existing.first()
    if row:
        return str(row[0])

    doc = VectorDocument(
        org_id=org_uuid,
        source=source,
        content_hash=content_hash,
        opensearch_id=None,
    )
    db.add(doc)
    await db.flush()

    # Single-chunk ingestion. Multi-chunk splitting happens in the
    # API layer in PR4.
    chunk = VectorChunk(
        document_id=doc.id,
        org_id=org_uuid,
        chunk_index=0,
        text=content[:chunk_size],
        embedding=_serialize_embedding(embedding),
    )
    db.add(chunk)
    await db.flush()

    return str(doc.id)


async def delete(db: AsyncSession, *, doc_id: str | UUID) -> None:
    """Delete a document and its chunks."""
    from app.models.vector_doc import VectorDocument

    doc_uuid = UUID(str(doc_id))
    doc = await db.get(VectorDocument, doc_uuid)
    if not doc:
        return
    # Delete chunks first to avoid FK error if the migration didn't
    # add ON DELETE CASCADE.
    await db.execute(
        text("DELETE FROM vector_chunks WHERE document_id = :d"),
        {"d": str(doc_uuid)},
    )
    await db.delete(doc)
    await db.flush()


async def search(
    db: AsyncSession,
    *,
    org_id: str | UUID,
    query_embedding: list[float],
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[SearchHit]:
    """K-nearest-neighbour search by cosine distance.

    On Postgres (production + staging) this uses the HNSW index
    via ``<=>`` operator. On SQLite (tests) it falls back to a
    brute-force scan — fine for the small test corpora.
    """
    org_uuid = UUID(str(org_id))

    if _is_postgres(db):
        # HNSW cosine search: lower distance = better, so we ORDER BY
        # distance ASC and convert to a similarity score in [0, 1] via
        # 1 - distance (clamped).
        sql = text(
            """
            SELECT id, document_id, text,
                   1 - (embedding::vector(1536) <=> :q_vec) AS score
              FROM vector_chunks
             WHERE org_id = :org_id
             ORDER BY embedding::vector(1536) <=> :q_vec ASC
             LIMIT :k
            """
        )
        rows = await db.execute(
            sql,
            {
                "q_vec": _serialize_embedding(query_embedding),
                "org_id": str(org_uuid),
                "k": top_k,
            },
        )
    else:
        # SQLite fallback: pull all chunks and sort in Python.
        # Fine for tests with <100 rows.
        from sqlalchemy import select
        result = await db.execute(
            select(VectorChunk).where(VectorChunk.org_id == org_uuid)
        )
        chunks = list(result.scalars().all())
        scored: list[tuple[VectorChunk, float]] = []
        q = query_embedding
        for c in chunks:
            try:
                v = json.loads(c.embedding)
            except (TypeError, ValueError):
                continue
            score = _cosine_similarity(q, v)
            scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        rows = iter(scored[:top_k])

    hits: list[SearchHit] = []
    for row in rows:
        if _is_postgres(db):
            chunk_id, doc_id, text_value, score = row
        else:
            chunk, score = row
            chunk_id = chunk.id
            doc_id = chunk.document_id
            text_value = chunk.text
        if score < min_score:
            continue
        hits.append(
            SearchHit(
                doc_id=str(doc_id),
                chunk_id=str(chunk_id),
                text=text_value,
                score=float(score),
            )
        )
    return hits


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


__all__ = [
    "SearchHit",
    "VectorChunk",
    "delete",
    "ensure_schema",
    "search",
    "upsert",
]


# Re-exported for migration discovery
_INDEXES: tuple[Any, ...] = (
    Index("ix_vector_chunks_org_id", "org_id"),
)
