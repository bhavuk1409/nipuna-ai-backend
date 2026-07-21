"""User-memory endpoints (PR4).

Three endpoints, all scoped to the current user:

  - ``GET    /memories``         — list (decrypted)
  - ``DELETE /memories/{id}``    — archive single
  - ``DELETE /memories``         — forget-all (GDPR)

The list endpoint decrypts the ``value_encrypted`` column for each
row. The decrypted value is *not* cached anywhere — the LLM prompt
template (``app.services.memory.manager.build_memory_block``) is the
only consumer and it decrypts on each turn.

Forget-all is hard delete + an audit log entry. The audit entry
preserves the count and a sample of keys for forensic / customer-
support purposes, but the underlying facts are gone.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.models.user_memory import UserMemory
from app.services.memory.manager import list_memories
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memories", tags=["memories"])


# ──────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────


class MemoryOut(BaseModel):
    id: str
    key: str
    value: str
    confidence: int
    source_conversation_id: str | None = None
    created_at: str
    updated_at: str


class MemoryListResponse(BaseModel):
    memories: list[MemoryOut]
    total: int


class ForgetAllResponse(BaseModel):
    deleted: int
    keys: list[str]


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _to_out(row: UserMemory) -> MemoryOut:
    """Decrypt the row, falling back to the plaintext column when
    encryption is unavailable (the one-release backfill window).
    """
    from app.utils.encryption import decrypt_bytes
    value: str
    if row.value_encrypted is not None:
        try:
            value = decrypt_bytes(row.value_encrypted)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Memory %s decrypt failed: %s", row.id, exc)
            value = row.value
    else:
        value = row.value
    return MemoryOut(
        id=str(row.id),
        key=row.key,
        value=value,
        confidence=row.confidence,
        source_conversation_id=str(row.source_conversation_id) if row.source_conversation_id else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


# ──────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────


@router.get("", response_model=MemoryListResponse)
async def get_memories(
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryListResponse:
    rows = await list_memories(db, user_id=str(user.id), org_id=str(org.id))
    out = [_to_out(r) for r in rows]
    return MemoryListResponse(memories=out, total=len(out))


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a single memory. We keep the row for the audit
    trail (it shows up in the forget-all response too) but set
    ``archived=true`` so the manager no longer injects it.
    """
    res = await db.execute(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user.id,
            UserMemory.org_id == org.id,
        )
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    row.archived = True
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="memory_archived",
        metadata={"memory_id": str(memory_id), "key": row.key},
    )
    await db.commit()


@router.delete("", response_model=ForgetAllResponse)
async def forget_all_memories(
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForgetAllResponse:
    """GDPR-style forget-all. Hard delete + audit log entry.

    The audit log preserves the count and a sample of keys; the
    underlying facts are gone forever.
    """
    res = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user.id,
            UserMemory.org_id == org.id,
        )
    )
    rows = list(res.scalars().all())
    keys = [r.key for r in rows]
    for r in rows:
        await db.delete(r)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="memory_forget_all",
        metadata={
            "deleted": len(rows),
            "keys_sample": keys[:20],
        },
    )
    await db.commit()
    return ForgetAllResponse(deleted=len(rows), keys=keys[:20])


__all__ = ["router"]
