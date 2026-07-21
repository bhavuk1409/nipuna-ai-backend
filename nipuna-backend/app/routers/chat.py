"""Chat router — powers the AI Command Center.

Endpoints:
  POST /chat/send        — standard request/response
  GET  /chat/stream      — Server-Sent Events (real-time tokens + tool indicators)
  GET  /chat/history     — fetch conversation history for an agent
"""

import json
import logging
import time
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


async def require_chat_permission(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Viewers cannot send chat messages — only admin and member roles can.

    Reads the role from the active `OrganizationMember` row (the
    multi-org source of truth).
    """
    from app.models.organization_member import OrganizationMember
    res = await db.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == user.active_org_id,
            OrganizationMember.status == "active",
        )
    )
    role = res.scalar_one_or_none() or "viewer"
    if role == "viewer":
        raise HTTPException(
            status_code=403,
            detail="Viewers have read-only access and cannot use the AI chat."
        )
    return user


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

    # If no agent exists, auto-create a default one from the
    # `general_assistant` template. The template owns name, domain,
    # objective, icon, and color; the agent row records the
    # template_id for later identification in the UI.
    from app.services.ai.agent_templates import get_template
    template = get_template("general_assistant")
    agent = Agent(
        org_id=org_id,
        name=template.name,
        domain=template.domain,
        objective=template.objective,
        status="active",
        created_by=user_id,
        template_id=template.id,
        icon=template.icon,
        color=template.color,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _get_rag_chunks(org: Organization, query: str, db: AsyncSession) -> list[dict]:
    """Run vector search for the query; silently skip if no embedding provider configured.

    Single source of truth for "is RAG enabled?" lives on
    ``embedding_client.enabled`` — the Groq-vs-OpenAI branch
    previously inlined here is gone (Groq has no embeddings; the
    check is now "do we have *any* embedding provider?").
    """
    try:
        from app.services.ai.embedding_client import embedding_client
        from app.services.ai import pgvector_store

        if not embedding_client.enabled:
            return []

        embedding = await embedding_client.embed(query)
        if not embedding:
            return []

        hits = await pgvector_store.search(
            db=db,
            org_id=org.id,
            query_embedding=embedding,
            top_k=5,
        )
        return [
            {
                "doc_id": h.doc_id,
                "text": h.text,
                "score": h.score,
            }
            for h in hits
        ]
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
    user: User = Depends(require_chat_permission),
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

    # PR4 — generate a sidebar title from the first user message,
    # fire-and-forget. Pure function, no LLM. The block is inside
    # the (sync) request scope so we just do it inline; the result
    # is a single UPDATE.
    if not conversation.title and body.content:
        from app.services.conversations.titler import generate_title
        new_title = generate_title(body.content)
        if new_title:
            conversation.title = new_title
            await db.flush()

    # Load full history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = list(history_result.scalars().all())

    # RAG search for relevant knowledge-base chunks
    rag_chunks = await _get_rag_chunks(org, body.content, db)

    # PR4 — fetch the user's top memories and render the
    # ``KNOWN FACTS ABOUT THIS USER`` block for the system prompt.
    from app.services.memory import manager as memory_manager
    memory_facts = await memory_manager.facts_for_injection(
        db,
        user_id=str(user.id),
        org_id=str(org.id),
    )
    memory_block = memory_manager.build_memory_block(memory_facts)

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
        memory_block=memory_block,
    )

    # Save final AI response
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=pipeline_result.answer,
    )
    db.add(assistant_msg)

    # Deduct one AI credit per turn atomically (floor at 0 to prevent negatives)
    from sqlalchemy import text
    await db.execute(
        text("UPDATE organizations SET ai_credits = ai_credits - 1 WHERE id = :org_id AND ai_credits > 0"),
        {"org_id": org.id}
    )

    await db.commit()

    # PR4 — fire-and-forget memory extraction. Runs in a fresh DB
    # session so the request's commit above is visible; the
    # extractor's own commit runs in its own session. Failures are
    # swallowed (best-effort).
    import asyncio
    try:
        from app.services.memory import extractor as memory_extractor
        from app.database import AsyncSessionLocal

        async def _run_extractor():
            try:
                async with AsyncSessionLocal() as ex_db:
                    await memory_extractor.extract_and_persist(
                        ex_db,
                        user_id=str(user.id),
                        org_id=str(org.id),
                        conversation_id=str(conversation.id),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Memory extractor (non-stream) failed: %s", exc)

        asyncio.create_task(_run_extractor())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not schedule memory extractor: %s", exc)

    return ChatResponse(
        content=pipeline_result.answer,
        conversation_id=str(conversation.id),
        tool_calls_made=pipeline_result.tool_calls_made,
    )


# ──────────────────────────────────────────────────────────────────
# GET /chat/stream — Server-Sent Events
# ──────────────────────────────────────────────────────────────────

# Heartbeat: how often (in seconds) to emit a `: ping\n\n` comment
# while the queue is empty and the background task is still
# running. This keeps proxies (nginx, CloudFront) from closing the
# SSE connection during long tool execution.
HEARTBEAT_INTERVAL_S = 15.0

# Incremental persistence: commit partial assistant messages to the
# DB every N tokens so a disconnect doesn't lose the whole answer.
INCREMENTAL_PERSIST_EVERY_N_TOKENS = 100

# First-non-trivial-event deduct: the credit deduct happens on the
# first of (a) this many tokens emitted, (b) a successful tool
# call, or (c) a persisted assistant message >= this many chars.
# Below these thresholds, the turn is "free" (the user got nothing
# of value).
CREDIT_DEDUCT_MIN_TOKENS = 5
CREDIT_DEDUCT_MIN_MESSAGE_CHARS = 50


@router.post("/stream")
async def stream_message(
    body: ChatRequest,
    request: Request,
    org: Organization = Depends(get_current_org),
    user: User = Depends(require_chat_permission),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint. Frontend connects with EventSource and receives events:

      data: {"type": "thinking", "content": "..."}
      data: {"type": "tool_start", "tool_name": "gmail_search_emails"}
      data: {"type": "tool_end",   "tool_name": "gmail_search_emails", "tool_result": "..."}
      data: {"type": "token",      "content": "..."}
      data: {"type": "done",       "content": "...", "conversation_id": "..."}
      data: {"type": "error",      "content": "..."}

    PR3 hardening:
      - `request.is_disconnected()` polled every 50ms inside the
        event generator. On disconnect, the cancel_event is set so
        the background pipeline aborts at the next node boundary.
      - `: ping\\n\\n` heartbeat comments emitted every 15s while
        the queue is empty (i.e. during long tool execution).
      - Assistant message persisted incrementally every
        INCREMENTAL_PERSIST_EVERY_N_TOKENS tokens; on disconnect the
        partial answer survives in the DB with `truncated_at = now()`.
      - Credit deduct happens on the first non-trivial event (≥5
        tokens, successful tool, or persisted message ≥50 chars).
        Once deducted, the turn is billed even on disconnect.
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

    # PR4 — generate a sidebar title from the first user message.
    if not conversation.title and body.content:
        from app.services.conversations.titler import generate_title
        new_title = generate_title(body.content)
        if new_title:
            conversation.title = new_title
            await db.flush()

    # PR4 — fetch the user's top memories for the system prompt.
    from app.services.memory import manager as memory_manager
    memory_facts = await memory_manager.facts_for_injection(
        db,
        user_id=str(user.id),
        org_id=str(org.id),
    )
    memory_block = memory_manager.build_memory_block(memory_facts)

    # Load history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    history = list(history_result.scalars().all())
    rag_chunks = await _get_rag_chunks(org, body.content, db)

    # Set up the cancel signal and the pre-pipeline bookkeeping.
    import asyncio
    cancel_event = asyncio.Event()
    # Pre-create the assistant message row so we can update it
    # incrementally as tokens arrive. The row starts empty; on
    # disconnect, we set `truncated_at = now()` and commit whatever
    # we have so the user sees a partial answer.
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        tokens_used=0,
    )
    db.add(assistant_msg)
    await db.flush()

    async def event_generator():
        nonlocal_assistant_msg = assistant_msg
        token_buffer: list[str] = []
        tokens_emitted = 0
        credit_deducted = False
        last_persist_at_tokens = 0
        last_heartbeat = time.monotonic()
        disconnected = False
        final_answer = ""
        tool_calls_made = 0

        async def _deduct_credit_once() -> None:
            """Deduct one credit at most once per turn. Idempotent
            on the same connection — a re-call is a no-op.
            """
            nonlocal credit_deducted
            if credit_deducted:
                return
            credit_deducted = True
            from sqlalchemy import text
            await db.execute(
                text(
                    "UPDATE organizations SET ai_credits = ai_credits - 1 "
                    "WHERE id = :org_id AND ai_credits > 0"
                ),
                {"org_id": org.id},
            )
            logger.debug("Credit deducted for org=%s turn=%s", org.id, conversation.id)

        async def _persist_assistant_partial() -> None:
            """Commit whatever tokens are in the buffer to the DB
            so a disconnect doesn't lose the work.
            """
            if not token_buffer:
                return
            new_content = (nonlocal_assistant_msg.content or "") + "".join(token_buffer)
            token_buffer.clear()
            nonlocal_assistant_msg.content = new_content
            nonlocal_assistant_msg.tokens_used = (
                (nonlocal_assistant_msg.tokens_used or 0) + tokens_emitted
            )
            try:
                await db.commit()
            except Exception as exc:
                logger.warning("Incremental persist failed: %s", exc)
                try:
                    await db.rollback()
                except Exception:
                    pass

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
                cancel_event=cancel_event,
                memory_block=memory_block,
            ):
                # Check disconnect on every event. Setting the
                # cancel_event here lets the background task exit
                # at the next node boundary.
                if await request.is_disconnected():
                    logger.info("SSE client disconnected; setting cancel_event")
                    cancel_event.set()
                    disconnected = True
                    break

                # First-non-trivial-event deduct.
                if not credit_deducted:
                    if event.type == "token":
                        tokens_emitted += 1
                        if tokens_emitted >= CREDIT_DEDUCT_MIN_TOKENS:
                            await _deduct_credit_once()
                    elif event.type == "tool_end":
                        # tool_end with a non-error result counts
                        # as non-trivial.
                        if event.tool_result and "ERROR" not in (event.tool_result or ""):
                            await _deduct_credit_once()

                # Buffer tokens for incremental persist.
                if event.type == "token" and event.content:
                    token_buffer.append(event.content)

                # Periodically persist partial assistant content.
                if (
                    event.type == "token"
                    and tokens_emitted - last_persist_at_tokens
                    >= INCREMENTAL_PERSIST_EVERY_N_TOKENS
                ):
                    await _persist_assistant_partial()
                    last_persist_at_tokens = tokens_emitted

                # On a successful tool, also persist so the partial
                # answer survives a disconnect mid-tool.
                if event.type == "tool_end" and token_buffer:
                    await _persist_assistant_partial()
                    last_persist_at_tokens = tokens_emitted

                # Emit the event to the SSE client.
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
                    # PR4 — fire-and-forget memory extraction after
                    # the conversation completes a real turn. We
                    # only schedule if the turn actually produced
                    # something the user could read (≥50 chars);
                    # otherwise we'd extract from greetings.
                    if final_answer and len(final_answer) >= 50:
                        try:
                            from app.services.memory import extractor as memory_extractor
                            from app.database import AsyncSessionLocal
                            import asyncio

                            async def _run_extractor():
                                try:
                                    async with AsyncSessionLocal() as ex_db:
                                        await memory_extractor.extract_and_persist(
                                            ex_db,
                                            user_id=str(user.id),
                                            org_id=str(org.id),
                                            conversation_id=str(conversation.id),
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    logger.debug("Memory extractor (stream) failed: %s", exc)

                            asyncio.create_task(_run_extractor())
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Could not schedule memory extractor: %s", exc)

                # First-non-trivial-event deduct on persisted
                # message (in case we never hit a token / tool
                # threshold but the message is substantive).
                if (
                    not credit_deducted
                    and event.type == "done"
                    and final_answer
                    and len(final_answer) >= CREDIT_DEDUCT_MIN_MESSAGE_CHARS
                ):
                    await _deduct_credit_once()

            # Drain the buffer at the end of the stream.
            await _persist_assistant_partial()

            # Set conversation.last_message_at so the sidebar
            # list (added in PR4) shows the right order.
            try:
                from sqlalchemy import update
                from app.models.conversation import Conversation
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation.id)
                    .values(last_message_at=nonlocal_assistant_msg.created_at or None)
                )
                await db.commit()
            except Exception as exc:
                logger.debug("last_message_at update failed: %s", exc)

        except asyncio.CancelledError:
            disconnected = True
            cancel_event.set()
            logger.info("SSE generator cancelled (likely disconnect)")
        except Exception as exc:
            logger.error("SSE pipeline error: %s", exc, exc_info=True)
            yield "data: " + json.dumps({"type": "error", "content": str(exc)}) + "\n\n"

        finally:
            # On disconnect, mark the message as truncated so the
            # FE can render "...response cut off" and the user
            # knows it's not a complete answer. The credit deduct
            # is preserved — we don't refund.
            if disconnected or cancel_event.is_set():
                try:
                    from datetime import datetime, timezone
                    from sqlalchemy import update
                    await db.execute(
                        update(Message)
                        .where(Message.id == nonlocal_assistant_msg.id)
                        .values(
                            truncated_at=datetime.now(timezone.utc),
                            content=nonlocal_assistant_msg.content,
                        )
                    )
                    await db.commit()
                    logger.info(
                        "Marked assistant message %s as truncated for conv=%s",
                        nonlocal_assistant_msg.id, conversation.id,
                    )
                except Exception as exc:
                    logger.warning("Failed to set truncated_at: %s", exc)
                    try:
                        await db.rollback()
                    except Exception:
                        pass

    # Wraps the event_generator so we can also emit heartbeats
    # when the queue is empty (long tool execution). The wrapper
    # races the next event against the heartbeat, but on a
    # heartbeat it does NOT cancel the inner event_task — that
    # would tear down the long-running generator. Instead we
    # leave the task running and just emit a ping. The next
    # iteration of the loop re-awaits the same task.
    async def wrapped_event_generator():
        inner = event_generator()
        inner_task: asyncio.Task | None = None

        async def _start_next() -> asyncio.Task:
            """Wrap the inner generator's __anext__ in a task so
            we can race it against the heartbeat.
            """
            return asyncio.create_task(inner.__anext__())

        inner_task = await _start_next()

        while True:
            try:
                heartbeat_task = asyncio.create_task(
                    asyncio.sleep(HEARTBEAT_INTERVAL_S)
                )
                done, pending = await asyncio.wait(
                    {inner_task, heartbeat_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if inner_task in done:
                    # Cancel the heartbeat (still pending) and
                    # yield the result.
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    try:
                        ev = inner_task.result()
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        # Inner was cancelled (e.g. disconnect).
                        break
                    yield ev
                    # Start a fresh task for the next event.
                    inner_task = await _start_next()
                else:
                    # Heartbeat fired; inner is still running.
                    # Emit a ping and continue.
                    yield ": ping\n\n"
                    # heartbeat_task is done; don't cancel inner.
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                if inner_task is not None and not inner_task.done():
                    inner_task.cancel()
                    try:
                        await inner_task
                    except (asyncio.CancelledError, Exception):
                        pass
                break
            except Exception as exc:
                logger.error("SSE wrapper error: %s", exc)
                yield "data: " + json.dumps({"type": "error", "content": str(exc)}) + "\n\n"
                if inner_task is not None and not inner_task.done():
                    inner_task.cancel()
                break

    return StreamingResponse(
        wrapped_event_generator(),
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
    conversation_id: str | None = None,
    limit: int = 50,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent messages for the given conversation or agent."""
    # If conversation_id is provided, return that specific conversation
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(conversation_id.replace("chat-", ""))
            conv_result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conv_uuid,
                    Conversation.org_id == org.id,
                )
            )
            conversation = conv_result.scalar_one_or_none()
            if conversation:
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
        except ValueError:
            pass

    # Otherwise return most recent conversation for the agent
    agent = await _get_or_create_default_agent(db, org.id, user.id, agent_id)

    result = await db.execute(
        select(Conversation).where(
            Conversation.org_id == org.id,
            Conversation.agent_id == agent.id,
            Conversation.user_id == user.id,
        ).order_by(Conversation.created_at.desc())
    )
    conversation = result.scalars().first()
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
