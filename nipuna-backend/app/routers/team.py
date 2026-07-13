"""Team router — workspace members and pending invitations.

Multi-org model (this rewrite)
------------------------------

Invitations and memberships are now rows in `organization_members`:

- An active membership is a row with `user_id = <u>`, `status = "active"`.
- A pending invite is a row with `user_id IS NULL`, `email = <e>`,
  `status = "pending"`.
- The old `User.org_id` / `User.role` / `User.status` columns are no
  longer the source of truth; the membership row is. The legacy
  columns are still kept in sync (in `resolve_current_user` and the
  Clerk webhook handlers) for downstream code that hasn't migrated
  yet, but the team router itself reads/writes only the membership
  table.

Endpoint surface (unchanged from the previous version of this file)
-----------------------------------------------------------------
- GET    /api/v1/team                       — list members + pending invites
- POST   /api/v1/team/invites               — create a pending invite
- PATCH  /api/v1/team/members/{id}/role     — change a member's role
- DELETE /api/v1/team/members/{id}          — remove a member
- DELETE /api/v1/team/invites/{id}          — cancel a pending invite
- POST   /api/v1/team/invites/{id}/resend   — re-fire the Clerk email
- POST   /api/v1/team/accept                — accept an invite
- POST   /api/v1/team/decline               — decline an invite

The `member_id` and `invite_id` URL params are now `OrganizationMember.id`
values, not `User.id` values. (The wire format looks the same — UUIDs
in both cases — so the frontend doesn't need to change its call sites.)

Owner semantics
---------------
The DB stores `role ∈ {admin, member, viewer}`. The frontend treats
role as a 4-value enum where "owner" is a *display* role resolved at
read time as the active admin with the lowest `created_at` (tie-break:
lowest `id`). All other admins are surfaced as "admin". When the owner
is demoted, the next-oldest admin inherits the owner designation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user, require_admin
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.schemas.team import (
    AcceptInviteRequest,
    ChangeRoleRequest,
    InviteMemberRequest,
    PendingInviteResponse,
    TeamListResponse,
    TeamMemberResponse,
)
from app.config import get_settings
from app.services.clerk import (
    ClerkAPIError,
    lookup_clerk_user_by_email,
    send_clerk_org_invitation,
)
from app.services.notifications.team_invite_email import (
    build_dev_share_link,
    send_team_invite_email,
)

router = APIRouter(prefix="/team", tags=["team"])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _display_name(u: User | None, fallback_email: str) -> str:
    """Best-effort display name for a row.

    Active members have a User row with a name; pending invites have
    no User row, so we fall back to the email. Same code path used
    in both cases.
    """
    if u is None:
        return fallback_email
    parts = [p for p in (u.first_name, u.last_name) if p]
    return " ".join(parts) if parts else (u.email or fallback_email)


def _resolve_owner(memberships: list[OrganizationMember]) -> uuid.UUID | None:
    """Pick the owner: oldest active admin in the org. None if no admins.

    Owner is *display-only*. The membership's `role` is still "admin"
    on the wire; the dep frontend upgrades it to "owner" for the row
    that matches this id.
    """
    admins = [m for m in memberships if m.role == "admin" and m.status == "active"]
    if not admins:
        return None
    admins.sort(key=lambda m: (m.created_at, m.id))
    return admins[0].id


def _role_for_display(
    membership: OrganizationMember,
    owner_id: uuid.UUID | None,
) -> str:
    """Map a membership to its display role string.

    "owner" is the oldest active admin; everyone else gets their
    stored `role` verbatim.
    """
    if owner_id is not None and membership.id == owner_id and membership.role == "admin":
        return "owner"
    return membership.role  # type: ignore[return-value]


async def _touch_last_active(user: User, db: AsyncSession) -> None:
    """Best-effort, debounced touch of the current user's `last_active_at`.

    Skips the write if the column was set in the last 5 minutes — keeps
    write load flat even if the team page polls aggressively.
    """
    now = datetime.now(timezone.utc)
    if user.last_active_at is not None:
        # The DB column is `DateTime(timezone=True)`, but rows created
        # by the old migration may have a naive value. Treat naive
        # values as UTC for the debounce check.
        last = user.last_active_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = now - last
        if delta.total_seconds() < 300:
            return
    user.last_active_at = now
    db.add(user)
    # No commit here — the route's commit (or the caller's) will pick it up.


async def _get_active_membership(
    user: User, org_id: uuid.UUID, db: AsyncSession,
) -> OrganizationMember | None:
    """Return the user's active membership in `org_id`, or None."""
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org_id,
            OrganizationMember.status == "active",
        )
    )
    return res.scalar_one_or_none()


async def _find_pending_invite(
    org_id: uuid.UUID,
    email: str,
    db: AsyncSession,
    user_id: uuid.UUID | None = None,  # kept for API compat, no longer used for filtering
) -> OrganizationMember | None:
    """Return the pending membership for (org, email).

    We match by email only — the email is the canonical identifier for
    invitations set when the invite is created. A user may have multiple
    Clerk sessions (different user_id rows) for the same email address.
    If the pending invite is bound to an older Clerk account's user_id,
    it must still be discoverable from the current session.

    The caller (accept_invitation / decline_invitation) is responsible
    for re-binding `pending.user_id = user.id` when accepting.
    """
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.email == email.lower(),
            OrganizationMember.status == "pending",
        )
    )
    return res.scalar_one_or_none()


async def _is_org_admin(
    user: User, org_id: uuid.UUID, db: AsyncSession,
) -> bool:
    """Return True iff the user has an active admin membership in `org_id`."""
    res = await db.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org_id,
            OrganizationMember.status == "active",
        )
    )
    role = res.scalar_one_or_none()
    return role == "admin"


# ---------------------------------------------------------------------------
# GET /team
# ---------------------------------------------------------------------------


@router.get("", response_model=TeamListResponse)
async def list_team(
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> TeamListResponse:
    # Active members: rows with user_id IS NOT NULL and status = "active".
    active_rows = (await db.execute(
        select(OrganizationMember, User)
        .outerjoin(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.status == "active",
            OrganizationMember.user_id.is_not(None),
        )
        .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
    )).all()

    owner_id = _resolve_owner([m for m, _ in active_rows])

    members: list[TeamMemberResponse] = [
        TeamMemberResponse(
            id=m.id,
            name=_display_name(u, m.email),
            email=m.email,
            role=_role_for_display(m, owner_id),  # type: ignore[arg-type]
            status="active",
            last_active=u.last_active_at if u is not None else None,
            is_you=(u is not None and u.id == user.id),
        )
        for m, u in active_rows
    ]

    # Pending invites: rows with status = "pending" (user_id may be NULL).
    pending_rows = (await db.execute(
        select(OrganizationMember, User)
        .outerjoin(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.status == "pending",
        )
        .order_by(OrganizationMember.created_at.desc())
    )).all()

    # For "invited_by": the owner of the org (oldest active admin) is a
    # reasonable default. We do one query to get the owner's display
    # name; pending invites all attribute to the same inviter in
    # practice (the admin who sent the invite).
    inviter_name = "A workspace admin"
    if owner_id is not None:
        owner_res = await db.execute(
            select(User).where(User.id == owner_id)
        )
        owner_user = owner_res.scalar_one_or_none()
        if owner_user is not None:
            inviter_name = _display_name(owner_user, owner_user.email)

    settings = get_settings()
    is_dev_org = org.clerk_org_id.startswith("manual_")

    pending_invites: list[PendingInviteResponse] = []
    for m, u in pending_rows:
        dev_share_link: str | None = None
        if is_dev_org:
            dev_share_link = build_dev_share_link(
                frontend_url=settings.frontend_url,
                org_id=str(org.id),
                email=m.email,
            )
        pending_invites.append(
            PendingInviteResponse(
                id=m.id,
                email=m.email,
                role=m.role,  # type: ignore[arg-type]
                sent_at=m.created_at,
                invited_by=inviter_name,
                dev_share_link=dev_share_link,
            )
        )

    # Touch current user's last_active_at (debounced).
    await _touch_last_active(user, db)
    await db.commit()

    return TeamListResponse(
        members=members,
        pending_invites=pending_invites,
        owner_id=owner_id,
    )


# ---------------------------------------------------------------------------
# POST /team/invites
# ---------------------------------------------------------------------------


@router.post(
    "/invites",
    response_model=PendingInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    body: InviteMemberRequest,
    user: User = Depends(get_current_user),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PendingInviteResponse:
    """Create a pending invite for `body.email` in the current org.

    Branch on whether the email is already a Clerk user. Either way
    we write a pending `OrganizationMember` row (the new "placeholder"
    — the old `User.clerk_user_id="invited_*"` pattern is gone).

    - Existing Clerk user → no email (synthetic notification surfaces
      the invite in their bell on next poll).
    - Dev `manual_*` org → no Clerk API call; we build a self-serve
      share link the inviter can pass to the invitee manually.
    - Real Clerk org, new email → call Clerk's
      `POST /v1/organizations/{id}/invitations`. If Clerk rejects, we
      roll back the membership and return 502 (no orphan rows).
    """

    # Reject if a User with this email is already an active member.
    # Note: `User.email` is not UNIQUE in the schema (Clerk users can
    # have multiple local rows for the same email in edge cases —
    # e.g. a re-invite flow that re-created the placeholder), so
    # use `.scalars().first()` and take any match. The downstream
    # `existing_member` check below still uses the unique
    # (org_id, user_id) index.
    existing_user_res = await db.execute(
        select(User).where(User.email == body.email).order_by(User.created_at.asc())
    )
    existing_user = existing_user_res.scalars().first()
    if existing_user is not None:
        existing_member = (await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id,
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.status == "active",
            )
        )).scalar_one_or_none()
        if existing_member is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This person is already a member of this workspace.",
            )

    # Reject if a pending invite already exists for this email in this org.
    existing_invite = await _find_pending_invite(org.id, body.email, db)
    if existing_invite is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invitation is already pending for this email.",
        )

    settings = get_settings()
    is_dev_org = org.clerk_org_id.startswith("manual_")

    # Best-effort Clerk lookup. If the email is already a Clerk user,
    # we send them BOTH an in-app notification (synthetic bell) AND a
    # Resend email so they are immediately alerted.
    existing_clerk_user_id: str | None = None
    if existing_user is not None:
        # Already a Nipuna AI user — the synthetic notification will
        # surface the invite in their bell. We ALSO send a Resend
        # email so they're notified even if they're not actively
        # checking the app.
        pass
    else:
        try:
            existing_clerk_user_id = await lookup_clerk_user_by_email(
                email=body.email,
                secret_key=settings.clerk_secret_key,
            )
        except ClerkAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not look up the invitee: {exc}",
            ) from exc

    # Build the dashboard link for existing users to find their notification
    dashboard_link = f"{settings.frontend_url.rstrip('/')}/dashboard"

    if existing_user is not None:
        # Existing Nipuna AI user: send a Resend email pointing them
        # to their notification bell. Best-effort — don't fail the
        # invite if email delivery fails.
        logger.info(
            "create_invite: existing user %s; sending Resend notification email",
            body.email,
        )
        await send_team_invite_email(
            to_email=body.email,
            org_name=org.name,
            inviter_name=_display_name(user, user.email),
            role=body.role,
            share_link=dashboard_link,
            logo_url=org.logo_url,
        )
    elif existing_user is None and existing_clerk_user_id is None and not is_dev_org:
        # New email, real Clerk org — send a real invitation email.
        try:
            await send_clerk_org_invitation(
                clerk_org_id=org.clerk_org_id,
                email=body.email,
                role=body.role,
                inviter_user_id=user.clerk_user_id,
                redirect_url=f"{settings.frontend_url}/dashboard",
                secret_key=settings.clerk_secret_key,
            )
        except ClerkAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send invitation email: {exc}",
            ) from exc
    elif is_dev_org and existing_clerk_user_id is None and existing_user is None:
        # Dev-only path: org is a `manual_*` placeholder (not a real
        # Clerk org), so we can't ask Clerk to send a real email. We
        # still write the membership row; the inviter can copy the
        # self-serve share link and pass it to the invitee manually.
        # As a UX improvement, we ALSO send the link via Resend so
        # the invitee actually gets contacted. Email send is
        # best-effort: if Resend isn't configured or fails, the
        # inviter still sees the share link in the response.
        share_link = build_dev_share_link(
            frontend_url=settings.frontend_url,
            org_id=str(org.id),
            email=body.email,
            org_name=org.name,
        )
        logger.info(
            "create_invite: dev org %s (clerk_org_id=%s); emailing share link to %s",
            org.id, org.clerk_org_id, body.email,
        )
        await send_team_invite_email(
            to_email=body.email,
            org_name=org.name,
            inviter_name=_display_name(user, user.email),
            role=body.role,
            share_link=share_link,
            logo_url=org.logo_url,
        )

    # Bind to a User if we already have one (the email matched an
    # existing Nipuna AI account), else leave user_id NULL — the
    # accept / Clerk webhook flow will fill it in when the invitee
    # signs in.
    invite = OrganizationMember(
        user_id=existing_user.id if existing_user is not None else None,
        org_id=org.id,
        email=body.email.lower(),
        role=body.role,
        status="pending",
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    # (Membership row is the source of truth for role/status — the
    # legacy `User.role` / `User.status` columns were dropped in
    # step 8.)
    if existing_user is not None:
        # If the user has no other active memberships in this org, no
        # change to active_org_id. If they do, leave it — switching
        # active org on invite creation would be surprising.
        db.add(existing_user)
        await db.commit()

    # Dev share link (only when there is no real Clerk org to ask).
    # `build_dev_share_link` is the single source of truth for the
    # link shape (used by the email path above and the API response
    # below) so the URL is consistent.
    dev_share_link: str | None = None
    delivery_note: str | None = None
    if is_dev_org and existing_user is None and existing_clerk_user_id is None:
        dev_share_link = build_dev_share_link(
            frontend_url=settings.frontend_url,
            org_id=str(org.id),
            email=body.email,
            org_name=org.name,
        )
        delivery_note = (
            "Dev mode: Resend email was sent to the invitee. The link "
            "below is also included for manual sharing if email fails."
        )
    elif existing_user is not None:
        delivery_note = (
            "Invitee is already a Nipuna AI user. An email notification "
            "has been sent, and the invitation appears in their notification bell."
        )

    return PendingInviteResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role,  # type: ignore[arg-type]
        sent_at=invite.created_at,
        invited_by=_display_name(user, user.email),
        dev_share_link=dev_share_link,
        delivery_note=delivery_note,
    )



# ---------------------------------------------------------------------------
# PATCH /team/members/{membership_id}/role
# ---------------------------------------------------------------------------


@router.patch("/members/{membership_id}/role", response_model=TeamMemberResponse)
async def change_member_role(
    membership_id: uuid.UUID,
    body: ChangeRoleRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> TeamMemberResponse:
    target = await db.get(OrganizationMember, membership_id)
    if target is None or target.org_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace.",
        )

    # Owner designation is derived; the underlying role is still
    # "admin". Refuse to demote the owner — the admin will become a
    # regular admin again next read.
    active_memberships = (await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.org_id == org.id, OrganizationMember.status == "active")
        .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
    )).scalars().all()
    owner_id = _resolve_owner(active_memberships)

    if owner_id is not None and target.id == owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace owner role can't be changed here. Transfer ownership first.",
        )

    # Prevent the workspace from ending up with zero admins.
    if target.role == "admin" and body.role != "admin":
        admin_count = sum(1 for m in active_memberships if m.role == "admin")
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace must have at least one admin. Promote another member first.",
            )

    target.role = body.role
    db.add(target)
    await db.commit()
    await db.refresh(target)

    # Trigger email notification for role change
    from app.services.notifications.role_change_email import send_role_change_email
    background_tasks.add_task(
        send_role_change_email,
        to_email=target.email,
        org_name=org.name,
        role=body.role,
        updater_name=_display_name(user, user.email),
        logo_url=org.logo_url,
    )

    # (The `OrganizationMember.role` is the source of truth — the
    # legacy `User.role` column was dropped in step 8.)
    new_owner_id = _resolve_owner(active_memberships)

    # The TeamMemberResponse expects a "user id" — we use the
    # membership id (UUID) for stability, since it's what the
    # frontend already keys on.
    member_user = None
    if target.user_id is not None:
        member_user = await db.get(User, target.user_id)

    return TeamMemberResponse(
        id=target.id,
        name=_display_name(member_user, target.email),
        email=target.email,
        role=_role_for_display(target, new_owner_id),  # type: ignore[arg-type]
        status=target.status,  # type: ignore[arg-type]
        last_active=member_user.last_active_at if member_user is not None else None,
        is_you=(member_user is not None and member_user.id == user.id),
    )


# ---------------------------------------------------------------------------
# DELETE /team/members/{membership_id}
# ---------------------------------------------------------------------------


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    target = await db.get(OrganizationMember, membership_id)
    if target is None or target.org_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace.",
        )

    active_memberships = (await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.org_id == org.id, OrganizationMember.status == "active")
        .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
    )).scalars().all()
    owner_id = _resolve_owner(active_memberships)

    if owner_id is not None and target.id == owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The workspace owner cannot be removed.",
        )

    # Don't let an admin remove themselves if they're the last admin.
    if (
        target.role == "admin"
        and target.user_id is not None
        and target.user_id == user.id
    ):
        admin_count = sum(1 for m in active_memberships if m.role == "admin")
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace must have at least one admin. Promote another member first.",
            )

    # If the removed member's `active_org_id` was this org, clear it
    # — the dep will lazy-pick a new active org on the next request.
    if target.user_id is not None:
        removed_user = await db.get(User, target.user_id)
        if removed_user is not None and removed_user.active_org_id == org.id:
            removed_user.active_org_id = None
            db.add(removed_user)

    await db.delete(target)
    await db.commit()


# ---------------------------------------------------------------------------
# DELETE /team/invites/{membership_id}
# ---------------------------------------------------------------------------


@router.delete("/invites/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invite(
    membership_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    invite = await db.get(OrganizationMember, membership_id)
    if (
        invite is None
        or invite.org_id != org.id
        or invite.status != "pending"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )

    await db.delete(invite)
    await db.commit()


# ---------------------------------------------------------------------------
# POST /team/invites/{membership_id}/resend
# ---------------------------------------------------------------------------


@router.post("/invites/{membership_id}/resend", response_model=PendingInviteResponse)
async def resend_invite(
    membership_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _admin: User = Depends(require_admin),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PendingInviteResponse:
    invite = await db.get(OrganizationMember, membership_id)
    if (
        invite is None
        or invite.org_id != org.id
        or invite.status != "pending"
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )

    settings = get_settings()
    is_dev_org = org.clerk_org_id.startswith("manual_")

    # Is the invitee already a Nipuna AI user? The synthetic
    # notification surfaces the invite in their bell; no email
    # needed.
    invitee_user = None
    if invite.user_id is not None:
        invitee_user = await db.get(User, invite.user_id)

    dev_share_link: str | None = None
    delivery_note: str | None = None

    if invitee_user is not None:
        delivery_note = (
            "Invitee is already a Nipuna AI user. The invitation "
            "appears in their notification bell — no email needed."
        )
    elif is_dev_org:
        # Dev-only path: no Clerk org, so no Clerk email. Build a
        # self-serve share link and re-send it via Resend.
        logger.info(
            "resend_invite: dev org %s (clerk_org_id=%s); emailing share link to %s",
            org.id, org.clerk_org_id, invite.email,
        )
        dev_share_link = build_dev_share_link(
            frontend_url=settings.frontend_url,
            org_id=str(org.id),
            email=invite.email,
        )
        await send_team_invite_email(
            to_email=invite.email,
            org_name=org.name,
            inviter_name=_display_name(user, user.email),
            role=invite.role,  # type: ignore[arg-type]
            share_link=dev_share_link,
            logo_url=org.logo_url,
        )
        delivery_note = (
            "Dev mode: Resend email re-sent to the invitee. The link "
            "below is also included for manual sharing if email fails."
        )
    else:
        # Real Clerk org, new email — re-fire the invitation.
        try:
            await send_clerk_org_invitation(
                clerk_org_id=org.clerk_org_id,
                email=invite.email,
                role=invite.role,  # type: ignore[arg-type]
                inviter_user_id=user.clerk_user_id,
                redirect_url=f"{settings.frontend_url}/dashboard",
                secret_key=settings.clerk_secret_key,
            )
            delivery_note = "Invitation email re-sent."
        except ClerkAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to re-send invitation email: {exc}",
            ) from exc

    return PendingInviteResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role,  # type: ignore[arg-type]
        sent_at=invite.created_at,
        invited_by=_display_name(user, user.email),
        dev_share_link=dev_share_link,
        delivery_note=delivery_note,
    )


# ---------------------------------------------------------------------------
# POST /team/accept  /  POST /team/decline
# ---------------------------------------------------------------------------


@router.post("/accept", response_model=TeamMemberResponse)
async def accept_invitation(
    body: AcceptInviteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamMemberResponse:
    """Accept a pending invite into the inviting org.

    Multi-org aware: we bind the user to the pending membership and
    add this org to their set of memberships. We do NOT delete any
    other memberships they may have — they keep their existing
    workspaces and gain a new one. `active_org_id` is updated to
    point at the new org so the next request lands in the right
    place.
    """
    pending = await _find_pending_invite(body.org_id, user.email, db, user_id=user.id)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending invitation for this workspace.",
        )

    # Bind the current user to the pending membership and flip status.
    # This handles three cases:
    #   1. user_id IS NULL — fresh placeholder, bind for the first time.
    #   2. user_id == user.id — already bound (self-heal ran first),
    #      just flip status.
    #   3. user_id == other account's id — invite bound to an older
    #      Clerk session for the same email. Re-bind to the current
    #      user so this account becomes the member.
    pending.user_id = user.id
    pending.status = "active"

    db.add(pending)
    await db.flush()

    # Make this the user's active org. Keep all other memberships.
    # (`OrganizationMember` is the source of truth for role/status —
    # the legacy `User.org_id` / `User.role` / `User.status` columns
    # were dropped in step 8.)
    user.active_org_id = body.org_id
    db.add(user)
    await db.commit()
    await db.refresh(pending)
    await db.refresh(user)

    # Refetch the now-active memberships to compute owner designation
    # for the response.
    active_memberships = (await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.org_id == body.org_id, OrganizationMember.status == "active")
        .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
    )).scalars().all()
    owner_id = _resolve_owner(active_memberships)

    return TeamMemberResponse(
        id=pending.id,
        name=_display_name(user, user.email),
        email=pending.email,
        role=_role_for_display(pending, owner_id),  # type: ignore[arg-type]
        status=pending.status,  # type: ignore[arg-type]
        last_active=user.last_active_at,
        is_you=True,
    )


@router.post("/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_invitation(
    body: AcceptInviteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Decline a pending invite.

    We flip the membership's status to `declined` rather than deleting
    the row, so we keep an audit trail. The membership won't surface
    in `list_team` (which filters on `status == "active"`) and won't
    match the synthetic-notification query (which filters on
    `status == "pending"`).
    """
    pending = await _find_pending_invite(body.org_id, user.email, db, user_id=user.id)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending invitation for this workspace.",
        )

    # Always flip the status to 'declined' (never delete) so we
    # keep an audit trail. We also bind the current user_id if the
    # invite was previously bound to an older Clerk session for the
    # same email — this keeps the row consistent.
    pending.user_id = user.id
    pending.status = "declined"
    db.add(pending)
    await db.commit()
