from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_org, get_current_user, require_admin
from app.models.organization import Organization
from app.models.user import User
from app.schemas.team import InviteRequest, MemberResponse, TeamResponse
from app.services.notifications.email import send_email

router = APIRouter(prefix="/team", tags=["team"])


@router.get("/debug-all-orgs")
async def debug_all_orgs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organization))
    orgs = result.scalars().all()
    return [
        {"name": o.name, "clerk_org_id": o.clerk_org_id, "id": str(o.id)}
        for o in orgs
    ]


@router.get("/members", response_model=TeamResponse)
async def get_team_members(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamResponse:
    seats_used_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status != "suspended",
        )
    )
    seats_used = seats_used_result.scalar() or 0

    admin_count_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.role == "admin",
        )
    )
    admin_count = admin_count_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status == "pending",
        )
    )
    pending_reviews = pending_result.scalar() or 0

    members_result = await db.execute(
        select(User).where(
            User.org_id == org.id,
            User.status != "suspended",
        )
    )
    members = members_result.scalars().all()

    return TeamResponse(
        seats_used=seats_used,
        max_seats=org.seats_max,
        admin_count=admin_count,
        pending_reviews=pending_reviews,
        members=[MemberResponse.model_validate(m) for m in members],
    )


@router.post("/invite", response_model=dict[str, str])
async def invite_member(
    body: InviteRequest,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    seats_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status != "suspended",
        )
    )
    seats_used = seats_result.scalar() or 0
    if seats_used >= org.seats_max:
        raise HTTPException(status_code=400, detail="Seat limit reached")

    settings = get_settings()
    clerk_role = body.role
    import httpx
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"Sending Clerk invite: OrgID={org.clerk_org_id}, Email={body.email}, Role={clerk_role}")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.clerk.com/v1/organizations/{org.clerk_org_id}/invitations",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            json={
                "email_address": body.email,
                "role": clerk_role,
                "redirect_url": "https://app.nipunaai.in/dashboard",
            },
        )
        if resp.status_code not in (200, 201):
            error_data = resp.json()
            error_msg = error_data.get("errors", [{}])[0].get("message", "Unknown Clerk error")
            raise HTTPException(
                status_code=400,
                detail=f"Clerk Error: {error_msg}",
            )

    # Send custom invitation email via Resend
    email_html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #1a1a1a;">You've been invited to join {org.name} on Nipuna AI</h2>
                <p>Hello,</p>
                <p>You have been invited to join the <strong>{org.name}</strong> workspace on Nipuna AI as a <strong>{body.role}</strong>.</p>
                <p>Nipuna AI helps teams manage execution, approvals, and enterprise automation coverage with AI-driven agents.</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="https://app.nipunaai.in/dashboard" style="background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Join Workspace</a>
                </div>
                <p>If the button above doesn't work, copy and paste this link into your browser:</p>
                <p style="word-break: break-all;"><a href="https://app.nipunaai.in/dashboard">https://app.nipunaai.in/dashboard</a></p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #888; text-align: center;">Sent via Nipuna AI</p>
            </div>
        </body>
    </html>
    """
    await send_email(
        to=body.email,
        subject=f"Invitation to join {org.name} on Nipuna AI",
        html=email_html,
    )

    return {"status": "invitation_sent"}
