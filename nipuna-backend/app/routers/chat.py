"""Chat router — powers the AI Command Center.

Endpoints:
  POST /chat/send        — standard request/response
  GET  /chat/stream      — Server-Sent Events (real-time tokens + tool indicators)
  GET  /chat/history     — fetch conversation history for an agent
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.agent import Agent
from app.models.conversation import Conversation, Message
from app.models.organization import Organization
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai.langgraph_pipeline import (
    PipelineResult,
    run_langgraph_pipeline,
    run_langgraph_pipeline_stream,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

async def _get_or_create_conversation(
    db: AsyncSession,
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: str | None = None,
) -> Conversation:
    """Return an existing conversation or create a new one."""
    conv_uuid: uuid.UUID | None = None
    if conversation_id:
        # Strip "chat-" prefix if present
        clean_id = conversation_id
        if clean_id.startswith("chat-"):
            clean_id = clean_id[5:]
        try:
            conv_uuid = uuid.UUID(clean_id)
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conv_uuid,
                    Conversation.org_id == org_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv:
                return conv
        except ValueError:
            pass

    # If not found or invalid ID, create a new one
    conv = Conversation(org_id=org_id, agent_id=agent_id, user_id=user_id)
    if conv_uuid:
        # Preserve the parsed UUID on the new conversation so that
        # the client doesn't get out of sync with its local ID.
        conv.id = conv_uuid
    db.add(conv)
    await db.flush()
    return conv


async def _get_or_create_default_agent(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, agent_id: str | None = None) -> Agent:
    if agent_id and agent_id != "default" and agent_id != "undefined" and agent_id != "null":
        try:
            agent_uuid = uuid.UUID(agent_id)
            result = await db.execute(
                select(Agent).where(
                    Agent.id == agent_uuid,
                    Agent.org_id == org_id,
                    Agent.status != "deleted",
                )
            )
            agent = result.scalar_one_or_none()
            if agent:
                return agent
        except ValueError:
            pass

    # Check for any active agent for this org
    result = await db.execute(
        select(Agent).where(
            Agent.org_id == org_id,
            Agent.status != "deleted",
        ).order_by(Agent.created_at)
    )
    agent = result.scalar_one_or_none()
    if agent:
        return agent

    # If no agent exists, auto-create a default one
    agent = Agent(
        org_id=org_id,
        name="Nipuna AI",
        domain="General Business",
        objective="Analyze cash flow, invoices, communications, and help run business operations.",
        status="active",
        created_by=user_id,
    )
    db.add(agent)
    await db.flush()
    await db.commit()
    return agent


async def _get_rag_chunks(org: Organization, query: str) -> list[dict]:
    """Run vector search for the query; silently skip if no embedding provider configured."""
    try:
        from app.config import get_settings
        settings = get_settings()
        # Groq doesn't support embeddings — skip to avoid 404 noise
        if (settings.llm_provider or "groq").lower() == "groq" and not settings.openai_api_key:
            return []

        from app.services.ai.embedding_client import embedding_client
        from app.services.ai.vector_store import vector_store

        embedding = await embedding_client.embed(query)
        if embedding:
            return await vector_store.search(str(org.id), embedding)
    except Exception as exc:
        logger.debug("RAG search failed (non-fatal): %s", exc)
    return []


# ──────────────────────────────────────────────────────────────────
# POST /chat/send — standard round-trip
# ──────────────────────────────────────────────────────────────────

@router.post("/send", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    if org.ai_credits <= 0:
        raise HTTPException(
            status_code=402,
            detail="AI credits exhausted. Please upgrade your plan.",
        )

    agent = await _get_or_create_default_agent(db, org.id, user.id, body.agent_id)

    conversation = await _get_or_create_conversation(
        db=db,
        org_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        conversation_id=body.conversation_id,
    )

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()

    # Load full history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = list(history_result.scalars().all())

    # RAG search for relevant knowledge-base chunks
    rag_chunks = await _get_rag_chunks(org, body.content)

    # Run the LangGraph zero-hallucination pipeline
    pipeline_result: PipelineResult = await run_langgraph_pipeline(
        org=org,
        agent=agent,
        conversation_history=history,
        db=db,
        rag_chunks=rag_chunks,
        conversation_id=str(conversation.id),
        high_intel=body.high_intel if body.high_intel is not None else True,
        query_datasources=body.query_datasources if body.query_datasources is not None else True,
        tone=body.tone,
        currency=body.currency,
        memory=body.memory,
        attachments=body.attachments,
    )

    # Save final AI response
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=pipeline_result.answer,
    )
    db.add(assistant_msg)

    # Deduct one AI credit per turn atomically
    from sqlalchemy import text
    await db.execute(
        text("UPDATE organizations SET ai_credits = ai_credits - 1 WHERE id = :org_id"),
        {"org_id": org.id}
    )

    await db.commit()

    return ChatResponse(
        content=pipeline_result.answer,
        conversation_id=str(conversation.id),
        tool_calls_made=pipeline_result.tool_calls_made,
    )


# ──────────────────────────────────────────────────────────────────
# GET /chat/stream — Server-Sent Events
# ──────────────────────────────────────────────────────────────────

@router.post("/stream")
async def stream_message(
    body: ChatRequest,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE endpoint. Frontend connects with EventSource and receives events:
      data: {"type": "thinking", "content": "..."}
      data: {"type": "tool_start", "tool_name": "gmail_search_emails"}
      data: {"type": "tool_end",   "tool_name": "gmail_search_emails", "tool_result": "..."}
      data: {"type": "token",      "content": "..."}
      data: {"type": "done",       "content": "...", "conversation_id": "..."}
      data: {"type": "error",      "content": "..."}
    """
    if org.ai_credits <= 0:
        async def credits_err():
            yield "data: " + json.dumps({"type": "error", "content": "AI credits exhausted."}) + "\n\n"
        return StreamingResponse(credits_err(), media_type="text/event-stream")

    agent = await _get_or_create_default_agent(db, org.id, user.id, body.agent_id)

    conversation = await _get_or_create_conversation(
        db=db,
        org_id=org.id,
        agent_id=agent.id,
        user_id=user.id,
        conversation_id=body.conversation_id,
    )

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()

    # Load history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = list(history_result.scalars().all())
    rag_chunks = await _get_rag_chunks(org, body.content)

    async def event_generator():
        final_answer = ""
        tool_calls_made = 0
        try:
            async for event in run_langgraph_pipeline_stream(
                org=org,
                agent=agent,
                conversation_history=history,
                db=db,
                rag_chunks=rag_chunks,
                conversation_id=str(conversation.id),
                high_intel=body.high_intel if body.high_intel is not None else True,
                query_datasources=body.query_datasources if body.query_datasources is not None else True,
                tone=body.tone,
                currency=body.currency,
                memory=body.memory,
                attachments=body.attachments,
            ):
                # We can't check request.is_disconnected() easily inside the generator 
                # without passing the request object, but yielding to a disconnected client
                # will raise a ClientDisconnect exception.

                payload = {
                    "type": event.type,
                    "content": event.content,
                    "tool_name": event.tool_name,
                    "tool_result": event.tool_result,
                    "conversation_id": event.conversation_id,
                    "tool_calls_made": event.tool_calls_made,
                }
                yield "data: " + json.dumps(payload) + "\n\n"

                if event.type == "done":
                    final_answer = event.content or ""
                    tool_calls_made = event.tool_calls_made or 0

            # Persist final answer + deduct credit
            if final_answer:
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=final_answer,
                )
                db.add(assistant_msg)
                
                from sqlalchemy import text
                await db.execute(
                    text("UPDATE organizations SET ai_credits = ai_credits - 1 WHERE id = :org_id"),
                    {"org_id": org.id}
                )
                await db.commit()

        except Exception as exc:
            logger.error("SSE pipeline error: %s", exc, exc_info=True)
            yield "data: " + json.dumps({"type": "error", "content": str(exc)}) + "\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────────────────────────
# GET /chat/history — fetch conversation messages
# ──────────────────────────────────────────────────────────────────

@router.get("/history")
async def get_chat_history(
    agent_id: str | None = None,
    limit: int = 50,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent messages for the given agent's conversation with this user."""
    agent = await _get_or_create_default_agent(db, org.id, user.id, agent_id)

    result = await db.execute(
        select(Conversation).where(
            Conversation.org_id == org.id,
            Conversation.agent_id == agent.id,
            Conversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return {"conversation_id": None, "messages": []}

    msgs_result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.role.in_(["user", "assistant"]),
            Message.tool_call.is_(False),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    msgs = list(reversed(msgs_result.scalars().all()))

    return {
        "conversation_id": str(conversation.id),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "tool_calls_made": 1 if m.tool_call else 0,
            }
            for m in msgs
        ],
    }
