from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, text, update
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


async def _alerts_have_read_at_column(db: AsyncSession) -> bool:
    def check(session):
        from sqlalchemy import inspect
        # session is a synchronous Session object; get its bind connection
        conn = session.connection()
        insp = inspect(conn)
        # Handle cases where table doesn't exist yet (e.g. initial setup)
        if not insp.has_table("alerts"):
            return False
        columns = [c["name"] for c in insp.get_columns("alerts")]
        return "read_at" in columns

    return await db.run_sync(check)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    has_read_at = await _alerts_have_read_at_column(db)

    if has_read_at:
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
    else:
        result = await db.execute(
            text(
                """
                SELECT id, rule_id, severity, message, delivered_at, created_at
                FROM alerts
                WHERE org_id = :org_id AND rule_id != 'TEAM_INVITATION'
                ORDER BY created_at DESC
                LIMIT 50
                """
            ),
            {"org_id": org.id},
        )
        rows = result.mappings().all()
        notifications = [
            NotificationResponse(
                id=row["id"],
                title=_notification_title(row["rule_id"]),
                description=row["message"],
                severity=row["severity"],
                read=False,
                created_at=row["created_at"],
                rule_id=row["rule_id"],
            )
            for row in rows
        ]
        unread_count = len(notifications)

    # Fetch pending invites dynamically for _user
    invitation_notifications = []
    if _user.email:
        invites_query = await db.execute(
            select(User, Organization)
            .join(Organization, User.org_id == Organization.id)
            .where(
                User.email == _user.email,
                User.status == "pending",
                User.clerk_user_id.like("invited_%")
            )
        )
        pending_invites = invites_query.all()
        for p_user, p_org in pending_invites:
            invitation_notifications.append(
                NotificationResponse(
                    id=p_user.id,
                    title="Workspace Invitation",
                    description=f"You have been invited to join the workspace {p_org.name} as a {p_user.role}.",
                    severity="info",
                    read=False,
                    created_at=p_user.created_at,
                    rule_id="TEAM_INVITATION",
                    target_org_id=str(p_org.id),
                )
            )

    notifications = invitation_notifications + notifications
    unread_count += len(invitation_notifications)

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
    # Check if the notification_id is a dynamic team invitation
    if _user.email:
        invite_res = await db.execute(
            select(User, Organization)
            .join(Organization, User.org_id == Organization.id)
            .where(
                User.id == notification_id,
                User.email == _user.email,
                User.status == "pending",
                User.clerk_user_id.like("invited_%")
            )
        )
        invite_row = invite_res.first()
        if invite_row:
            p_user, p_org = invite_row
            return NotificationResponse(
                id=p_user.id,
                title="Workspace Invitation",
                description=f"You have been invited to join the workspace {p_org.name} as a {p_user.role}.",
                severity="info",
                read=True,
                created_at=p_user.created_at,
                rule_id="TEAM_INVITATION",
                target_org_id=str(p_org.id),
            )

    has_read_at = await _alerts_have_read_at_column(db)

    if has_read_at:
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

    result = await db.execute(
        text(
            """
            SELECT id, rule_id, severity, message, delivered_at, created_at
            FROM alerts
            WHERE id = :notification_id AND org_id = :org_id
            """
        ),
        {"notification_id": notification_id, "org_id": org.id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    return NotificationResponse(
        id=row["id"],
        title=_notification_title(row["rule_id"]),
        description=row["message"],
        severity=row["severity"],
        read=True,
        created_at=row["created_at"],
        rule_id=row["rule_id"],
    )


@router.post("/read-all", response_model=NotificationActionResponse)
async def mark_all_notifications_read(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationActionResponse:
    if await _alerts_have_read_at_column(db):
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
    await db.execute(delete(Alert).where(Alert.org_id == org.id))
    await db.commit()
    return NotificationActionResponse(status="ok")
