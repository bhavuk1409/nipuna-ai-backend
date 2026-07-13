"""Auth router — Clerk webhook handler only.

POST /auth/webhook is unauthenticated; Svix signature is the trust mechanism.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import get_settings
from app.database import get_db
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.settings import OrgPreferences, WorkspaceSettings
from app.models.user import User
from app.schemas.workspace import (
    MembershipSummary,
    SwitchOrgRequest,
    SwitchOrgResponse,
    UserProfileResponse,
    UploadLogoRequest,
    RegisterWorkspaceRequest,
)
from app.utils.audit import log_action
from app.dependencies import get_current_user, get_current_org, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Import membership status enum values
_ACTIVE_STATUS = "active"


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    """Return the current user's profile, including their active org
    and the full list of orgs they belong to.

    The frontend uses this to render the org switcher dropdown.
    `active_org_id` is the DB-driven pointer that `get_current_org`
    reads; the list of `memberships` is what the dropdown shows.
    """
    active_org_name: str | None = None
    if user.active_org_id is not None:
        active_org_res = await db.execute(
            select(Organization).where(Organization.id == user.active_org_id)
        )
        active_org = active_org_res.scalar_one_or_none()
        if active_org is not None:
            active_org_name = active_org.name

    # Pull ACTIVE memberships + their org names for the org switcher.
    # We only show orgs the user can actually switch to (status='active').
    # Pending/declined/suspended memberships are not switchable and
    # must NOT appear in the org switcher dropdown.
    active_member_rows = (await db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.org_id)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == _ACTIVE_STATUS,
        )
        .order_by(OrganizationMember.created_at.asc())
    )).all()

    memberships: list[MembershipSummary] = [
        MembershipSummary(
            id=m.id,
            org_id=m.org_id,
            org_name=org.name,
            role=m.role,  # type: ignore[arg-type]
            status=m.status,  # type: ignore[arg-type]
            is_active=(m.org_id == user.active_org_id and m.status == _ACTIVE_STATUS),
            created_at=m.created_at,
            clerk_org_id=org.clerk_org_id,
            logo_url=org.logo_url,
        )
        for m, org in active_member_rows
    ]

    active_role = "member"
    active_logo_url = None
    if active_org is not None:
        active_logo_url = active_org.logo_url

    for m in memberships:
        if m.is_active:
            active_role = m.role

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        active_org_id=user.active_org_id,
        memberships=memberships,
        role=active_role,
        logo_url=active_logo_url,
    )


@router.post("/switch-org", response_model=SwitchOrgResponse)
async def switch_org(
    body: SwitchOrgRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SwitchOrgResponse:
    """Set the user's active org. The user must have an active
    `OrganizationMember` row for `body.org_id`; otherwise 403.

    The `active_org_id` is the DB-driven pointer the rest of the API
    reads on every request. The Clerk `org_id` JWT claim is *not*
    used; this endpoint is the single way to change the active org
    from the API.
    """
    membership_res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == body.org_id,
        )
    )
    membership = membership_res.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You don't have access to that workspace.",
        )
    if membership.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"Your membership in that workspace is {membership.status}.",
        )

    user.active_org_id = body.org_id
    # Multi-org model: just update `User.active_org_id`. The legacy
    # `User.org_id` / `User.role` / `User.status` columns are no
    # longer the source of truth — the `OrganizationMember` row is.
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await log_action(
        db,
        body.org_id,
        "membership.switched_active",
        user_id=user.id,
        metadata={"to": str(body.org_id)},
    )
    await db.commit()

    return SwitchOrgResponse(
        active_org_id=body.org_id,
        role=membership.role,  # type: ignore[arg-type]
        status=membership.status,  # type: ignore[arg-type]
    )


@router.post("/register-workspace", status_code=201)
async def register_workspace(
    body: RegisterWorkspaceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pre-register a Clerk org in the local DB right after the frontend
    calls Clerk's `createOrganization`. This ensures the Organization and
    OrganizationMember rows exist before the page redirects to /dashboard,
    sidestepping the race condition where the Clerk webhook hasn't fired yet.

    Idempotent: if the org already exists it just sets `active_org_id` and
    returns the existing record.
    """
    if not body.clerk_org_id.startswith("org_"):
        raise HTTPException(status_code=400, detail="Invalid clerk_org_id format.")

    # Look up or create the Organization row.
    org_res = await db.execute(
        select(Organization).where(Organization.clerk_org_id == body.clerk_org_id)
    )
    org = org_res.scalar_one_or_none()

    if org is None:
        org = Organization(
            clerk_org_id=body.clerk_org_id,
            name=body.name,
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        db.add(org)
        await db.flush()  # get org.id without committing yet

        ws = WorkspaceSettings(org_id=org.id, name=org.name)
        prefs = OrgPreferences(
            org_id=org.id,
            approval_required=False,
            digest_time="09:00",
            escalation_window=24,
        )
        db.add(ws)
        db.add(prefs)
        logger.info(
            "register_workspace: created Organization %s (clerk_org_id=%s) for user %s",
            org.name, body.clerk_org_id, user.email,
        )

    # Look up or create the OrganizationMember row.
    mem_res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org.id,
        )
    )
    membership = mem_res.scalar_one_or_none()

    if membership is None:
        membership = OrganizationMember(
            user_id=user.id,
            org_id=org.id,
            email=user.email.lower(),
            role="admin",
            status="active",
        )
        db.add(membership)
        logger.info(
            "register_workspace: created admin membership for user %s in org %s",
            user.email, org.id,
        )
    elif membership.status != "active":
        membership.status = "active"
        db.add(membership)

    # Switch the user's active org to the new one.
    user.active_org_id = org.id
    db.add(user)

    await db.commit()
    await db.refresh(org)

    logger.info(
        "register_workspace: set active_org_id=%s for user %s",
        org.id, user.email,
    )

    return {
        "org_id": str(org.id),
        "clerk_org_id": org.clerk_org_id,
        "name": org.name,
    }


@router.post("/workspace/logo")
async def upload_workspace_logo(
    body: UploadLogoRequest,
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload/update the company logo as a base64 string in the database.

    If `body.org_id` is provided, uploads the logo for that specific org
    (the user must be an admin of it). Otherwise uploads for the active org.
    This allows uploading logos for non-active workspaces from the switcher.
    """
    target_org = org  # default: active org

    if body.org_id is not None and body.org_id != org.id:
        # Look up the target org
        target_res = await db.execute(
            select(Organization).where(Organization.id == body.org_id)
        )
        target_org = target_res.scalar_one_or_none()
        if target_org is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")

        # Verify the user is an admin of the target org
        mem_res = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.org_id == target_org.id,
                OrganizationMember.status == "active",
            )
        )
        membership = mem_res.scalar_one_or_none()
        if membership is None or membership.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Only admins can update this workspace's logo.",
            )
    else:
        # Active org — use the standard require_admin check
        await require_admin(user, db)

    target_org.logo_url = body.logo_data
    db.add(target_org)
    await db.commit()
    await db.refresh(target_org)

    return {"status": "ok", "logo_url": target_org.logo_url, "org_id": str(target_org.id)}






@router.post("/webhook", include_in_schema=False)
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(None, alias="svix-id"),
    svix_timestamp: str = Header(None, alias="svix-timestamp"),
    svix_signature: str = Header(None, alias="svix-signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    secret = settings.clerk_webhook_secret
    if not secret:
        logger.error("CLERK_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body_bytes = await request.body()

    headers = {
        "svix-id": svix_id or "",
        "svix-timestamp": svix_timestamp or "",
        "svix-signature": svix_signature or "",
    }

    try:
        wh = Webhook(secret)
        payload = wh.verify(body_bytes, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type: str = payload.get("type", "")
    data: dict = payload.get("data", {})

    try:
        if event_type == "user.created":
            await _handle_user_created(db, data)

        elif event_type == "organization.created":
            await _handle_org_created(db, data)

        elif event_type == "organizationMembership.created":
            await _handle_membership_created(db, data)

        elif event_type == "organizationMembership.updated":
            await _handle_membership_updated(db, data)

        elif event_type == "organizationMembership.deleted":
            await _handle_membership_deleted(db, data)

        elif event_type == "user.deleted":
            await _handle_user_deleted(db, data)

        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Error processing Clerk webhook event '%s': %s", event_type, exc)
        raise HTTPException(status_code=500, detail="Internal error processing webhook")

    return {"status": "ok"}


async def _handle_user_created(db: AsyncSession, data: dict) -> None:
    clerk_user_id = data.get("id")
    if not clerk_user_id:
        return

    existing = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    if existing.scalar_one_or_none():
        logger.info("User clerk_user_id=%s already exists (user.created ignored)", clerk_user_id)
        return

    email_list = data.get("email_addresses", [])
    email = email_list[0].get("email_address", "") if email_list else ""
    phone_list = data.get("phone_numbers", [])
    phone = phone_list[0].get("phone_number") if phone_list else None

    # Check if there's a pending `OrganizationMember(user_id IS NULL,
    # email, ...)` row that this user should be bound to. This is the
    # multi-org replacement for the old `clerk_user_id="invited_*"`
    # placeholder pattern. If a pending membership exists, we create
    # the User, then bind them to it (and to its org).
    if email:
        pending_membership = (await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.email == email.lower(),
                OrganizationMember.status == "pending",
                OrganizationMember.user_id.is_(None),
            )
        )).scalar_one_or_none()
        if pending_membership is not None:
            user = User(
                clerk_user_id=clerk_user_id,
                email=email,
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                phone=phone,
                status="active",
                role=pending_membership.role,  # carry over the inviter's choice
            )
            db.add(user)
            await db.flush()
            # Now bind.
            pending_membership.user_id = user.id
            pending_membership.status = "active"
            user.active_org_id = pending_membership.org_id
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info(
                "Matched pending membership for email %s and clerk_user_id %s (org=%s)",
                email, clerk_user_id, pending_membership.org_id,
            )
            return

    user = User(
        clerk_user_id=clerk_user_id,
        email=email,
        first_name=data.get("first_name") or "",
        last_name=data.get("last_name") or "",
        phone=phone,
        status="active",
        role="member",
    )
    db.add(user)
    logger.info("Created user clerk_user_id=%s", clerk_user_id)


async def _handle_org_created(db: AsyncSession, data: dict) -> None:
    clerk_org_id = data.get("id")
    if not clerk_org_id:
        return

    existing = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if existing.scalar_one_or_none():
        logger.info("Org clerk_org_id=%s already exists (org.created ignored)", clerk_org_id)
        return

    org = Organization(
        clerk_org_id=clerk_org_id,
        name=data.get("name", "My Organization"),
        plan="free",
        seats_max=5,
        ai_credits=100,
    )
    db.add(org)
    await db.flush()

    ws = WorkspaceSettings(org_id=org.id, name=org.name)
    prefs = OrgPreferences(
        org_id=org.id,
        approval_required=False,
        digest_time="09:00",
        escalation_window=24,
    )
    db.add(ws)
    db.add(prefs)

    await log_action(
        db,
        org.id,
        "org.created",
        metadata={"clerk_org_id": clerk_org_id, "name": org.name},
    )
    logger.info("Created org clerk_org_id=%s", clerk_org_id)


async def _handle_membership_created(db: AsyncSession, data: dict) -> None:
    """Upsert an `OrganizationMember` row for this (user, org) pair.

    Multi-org aware: a user can have many of these rows. If a pending
    membership exists for this email (the user_id is NULL placeholder
    we wrote when the admin first sent the invite), bind the user to
    it and flip status to active.
    """
    public_user_data = data.get("public_user_data", {})
    clerk_user_id = public_user_data.get("user_id")
    clerk_org_id = data.get("organization", {}).get("id")
    clerk_role = data.get("role", "org:member")
    if not clerk_user_id or not clerk_org_id:
        return

    user_result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = user_result.scalar_one_or_none()
    org_result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    org = org_result.scalar_one_or_none()

    if not user or not org:
        logger.warning("Membership created but user or org not found: %s / %s", clerk_user_id, clerk_org_id)
        return

    # Map Clerk role → internal role, preserving viewer if the user
    # already has it (Clerk has no `org:viewer`). We check the user's
    # existing active membership to preserve viewer status.
    existing_role = "member"
    if user.active_org_id is not None:
        existing_membership = (await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.org_id == user.active_org_id,
            )
        )).scalar_one_or_none()
        if existing_membership is not None:
            existing_role = existing_membership.role  # type: ignore[assignment]
    if clerk_role == "org:admin":
        new_role = "admin"
    elif existing_role == "viewer":
        new_role = "viewer"
    else:
        new_role = "member"

    # If a pending `OrganizationMember(user_id IS NULL, email, ...)` row
    # exists for this org+email, bind the user to it and flip status.
    pending_membership = (await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.user_id.is_(None),
            OrganizationMember.email == user.email.lower(),
        )
    )).scalar_one_or_none()

    if pending_membership is not None:
        pending_membership.user_id = user.id
        pending_membership.status = "active"
        pending_membership.role = new_role
        membership = pending_membership
    else:
        # Otherwise upsert a normal active membership.
        existing = (await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.org_id == org.id,
            )
        )).scalar_one_or_none()
        if existing is not None:
            existing.role = new_role
            existing.status = "active"
            membership = existing
        else:
            membership = OrganizationMember(
                user_id=user.id,
                org_id=org.id,
                email=user.email.lower(),
                role=new_role,
                status="active",
            )
            db.add(membership)

    # Sync `User.active_org_id` to the new org. The legacy
    # `User.org_id` / `User.role` / `User.status` columns were
    # dropped in step 8 — the membership row is the source of truth.
    user.active_org_id = org.id

    await log_action(
        db,
        org.id,
        "membership.created",
        user_id=user.id,
        metadata={"clerk_role": clerk_role, "role": new_role},
    )
    logger.info("Linked user %s to org %s as %s", clerk_user_id, clerk_org_id, new_role)


async def _handle_membership_updated(db: AsyncSession, data: dict) -> None:
    """Update the membership's role when Clerk role changes.

    Old model had no equivalent (the webhook for this was missing
    entirely). Multi-org model updates only the affected membership
    row; if the user is in other orgs, those memberships are
    untouched.
    """
    public_user_data = data.get("public_user_data", {})
    clerk_user_id = public_user_data.get("user_id")
    clerk_org_id = data.get("organization", {}).get("id")
    clerk_role = data.get("role", "org:member")
    if not clerk_user_id or not clerk_org_id:
        return

    user_result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = user_result.scalar_one_or_none()
    org_result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    org = org_result.scalar_one_or_none()
    if not user or not org:
        logger.warning("Membership updated but user or org not found: %s / %s", clerk_user_id, clerk_org_id)
        return

    new_role = "admin" if clerk_role == "org:admin" else "member"

    membership = (await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org.id,
        )
    )).scalar_one_or_none()
    if membership is None:
        # Clerk says this user belongs to this org but we have no
        # membership row — treat as a create.
        membership = OrganizationMember(
            user_id=user.id,
            org_id=org.id,
            email=user.email.lower(),
            role=new_role,
            status="active",
        )
        db.add(membership)
    else:
        # Preserve viewer if the user already had it (Clerk has no
        # org:viewer; the role can only have been downgraded from
        # member in the Clerk UI).
        if membership.role != "viewer":
            membership.role = new_role
        membership.status = "active"

    # The `OrganizationMember.role` is the source of truth. The legacy
    # `User.role` / `User.status` columns were dropped in step 8 — the
    # active-membership role drives `require_admin` and the chat
    # permission gate.

    await log_action(
        db,
        org.id,
        "membership.updated",
        user_id=user.id,
        metadata={"clerk_role": clerk_role, "role": membership.role},
    )
    logger.info("Updated membership for user %s in org %s to %s", clerk_user_id, clerk_org_id, membership.role)


async def _handle_membership_deleted(db: AsyncSession, data: dict) -> None:
    """Delete the membership row for this (user, org) pair.

    Multi-org aware: a user can have many of these rows. We do NOT
    suspend the user — they may still belong to other orgs. If the
    deleted membership was the user's `active_org_id`, we clear the
    pointer; the next request will pick a different active org from
    the remaining memberships via the dep's lazy default.
    """
    public_user_data = data.get("public_user_data", {})
    clerk_user_id = public_user_data.get("user_id")
    clerk_org_id = data.get("organization", {}).get("id")
    if not clerk_user_id or not clerk_org_id:
        return

    user_result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return

    org_result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    org = org_result.scalar_one_or_none()
    if not org:
        return

    membership = (await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org.id,
        )
    )).scalar_one_or_none()
    if membership is not None:
        await db.delete(membership)

    # If the deleted membership was the active one, clear it. The dep
    # will lazy-pick a new active org from the user's remaining
    # memberships on the next request.
    if user.active_org_id == org.id:
        user.active_org_id = None
        db.add(user)

    await log_action(
        db,
        org.id,
        "membership.deleted",
        user_id=user.id,
        metadata={"clerk_user_id": clerk_user_id},
    )
    logger.info("Removed membership for user %s from org %s", clerk_user_id, clerk_org_id)


async def _handle_user_deleted(db: AsyncSession, data: dict) -> None:
    """Delete the User row. CASCADE on `organization_members.user_id`
    cleans up the user's memberships.

    Multi-org aware: we do NOT cascade-delete the Organization. Other
    members may still belong to it. The Organization row persists
    until the owner explicitly deletes it via the settings flow.
    """
    clerk_user_id = data.get("id")
    if not clerk_user_id:
        return

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.info("user.deleted for unknown clerk_user_id=%s (no-op)", clerk_user_id)
        return

    user_id = user.id
    # Pull the user's orgs before delete so we can log the deletion
    # against each (audit log is per-org).
    user_org_ids = (await db.execute(
        select(OrganizationMember.org_id).where(OrganizationMember.user_id == user_id)
    )).scalars().all()

    await db.delete(user)
    # CASCADE removes the OrganizationMember rows. The Organization
    # rows are NOT deleted.

    for org_id in user_org_ids:
        await log_action(
            db,
            org_id,
            "user.deleted",
            user_id=None,
            metadata={"clerk_user_id": clerk_user_id, "removed_memberships": True},
        )
    logger.info(
        "Deleted user clerk_user_id=%s; CASCADE removed %d memberships; orgs preserved",
        clerk_user_id, len(user_org_ids),
    )
