"""FastAPI dependencies — auth, org resolution, role enforcement."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwks import get_jwks
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        jwks = await get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    clerk_user_id: str | None = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    result = await db.execute(
        select(User).where(
            User.clerk_user_id == clerk_user_id,
            User.status != "suspended",
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        # Auto-create the user row if they authenticated with Clerk but
        # the webhook hasn't fired yet (race condition common in dev).
        # We use a separate session so we don't interfere with the caller's
        # transaction — the route handler owns its own commit.
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as bootstrap_db:
            # Double-check in the new session to avoid race conditions
            check = await bootstrap_db.execute(
                select(User).where(User.clerk_user_id == clerk_user_id)
            )
            user = check.scalar_one_or_none()
            if user is None:
                user = User(
                    clerk_user_id=clerk_user_id,
                    email="",  # Clerk JWTs don't embed email by default
                    first_name="",
                    last_name="",
                    status="active",
                    role="member",
                )
                bootstrap_db.add(user)
                await bootstrap_db.commit()
                await bootstrap_db.refresh(user)
        # Re-fetch in the caller's session so the object is bound correctly
        result2 = await db.execute(
            select(User).where(User.clerk_user_id == clerk_user_id)
        )
        user = result2.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found. Complete onboarding first.",
            )
    return user


async def get_current_org(
    token: Optional[str] = Depends(oauth2_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Try to get org_id from JWT first (most reliable)
    clerk_org_id: str | None = None
    try:
        jwks = await get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        clerk_org_id = claims.get("org_id")
    except JWTError as exc:
        logger.warning("JWT decode failed in org check: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    # Look up by clerk_org_id from JWT if present
    if clerk_org_id:
        result = await db.execute(
            select(Organization).where(Organization.clerk_org_id == clerk_org_id)
        )
        org = result.scalar_one_or_none()
        if org is not None:
            return org

    # Fall back to user's org_id (set by webhook or onboarding)
    if user.org_id:
        result = await db.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
        org = result.scalar_one_or_none()
        if org is not None:
            return org

    raise HTTPException(
        status_code=404,
        detail="No workspace found for this user.",
    )


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
