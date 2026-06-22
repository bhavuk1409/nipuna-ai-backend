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
            html=f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e5e7eb; rounded-lg;">
                <h2 style="color: #111827; font-size: 20px; font-weight: bold; margin-bottom: 16px;">Verify your identity</h2>
                <p style="color: #4b5563; font-size: 14px; line-height: 1.5; margin-bottom: 24px;">
                    We received a request to change your email address on Nipuna AI. Enter the following 6-digit verification code to confirm your identity:
                </p>
                <div style="background-color: #f3f4f6; padding: 16px; border-radius: 8px; text-align: center; margin-bottom: 24px;">
                    <span style="font-family: monospace; font-size: 28px; font-weight: bold; letter-spacing: 4px; color: #111827;">{code}</span>
                </div>
                <p style="color: #9ca3af; font-size: 12px;">
                    This code is valid for 10 minutes. If you did not request this change, please ignore this email or contact support.
                </p>
            </div>
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

