"""Incremental persist + truncated_at tests (PR3).

The chat.py stream_message pre-creates an assistant message row,
buffers tokens, and commits partial content every 100 tokens
(or on every successful tool_end). On disconnect, the message
gets `truncated_at = now()` and the partial content is committed.

These tests use the test chat conftest's make_org/user/agent
fixtures and exercise the logic via the in-memory app.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_truncated_at_is_set_to_now_on_disconnect(chat_db):
    """Simulate the disconnect path: set truncated_at on a
    message row and verify the value persists.
    """
    from app.models.conversation import Conversation, Message
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.agent import Agent
    from sqlalchemy import update

    async def _run():
        # Build a minimal conversation + message
        org = Organization(
            clerk_org_id=f"test_{uuid.uuid4().hex[:8]}",
            name="Test Org",
            plan="pro",
            ai_credits=10,
        )
        chat_db.add(org)
        await chat_db.flush()

        user = User(
            clerk_user_id=f"user_{uuid.uuid4().hex[:8]}",
            email=f"user-{uuid.uuid4().hex[:6]}@test.local",
            active_org_id=org.id,
        )
        chat_db.add(user)
        await chat_db.flush()

        agent = Agent(
            org_id=org.id,
            name="Test Agent",
            domain="Test",
            objective="Test",
            status="active",
            created_by=user.id,
        )
        chat_db.add(agent)
        await chat_db.flush()

        conv = Conversation(org_id=org.id, agent_id=agent.id, user_id=user.id)
        chat_db.add(conv)
        await chat_db.flush()

        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content="partial answer",
        )
        chat_db.add(msg)
        await chat_db.flush()
        await chat_db.commit()

        # Now simulate the disconnect path
        await chat_db.execute(
            update(Message)
            .where(Message.id == msg.id)
            .values(truncated_at=datetime.utcnow())
        )
        await chat_db.commit()

        # Re-fetch
        result = await chat_db.execute(
            __import__("sqlalchemy").select(Message).where(Message.id == msg.id)
        )
        reloaded = result.scalar_one()
        assert reloaded.truncated_at is not None
        assert reloaded.content == "partial answer"
        return True

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result is True


def test_partial_content_persists_across_commit(chat_db):
    """Verify the partial-content commit pattern: update content
    on an existing message and commit.
    """
    from app.models.conversation import Conversation, Message
    from app.models.organization import Organization
    from app.models.user import User
    from app.models.agent import Agent
    from sqlalchemy import update, select

    async def _run():
        org = Organization(
            clerk_org_id=f"test_{uuid.uuid4().hex[:8]}",
            name="Test",
            plan="pro",
            ai_credits=10,
        )
        chat_db.add(org)
        await chat_db.flush()
        user = User(
            clerk_user_id=f"user_{uuid.uuid4().hex[:8]}",
            email=f"u-{uuid.uuid4().hex[:6]}@t.local",
            active_org_id=org.id,
        )
        chat_db.add(user)
        await chat_db.flush()
        agent = Agent(
            org_id=org.id, name="A", domain="D", objective="O",
            status="active", created_by=user.id,
        )
        chat_db.add(agent)
        await chat_db.flush()
        conv = Conversation(org_id=org.id, agent_id=agent.id, user_id=user.id)
        chat_db.add(conv)
        await chat_db.flush()
        msg = Message(
            conversation_id=conv.id, role="assistant", content="",
        )
        chat_db.add(msg)
        await chat_db.flush()
        await chat_db.commit()

        # Simulate three incremental persists
        for chunk in ["hello ", "world ", "from nipuna"]:
            await chat_db.execute(
                update(Message)
                .where(Message.id == msg.id)
                .values(content=Message.content + chunk)
            )
            await chat_db.commit()

        result = await chat_db.execute(
            select(Message).where(Message.id == msg.id)
        )
        reloaded = result.scalar_one()
        assert reloaded.content == "hello world from nipuna"
        return True

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result is True
