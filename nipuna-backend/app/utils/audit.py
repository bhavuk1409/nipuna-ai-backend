from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def log_action(
    db: AsyncSession,
    org_id: str | uuid.UUID,
    action: str,
    user_id: str | uuid.UUID | None = None,
    metadata: dict | None = None,
) -> None:
    log = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        metadata_json=metadata or {},
    )
    db.add(log)
