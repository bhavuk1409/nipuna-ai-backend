"""Knowledge-base endpoints (PR4).

Four endpoints:

  - ``GET  /knowledge/status``     — health + document count
  - ``GET  /knowledge/documents``  — paginated list (admin)
  - ``POST /knowledge/documents``  — chunk + embed + upsert (admin)
  - ``DELETE /knowledge/documents/{id}`` — scoped delete (admin)

The /status endpoint is cached at the edge with ``Cache-Control:
max-age=30``; the FE hits it on every chat page load. Admin-gated
writes go through ``require_admin``. Cross-org 403 is enforced via
``pgvector_store.upsert`` (the ``org_id`` argument is the source of
truth, not the URL).

The chunking strategy is a simple sliding-window: 1000-char chunks
with 200-char overlap. The overlap is what makes a question that
spans a chunk boundary still retrieve a hit. We don't try fancier
strategies (sentence-aware, embedding-based) — those add a heavy
dependency and the marginal recall gain is small for a sidebar use
case.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user, require_admin
from app.models.organization import Organization
from app.models.user import User
from app.models.vector_doc import VectorDocument
from app.services.ai import pgvector_store
from app.services.ai.embedding_client import embedding_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# Chunking config. Mirrors pgvector_store's defaults so the chunk
# count returned in the response matches what's actually stored.
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 200


# ──────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────


class KnowledgeStatus(BaseModel):
    enabled: bool
    reason: str
    document_count: int
    last_indexed_at: str | None = None


class DocumentSummary(BaseModel):
    id: str
    source: str
    chunk_count: int
    last_indexed_at: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class DocumentCreate(BaseModel):
    source: str = Field(..., min_length=1, max_length=255, description="Free-form source label")
    content: str = Field(..., min_length=1, max_length=200_000, description="Full text to embed")
    metadata: dict[str, Any] | None = Field(default=None)


class DocumentCreateResponse(BaseModel):
    id: str
    chunks_created: int


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _split_chunks(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Sliding-window chunker. Pure function; no LLM involvement.

    Edge cases:
      - text shorter than ``chunk_size`` → single chunk, no overlap.
      - overlap >= chunk_size → capped to chunk_size // 2 so we
        always make forward progress.
    """
    if chunk_size <= 0:
        return [text]
    if overlap < 0:
        overlap = 0
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 2)
    if len(text) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start += step
    return chunks


async def _embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Embed each chunk via the central client. Returns a list the
    same length as ``chunks``; an empty list at a position means
    "embedding failed for this chunk, skip it".
    """
    out: list[list[float]] = []
    for c in chunks:
        try:
            emb = await embedding_client.embed(c)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embed failed for chunk: %s", exc)
            emb = []
        out.append(emb)
    return out


# ──────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────


@router.get("/status", response_model=KnowledgeStatus)
async def knowledge_status(
    response: Response,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeStatus:
    """FE polls this on every chat page load.

    Cache-Control is 30s. The doc count is cheap (one COUNT query)
    but we still want the FE to stop polling on every keystroke.
    """
    response.headers["Cache-Control"] = "max-age=30"

    enabled = embedding_client.enabled
    reason = "ok" if enabled else "no_embedding_provider"

    count_res = await db.execute(
        select(func.count(VectorDocument.id)).where(VectorDocument.org_id == org.id)
    )
    doc_count = int(count_res.scalar_one() or 0)

    last_res = await db.execute(
        select(func.max(VectorDocument.created_at)).where(VectorDocument.org_id == org.id)
    )
    last_indexed = last_res.scalar_one()

    return KnowledgeStatus(
        enabled=enabled,
        reason=reason,
        document_count=doc_count,
        last_indexed_at=last_indexed.isoformat() if last_indexed else None,
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents for the active org. Admin-only — the count
    leaks the size of the knowledge base to non-admins.
    """
    total_res = await db.execute(
        select(func.count(VectorDocument.id)).where(VectorDocument.org_id == org.id)
    )
    total = int(total_res.scalar_one() or 0)

    res = await db.execute(
        select(VectorDocument)
        .where(VectorDocument.org_id == org.id)
        .order_by(VectorDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(res.scalars().all())
    docs = [
        DocumentSummary(
            id=str(d.id),
            source=d.source,
            chunk_count=0,  # pgvector_store doesn't expose counts; the FE
            # doesn't need the exact chunk count for a list view, and
            # counting chunks per doc is a N+1 trap we'd rather not
            # hit on every list call. PR5 can revisit if the FE needs
            # a chunk-count column.
            last_indexed_at=d.created_at.isoformat() if d.created_at else None,
        )
        for d in rows
    ]
    return DocumentListResponse(documents=docs, total=total, limit=limit, offset=offset)


@router.post("/documents", response_model=DocumentCreateResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> DocumentCreateResponse:
    """Chunk, embed, and upsert a document. Admin-only.

    Returns ``{id, chunks_created}`` so the FE can show a success
    toast with the new row's id (for inspection / deletion later).

    The first chunk is upserted via the existing
    ``pgvector_store.upsert`` path (which dedupes on content hash for
    the whole org). Subsequent chunks of the same document are
    inserted as additional ``vector_chunks`` rows directly so the
    pgvector HNSW index hits them on a search.
    """
    if not embedding_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base is disabled: no embedding provider configured.",
        )

    chunks = _split_chunks(body.content)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document content is empty after chunking.")

    embeddings = await _embed_chunks(chunks)
    if not any(e for e in embeddings):
        raise HTTPException(
            status_code=502,
            detail="Embedding provider returned no vectors for any chunk.",
        )

    # The first chunk dedupes via the existing upsert path; later
    # chunks of the same document are appended as siblings.
    first_doc_id: str | None = None
    created = 0
    for chunk_text, emb in zip(chunks, embeddings):
        if not emb:
            continue
        if first_doc_id is None:
            doc_id = await pgvector_store.upsert(
                db,
                org_id=org.id,
                source=body.source,
                content=chunk_text,
                embedding=emb,
                metadata=body.metadata,
            )
            first_doc_id = doc_id
            created += 1
        else:
            # Subsequent chunks: append as a vector_chunks row.
            from app.services.ai.pgvector_store import VectorChunk, _serialize_embedding
            chunk = VectorChunk(
                document_id=UUID(first_doc_id),
                org_id=org.id,
                chunk_index=created,
                text=chunk_text,
                embedding=_serialize_embedding(emb),
            )
            db.add(chunk)
            created += 1
    if created == 0:
        raise HTTPException(status_code=502, detail="No chunks were embedded.")
    await db.commit()
    return DocumentCreateResponse(id=first_doc_id or "", chunks_created=created)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: UUID,
    admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a document and its chunks. Admin-only. Scoped to the
    active org — a cross-org id returns 404 (not 403) so we don't
    leak document existence.
    """
    res = await db.execute(
        select(VectorDocument).where(
            VectorDocument.id == doc_id,
            VectorDocument.org_id == org.id,
        )
    )
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await pgvector_store.delete(db, doc_id=doc_id)
    await db.commit()
    return Response(status_code=204)


__all__ = ["router"]
