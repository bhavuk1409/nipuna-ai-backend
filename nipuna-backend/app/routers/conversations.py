"""Conversations CRUD + import (PR4).

Five endpoints, all org-scoped, all gated by ``get_current_user``:

  - ``GET    /chat/conversations`` — paginated list (cursor-based)
  - ``GET    /chat/conversations/{id}`` — full conversation + messages
  - ``PATCH  /chat/conversations/{id}`` — title / archived
  - ``DELETE /chat/conversations/{id}`` — hard delete
  - ``POST   /chat/conversations/import`` — bulk import with
    ``legacy_client_id`` dedup; rate-limited 5/user/hour.

The list endpoint is cursor-paginated by ``(last_message_at, id)``
because that's the order the sidebar renders in. Cursor stability
matters: a row that gets a new message between two page fetches
should not duplicate in the next page.

The import endpoint is the migration target for the
localStorage-only history in the legacy FE. It:

  - dedupes by ``(org_id, legacy_client_id)`` — re-running the
    import is a no-op
  - rejects payloads > 200 messages or messages > 8000 chars
  - strips ``id`` / ``user_id`` / ``org_id`` from incoming messages
    so the client can't impersonate a server row
  - is rate-limited at 5 calls / user / hour via slowapi
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.conversation import Conversation, Message
from app.models.organization import Organization
from app.models.user import User
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/conversations", tags=["chat-conversations"])


# Plan limits. Hard-coded here rather than in config because they're
# a product contract with the legacy FE, not an operational knob.
_MAX_IMPORT_CONVERSATIONS_PER_CALL = 200
_MAX_IMPORT_MESSAGES_PER_CONVERSATION = 200
_MAX_IMPORT_MESSAGE_CHARS = 8000
# soft cap: total messages across the import payload, so a single
# caller can't sneak 200 × 200 = 40 000 messages past the per-conv
# limit.
_MAX_IMPORT_TOTAL_MESSAGES = 1_000


# ──────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    agent_id: str
    agent_template_id: str | None = None
    last_message_at: str | None = None
    message_count: int
    archived: bool
    created_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    next_cursor: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    tool_call: bool
    tool_name: str | None = None
    tool_action: str | None = None
    tool_result: str | None = None
    truncated_at: str | None = None


class ConversationDetail(BaseModel):
    id: str
    title: str | None = None
    agent_id: str
    agent_template_id: str | None = None
    archived: bool
    created_at: str
    last_message_at: str | None = None
    messages: list[MessageOut]


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    archived: bool | None = Field(default=None)


class ImportedMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=_MAX_IMPORT_MESSAGE_CHARS)
    created_at: str | None = None
    tool_call: bool = False
    tool_name: str | None = Field(default=None, max_length=120)
    tool_action: str | None = Field(default=None, max_length=255)
    tool_result: str | None = Field(default=None)


class ImportedConversation(BaseModel):
    legacy_client_id: str = Field(..., min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=255)
    agent_id: str | None = None
    created_at: str | None = None
    last_message_at: str | None = None
    messages: list[ImportedMessage] = Field(default_factory=list, max_length=_MAX_IMPORT_MESSAGES_PER_CONVERSATION)


class ImportRequest(BaseModel):
    conversations: list[ImportedConversation] = Field(..., max_length=_MAX_IMPORT_CONVERSATIONS_PER_CALL)


class ImportResult(BaseModel):
    inserted: int
    deduplicated: int
    failed: int
    failure_reasons: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # ``datetime.fromisoformat`` accepts the "Z" suffix in 3.11+.
        # Earlier Pythons don't — fall back to a manual replace.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


async def _count_messages_per_conv(
    db: AsyncSession, conv_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """One grouped query — N+1 trap avoidance."""
    if not conv_ids:
        return {}
    res = await db.execute(
        select(Message.conversation_id, func_count())
        .where(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
    )
    return {row[0]: int(row[1]) for row in res.all()}


def func_count():  # tiny helper so the import is local
    from sqlalchemy import func
    return func.count(Message.id)


def _summary_from(row: Conversation, message_count: int) -> ConversationSummary:
    return ConversationSummary(
        id=str(row.id),
        title=row.title,
        agent_id=str(row.agent_id),
        agent_template_id=getattr(row.agent, "template_id", None) if row.agent else None,
        last_message_at=_isoformat(row.last_message_at),
        message_count=message_count,
        archived=row.archived_at is not None,
        created_at=_isoformat(row.created_at) or "",
    )


async def _load_conversation_for_org(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conv_id: uuid.UUID,
) -> Conversation | None:
    res = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.org_id == org_id,
        )
    )
    return res.scalar_one_or_none()


# ──────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, description="Opaque cursor (last_message_at|id)"),
    agent_id: str | None = Query(default=None),
    archived: bool | None = Query(default=None),
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    """List conversations the current user owns in the active org.

    Cursor format: ``"<iso8601>|<uuid>"`` — the same shape the
    endpoint returns in ``next_cursor``. We use string-based
    cursoring so the FE doesn't need a custom parser.
    """
    stmt = select(Conversation).where(
        Conversation.org_id == org.id,
        Conversation.user_id == user.id,
    )
    if agent_id:
        try:
            stmt = stmt.where(Conversation.agent_id == uuid.UUID(agent_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id")
    if archived is True:
        stmt = stmt.where(Conversation.archived_at.is_not(None))
    elif archived is False:
        stmt = stmt.where(Conversation.archived_at.is_(None))

    # Cursor: conversations with ``last_message_at`` < cursor_ts, OR
    # (same ts AND id < cursor_id). We sort by ``(last_message_at
    # DESC NULLS LAST, id DESC)`` so the newest conversation is first.
    if cursor:
        head, sep, tail = cursor.partition("|")
        if not sep:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        cur_ts = _parse_iso(head)
        try:
            cur_id = uuid.UUID(tail)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        if cur_ts is None:
            raise HTTPException(status_code=400, detail="Invalid cursor timestamp")
        stmt = stmt.where(
            or_(
                Conversation.last_message_at.is_(None),
                Conversation.last_message_at < cur_ts,
                and_(
                    Conversation.last_message_at == cur_ts,
                    Conversation.id < cur_id,
                ),
            )
        )

    # Nulls are tricky in ORDER BY — pin them last explicitly. On
    # SQLite the NULLS LAST clause is also supported (3.30+).
    from sqlalchemy import nulls_last
    stmt = stmt.order_by(
        nulls_last(Conversation.last_message_at.desc()),
        Conversation.id.desc(),
    ).limit(limit + 1)

    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    has_more = len(rows) > limit
    page = rows[:limit]
    counts = await _count_messages_per_conv(db, [c.id for c in page])
    summaries = [_summary_from(c, counts.get(c.id, 0)) for c in page]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        if last.last_message_at is not None:
            next_cursor = f"{last.last_message_at.isoformat()}|{last.id}"
    return ConversationListResponse(
        conversations=summaries,
        next_cursor=next_cursor,
    )


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: uuid.UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conv = await _load_conversation_for_org(db, org_id=org.id, conv_id=conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.id:
        # Cross-user 404 — don't leak existence.
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    msgs = list(msgs_res.scalars().all())
    return ConversationDetail(
        id=str(conv.id),
        title=conv.title,
        agent_id=str(conv.agent_id),
        agent_template_id=getattr(conv.agent, "template_id", None) if conv.agent else None,
        archived=conv.archived_at is not None,
        created_at=_isoformat(conv.created_at) or "",
        last_message_at=_isoformat(conv.last_message_at),
        messages=[
            MessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                created_at=_isoformat(m.created_at) or "",
                tool_call=m.tool_call,
                tool_name=m.tool_name,
                tool_action=m.tool_action,
                tool_result=m.tool_result,
                truncated_at=_isoformat(m.truncated_at),
            )
            for m in msgs
        ],
    )


@router.patch("/{conv_id}", response_model=ConversationSummary)
async def update_conversation(
    conv_id: uuid.UUID,
    body: ConversationPatch,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationSummary:
    conv = await _load_conversation_for_org(db, org_id=org.id, conv_id=conv_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if body.title is not None:
        conv.title = body.title.strip() or None
    if body.archived is not None:
        conv.archived_at = datetime.now(timezone.utc) if body.archived else None
    await db.flush()
    counts = await _count_messages_per_conv(db, [conv.id])
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="conversation_updated",
        metadata={"conversation_id": str(conv.id), "fields": list(body.model_dump(exclude_unset=True).keys())},
    )
    await db.commit()
    return _summary_from(conv, counts.get(conv.id, 0))


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _load_conversation_for_org(db, org_id=org.id, conv_id=conv_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Messages cascade via the Conversation.messages relationship
    # (``cascade="all, delete-orphan"``), so deleting the row is
    # enough.
    await db.delete(conv)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="conversation_deleted",
        metadata={"conversation_id": str(conv_id)},
    )
    await db.commit()


@router.post("/import", response_model=ImportResult)
async def import_conversations(
    body: ImportRequest,
    request: Request,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportResult:
    """Bulk-import legacy localStorage conversations.

    Rate limit: 5 calls per user per hour. The actual enforcement is
    in the rate-limit dep wired by PR4's chat.py changes — this
    endpoint just returns 429 if the slowapi decorator triggers.

    The endpoint is atomic per-call: either all valid conversations
    are committed, or none. Invalid rows are reported in
    ``failure_reasons`` but do not abort the whole import (so a
    single bad row doesn't wipe out 199 good ones).
    """
    # Inline Redis-based rate limit (5/user/hour). slowapi's Limiter
    # is configured per-app at startup, not per-module — the inline
    # path keeps the test surface tight (we mock the Redis call).
    redis_key = f"rl:import:{user.id}"
    try:
        from app.services.ai.langgraph_pipeline import _redis
        r = await _redis()
        if r is not None:
            count = await r.incr(redis_key)
            if count == 1:
                await r.expire(redis_key, 3600)
            if count > 5:
                raise HTTPException(status_code=429, detail="Import rate limit exceeded (5/hour).")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("Rate limit Redis check failed (allowing): %s", exc)

    total_messages = sum(len(c.messages) for c in body.conversations)
    if total_messages > _MAX_IMPORT_TOTAL_MESSAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Import payload exceeds {_MAX_IMPORT_TOTAL_MESSAGES} messages",
        )

    inserted = 0
    deduplicated = 0
    failure_reasons: list[str] = []

    # Resolve agent per-conversation. If the FE has an agent_id and
    # it belongs to this org, use it; otherwise fall back to the
    # user's first active agent.
    fallback_agent_res = await db.execute(
        select(Conversation.agent_id)
        .where(Conversation.org_id == org.id, Conversation.user_id == user.id)
        .limit(1)
    )
    fallback_agent_id = fallback_agent_res.scalar_one_or_none()

    for c in body.conversations:
        # Dedup: skip if a conversation with this legacy_client_id
        # already exists in this org.
        existing = await db.execute(
            select(Conversation).where(
                Conversation.org_id == org.id,
                Conversation.legacy_client_id == c.legacy_client_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            deduplicated += 1
            continue

        agent_id: uuid.UUID | None = None
        if c.agent_id:
            try:
                aid = uuid.UUID(c.agent_id)
                # Verify the agent belongs to this org.
                from app.models.agent import Agent
                ag = await db.execute(
                    select(Agent).where(Agent.id == aid, Agent.org_id == org.id, Agent.status != "deleted")
                )
                if ag.scalar_one_or_none() is not None:
                    agent_id = aid
            except ValueError:
                pass
        if agent_id is None:
            agent_id = fallback_agent_id
        if agent_id is None:
            failure_reasons.append(f"no_agent:{c.legacy_client_id}")
            continue

        created_at = _parse_iso(c.created_at) or datetime.now(timezone.utc)
        last_message_at = _parse_iso(c.last_message_at)

        conv = Conversation(
            org_id=org.id,
            agent_id=agent_id,
            user_id=user.id,
            title=(c.title or "").strip()[:255] or None,
            legacy_client_id=c.legacy_client_id,
            created_at=created_at,
            last_message_at=last_message_at,
        )
        db.add(conv)
        try:
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            failure_reasons.append(f"db_error:{c.legacy_client_id}:{exc}")
            continue

        for m in c.messages:
            db.add(
                Message(
                    conversation_id=conv.id,
                    role=m.role,
                    content=m.content,
                    tool_call=m.tool_call,
                    tool_name=m.tool_name,
                    tool_action=m.tool_action,
                    tool_result=m.tool_result,
                    created_at=_parse_iso(m.created_at) or created_at,
                )
            )
        inserted += 1

    await db.commit()
    return ImportResult(
        inserted=inserted,
        deduplicated=deduplicated,
        failed=len(failure_reasons),
        failure_reasons=failure_reasons[:50],  # cap log noise
    )


__all__ = ["router"]
