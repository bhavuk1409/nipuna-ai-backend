"""Read-path for user memories.

The manager is the single source of truth for "what facts about this
user do we inject into the system prompt?" It is called once per turn
in ``node_build_tools`` (PR2) before the LLM is invoked.

The manager does three things:

  1. Fetches the top-``max_memories`` active rows for the user
     ordered by ``confidence DESC, updated_at DESC``.
  2. Decrypts ``value_encrypted`` (Fernet), preferring the encrypted
     column when present and falling back to the legacy plaintext
     ``value`` column during the one-release backfill window.
  3. Dedupes by ``key`` (case-insensitive) so a more recent write
     overrides an older one. The first occurrence (highest confidence)
     wins; the row's ``updated_at`` is the tie-breaker.
  4. Formats the result as a ``KNOWN FACTS ABOUT THIS USER`` block for
     the LLM. The block has a hard cap on length so a user with 50
     memories doesn't blow the context window.

If decryption fails for a single row (e.g. a key was rotated in dev
but the row wasn't re-encrypted), the row is silently skipped —
broken rows never surface to the LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import UserMemory

logger = logging.getLogger(__name__)


# Hard cap on injected memories. Plan says 5; the request body may
# override (e.g. a "tell me more about me" feature wants 10) but
# callers should pick from the registered presets.
DEFAULT_MAX_MEMORIES = 5

# Soft cap on the rendered ``KNOWN FACTS ABOUT THIS USER`` block.
# ~600 chars = ~150 tokens, fits comfortably in the 8K-token context
# we have headroom for after RAG + tools + the user's message.
_MAX_BLOCK_CHARS = 600


@dataclass(frozen=True)
class MemoryFact:
    """A single fact, decrypted and ready for the system prompt."""

    id: str
    key: str
    value: str
    confidence: int


def _decrypt_value(row: UserMemory) -> str | None:
    """Return the plaintext ``value`` for a memory row.

    Preference order:
      1. ``value_encrypted`` (Fernet) — the source of truth going forward.
      2. ``value`` (plaintext) — kept for one release window as a
         rollback target; readers prefer the encrypted column when
         present so a row can be re-encrypted without a code change.
    """
    if row.value_encrypted is not None:
        try:
            from app.utils.encryption import decrypt_bytes

            return decrypt_bytes(row.value_encrypted)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Memory %s decrypt failed, falling back: %s", row.id, exc)
            return row.value
    return row.value


def _dedupe_by_key(facts: list[MemoryFact]) -> list[MemoryFact]:
    """Drop duplicate ``key`` rows. The first occurrence (highest
    confidence / most recent) wins; later duplicates are skipped.

    Caller must pre-sort by ``confidence DESC, updated_at DESC`` so the
    "first occurrence" semantics is the right semantics.
    """
    seen: set[str] = set()
    out: list[MemoryFact] = []
    for fact in facts:
        k = (fact.key or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(fact)
    return out


def _format_block(facts: list[MemoryFact], max_chars: int = _MAX_BLOCK_CHARS) -> str:
    """Render facts as the ``KNOWN FACTS ABOUT THIS USER`` block.

    The format is line-oriented so the LLM can scan it:

        - role: CFO at Acme
        - currency: INR
        - fiscal year end: March 31

    If the rendered block would exceed ``max_chars`` the lowest-
    confidence fact is dropped first. We never truncate mid-line;
    partial lines look like garbage to the LLM.
    """
    if not facts:
        return ""

    lines: list[str] = []
    total = 0
    for fact in facts:
        line = f"- {fact.key}: {fact.value}"
        if lines and total + len(line) + 1 > max_chars:
            break
        if not lines and len(line) > max_chars:
            # Single fact is larger than the entire block budget;
            # best-effort: emit it anyway, the LLM will still see it.
            lines.append(line)
            total = len(line) + 1
            continue
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


async def list_memories(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    include_archived: bool = False,
) -> list[UserMemory]:
    """Return the user's memories for the read endpoint, ordered by
    ``confidence DESC, updated_at DESC``. Includes encrypted bytes —
    the caller is responsible for decryption (or for returning the
    ``MemoryFact`` DTO via ``facts``).
    """
    import uuid as _uuid
    user_uuid = _uuid.UUID(user_id) if not isinstance(user_id, _uuid.UUID) else user_id
    org_uuid = _uuid.UUID(org_id) if not isinstance(org_id, _uuid.UUID) else org_id
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_uuid,
        UserMemory.org_id == org_uuid,
    )
    if not include_archived:
        stmt = stmt.where(UserMemory.archived.is_(False))
    stmt = stmt.order_by(UserMemory.confidence.desc(), UserMemory.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def facts_for_injection(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    max_memories: int = DEFAULT_MAX_MEMORIES,
) -> list[MemoryFact]:
    """Return the deduplicated top-``max_memories`` decrypted facts
    for the system prompt.
    """
    rows = await list_memories(db, user_id=user_id, org_id=org_id)
    if not rows:
        return []

    facts: list[MemoryFact] = []
    for row in rows:
        value = _decrypt_value(row)
        if value is None:
            continue
        facts.append(
            MemoryFact(
                id=str(row.id),
                key=row.key,
                value=value,
                confidence=row.confidence,
            )
        )

    deduped = _dedupe_by_key(facts)
    return deduped[:max_memories]


def build_memory_block(
    facts: Iterable[MemoryFact],
    max_chars: int = _MAX_BLOCK_CHARS,
) -> str:
    """Render the injection block. Returns an empty string if there
    are no facts — the LLM prompt template then leaves the block out
    entirely (rather than rendering a header with an empty body).
    """
    return _format_block(list(facts), max_chars=max_chars)


__all__ = [
    "DEFAULT_MAX_MEMORIES",
    "MemoryFact",
    "build_memory_block",
    "facts_for_injection",
    "list_memories",
]
