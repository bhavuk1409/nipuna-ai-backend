"""FastAPI dependencies — auth, org resolution, role enforcement."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.jwks import get_jwks
from app.database import get_db
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


async def resolve_current_user(token: Optional[str], db: AsyncSession) -> User:
    settings = get_settings()

    if settings.env == "dev" and (not token or token in ("mock_token", "undefined", "null", "")):
        result = await db.execute(select(User).order_by(User.created_at).limit(1))
        user = result.scalar_one_or_none()
        if user:
            logger.info("Dev bypass: returning user %s (%s)", user.id, user.email)
            return user

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
        if settings.env == "dev":
            result = await db.execute(select(User).order_by(User.created_at).limit(1))
            user = result.scalar_one_or_none()
            if user:
                logger.info("Dev bypass on JWT error: returning user %s (%s)", user.id, user.email)
                return user
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    # Verify issuer (iss) if CLERK_DOMAIN is configured
    settings = get_settings()
    if settings.clerk_domain:
        expected_iss = f"https://{settings.clerk_domain}"
        if claims.get("iss") != expected_iss:
            logger.warning("JWT issuer mismatch: expected %s, got %s", expected_iss, claims.get("iss"))
            if settings.env == "dev":
                result = await db.execute(select(User).order_by(User.created_at).limit(1))
                user = result.scalar_one_or_none()
                if user:
                    logger.info("Dev bypass on issuer mismatch: returning user %s (%s)", user.id, user.email)
                    return user
            raise HTTPException(status_code=401, detail="Invalid token issuer")

    clerk_user_id: str | None = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims: missing sub")

    result = await db.execute(
        select(User).where(
            User.clerk_user_id == clerk_user_id,
        )
    )
    user = result.scalar_one_or_none()

    if user is not None:
        # Check if there is a pending invitation for this user's email under a different organization
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as bootstrap_db:
            pending_check = await bootstrap_db.execute(
                select(User).where(
                    User.email == user.email,
                    User.status == "pending",
                    User.clerk_user_id.like("invited_%")
                )
            )
            pending_invite = pending_check.scalar_one_or_none()
            if pending_invite and pending_invite.org_id != user.org_id:
                # Retrieve fresh copy in bootstrap_db to update
                fresh_user_res = await bootstrap_db.execute(
                    select(User).where(User.id == user.id)
                )
                fresh_user = fresh_user_res.scalar_one_or_none()
                if fresh_user:
                    fresh_user.org_id = pending_invite.org_id
                    fresh_user.role = pending_invite.role
                    fresh_user.status = "pending"
                    
                    await bootstrap_db.delete(pending_invite)
                    await bootstrap_db.commit()
                    
                    # Re-fetch/refresh the user object in the request's main DB session
                    await db.refresh(user)
                    logger.info("Migrated existing user email=%s to new pending org_id=%s from invitation", user.email, fresh_user.org_id)
        
        # If the user is suspended and has no new invites, deny access
        if user.status == "suspended":
            raise HTTPException(status_code=403, detail="User account is suspended")

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
                email = claims.get("email") or ""
                first_name = claims.get("first_name") or claims.get("given_name") or ""
                last_name = claims.get("last_name") or claims.get("family_name") or ""

                if email:
                    pending_check = await bootstrap_db.execute(
                        select(User).where(
                            User.email == email,
                            User.status == "pending",
                            User.clerk_user_id.like("invited_%")
                        )
                    )
                    pending_user = pending_check.scalar_one_or_none()
                    if pending_user:
                        pending_user.clerk_user_id = clerk_user_id
                        if first_name:
                            pending_user.first_name = first_name
                        if last_name:
                            pending_user.last_name = last_name
                        user = pending_user
                        await bootstrap_db.commit()
                        await bootstrap_db.refresh(user)
                        logger.info("Linked clerk_user_id=%s to pending invitation for email=%s", clerk_user_id, email)

                if user is None:
                    user = User(
                        clerk_user_id=clerk_user_id,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        status="active",
                        role="member",
                    )
                    bootstrap_db.add(user)
                    await bootstrap_db.commit()
                    await bootstrap_db.refresh(user)
                    logger.info("Auto-created user %s (%s) during token bootstrap", clerk_user_id, email)
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


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        token = request.query_params.get("token")
    return await resolve_current_user(token=token, db=db)


async def resolve_current_org(
    token: Optional[str],
    user: User,
    db: AsyncSession,
) -> Organization:
    settings = get_settings()

    if settings.env == "dev" and (not token or token in ("mock_token", "undefined", "null", "")):
        if user.org_id:
            result = await db.execute(
                select(Organization).where(Organization.id == user.org_id)
            )
            org = result.scalar_one_or_none()
            if org is not None:
                return org
        result = await db.execute(select(Organization).order_by(Organization.created_at).limit(1))
        org = result.scalar_one_or_none()
        if org is not None:
            return org

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    clerk_org_id: str | None = None
    try:
        jwks = await get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        if settings.clerk_domain:
            expected_iss = f"https://{settings.clerk_domain}"
            if claims.get("iss") != expected_iss:
                logger.warning("JWT issuer mismatch in org check: expected %s, got %s", expected_iss, claims.get("iss"))
                if settings.env == "dev":
                    if user.org_id:
                        result = await db.execute(
                            select(Organization).where(Organization.id == user.org_id)
                        )
                        org = result.scalar_one_or_none()
                        if org is not None:
                            return org
                    result = await db.execute(select(Organization).order_by(Organization.created_at).limit(1))
                    org = result.scalar_one_or_none()
                    if org is not None:
                        return org
                raise HTTPException(status_code=401, detail="Invalid token issuer")
        clerk_org_id = claims.get("org_id")
    except JWTError as exc:
        if settings.env == "dev":
            if user.org_id:
                result = await db.execute(
                    select(Organization).where(Organization.id == user.org_id)
                )
                org = result.scalar_one_or_none()
                if org is not None:
                    return org
            result = await db.execute(select(Organization).order_by(Organization.created_at).limit(1))
            org = result.scalar_one_or_none()
            if org is not None:
                return org
        logger.warning("JWT decode failed in org check: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    if clerk_org_id:
        result = await db.execute(
            select(Organization).where(Organization.clerk_org_id == clerk_org_id)
        )
        org = result.scalar_one_or_none()
        if org is not None:
            return org

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


async def get_current_org(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    if not token:
        token = request.query_params.get("token")
    return await resolve_current_org(token=token, user=user, db=db)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
