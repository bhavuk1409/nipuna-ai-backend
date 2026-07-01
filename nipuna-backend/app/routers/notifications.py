from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.alert import Alert
from app.models.organization import Organization
from app.models.user import User
from app.schemas.notification import (
    NotificationActionResponse,
    NotificationListResponse,
    NotificationResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notification_title(rule_id: str) -> str:
    titles = {
        "CREDIT_LOW": "AI Credits Running Low",
        "AGENT_IDLE": "Agent Idle",
        "INTEGRATION_ERROR": "Integration Needs Attention",
        "INTEGRATION_DISCONNECTED": "Integration Disconnected",
        "SEAT_LIMIT": "Seat Limit Reached",
        "SUBSCRIPTION_EXPIRY": "Subscription Expiring",
        "TALLY_SYNC_COMPLETE": "Tally Sync Completed",
        "NEW_OPERATOR_JOINED": "New Operator Joined",
        "INVOICE_INGESTION_STARTED": "Invoice Ingestion Started",
    }
    return titles.get(rule_id, rule_id.replace("_", " ").title())


def _to_notification(alert: Alert) -> NotificationResponse:
    return NotificationResponse(
        id=alert.id,
        title=_notification_title(alert.rule_id),
        description=alert.message,
        severity=alert.severity,
        read=alert.read_at is not None,
        created_at=alert.created_at,
        rule_id=alert.rule_id,
    )



@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    result = await db.execute(
        select(Alert)
        .where(Alert.org_id == org.id, Alert.rule_id != "TEAM_INVITATION")
        .order_by(Alert.created_at.desc())
        .limit(50)
    )
    alerts = result.scalars().all()
    unread_result = await db.execute(
        select(func.count(Alert.id)).where(
            Alert.org_id == org.id,
            Alert.read_at.is_(None),
            Alert.rule_id != "TEAM_INVITATION",
        )
    )
    unread_count = int(unread_result.scalar() or 0)
    notifications = [_to_notification(alert) for alert in alerts]

    return NotificationListResponse(
        notifications=notifications,
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    result = await db.execute(
        select(Alert).where(
            Alert.id == notification_id,
            Alert.org_id == org.id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    if alert.read_at is None:
        alert.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(alert)

    return _to_notification(alert)


@router.post("/read-all", response_model=NotificationActionResponse)
async def mark_all_notifications_read(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationActionResponse:
    await db.execute(
        update(Alert)
        .where(
            Alert.org_id == org.id,
            Alert.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return NotificationActionResponse(status="ok")


@router.delete("", response_model=NotificationActionResponse)
async def clear_notifications(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationActionResponse:
    # Only delete non-invitation alerts — TEAM_INVITATION entries are
    # derived from the pending User rows, not from the alerts table directly,
    # but we still exclude them here to avoid any stale rows
    await db.execute(
        delete(Alert).where(
            Alert.org_id == org.id,
            Alert.rule_id != "TEAM_INVITATION",
        )
    )
    await db.commit()
    return NotificationActionResponse(status="ok")
