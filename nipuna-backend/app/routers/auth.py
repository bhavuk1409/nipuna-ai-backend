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
from app.models.settings import OrgPreferences, WorkspaceSettings
from app.models.user import User
from app.utils.audit import log_action
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def get_current_user_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    org_name = None
    if user.org_id:
        org_result = await db.execute(select(Organization).where(Organization.id == user.org_id))
        org = org_result.scalar_one_or_none()
        if org:
            org_name = org.name

    return {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "status": user.status,
        "org_id": str(user.org_id) if user.org_id else None,
        "org_name": org_name,
    }



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

    # Check if a user with this email was already invited (has pending status)
    if email:
        pending_result = await db.execute(
            select(User).where(
                User.email == email,
                User.status == "pending",
                User.clerk_user_id.like("invited_%")
            )
        )
        pending_user = pending_result.scalar_one_or_none()
        if pending_user:
            pending_user.clerk_user_id = clerk_user_id
            pending_user.status = "pending"
            pending_user.first_name = data.get("first_name") or ""
            pending_user.last_name = data.get("last_name") or ""
            pending_user.phone = phone
            logger.info("Matched pending user invitation for email %s and clerk_user_id %s", email, clerk_user_id)
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
    public_user_data = data.get("public_user_data", {})
    clerk_user_id = public_user_data.get("user_id")
    clerk_org_id = data.get("organization", {}).get("id")
    if not clerk_user_id or not clerk_org_id:
        return

    user_result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = user_result.scalar_one_or_none()
    org_result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    org = org_result.scalar_one_or_none()

    if not user or not org:
        logger.warning("Membership created but user or org not found: %s / %s", clerk_user_id, clerk_org_id)
        return

    user.org_id = org.id
    clerk_role = data.get("role", "org:member")
    # Map Clerk role to our internal role, but preserve viewer role if already set
    if clerk_role == "org:admin":
        user.role = "admin"
    elif user.role not in ("admin", "viewer"):  # don't downgrade admins or strip viewer
        user.role = "member"

    await log_action(
        db,
        org.id,
        "membership.created",
        user_id=user.id,
        metadata={"clerk_role": clerk_role, "role": user.role},
    )
    logger.info("Linked user %s to org %s as %s", clerk_user_id, clerk_org_id, user.role)


async def _handle_membership_deleted(db: AsyncSession, data: dict) -> None:
    public_user_data = data.get("public_user_data", {})
    clerk_user_id = public_user_data.get("user_id")
    if not clerk_user_id:
        return

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user:
        if user.status != "suspended":
            user.status = "suspended"
            org_id = user.org_id
            user.org_id = None
            if org_id:
                await log_action(
                    db,
                    org_id,
                    "membership.deleted",
                    user_id=user.id,
                    metadata={"clerk_user_id": clerk_user_id},
                )
            logger.info("Suspended user clerk_user_id=%s", clerk_user_id)


async def _handle_user_deleted(db: AsyncSession, data: dict) -> None:
    clerk_user_id = data.get("id")
    if not clerk_user_id:
        return

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user:
        org_id = user.org_id
        if org_id:
            await log_action(
                db,
                org_id,
                "user.deleted",
                user_id=user.id,
                metadata={"clerk_user_id": clerk_user_id},
            )
        await db.delete(user)
        logger.info("Deleted user clerk_user_id=%s", clerk_user_id)
