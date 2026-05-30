from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.jwks import get_jwks
from app.database import get_db
from app.dependencies import oauth2_scheme
from app.models.organization import Organization
from app.models.settings import OrgPreferences, WorkspaceSettings
from app.models.user import User
from app.schemas.auth import OnboardingRequest, OnboardingResponse

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
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    clerk_user_id: str | None = claims.get("sub")
    clerk_org_id: str | None = claims.get("org_id")

    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    # ── 1. Upsert the user row ──────────────────────────────────────────────
    user_result = await db.execute(
        select(User).where(User.clerk_user_id == clerk_user_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None:
        user = User(
            clerk_user_id=clerk_user_id,
            email="",
            first_name="",
            last_name="",
            status="active",
            role="admin",
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

    # Try by user's existing org_id
    if org is None and user.org_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
        org = org_result.scalar_one_or_none()

    if org is None:
        # Create a brand new org
        # Use a unique fallback so we don't collide on the unique constraint
        effective_clerk_org_id = clerk_org_id or f"manual_{clerk_user_id}"
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

    # ── 3. Link user → org ─────────────────────────────────────────────────
    if user.org_id is None:
        user.org_id = org.id
        user.role = "admin"

    # ── 4. Ensure WorkspaceSettings row ────────────────────────────────────
    ws_result = await db.execute(
        select(WorkspaceSettings).where(WorkspaceSettings.org_id == org.id)
    )
    if ws_result.scalar_one_or_none() is None:
        db.add(WorkspaceSettings(org_id=org.id, name=org.name))

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

    # ── 6. Single commit ────────────────────────────────────────────────────
    await db.commit()

    return OnboardingResponse(status="ok", org_id=str(org.id))
