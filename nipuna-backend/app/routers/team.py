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
    email_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Invitation to join {org.name} on Nipuna AI</title>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      
      .wrapper {{
        width: 100%;
        background-color: #f8fafc;
        padding: 40px 20px;
      }}
      
      .container {{
        max-width: 580px;
        margin: 0 auto;
        background-color: #ffffff;
        border: 1px solid #eef0f2;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
        overflow: hidden;
      }}
      
      .content-padding {{
        padding: 40px 40px 32px 40px;
      }}
      
      .header {{
        padding-bottom: 24px;
        border-bottom: 1px solid #f1f3f5;
        margin-bottom: 32px;
      }}
      
      .header-logo {{
        vertical-align: middle;
        margin-right: 10px;
        width: 24px;
        height: 24px;
      }}
      
      .header-text {{
        font-size: 15px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .help-card {{
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 20px;
        margin-top: 32px;
        margin-bottom: 16px;
      }}
      
      .help-icon-wrapper {{
        float: left;
        width: 40px;
        height: 40px;
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 50%;
        text-align: center;
        margin-right: 16px;
      }}
      
      .help-icon {{
        width: 20px;
        height: 20px;
        margin-top: 9px;
      }}
      
      .help-content {{
        overflow: hidden;
      }}
      
      .help-title {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        margin: 0 0 4px 0;
      }}
      
      .help-link {{
        font-size: 12px;
        font-weight: 500;
        color: #64748b;
        text-decoration: none;
      }}
      
      .footer {{
        padding: 24px 40px;
        background-color: #ffffff;
        border-top: 1px solid #f1f3f5;
      }}
      
      .footer-col-left {{
        float: left;
        width: 50%;
      }}
      
      .footer-col-right {{
        float: right;
        width: 50%;
        text-align: right;
      }}
      
      .footer-logo {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
        margin-right: 8px;
        opacity: 0.8;
      }}
      
      .footer-brand {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .footer-sub {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        font-weight: 400;
      }}
      
      .footer-copy {{
        font-size: 12px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }}
      
      .clearfix::after {{
        content: "";
        clear: both;
        display: table;
      }}
      
      @media screen and (max-width: 600px) {{
        .wrapper {{
          padding: 20px 12px;
        }}
        
        .content-padding {{
          padding: 24px 20px 24px 20px;
        }}
        
        .footer {{
          padding: 20px;
        }}
        
        .footer-col-left, .footer-col-right {{
          float: none;
          width: 100%;
          text-align: left;
        }}
        
        .footer-col-right {{
          margin-top: 16px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="container">
        
        <!-- Email Body Container -->
        <div class="content-padding">
          
          <!-- Header -->
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Join your team.
          </h1>
          <h2 style="font-size: 20px; font-weight: 600; color: #0f172a; margin: 0 0 16px 0; letter-spacing: -0.02em; line-height: 1.3;">
            You've been invited to join {org.name} on Nipuna AI
          </h2>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            Hello,<br><br>
            You have been invited to join the <strong>{org.name}</strong> workspace on Nipuna AI as a <strong>{body.role}</strong>. Nipuna AI helps teams manage execution, approvals, and enterprise automation coverage with AI-driven agents.
          </p>
          
          <!-- Action Button -->
          <div style="margin-top: 32px; margin-bottom: 24px;">
            <a href="https://app.nipunaai.in/dashboard" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif;">
              Join Workspace &nbsp; <span style="font-size: 14px; font-weight: 400; vertical-align: middle;">➔</span>
            </a>
          </div>
          
          <!-- Help / Documentation Card -->
          <div class="help-card clearfix">
            <div class="help-icon-wrapper">
              <svg class="help-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="#334155">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
              </svg>
            </div>
            <div class="help-content">
              <h4 class="help-title">Need help getting started?</h4>
              <a href="https://nipunaai.in/documentation" class="help-link">View Documentation &nbsp;❯</a>
            </div>
          </div>
          
        </div>
        
        <!-- Footer -->
        <div class="footer clearfix">
          <div class="footer-col-left">
            <div>
              <img class="footer-logo" src="https://www.nipunaai.in/logo.png" alt="" />
              <span class="footer-brand">Nipuna AI</span>
            </div>
            <div class="footer-sub">AI Operating System for Business</div>
          </div>
          <div class="footer-col-right">
            <p class="footer-copy">© 2026 Nipuna AI.<br>All rights reserved.</p>
          </div>
        </div>
        
      </div>
    </div>
  </body>
</html>"""
    await send_email(
        to=body.email,
        subject=f"Invitation to join {org.name} on Nipuna AI",
        html=email_html,
    )

    return {"status": "invitation_sent"}
