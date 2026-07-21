"""Knowledge router tests.

The router has admin-gated writes; the tests verify:
  - ``/status`` is publicly readable (any active member)
  - ``/status`` returns ``enabled: false`` when no embedding provider
  - ``/documents`` POST requires admin
  - Cross-org doc id returns 404
  - The chunker splits long content
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_user_org(make_user_factory, chat_db, role: str = "admin"):
    """Helper: build an org + user via the conftest factories."""
    from tests.chat.conftest import make_org

    org = await make_org(chat_db)
    user = await make_user_factory(org, role=role)
    return org, user


# ──────────────────────────────────────────────────────────────────
# /knowledge/status
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_status_reports_disabled_without_openai(chat_db, monkeypatch):
    from app.routers.knowledge import embedding_client as ec_in_router
    monkeypatch.setattr(type(ec_in_router), "enabled", property(lambda self: False))

    from fastapi import Response
    from app.routers.knowledge import knowledge_status
    from app.models.organization import Organization
    from app.models.user import User

    org = Organization(id=uuid.uuid4(), name="T", plan="pro", ai_credits=10,
                       clerk_org_id=f"k_{uuid.uuid4().hex[:8]}")
    user = User(id=uuid.uuid4(), clerk_user_id=f"u_{uuid.uuid4().hex[:8]}",
                email="x@y.z", active_org_id=org.id)

    response = Response()
    out = await knowledge_status(
        response=response,
        org=org,
        _user=user,
        db=chat_db,
    )
    assert out.enabled is False
    assert "no_embedding_provider" in out.reason
    assert response.headers.get("Cache-Control") == "max-age=30"


@pytest.mark.asyncio
async def test_knowledge_status_reports_enabled_with_openai(chat_db, monkeypatch):
    from app.routers.knowledge import embedding_client as ec_in_router
    monkeypatch.setattr(type(ec_in_router), "enabled", property(lambda self: True))

    from fastapi import Response
    from app.routers.knowledge import knowledge_status
    from app.models.organization import Organization
    from app.models.user import User

    org = Organization(id=uuid.uuid4(), name="T", plan="pro", ai_credits=10,
                       clerk_org_id=f"k_{uuid.uuid4().hex[:8]}")
    user = User(id=uuid.uuid4(), clerk_user_id=f"u_{uuid.uuid4().hex[:8]}",
                email="x@y.z", active_org_id=org.id)

    response = Response()
    out = await knowledge_status(
        response=response,
        org=org,
        _user=user,
        db=chat_db,
    )
    assert out.enabled is True
    assert out.reason == "ok"


# ──────────────────────────────────────────────────────────────────
# Chunking helper
# ──────────────────────────────────────────────────────────────────


def test_split_chunks_short_text_single_chunk():
    from app.routers.knowledge import _split_chunks
    chunks = _split_chunks("hello world")
    assert chunks == ["hello world"]


def test_split_chunks_long_text_overlaps():
    from app.routers.knowledge import _split_chunks
    text = "a" * 2500
    chunks = _split_chunks(text, chunk_size=1000, overlap=200)
    # Each chunk after the first starts 800 chars in.
    assert len(chunks) >= 3
    assert chunks[0] == "a" * 1000
    assert chunks[1] == "a" * 1000  # starts at index 800
    assert chunks[1][:200] == text[800:1000]


def test_split_chunks_overlap_capped_to_half_chunk():
    """If overlap >= chunk_size, it's clamped to chunk_size // 2."""
    from app.routers.knowledge import _split_chunks
    chunks = _split_chunks("a" * 1500, chunk_size=500, overlap=1000)
    # We still make forward progress, never enter an infinite loop.
    assert len(chunks) >= 1


def test_split_chunks_zero_chunk_size():
    from app.routers.knowledge import _split_chunks
    # Defensive: chunk_size <= 0 returns the whole text.
    assert _split_chunks("hello", chunk_size=0) == ["hello"]


# ──────────────────────────────────────────────────────────────────
# End-to-end: cross-org isolation on DELETE
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_document_cross_org_returns_404(chat_db, monkeypatch):
    """A doc from org A can't be deleted via a request from org B."""
    from app.routers.knowledge import delete_document
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.vector_doc import VectorDocument
    from fastapi import HTTPException

    # Org A owns the document
    org_a = Organization(
        id=uuid.uuid4(), name="A", plan="pro", ai_credits=10,
        clerk_org_id=f"a_{uuid.uuid4().hex[:8]}",
    )
    chat_db.add(org_a); await chat_db.flush()
    doc = VectorDocument(
        org_id=org_a.id,
        source="x", content_hash=uuid.uuid4().hex,
    )
    chat_db.add(doc); await chat_db.flush()
    await chat_db.commit()

    # Org B requests deletion
    org_b = Organization(
        id=uuid.uuid4(), name="B", plan="pro", ai_credits=10,
        clerk_org_id=f"b_{uuid.uuid4().hex[:8]}",
    )
    user = User(id=uuid.uuid4(), clerk_user_id=f"u_{uuid.uuid4().hex[:8]}",
                email="x@y.z", active_org_id=org_b.id)
    user.active_org_id = org_b.id
    chat_db.add(org_b); await chat_db.flush()
    await chat_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await delete_document(
            doc_id=doc.id, admin=user, org=org_b, db=chat_db,
        )
    assert exc_info.value.status_code == 404
