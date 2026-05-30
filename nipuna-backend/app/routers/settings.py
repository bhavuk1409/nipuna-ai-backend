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
