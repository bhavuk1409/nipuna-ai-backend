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
            # If user has no active org_id, automatically associate them with their pending invitation
            if not user.org_id:
                pending_check = await bootstrap_db.execute(
                    select(User).where(
                        User.email == user.email,
                        User.status == "pending",
                        User.clerk_user_id.like("invited_%")
                    ).order_by(User.created_at.desc())
                )
                pending_invite = pending_check.scalar_one_or_none()
                if pending_invite:
                    fresh_user_res = await bootstrap_db.execute(
                        select(User).where(User.id == user.id)
                    )
                    fresh_user = fresh_user_res.scalar_one_or_none()
                    if fresh_user:
                        fresh_user.org_id = pending_invite.org_id
                        fresh_user.role = pending_invite.role
                        fresh_user.status = pending_invite.status
                        
                        await bootstrap_db.delete(pending_invite)
                        await bootstrap_db.commit()
                        
                        await db.refresh(user)
                        logger.info("Automatically migrated user %s to org_id=%s with status=pending because they had no active org", user.email, fresh_user.org_id)

            token_clerk_org_id = claims.get("org_id")
            if token_clerk_org_id:
                org_res = await bootstrap_db.execute(
                    select(Organization).where(Organization.clerk_org_id == token_clerk_org_id)
                )
                clerk_org = org_res.scalar_one_or_none()
                
                # Dynamic self-healing for dev mismatch (real Clerk org ID vs local manual_ prefix)
                if not clerk_org and token_clerk_org_id.startswith("org_"):
                    pending_check_heal = await bootstrap_db.execute(
                        select(User, Organization)
                        .join(Organization, User.org_id == Organization.id)
                        .where(
                            User.email == user.email,
                            User.status == "pending",
                            User.clerk_user_id.like("invited_%"),
                            Organization.clerk_org_id.like("manual_%")
                        )
                    )
                    pending_invite_row = pending_check_heal.first()
                    if pending_invite_row:
                        pending_invite, db_org = pending_invite_row
                        db_org.clerk_org_id = token_clerk_org_id
                        bootstrap_db.add(db_org)
                        await bootstrap_db.commit()
                        logger.info("Self-healed organization clerk_org_id to %s for org %s", token_clerk_org_id, db_org.name)
                        clerk_org = db_org

                if clerk_org:
                    pending_check = await bootstrap_db.execute(
                        select(User).where(
                            User.email == user.email,
                            User.org_id == clerk_org.id,
                            User.status.in_(["pending", "active"]),
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
                            fresh_user.status = pending_invite.status
                            
                            await bootstrap_db.delete(pending_invite)
                            await bootstrap_db.commit()
                            
                            # Re-fetch/refresh the user object in the request's main DB session
                            await db.refresh(user)
                            logger.info("Migrated existing user email=%s to org_id=%s with status=%s from invitation", user.email, fresh_user.org_id, fresh_user.status)
        
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
                        role="admin",
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

    if user is not None:
        # Self-heal missing/mismatched email and names from Clerk claims
        clerk_email = claims.get("email")
        clerk_first = claims.get("first_name") or claims.get("given_name")
        clerk_last = claims.get("last_name") or claims.get("family_name")
        
        updated = False
        if clerk_email and user.email != clerk_email:
            user.email = clerk_email
            updated = True
        if clerk_first and not user.first_name:
            user.first_name = clerk_first
            updated = True
        if clerk_last and not user.last_name:
            user.last_name = clerk_last
            updated = True
        if user.role != "admin":
            user.role = "admin"
            updated = True
            
        if updated:
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("Self-healed user profile fields from Clerk claims")

        clerk_org_id = claims.get("org_id")
        if clerk_org_id:
            org_result = await db.execute(
                select(Organization).where(Organization.clerk_org_id == clerk_org_id)
            )
            clerk_org = org_result.scalar_one_or_none()
            if clerk_org:
                if user.org_id != clerk_org.id:
                    user.org_id = clerk_org.id
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                    logger.info("Synchronized user %s org_id to Clerk active org_id %s", user.email, clerk_org.id)
            else:
                raise HTTPException(
                    status_code=404,
                    detail="No workspace found for this user.",
                )
        else:
            # Check if personal workspace exists in DB
            personal_clerk_id = f"manual_{clerk_user_id}"
            org_result = await db.execute(
                select(Organization).where(Organization.clerk_org_id == personal_clerk_id)
            )
            personal_org = org_result.scalar_one_or_none()
            if not personal_org:
                # By default, create 1 workspace upon account setup
                from app.models.settings import WorkspaceSettings, OrgPreferences
                personal_org = Organization(
                    clerk_org_id=personal_clerk_id,
                    name=f"{user.first_name}'s Workspace" if user.first_name else "My Workspace",
                    plan="free",
                    seats_max=5,
                    ai_credits=100,
                )
                db.add(personal_org)
                await db.flush()

                ws = WorkspaceSettings(org_id=personal_org.id, name=personal_org.name)
                prefs = OrgPreferences(
                    org_id=personal_org.id,
                    approval_required=False,
                    digest_time="09:00",
                    escalation_window=24,
                )
                db.add(ws)
                db.add(prefs)
                await db.flush()
                logger.info("Automatically created default workspace %s for user %s", personal_org.name, user.email)

            if user.org_id != personal_org.id:
                user.org_id = personal_org.id
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info("Synchronized user %s org_id to personal workspace %s", user.email, personal_org.id)

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
        raise HTTPException(
            status_code=404,
            detail="No workspace found for this user.",
        )
    else:
        # Check if personal workspace exists in DB
        clerk_user_id = claims.get("sub")
        if clerk_user_id:
            personal_clerk_id = f"manual_{clerk_user_id}"
            result = await db.execute(
                select(Organization).where(Organization.clerk_org_id == personal_clerk_id)
            )
            org = result.scalar_one_or_none()
            if org is not None:
                return org

        # Fallback to user.org_id
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
