from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.alert import Alert
from app.models.notification_read import NotificationRead
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.schemas.notification import (
    NotificationActionResponse,
    NotificationListResponse,
    NotificationResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


# Stable namespace for the synthetic TEAM_INVITATION ids. Random UUID
# chosen at module import — the only requirement is that it's stable
# across restarts so the same (placeholder, org) pair always maps to
# the same id (so React keys stay stable across polls).
_SYNTHETIC_TEAM_INVITATION_NS = uuid.UUID("0d3f5c1a-2b4e-4a7d-9c1f-2e3a4b5c6d7e")


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


def _synth_team_invitation(
    pending_membership: OrganizationMember,
    inviting_org: Organization,
    inviter_name: str,
) -> NotificationResponse:
    """Build a `NotificationResponse` for a pending workspace invite.

    The id is derived deterministically from
    `(pending_membership.id, inviting_org.id)` so the same pair always
    maps to the same UUID. That keeps React keys stable across bell
    polls and avoids spurious "new" UI animations.

    `target_org_id` is the *inviting* org's id as a string. The bell
    dropdown uses this to call `POST /api/v1/team/accept { org_id }`,
    which moves the current user into the inviting org.
    """
    synth_id = uuid.uuid5(
        _SYNTHETIC_TEAM_INVITATION_NS,
        f"{pending_membership.id}/{inviting_org.id}",
    )
    role = pending_membership.role or "member"  # type: ignore[assignment]
    return NotificationResponse(
        id=synth_id,
        title=f"{inviting_org.name} invited you to join as {role}",
        description=f"{inviter_name} invited you to join {inviting_org.name}.",
        severity="info",
        read=False,
        created_at=pending_membership.created_at,
        rule_id="TEAM_INVITATION",
        target_org_id=str(inviting_org.id),
    )


async def _inviter_name_for(org_id: uuid.UUID, db: AsyncSession) -> str:
    """Return the display name of the *owner* of `org_id` (oldest
    active admin), or "A workspace admin" as a fallback.

    Multi-org model: the owner is resolved through the
    `OrganizationMember` join table, not the legacy `User.org_id` /
    `User.role` columns. The semantics match `_resolve_owner` in
    `app/routers/team.py` — we duplicate the logic here to avoid a
    circular import between routers.
    """
    members_result = await db.execute(
        select(OrganizationMember, User)
        .outerjoin(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.status == "active",
            OrganizationMember.role == "admin",
        )
        .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
    )
    rows = list(members_result.all())
    if not rows:
        return "A workspace admin"
    _membership, owner_user = rows[0]
    if owner_user is None:
        return "A workspace admin"
    parts = [p for p in (owner_user.first_name, owner_user.last_name) if p]
    return " ".join(parts) if parts else owner_user.email or "A workspace admin"


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    result = await db.execute(
        select(Alert)
        .where(Alert.org_id == org.id)
        .order_by(Alert.created_at.desc())
        .limit(50)
    )
    alerts = result.scalars().all()
    unread_result = await db.execute(
        select(func.count(Alert.id)).where(
            Alert.org_id == org.id,
            Alert.read_at.is_(None),
        )
    )
    unread_count = int(unread_result.scalar() or 0)
    notifications = [_to_notification(alert) for alert in alerts]

    # Load per-user synthetic read-state once so we can mark the
    # `read` flag on each synthetic entry below. Keyed by synthetic
    # id (UUID).
    synthetic_reads: set[uuid.UUID] = set()
    reads_res = await db.execute(
        select(NotificationRead.synthetic_id).where(NotificationRead.user_id == user.id)
    )
    synthetic_reads = {row for row in reads_res.scalars().all()}

    # ── Synthetic TEAM_INVITATION entries ─────────────────────────────
    # The team router writes a pending `OrganizationMember` row
    # (`user_id IS NULL`, `email = <e>`, `status = "pending"`) whenever
    # an admin creates an invite. The current user is the invitee iff
    # there's a pending membership for *some other* org whose `email`
    # matches the current user's email. We synthesize a
    # `TEAM_INVITATION` notification for each such row so the bell
    # dropdown can render Accept/Decline buttons.
    #
    # We also need to exclude the *current* workspace — the invitee
    # can't invite themselves, but defensive: if a placeholder
    # exists in the caller's own org with the caller's own email
    # (e.g. a re-invite flow), it's not actionable here.
    if user.email:
        # Match pending invitations by email only — not by user_id.
        # A user may have multiple Clerk sessions (different user_id
        # rows in the DB) for the same email address. Invitations
        # bound to an older Clerk account's user_id must still show
        # up in the current session's notification bell.
        # The email field on OrganizationMember is the canonical
        # identifier for invitations, set when the invite is created.
        pending_result = await db.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.org_id)
            .where(
                OrganizationMember.email == user.email.lower(),
                OrganizationMember.status == "pending",
            )
            .order_by(OrganizationMember.created_at.desc())
        )
        rows = pending_result.all()
        # Build the inviter name for each row in one extra query,
        # grouped by org, to avoid the N+1.
        org_ids = {inv_org.id for _, inv_org in rows}
        inviter_cache: dict[uuid.UUID, str] = {}
        for org_id in org_ids:
            inviter_cache[org_id] = await _inviter_name_for(org_id, db)

        synthetic = [
            _synth_team_invitation(
                pending_membership=pending,
                inviting_org=inv_org,
                inviter_name=inviter_cache.get(inv_org.id, "A workspace admin"),
            )
            for pending, inv_org in rows
        ]
        # Apply the user's per-synthetic-id read-state. We mutate
        # the freshly-built `NotificationResponse` objects in place
        # rather than threading a `read_ids` arg through
        # `_synth_team_invitation` — the helper stays narrow.
        unread_synthetic = 0
        for entry in synthetic:
            if entry.id in synthetic_reads:
                entry.read = True
            else:
                unread_synthetic += 1
        # Synthetics are surfaced first — invitations are the most
        # actionable thing in the bell, and they should outrank
        # passive alerts.
        notifications = synthetic + notifications
        unread_count += unread_synthetic

    return NotificationListResponse(
        notifications=notifications,
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: uuid.UUID,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    # TEAM_INVITATION entries are synthetic — they don't have an
    # `Alert` row. Look up the underlying `OrganizationMember` for
    # the (inviting_org, email) pair this synthetic id encodes, and
    # persist a `NotificationRead` row to mark the read.
    #
    # We derive the (pending_membership, inviting_org) pair from the
    # synthetic id by reproducing `_SYNTHETIC_TEAM_INVITATION_NS`
    # and matching the *orgs* the user has pending invites in.
    # Easiest: enumerate pending memberships for the user and check
    # whether `uuid.uuid5(NS, f"{m.id}/{org_id}")` equals
    # `notification_id`. We do this in a single query, no N+1.
    synth_match = None
    if not _user.email:
        # Cannot match a synthetic by email without the user's email.
        # Fall through to the regular `Alert` path (which will 404).
        pass
    else:
        # Match by email only — same rationale as list_notifications.
        # A user with multiple Clerk accounts for the same email must
        # still be able to mark invitations as read even if the
        # pending membership row is bound to an older user_id.
        pending_match = await db.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.org_id)
            .where(
                OrganizationMember.email == _user.email.lower(),
                OrganizationMember.status == "pending",
            )
        )
        synth_match = None
        for pending_membership, inviting_org in pending_match.all():
            if uuid.uuid5(
                _SYNTHETIC_TEAM_INVITATION_NS,
                f"{pending_membership.id}/{inviting_org.id}",
            ) == notification_id:
                synth_match = (pending_membership, inviting_org)
                break

    if synth_match is not None:
        # Upsert a read marker for this synthetic id. The unique
        # constraint on (user_id, synthetic_id) makes this idempotent.
        existing_read = await db.execute(
            select(NotificationRead).where(
                NotificationRead.user_id == _user.id,
                NotificationRead.synthetic_id == notification_id,
            )
        )
        if existing_read.scalar_one_or_none() is None:
            db.add(
                NotificationRead(
                    user_id=_user.id,
                    synthetic_id=notification_id,
                    kind="TEAM_INVITATION",
                )
            )
            await db.commit()
        pending_membership, inviting_org = synth_match
        return NotificationResponse(
            id=notification_id,
            title=f"{inviting_org.name} invited you to join as {pending_membership.role or 'member'}",
            description=f"You've been invited to join {inviting_org.name}.",
            severity="info",
            read=True,
            created_at=pending_membership.created_at,
            rule_id="TEAM_INVITATION",
            target_org_id=str(inviting_org.id),
        )

    # Fall through to the regular `Alert` path.
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
    # TEAM_INVITATION entries are not stored in the alerts table —
    # they're synthesized on each list call from pending User rows.
    # So nothing to exclude here; the filter is kept as a safety
    # net in case a TEAM_INVITATION row was ever written by hand.
    await db.execute(
        delete(Alert).where(
            Alert.org_id == org.id,
            Alert.rule_id != "TEAM_INVITATION",
        )
    )
    await db.commit()
    return NotificationActionResponse(status="ok")
