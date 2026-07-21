"""Memory extraction from a completed conversation.

The extractor runs *out of band* — never on the request path. After a
conversation is marked complete (a "done" SSE event lands, or a
``/chat/send`` returns 200), the caller schedules a fire-and-forget
``asyncio.create_task(extract_and_persist(...))`` that:

  1. Throttles: skip if the user has been extracted in the last 24h
     (stored in Redis as ``mem:extracted:<user_id>``).
  2. Asks ``gpt-4o-mini`` (NOT Groq — Groq's structured-output support
     is unreliable as of mid-2025) to extract a small list of facts
     from the user messages in the conversation, with a strict JSON
     schema: ``[{"key": str, "value": str, "confidence": 0-100}]``.
  3. Diffs the result against the user's existing memories:
     - new key  → INSERT
     - existing key with the same/different value → UPDATE value +
       bump ``updated_at``; if the new value contradicts the old,
       archive the old row and INSERT a new one so the provenance
       trail is preserved.
  4. Persists each row with ``value_encrypted`` (Fernet) + legacy
     ``value`` plaintext mirror for the one-release rollback window.

If OpenAI is not configured (``OPENAI_API_KEY`` missing), the
extractor is a no-op. This is the dev-default — we never want to
crash a chat because the memory sidecar is offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.user_memory import UserMemory

logger = logging.getLogger(__name__)


# OpenAI-mini is fine for the structured output; the call is small
# (~200 input tokens for a 5-message thread) and OpenAI's structured
# output schema enforcement is more reliable than Groq's.
_EXTRACTOR_MODEL = "gpt-4o-mini"

# 24h throttle. The plan says "24h per user"; a per-user key in Redis
# (no DB column) keeps the extractor stateless.
_THROTTLE_WINDOW = timedelta(hours=24)

# Hard caps. The plan says "cap memories at 5 until we have data" but
# the *extractor* can yield more — the manager caps what gets
# injected. Cap the extractor's yield so we don't blow the LLM budget
# on a 50-message thread.
_MAX_USER_MESSAGES = 12
_MAX_EXTRACTED_FACTS = 5

# Confidence below this is dropped. "user mentioned they prefer
# bullet points" (50) survives; "user maybe works in finance" (30)
# doesn't.
_MIN_CONFIDENCE = 40


@dataclass(frozen=True)
class ExtractedFact:
    key: str
    value: str
    confidence: int


@dataclass(frozen=True)
class ExtractionResult:
    """Summary of one extraction run. Returned for logging / tests."""
    facts_extracted: int
    facts_inserted: int
    facts_updated: int
    facts_archived: int
    skipped_reason: str | None = None


def _is_contradiction(old_value: str, new_value: str) -> bool:
    """Heuristic contradiction check.

    We only check the trivial "is / is not" pattern. Anything more
    elaborate (negation, role reversal) requires an LLM pass; the
    current plan defers that to "after usage data".

    Examples that fire:
      - "user is single"  vs  "user is not single"
      - "uses Tally"      vs  "does not use Tally"

    Examples that don't fire (left for the LLM to handle later):
      - "user is a CFO"  vs  "user is a CEO"  (different roles, not
        a strict negation — could be a job change)
    """
    if not old_value or not new_value:
        return False
    o = old_value.lower()
    n = new_value.lower()
    if o == n:
        return False
    # Look for a key noun-phrase in one sentence that appears in the
    # other. We strip common copular forms ("is", "uses", "has",
    # "prefers") to get a 1-3 word tail that should match across
    # paraphrases.
    def _tail(s: str) -> str:
        for prefix in (
            "user is ", "user uses ", "user has ", "user prefers ",
            "user works with ", "is ", "uses ", "has ", "prefers ",
        ):
            if s.startswith(prefix):
                return s[len(prefix):]
        return s

    o_tail = _tail(o)
    n_tail = _tail(n)
    # A tail is a contradiction if it appears in the other sentence
    # and that sentence also contains a negation near the tail.
    for short, long_ in ((o_tail, n), (n_tail, o)):
        if short and short in long_:
            for neg in (
                " not ", " no ", " never ", " isn't ", " doesn't ",
                " don't ", " without ",
            ):
                if neg in long_:
                    return True
    return False


def _redis_key(user_id: str) -> str:
    return f"mem:extracted:{user_id}"


async def _get_redis():
    """Return the Redis client used by the throttle, or None.

    Indirection so tests can monkeypatch this without also patching
    the langgraph_pipeline module.
    """
    try:
        from app.services.ai.langgraph_pipeline import _redis
        return await _redis()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Redis client init failed: %s", exc)
        return None


async def _throttle_check(user_id: str) -> bool:
    """Return True if extraction is allowed for this user right now.

    Best-effort: if Redis is unavailable, allow the call. We'd rather
    pay an extra LLM cost than silently drop a memory.
    """
    try:
        r = await _get_redis()
        if r is None:
            return True
        key = _redis_key(user_id)
        # SETNX with a 24h expiry — only the first caller within the
        # window wins. Subsequent calls within the window see the key
        # and bail.
        ok = await r.set(key, "1", ex=int(_THROTTLE_WINDOW.total_seconds()), nx=True)
        return bool(ok)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Throttle check failed (allowing extract): %s", exc)
        return True


async def _gather_user_messages(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> list[str]:
    """Pull the last ``_MAX_USER_MESSAGES`` user messages for the LLM."""
    res = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc())
        .limit(_MAX_USER_MESSAGES)
    )
    rows = list(reversed(res.scalars().all()))
    return [m.content for m in rows if m.content]


def _llm_extract(messages: list[str]) -> list[ExtractedFact]:
    """Call OpenAI's gpt-4o-mini with structured output and return the
    parsed facts. Returns an empty list on any failure — the extractor
    is best-effort.
    """
    if not messages:
        return []
    try:
        # Imported lazily so a misconfigured OpenAI key doesn't break
        # app import. The dependency is already in the project's
        # requirements (langchain-openai pulls it).
        from openai import OpenAI
    except ImportError:
        logger.debug("openai package not installed; memory extractor disabled")
        return []

    try:
        from app.config import get_settings
        settings = get_settings()
        if not settings.openai_api_key:
            return []
        client = OpenAI(api_key=settings.openai_api_key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("OpenAI client init failed: %s", exc)
        return []

    system_prompt = (
        "You extract stable, durable user facts from a chat. "
        "Return a JSON object with a `facts` array. Each fact has "
        "`key` (snake_case, ≤40 chars), `value` (≤200 chars), and "
        "`confidence` (0-100; 100 = explicitly stated as a fact, "
        "60 = strongly implied, 40 = weakly implied, <40 = don't extract).\n\n"
        "Only extract facts that:\n"
        "  - are stated about the user (not the assistant)\n"
        "  - will still be true in a week\n"
        "  - are useful in a future conversation (role, company, "
        "    preferences, recurring entities, tools they use)\n\n"
        "Do NOT extract: one-off questions, transient plans, "
        "numerical answers to specific queries, or facts about the "
        "AI's behaviour. If there are no facts, return `{\"facts\": []}`."
    )

    user_prompt = (
        "Conversation (most recent last):\n\n"
        + "\n\n---\n\n".join(messages)
        + "\n\nExtract the facts."
    )

    try:
        response = client.chat.completions.create(
            model=_EXTRACTOR_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "memory_extraction",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "facts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string"},
                                        "value": {"type": "string"},
                                        "confidence": {"type": "integer"},
                                    },
                                    "required": ["key", "value", "confidence"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["facts"],
                        "additionalProperties": False,
                    },
                },
            },
            temperature=0,
            max_tokens=800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Memory extraction LLM call failed: %s", exc)
        return []

    raw = response.choices[0].message.content or "{}"
    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("LLM returned non-JSON: %r", raw)
        return []

    raw_facts = payload.get("facts") or []
    out: list[ExtractedFact] = []
    for f in raw_facts:
        if not isinstance(f, dict):
            continue
        key = (f.get("key") or "").strip()
        value = (f.get("value") or "").strip()
        try:
            conf = int(f.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0
        if not key or not value or conf < _MIN_CONFIDENCE:
            continue
        if len(key) > 64:
            key = key[:64]
        if len(value) > 1000:
            value = value[:1000]
        out.append(ExtractedFact(key=key, value=value, confidence=conf))
        if len(out) >= _MAX_EXTRACTED_FACTS:
            break
    return out


async def _persist_facts(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    conversation_id: str,
    facts: Iterable[ExtractedFact],
) -> tuple[int, int, int]:
    """Upsert the facts. Returns (inserted, updated, archived)."""
    from app.utils.encryption import encrypt_bytes
    import uuid as _uuid

    user_uuid = _uuid.UUID(user_id) if not isinstance(user_id, _uuid.UUID) else user_id
    org_uuid = _uuid.UUID(org_id) if not isinstance(org_id, _uuid.UUID) else org_id
    conv_uuid: _uuid.UUID | None = None
    if conversation_id:
        try:
            conv_uuid = _uuid.UUID(conversation_id)
        except (TypeError, ValueError):
            conv_uuid = None

    existing_res = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_uuid,
            UserMemory.org_id == org_uuid,
            UserMemory.archived.is_(False),
        )
    )
    by_key: dict[str, UserMemory] = {}
    for row in existing_res.scalars().all():
        by_key[(row.key or "").strip().lower()] = row

    inserted = updated = archived = 0
    for fact in facts:
        k_norm = fact.key.strip().lower()
        row = by_key.get(k_norm)
        if row is None:
            # New key — insert.
            new_row = UserMemory(
                user_id=user_uuid,
                org_id=org_uuid,
                key=fact.key,
                value=fact.value,
                value_encrypted=encrypt_bytes(fact.value),
                confidence=fact.confidence,
                source_conversation_id=conv_uuid,
                archived=False,
            )
            db.add(new_row)
            inserted += 1
            continue

        # Existing key — check for contradiction.
        if _is_contradiction(row.value, fact.value) and row.value != fact.value:
            row.archived = True
            db.add(row)
            archived += 1
            replacement = UserMemory(
                user_id=user_uuid,
                org_id=org_uuid,
                key=fact.key,
                value=fact.value,
                value_encrypted=encrypt_bytes(fact.value),
                confidence=fact.confidence,
                source_conversation_id=conv_uuid,
                archived=False,
            )
            db.add(replacement)
            inserted += 1
            continue

        if row.value != fact.value:
            row.value = fact.value
            row.value_encrypted = encrypt_bytes(fact.value)
            row.confidence = fact.confidence
            row.source_conversation_id = conv_uuid
            db.add(row)
            updated += 1
    return inserted, updated, archived


async def extract_and_persist(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    conversation_id: str,
) -> ExtractionResult:
    """Top-level: extract facts from a conversation and persist them.

    Idempotent within a 24h window per user (Redis throttled). Returns
    a summary suitable for logging or for the tests.
    """
    if not await _throttle_check(user_id):
        return ExtractionResult(0, 0, 0, 0, skipped_reason="throttled")

    messages = await _gather_user_messages(db, conversation_id=conversation_id)
    if len(messages) < 3:
        # Plan: "only run if conversation has ≥ 3 user messages". This
        # also catches the "user said hi, then nothing" case where
        # there's nothing to extract.
        return ExtractionResult(0, 0, 0, 0, skipped_reason="too_few_messages")

    facts = _llm_extract(messages)
    if not facts:
        return ExtractionResult(0, 0, 0, 0, skipped_reason="no_facts")

    inserted, updated, archived = await _persist_facts(
        db,
        user_id=user_id,
        org_id=org_id,
        conversation_id=conversation_id,
        facts=facts,
    )
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory persist commit failed: %s", exc)
        await db.rollback()
        return ExtractionResult(len(facts), 0, 0, 0, skipped_reason="commit_failed")

    return ExtractionResult(
        facts_extracted=len(facts),
        facts_inserted=inserted,
        facts_updated=updated,
        facts_archived=archived,
    )


def _payload_hash(payload: dict) -> str:
    """Stable hash for tests — the extractor is otherwise opaque."""
    s = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


__all__ = [
    "ExtractedFact",
    "ExtractionResult",
    "extract_and_persist",
]
