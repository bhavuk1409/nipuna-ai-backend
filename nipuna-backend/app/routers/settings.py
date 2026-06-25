from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_org, get_current_user, require_admin
from app.models.organization import Organization
from app.models.settings import OrgPreferences, WorkspaceSettings
from app.models.user import User
from app.schemas.settings import (
    PreferencesResponse,
    PreferencesUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.utils.audit import log_action

import httpx

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/workspace", response_model=WorkspaceResponse)
async def get_workspace(
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    result = await db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.org_id == org.id)
    )
    ws = result.scalar_one_or_none()
    return WorkspaceResponse(name=ws.name if ws else org.name)


@router.put("/workspace")
async def update_workspace(
    body: WorkspaceUpdate,
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.org_id == org.id)
    )
    ws = result.scalar_one_or_none()
    if ws:
        ws.name = body.name
    else:
        ws = WorkspaceSettings(org_id=org.id, name=body.name)
        db.add(ws)
    await db.commit()
    return {"status": "ok"}


@router.delete("/workspace/{clerk_org_id}")
async def delete_workspace(
    clerk_org_id: str,
    body: dict[str, str],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if clerk_org_id.startswith("manual_") or clerk_org_id == "manual":
        raise HTTPException(
            status_code=400,
            detail="Main workspace cannot be deleted"
        )

    # Fetch the organization
    result = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Workspace not found")

    confirm_name = body.get("confirm_name", "")
    if confirm_name != org.name:
        raise HTTPException(
            status_code=400,
            detail="Confirmation name does not match workspace name"
        )

    # Check Clerk organization membership API to verify admin role
    settings = get_settings()
    is_admin = False

    if settings.clerk_secret_key:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{user.clerk_user_id}/organization_memberships",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
            if resp.status_code == 200:
                memberships = resp.json().get("data", [])
                for m in memberships:
                    target_org = m.get("organization", {})
                    if target_org.get("id") == clerk_org_id:
                        role = m.get("role")
                        if role in ("org:admin", "admin"):
                            is_admin = True
                            break
            else:
                logger.warning("Failed to fetch organization memberships from Clerk: %s", resp.text)
    else:
        # Dev / test environment bypass
        is_admin = True

    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only workspace administrators can delete this workspace"
        )

    # Safety: update all users linked to this organization so they are not cascade-deleted
    users_result = await db.execute(
        select(User).where(User.org_id == org.id)
    )
    active_users = users_result.scalars().all()

    for u in active_users:
        # Find or create their personal workspace (manual_{u.clerk_user_id})
        personal_clerk_id = f"manual_{u.clerk_user_id}"
        p_org_result = await db.execute(
            select(Organization).where(Organization.clerk_org_id == personal_clerk_id)
        )
        p_org = p_org_result.scalar_one_or_none()
        if not p_org:
            p_org = Organization(
                clerk_org_id=personal_clerk_id,
                name="Main Workspace",
                plan="free",
                seats_max=5,
                ai_credits=100,
            )
            db.add(p_org)
            await db.flush() # get ID
            
            # Ensure workspace settings and preferences exist for the personal workspace
            db.add(WorkspaceSettings(org_id=p_org.id, name=p_org.name))
            db.add(OrgPreferences(org_id=p_org.id))

        u.org_id = p_org.id
        u.role = "admin"
        db.add(u)

    # Log before deleting the organization from Clerk and database
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workspace_deleted",
        metadata={"org_id": str(org.id), "name": org.name}
    )

    # Delete from Clerk
    if settings.clerk_secret_key:
        async with httpx.AsyncClient() as client:
            clerk_resp = await client.delete(
                f"https://api.clerk.com/v1/organizations/{clerk_org_id}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
            if clerk_resp.status_code not in (200, 204) and clerk_resp.status_code != 404:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete organization from Clerk: {clerk_resp.text}"
                )

    await db.delete(org)
    await db.commit()

    return {"status": "workspace deleted"}


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    result = await db.execute(
        select(OrgPreferences).where(OrgPreferences.org_id == org.id)
    )
    prefs = result.scalar_one_or_none()
    if prefs:
        return PreferencesResponse(
            approval_required=prefs.approval_required,
            digest_time=prefs.digest_time,
            escalation_window=prefs.escalation_window,
        )
    return PreferencesResponse(
        approval_required=False,
        digest_time="09:00",
        escalation_window=24,
    )


@router.put("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(OrgPreferences).where(OrgPreferences.org_id == org.id)
    )
    prefs = result.scalar_one_or_none()
    if prefs:
        prefs.approval_required = body.approval_required
        prefs.digest_time = body.digest_time
        prefs.escalation_window = body.escalation_window
    else:
        prefs = OrgPreferences(
            org_id=org.id,
            approval_required=body.approval_required,
            digest_time=body.digest_time,
            escalation_window=body.escalation_window,
        )
        db.add(prefs)
    await db.commit()
    return {"status": "ok"}


@router.delete("/account")
async def delete_account(
    body: dict[str, str],
    org: Organization = Depends(get_current_org),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    confirm = body.get("confirm", "")
    if confirm != "DELETE MY ACCOUNT":
        raise HTTPException(status_code=400, detail="Confirmation string must match exactly")

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"https://api.clerk.com/v1/users/{user.clerk_user_id}",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        )
        if resp.status_code not in (200, 204):
            raise HTTPException(status_code=500, detail="Failed to delete user from Clerk")

    await log_action(db, org_id=org.id, user_id=user.id,
                     action="account_deleted",
                     metadata={"org_id": str(org.id)})
    await db.delete(org)
    await db.commit()

    return {"status": "account deleted"}


import hmac
import hashlib
import time
import random
import logging

logger = logging.getLogger(__name__)


@router.post("/request-email-code")
async def request_email_code(
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    from app.services.notifications.email import send_email

    # Generate a random 6-digit verification code
    code = "".join(random.choices("0123456789", k=6))
    
    # Log it so developers can see the code if email service is not configured
    logger.info("SECURITY CODE GENERATED: User %s code is %s", user.email, code)

    # Send code via email
    try:
        await send_email(
            to=user.email,
            subject="Verify your identity — Nipuna AI",
            html=f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Verify your identity — Nipuna AI</title>
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
      
      .code-display {{
        background-color: #f8fafc;
        border: 1px solid #eef0f2;
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        margin-top: 32px;
        margin-bottom: 24px;
      }}
      
      .code-text {{
        font-family: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
        font-size: 36px;
        font-weight: 700;
        letter-spacing: 6px;
        color: #0f172a;
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
        
        <div class="content-padding">
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Verification Code
          </h1>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            We received a request to change your email address on Nipuna AI. Enter the following 6-digit verification code to confirm your identity:
          </p>
          
          <div class="code-display">
            <span class="code-text">{code}</span>
          </div>
          
          <p style="font-size: 12px; line-height: 1.5; color: #94a3b8; margin: 24px 0 0 0; font-weight: 400;">
            This code is valid for 10 minutes. If you did not request this change, please ignore this email or contact support.
          </p>
        </div>
        
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
</html>
"""
        )
    except Exception as e:
        logger.error("Failed to send verification email: %s", e)

    # Generate a secure signature of the code
    settings = get_settings()
    expiry = int(time.time()) + 600  # 10 minutes
    message = f"{user.id}:{code}:{expiry}"
    sig = hmac.new(
        (settings.clerk_secret_key or "default_secret").encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return {"signature": f"{expiry}:{sig}"}


@router.post("/verify-email-code")
async def verify_email_code(
    body: dict[str, str],
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    entered_code = body.get("code", "")
    signature = body.get("signature", "")

    if not entered_code or not signature:
        raise HTTPException(status_code=400, detail="Code and signature are required")

    try:
        expiry_str, sig = signature.split(":", 1)
        expiry = int(expiry_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature format")

    if time.time() > expiry:
        raise HTTPException(status_code=400, detail="Verification code has expired")

    settings = get_settings()
    message = f"{user.id}:{entered_code}:{expiry_str}"
    expected_sig = hmac.new(
        (settings.clerk_secret_key or "default_secret").encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(status_code=400, detail="Incorrect verification code")

    return {"verified": True}


@router.post("/verify-password")
async def verify_password(
    body: dict[str, str],
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    password = body.get("password", "")
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.clerk.com/v1/users/{user.clerk_user_id}/verify_password",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            json={"password": password},
        )
        if resp.status_code != 200:
            error_msg = "Incorrect password"
            try:
                error_data = resp.json()
                if "errors" in error_data and len(error_data["errors"]) > 0:
                    error_msg = error_data["errors"][0]["message"]
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=error_msg)

        data = resp.json()
        return {"verified": data.get("verified", False)}

