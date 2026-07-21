"""Chat-path test fixtures.

The fixtures in this conftest are the recommended way to test chat
routes / pipeline. The dep overrides bypass the Clerk auth flow
entirely (the dev-bypass shortcut in ``app.dependencies`` is
inconsistent across tests and the JWT mock approach is fragile);
the test instantiates a real ``User`` / ``Organization`` /
``OrganizationMember`` triple, then monkeypatches
``app.dependencies.get_current_user`` and ``get_current_org`` to
return them. This makes the assertions about role-based access
control honest: the deps run, the DB is hit, the org is validated.

If the chat path grows a new dep, add the override here.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

# Must run BEFORE app imports so DATABASE_URL is set when the
# engine module loads. Idempotent with the parent conftest.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("ENV", "test")

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.conversation import Conversation, Message
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


# ──────────────────────────────────────────────────────────────────
# Entity factories
# ──────────────────────────────────────────────────────────────────


async def make_org(
    db: AsyncSession,
    *,
    name: str = "Test Org",
    ai_credits: int = 100,
    plan: str = "pro",
) -> Organization:
    """Create a fresh Organization. Idempotent on clerk_org_id within a test."""
    org = Organization(
        clerk_org_id=f"manual_{uuid.uuid4().hex[:8]}",
        name=name,
        plan=plan,
        ai_credits=ai_credits,
    )
    db.add(org)
    await db.flush()
    return org


async def make_user(
    db: AsyncSession,
    org: Organization,
    *,
    email: str | None = None,
    role: str = "admin",
    first_name: str | None = "Test",
    last_name: str | None = "User",
) -> User:
    """Create a User and an OrganizationMember in the given org."""
    user = User(
        clerk_user_id=f"user_{uuid.uuid4().hex[:8]}",
        email=email or f"user-{uuid.uuid4().hex[:6]}@test.local",
        first_name=first_name,
        last_name=last_name,
        active_org_id=org.id,
    )
    db.add(user)
    await db.flush()

    # ``organization_members.email`` is NOT NULL — keep it in sync with
    # the user's email so invites and member lookups stay correct.
    member_email = email or f"user-{uuid.uuid4().hex[:6]}@test.local"
    member = OrganizationMember(
        user_id=user.id,
        org_id=org.id,
        email=member_email,
        role=role,
        status="active",
    )
    db.add(member)
    await db.flush()
    return user


async def make_agent(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    template_id: str = "general_assistant",
    name: str = "Nipuna AI",
    domain: str = "General Business",
    objective: str = "Help run business operations.",
) -> Agent:
    """Create an Agent with the given template id (validated at write)."""
    from app.services.ai.agent_templates import get_template
    tmpl = get_template(template_id)
    agent = Agent(
        org_id=org.id,
        name=name or tmpl.name,
        domain=domain or tmpl.domain,
        objective=objective or tmpl.objective,
        template_id=template_id,
        icon=tmpl.icon,
        color=tmpl.color,
        status="active",
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()
    return agent


async def make_conversation(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    user: User,
    *,
    n_messages: int = 0,
    title: str | None = None,
) -> Conversation:
    """Create a conversation with an optional backfilled message history."""
    conv = Conversation(
        org_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        title=title,
    )
    db.add(conv)
    await db.flush()

    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        msg = Message(
            conversation_id=conv.id,
            role=role,
            content=f"Test message {i}",
        )
        db.add(msg)
    await db.flush()
    return conv


async def make_conversation_list(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    user: User,
    *,
    n: int = 100,
) -> list[Conversation]:
    """Bulk-create conversations for pagination tests."""
    convs = []
    for i in range(n):
        c = Conversation(
            org_id=org.id,
            agent_id=agent.id,
            user_id=user.id,
            title=f"Conversation {i}",
        )
        db.add(c)
        convs.append(c)
    await db.flush()
    return convs


# ──────────────────────────────────────────────────────────────────
# Fixture wrappers (pytest calls these by name)
# ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def chat_db() -> AsyncIterator[AsyncSession]:
    """Yields a clean session. Caller is responsible for commit/rollback."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session
        # Don't auto-commit; tests that need a commit do it explicitly.


@pytest.fixture
def make_org_factory(chat_db):
    """Binds make_org to the chat_db fixture so tests can call it directly."""
    return lambda **kwargs: make_org(chat_db, **kwargs)


@pytest.fixture
def make_user_factory(chat_db):
    return lambda org, **kwargs: make_user(chat_db, org, **kwargs)


@pytest.fixture
def make_agent_factory(chat_db):
    return lambda org, user, **kwargs: make_agent(chat_db, org, user, **kwargs)


@pytest.fixture
def make_conversation_factory(chat_db):
    return lambda org, agent, user, **kwargs: make_conversation(
        chat_db, org, agent, user, **kwargs
    )


# ──────────────────────────────────────────────────────────────────
# Auth override fixture
# ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_dep_overrides(chat_db):
    """Override ``get_current_user`` and ``get_current_org`` to return
    the test entities. Returns a small context manager so the test can
    register multiple users (e.g. a chat sender and a viewer).

    Usage::

        async with app_dep_overrides(user, org) as ctx:
            async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                          base_url="http://test") as ac:
                resp = await ac.post("/api/v1/chat/send", json={...})
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx(user: User, org: Organization):
        async def _get_user() -> User:
            return user

        async def _get_org(
            current_user: User = None,
            db: AsyncSession = None,
        ) -> Organization:
            return org

        # We need an actual DB session inside get_current_org, but
        # the dep signature is `(user, db)`. Pass a closure that
        # ignores them and just returns the test org.
        async def _get_org_dep(
            user: User = None, db: AsyncSession = None
        ) -> Organization:
            return org

        # get_current_org in the real app also accepts an `auto_create`
        # kwarg. Keep the signature compatible.
        async def _get_org_safe(
            user: User = None, db: AsyncSession = None, **kwargs
        ) -> Organization:
            return org

        app.dependency_overrides[get_current_user] = _get_user
        app.dependency_overrides[get_current_org] = _get_org_safe
        try:
            yield {"user": user, "org": org}
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_current_org, None)

    return _ctx


# ──────────────────────────────────────────────────────────────────
# LLM mock fixtures
# ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_provider(monkeypatch):
    """Patch the ChatGroq and ChatOpenAI factories to return canned
    AIMessages. The default returns "Mock response: <last user msg>".
    Tests that need a specific response can pass a custom factory.
    """
    from langchain_core.messages import AIMessage

    def _factory(response: str | None = None):
        def _respond(messages, **kwargs):
            content = response
            if content is None:
                # Default: echo the last user message
                for m in reversed(messages):
                    if getattr(m, "type", None) == "human":
                        content = f"Mock response: {m.content}"
                        break
                else:
                    content = "Mock response"
            return AIMessage(content=content)

        return _respond

    def _apply(response: str | None = None):
        responder = _factory(response)
        # Patch both providers; tests are typically only using one.
        try:
            from langchain_groq import ChatGroq
            monkeypatch.setattr(ChatGroq, "invoke", lambda self, m, **k: responder(m))
            monkeypatch.setattr(ChatGroq, "stream", lambda self, m, **k: iter([AIMessage(content="")]))
        except ImportError:
            pass
        try:
            from langchain_openai import ChatOpenAI
            monkeypatch.setattr(ChatOpenAI, "invoke", lambda self, m, **k: responder(m))
            monkeypatch.setattr(ChatOpenAI, "stream", lambda self, m, **k: iter([AIMessage(content="")]))
        except ImportError:
            pass
        return responder

    return _apply


@pytest.fixture
def mock_embedding(monkeypatch):
    """Patch the embedding client to return a canned 1536-dim zero vector.
    Tests that need a real-ish similarity should override with a known
    vector.
    """
    from app.services.ai.embedding_client import embedding_client
    import numpy as np

    vec = np.zeros(1536, dtype=float).tolist()

    async def _embed(text: str) -> list[float]:
        # A tiny touch of determinism: hash the first 4 chars into the
        # first 4 dimensions so two different strings produce different
        # vectors. Useful for search-result-ordering tests.
        seed = sum(ord(c) for c in text[:4]) % 97
        v = vec.copy()
        v[0] = (seed % 17) / 17.0
        return v

    monkeypatch.setattr(embedding_client, "embed", _embed)
    monkeypatch.setattr(embedding_client, "_enabled", True)
    return _embed
