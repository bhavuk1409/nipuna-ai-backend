"""Audit writer for tool calls.

Every tool invocation in the chat pipeline calls
``record_tool_call`` after execution. The helper:

  1. Classifies errors into a small enum (``timeout``, ``rate_limit``,
     ``auth``, ``not_found``, ``invalid_input``, ``upstream_error``,
     ``unknown``) so the audit log is queryable, not just a wall of
     ``str(exc)``.
  2. Hashes params and result with ``sha256`` so duplicate calls
     (same args, same outcome) are dedupable. We do **not** store the
     raw params / result in this row — that's PII / secrets risk.
     The full result is on the ``messages.tool_result`` column.
  3. Is idempotent on ``(message_id, tool_name, action, params_hash)``.

The actual schema is in ``app/models/tool_call_audit.py`` (a follow-up
migration in this PR).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


_ERROR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("timeout", ("timeout", "timed out", "deadline exceeded")),
    ("rate_limit", ("429", "rate limit", "rate_limit", "too many requests", "tpd")),
    ("auth", ("401", "403", "unauthorised", "unauthorized", "forbidden", "invalid token")),
    ("not_found", ("404", "not found", "no such", "doesn't exist")),
    ("invalid_input", ("400", "bad request", "validation", "invalid argument", "schema")),
    ("upstream_error", ("500", "502", "503", "504", "internal server error", "bad gateway")),
)


def classify_error(exc: Exception | str | None) -> str:
    """Map an exception (or its ``str()``) to a small enum of error classes."""
    if exc is None:
        return "none"
    text = str(exc).lower()
    for cls, needles in _ERROR_PATTERNS:
        for needle in needles:
            if needle in text:
                return cls
    return "unknown"


def hash_payload(payload: Any) -> str:
    """Stable sha256 of a JSON-serialisable payload. Used for dedup + integrity."""
    try:
        canonical = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_tool_call(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None,
    conversation_id: str,
    message_id: str | None,
    tool_name: str,
    action: str,
    params: Any,
    result: Any = None,
    latency_ms: int = 0,
    success: bool = True,
    error_class: str | None = None,
) -> None:
    """Idempotently insert a row into ``tool_call_audit``.

    Safe to call from anywhere — failures are logged but never raised.
    The helper is imported as a function (not used via the model
    directly) so the calling code doesn't have to worry about which
    migration has been applied.
    """
    try:
        from app.models.tool_call_audit import ToolCallAudit
    except ImportError:
        # Migration not yet applied; the table doesn't exist. This
        # is fine in dev — the helper becomes a no-op until the
        # migration lands. In production the migration runs before
        # this code is reached.
        logger.debug("ToolCallAudit model not registered; skipping audit row.")
        return

    try:
        params_hash = hash_payload(params)
        result_hash = hash_payload(result) if result is not None else None
        if error_class is None and not success:
            error_class = "unknown"
        elif error_class is None:
            error_class = "none"

        values = {
            "org_id": org_id,
            "user_id": user_id,
            "conversation_id": conversation_id if isinstance(conversation_id, UUID) else UUID(conversation_id),
            "message_id": UUID(message_id) if message_id else None,
            "tool_name": tool_name,
            "tool_action": action,
            "params_hash": params_hash,
            "result_hash": result_hash,
            "latency_ms": latency_ms,
            "success": success,
            "error_class": error_class,
        }

        # Postgres ON CONFLICT DO NOTHING on (message_id, tool_name,
        # tool_action, params_hash) for idempotency. SQLite has no
        # native ON CONFLICT for the same shape, so we fall back to
        # a SELECT first.
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            stmt = pg_insert(ToolCallAudit).values(values)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["message_id", "tool_name", "tool_action", "params_hash"],
            )
            await db.execute(stmt)
        else:
            existing = await db.execute(
                select(ToolCallAudit).where(
                    ToolCallAudit.message_id == values["message_id"],
                    ToolCallAudit.tool_name == tool_name,
                    ToolCallAudit.tool_action == action,
                    ToolCallAudit.params_hash == params_hash,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is None:
                db.add(ToolCallAudit(**values))
                await db.flush()
    except Exception as exc:
        logger.warning("Failed to record tool audit: %s", exc)


__all__ = ["classify_error", "hash_payload", "record_tool_call"]
