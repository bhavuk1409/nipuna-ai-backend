from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from app.core.jwks import get_jwks
from app.database import get_db
from app.dependencies import oauth2_scheme
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.settings import OrgPreferences, WorkspaceSettings
from app.models.user import User
from app.schemas.auth import OnboardingRequest, OnboardingResponse
from app.config import get_settings

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("", response_model=OnboardingResponse)
async def create_onboarding(
    body: OnboardingRequest,
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    """
    Complete workspace setup. This endpoint does NOT use get_current_user
    or get_current_org as dependencies — it decodes the JWT directly so
    that it works even when no user/org row exists yet.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Decode JWT directly
    try:
        jwks = await get_jwks()
        claims = jwt.decode(
            token, jwks, algorithms=["RS256"], options={"verify_aud": False}
        )
    except JWTError as exc:
        logger.warning("JWT decode failed in onboarding: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    clerk_user_id: str | None = claims.get("sub")
    clerk_org_id: str | None = claims.get("org_id")

    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    # Enforce limit of 1 workspace
    settings = get_settings()
    if settings.clerk_secret_key:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}/organization_memberships",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
            if resp.status_code == 200:
                memberships = resp.json().get("data", [])
                if len(memberships) >= 3:
                    raise HTTPException(
                        status_code=400,
                        detail="You have reached the maximum limit of 3 workspaces.",
                    )

    # ── 1. Upsert the user row ──────────────────────────────────────────────
    user_result = await db.execute(
        select(User).where(User.clerk_user_id == clerk_user_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        if body.email:
            # Multi-org model: pending invites are rows in
            # `organization_members` with `user_id IS NULL` and
            # `status = "pending"`. We don't create a placeholder
            # `User` row in onboarding anymore — the membership
            # table is the source of truth. Find the first pending
            # invite for this email and bind to it.
            pending_result = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.email == body.email.lower(),
                    OrganizationMember.status == "pending",
                    OrganizationMember.user_id.is_(None),
                ).order_by(OrganizationMember.created_at.asc())
            )
            pending_membership = pending_result.scalar_one_or_none()
            if pending_membership is not None:
                # Bind the new user to the existing pending membership.
                user = User(
                    clerk_user_id=clerk_user_id,
                    email=body.email,
                    first_name=body.first_name or "",
                    last_name=body.last_name or "",
                )
                db.add(user)
                await db.flush()  # populate user.id before binding membership
                pending_membership.user_id = user.id
                pending_membership.status = "active"
                user.active_org_id = pending_membership.org_id
                logger.info(
                    "Linked onboarding user %s to pending membership in org %s",
                    body.email, pending_membership.org_id,
                )
            else:
                user = User(
                    clerk_user_id=clerk_user_id,
                    email=body.email or "",
                    first_name=body.first_name or "",
                    last_name=body.last_name or "",
                )
                db.add(user)
                await db.flush()  # gets user.id without committing

    # ── 2. Find or create the org ───────────────────────────────────────────
    org: Organization | None = None

    # Try by Clerk org_id from JWT first
    if clerk_org_id:
        org_result = await db.execute(
            select(Organization).where(Organization.clerk_org_id == clerk_org_id)
        )
        org = org_result.scalar_one_or_none()

    # Try by user's existing `active_org_id` (the new pointer column).
    # We don't read the legacy `User.org_id` anymore — it was dropped
    # in step 8.
    if org is None and user.active_org_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == user.active_org_id)
        )
        org = org_result.scalar_one_or_none()

    if org is None:
        # Create a brand new org
        effective_clerk_org_id = clerk_org_id

        if not effective_clerk_org_id:
            # If no clerk_org_id in JWT, try to create it in Clerk using Backend API
            settings = get_settings()
            if settings.clerk_secret_key:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # 1. Create org in Clerk
                        resp = await client.post(
                            "https://api.clerk.com/v1/organizations",
                            json={
                                "name": body.company_name,
                                "created_by": clerk_user_id,
                            },
                            headers={
                                "Authorization": f"Bearer {settings.clerk_secret_key}",
                                "Content-Type": "application/json",
                            },
                        )
                        if resp.status_code == 200:
                            clerk_org_data = resp.json()
                            new_org_id = clerk_org_data.get("id")
                            if new_org_id:
                                effective_clerk_org_id = new_org_id
                                logger.info("Created Clerk organization '%s' via Backend API: %s (creator: %s)", body.company_name, new_org_id, clerk_user_id)
                        else:
                            logger.warning(
                                "Clerk organization creation failed with status %s: %s",
                                resp.status_code, resp.text[:300]
                            )
                except Exception as exc:
                    logger.warning("Failed to create Clerk organization during onboarding auto-creation: %s", exc)

        # Fallback to local manual ID if Clerk API call failed or is disabled
        if not effective_clerk_org_id:
            effective_clerk_org_id = f"manual_{clerk_user_id}"

        org = Organization(
            clerk_org_id=effective_clerk_org_id,
            name=body.company_name,
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        db.add(org)
        await db.flush()  # gets org.id without committing

    # Always update the org name from the form
    org.name = body.company_name

    # ── 3. Link user → org via OrganizationMember ───────────────────────
    # Multi-org model: membership is the source of truth. We need
    # an active `OrganizationMember(user, org, role="admin")` row.
    # If the user already has an active membership in this org, we
    # keep it. If not, we add one.
    existing_membership = (await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == org.id,
        )
    )).scalar_one_or_none()

    if existing_membership is None:
        new_membership = OrganizationMember(
            user_id=user.id,
            org_id=org.id,
            email=user.email.lower(),
            role="admin",
            status="active",
        )
        db.add(new_membership)

    # Set the user's `active_org_id` (the new pointer column).
    # The legacy `User.org_id` / `User.role` / `User.status` columns
    # were dropped in step 8 — the membership row is the source of
    # truth.
    user.active_org_id = org.id

    # ── 4. Ensure WorkspaceSettings row ────────────────────────────────────
    ws_result = await db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.org_id == org.id)
    )
    ws = ws_result.scalar_one_or_none()
    if ws is None:
        db.add(WorkspaceSettings(org_id=org.id, name=org.name))
    else:
        ws.name = org.name

    # ── 5. Ensure OrgPreferences row ───────────────────────────────────────
    prefs_result = await db.execute(
        select(OrgPreferences).where(OrgPreferences.org_id == org.id)
    )
    if prefs_result.scalar_one_or_none() is None:
        db.add(
            OrgPreferences(
                org_id=org.id,
                approval_required=False,
                digest_time="09:00",
                escalation_window=24,
            )
        )

    # Update user fields if provided in request body and not already set
    if body.email and user.email != body.email:
        user.email = body.email
    if body.first_name and user.first_name != body.first_name:
        user.first_name = body.first_name
    if body.last_name and user.last_name != body.last_name:
        user.last_name = body.last_name

    # ── 6. Single commit ────────────────────────────────────────────────────
    await db.commit()

    # ── 7. Send Welcome Email ───────────────────────────────────────────────
    email_to_use = body.email or user.email
    if email_to_use:
        import asyncio
        from app.services.notifications.email import send_email
        settings = get_settings()

        first_name_to_use = body.first_name or user.first_name or "there"
        company_name_to_use = body.company_name or org.name or "your company"

        email_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Nipuna AI</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f7f9fa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f7f9fa; padding: 40px 0;">
        <tr>
            <td align="center">
                <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border: 1px solid #e1e4e6; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 20px 40px; border-bottom: 1px solid #f0f2f5;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td valign="middle" style="width: 40px;">
                                        <img src="https://nipunaai.in/logo.png" alt="Nipuna AI" width="36" height="36" style="display: block; border: 0; object-fit: contain;">
                                    </td>
                                    <td valign="middle" style="padding-left: 12px; font-size: 20px; font-weight: 700; color: #101012; letter-spacing: -0.02em;">
                                        Nipuna AI
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px 40px 30px 40px;">
                            <h1 style="margin: 0 0 16px 0; font-size: 24px; font-weight: 700; color: #101012; letter-spacing: -0.02em; line-height: 1.25;">
                                We're excited to serve you, {first_name_to_use}!
                            </h1>
                            <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.6; color: #444748;">
                                Thank you for setting up <strong>{company_name_to_use}</strong> on Nipuna AI. We're building the future of business operations, and we're thrilled to partner with you to automate, optimize, and supercharge your workflows.
                            </p>
                            
                            <!-- Accent Divider -->
                            <div style="height: 1px; background-color: #f0f2f5; margin-bottom: 30px;"></div>
                            
                            <h2 style="margin: 0 0 20px 0; font-size: 16px; font-weight: 600; color: #101012; letter-spacing: -0.01em;">
                                Key Platform Features to Explore:
                            </h2>
                            
                            <!-- Features List -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 32px;">
                                <!-- Feature 1 -->
                                <tr>
                                    <td valign="top" style="padding-bottom: 20px; width: 24px;">
                                        <div style="font-size: 16px; line-height: 1.5; color: #101012;">✦</div>
                                    </td>
                                    <td valign="top" style="padding-bottom: 20px; padding-left: 8px;">
                                        <strong style="font-size: 14px; color: #101012; display: block; margin-bottom: 3px;">Unified AI Command Center</strong>
                                        <span style="font-size: 14px; line-height: 1.5; color: #555b5a; display: block;">
                                            Your primary operations desk customized for {company_name_to_use} to launch tasks and oversee AI agent processes.
                                        </span>
                                    </td>
                                </tr>
                                <!-- Feature 2 -->
                                <tr>
                                    <td valign="top" style="padding-bottom: 20px; width: 24px;">
                                        <div style="font-size: 16px; line-height: 1.5; color: #101012;">✦</div>
                                    </td>
                                    <td valign="top" style="padding-bottom: 20px; padding-left: 8px;">
                                        <strong style="font-size: 14px; color: #101012; display: block; margin-bottom: 3px;">Zero Hallucination Financial Copilot</strong>
                                        <span style="font-size: 14px; line-height: 1.5; color: #555b5a; display: block;">
                                            Deterministic, real-time financial analysis, cash flow forecasting, and risk auditing connected directly to Tally or Zoho Books.
                                        </span>
                                    </td>
                                </tr>
                                <!-- Feature 3 -->
                                <tr>
                                    <td valign="top" style="padding-bottom: 20px; width: 24px;">
                                        <div style="font-size: 16px; line-height: 1.5; color: #101012;">✦</div>
                                    </td>
                                    <td valign="top" style="padding-bottom: 20px; padding-left: 8px;">
                                        <strong style="font-size: 14px; color: #101012; display: block; margin-bottom: 3px;">Specialized AI Employees</strong>
                                        <span style="font-size: 14px; line-height: 1.5; color: #555b5a; display: block;">
                                            Hire autonomous digital representatives for specialized functions like sales engagement, support dispatching, and financial specialist roles.
                                        </span>
                                    </td>
                                </tr>
                                <!-- Feature 4 -->
                                <tr>
                                    <td valign="top" style="padding-bottom: 20px; width: 24px;">
                                        <div style="font-size: 16px; line-height: 1.5; color: #101012;">✦</div>
                                    </td>
                                    <td valign="top" style="padding-bottom: 20px; padding-left: 8px;">
                                        <strong style="font-size: 14px; color: #101012; display: block; margin-bottom: 3px;">Full Integration Ecosystem</strong>
                                        <span style="font-size: 14px; line-height: 1.5; color: #555b5a; display: block;">
                                            Seamless hooks for Gmail, WhatsApp, Calendars, cloud services, and crypto/fiat wallets to maximize workflow automation.
                                        </span>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Call to action -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 10px;">
                                <tr>
                                    <td align="center">
                                        <a href="{settings.frontend_url}/dashboard" style="display: inline-block; padding: 14px 32px; background-color: #101012; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600; letter-spacing: -0.01em; box-shadow: 0 4px 10px rgba(16, 16, 18, 0.15); transition: background-color 0.2s ease;">
                                            Launch Command Center
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 30px 40px 40px 40px; background-color: #fafbfc; border-top: 1px solid #f0f2f5; text-align: center;">
                            <p style="margin: 0 0 8px 0; font-size: 12px; color: #8a8f8d;">
                                &copy; 2026 Nipuna AI. All rights reserved.
                            </p>
                            <p style="margin: 0; font-size: 12px; color: #8a8f8d;">
                                <a href="https://docs.nipunaai.in" style="color: #444748; text-decoration: underline;">Read Documentation</a> &nbsp;&bull;&nbsp; 
                                <a href="https://nipunaai.in/privacy" style="color: #444748; text-decoration: underline;">Privacy Policy</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        asyncio.create_task(
            send_email(
                to=email_to_use,
                subject=f"Welcome to Nipuna AI, {first_name_to_use}!",
                html=email_html,
                from_email="Nipuna AI <onboarding@nipunaai.in>",
            )
        )

    return OnboardingResponse(status="ok", org_id=str(org.id))
