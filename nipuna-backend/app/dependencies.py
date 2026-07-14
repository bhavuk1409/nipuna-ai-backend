"""FastAPI dependencies — auth, org resolution, role enforcement.

Multi-tenant model (post-Step-2)
--------------------------------

A user can belong to many organizations at once, joined through
`OrganizationMember(user_id, org_id, role, status)`. The user's
*active* org is the single FK `User.active_org_id`, which is set:

- by the alembic backfill (one membership per user),
- by `POST /api/v1/auth/switch-org` (the user picks),
- by `resolve_current_user`'s dev-bypass (first sign-in picks the
  most-recently-created active membership).

`resolve_current_org` reads `user.active_org_id` (DB-driven, not from
the Clerk `org_id` JWT claim — that claim is now informational only)
and validates the user has an `OrganizationMember` row for that org
with `status='active'` before returning the Organization.

The Clerk `org_id` claim is *not* used to pick the active org. It is
still read for logging and for the self-heal in
`_handle_membership_created`, but the active-org choice is always
DB-driven.

Backward compatibility during the migration window
---------------------------------------------------

`User.org_id`, `User.role`, and `User.status` columns still exist and
are kept in sync with the membership row by `resolve_current_user` so
the legacy code paths (the team router, settings, etc.) keep working
until they're rewritten in step 6. A follow-up migration (step 8)
drops those columns.
"""

from __future__ import annotations

import logging
import uuid
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
from app.models.organization_member import OrganizationMember
from app.models.user import User

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_active_membership(
    user: User,
    db: AsyncSession,
) -> OrganizationMember | None:
    """Return the user's membership for their `active_org_id`, or None.

    Validates the user actually has an active membership for the org
    the dep says is active. Returns None on miss so the caller can
    raise a 403/404 with a clear message.
    """
    if user.active_org_id is None:
        return None
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == user.active_org_id,
            OrganizationMember.status == "active",
        )
    )
    return res.scalar_one_or_none()


async def _pick_default_active_org(user: User, db: AsyncSession) -> uuid.UUID | None:
    """Pick the most-recently-created active membership for the user.

    Returns the org_id (UUID) or None if the user has no active
    memberships. The caller persists this on `user.active_org_id`.
    """
    res = await db.execute(
        select(OrganizationMember.org_id)
        .where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
        .order_by(OrganizationMember.created_at.desc())
        .limit(1)
    )
    val = res.scalar_one_or_none()
    return val if isinstance(val, uuid.UUID) else None


async def _ensure_dev_membership(user: User, db: AsyncSession) -> None:
    """Create a default `OrganizationMember` row for a dev user that has
    an `active_org_id` but no membership (e.g. a user whose legacy
    `User.org_id` was migrated to `active_org_id` but whose membership
    row is missing for some reason).

    Idempotent: if a membership already exists for the (user, active_org)
    pair, this is a no-op.
    """
    if user.active_org_id is None:
        return
    from sqlalchemy.exc import IntegrityError
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == user.active_org_id,
        )
    )
    if res.scalar_one_or_none() is not None:
        return
    new_membership = OrganizationMember(
        user_id=user.id,
        org_id=user.active_org_id,
        email=(user.email or "").lower() or f"dev-{user.id}@nipuna.local",
        role="admin",
        status="active",
    )
    db.add(new_membership)
    try:
        await db.commit()
    except IntegrityError:
        # Another request created it in parallel; safe to ignore.
        await db.rollback()


# ---------------------------------------------------------------------------
# Auth: user + active-org resolution
# ---------------------------------------------------------------------------


async def resolve_current_user(token: Optional[str], db: AsyncSession) -> User:
    settings = get_settings()

    if settings.env == "dev" and (not token or token in ("mock_token", "undefined", "null", "")):
        result = await db.execute(select(User).order_by(User.created_at).limit(1))
        user = result.scalar_one_or_none()
        if user:
            # Ensure the dev user has an `active_org_id` — the migration
            # backfilled it, but a freshly-created user (e.g. a new test
            # row) might not have one yet.
            if user.active_org_id is None:
                picked = await _pick_default_active_org(user, db)
                if picked is not None:
                    user.active_org_id = picked
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
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
                if user.active_org_id is None:
                    picked = await _pick_default_active_org(user, db)
                    if picked is not None:
                        user.active_org_id = picked
                        db.add(user)
                        await db.commit()
                        await db.refresh(user)
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
                    if user.active_org_id is None:
                        picked = await _pick_default_active_org(user, db)
                        if picked is not None:
                            user.active_org_id = picked
                            db.add(user)
                            await db.commit()
                            await db.refresh(user)
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
        # Self-heal block — runs in a separate session so we don't
        # interfere with the caller's transaction. This is the
        # multi-org-aware version of the old self-heal.
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as bootstrap_db:
            # If the user has zero active memberships anywhere AND
            # there's a pending invite for their email, auto-bind
            # them to the inviting org. This handles the "first
            # sign-in with a pending invite" flow: the inviter
            # wrote a `OrganizationMember(user_id IS NULL, email, ...)`
            # row, and the user has no other workspaces, so they
            # land in the inviting one.
            #
            # Important: we only auto-bind when the user has *no*
            # other active memberships. If they belong to other
            # orgs already, the user explicitly decides which org
            # to accept the invite into via `/team/accept` — we
            # don't surprise them by silently switching their
            # active org.
            if user.active_org_id is None:
                other_active = (await bootstrap_db.execute(
                    select(OrganizationMember.id)
                    .where(
                        OrganizationMember.user_id == user.id,
                        OrganizationMember.status == "active",
                    )
                    .limit(1)
                )).scalar_one_or_none()
                if other_active is None:
                    pending_membership = (await bootstrap_db.execute(
                        select(OrganizationMember)
                        .where(
                            OrganizationMember.email == user.email.lower(),
                            OrganizationMember.status == "pending",
                            OrganizationMember.user_id.is_(None),
                        )
                        .order_by(OrganizationMember.created_at.desc())
                    )).scalar_one_or_none()
                    if pending_membership is not None:
                        # Bind the user to the placeholder row but
                        # keep `status='pending'` so the explicit
                        # /team/accept flow is still the source of
                        # truth for "did the user accept this?".
                        # The membership's `user_id` is what gates
                        # the accept lookup against the wrong
                        # invitee.
                        pending_membership.user_id = user.id
                        await bootstrap_db.commit()
                        # Mark `active_org_id` to the inviting org
                        # so the user's first request lands in the
                        # right place, but only if they don't have
                        # an active org already. If they do, we
                        # leave the active pointer alone — the
                        # user explicitly chose where they were.
                        if user.active_org_id is None:
                            user.active_org_id = pending_membership.org_id
                            db.add(user)
                            await db.commit()
                            await db.refresh(user)
                        logger.info(
                            "Self-heal: bound user %s to pending membership in org %s (status still pending)",
                            user.email, pending_membership.org_id,
                        )

            token_clerk_org_id = claims.get("org_id")
            if token_clerk_org_id:
                # If the Clerk session carries an org, look up that org
                # by clerk_org_id. If it doesn't exist locally yet
                # (e.g. webhook hasn't fired), we self-heal by creating
                # a local Organization + membership for the user.
                org_res = await bootstrap_db.execute(
                    select(Organization).where(Organization.clerk_org_id == token_clerk_org_id)
                )
                clerk_org = org_res.scalar_one_or_none()

                # Dynamic self-healing for dev mismatch (real Clerk org ID vs local manual_ prefix)
                if not clerk_org and token_clerk_org_id.startswith("org_"):
                    pending_membership = (await bootstrap_db.execute(
                        select(OrganizationMember)
                        .join(Organization, Organization.id == OrganizationMember.org_id)
                        .where(
                            OrganizationMember.email == user.email.lower(),
                            OrganizationMember.status == "pending",
                            OrganizationMember.user_id.is_(None),
                            Organization.clerk_org_id.like("manual_%"),
                        )
                    )).scalar_one_or_none()
                    if pending_membership is not None:
                        target_org = (await bootstrap_db.execute(
                            select(Organization).where(Organization.id == pending_membership.org_id)
                        )).scalar_one_or_none()
                        if target_org is not None:
                            target_org.clerk_org_id = token_clerk_org_id
                            await bootstrap_db.commit()
                            clerk_org = target_org
                            logger.info(
                                "Self-healed organization clerk_org_id to %s for org %s",
                                token_clerk_org_id, target_org.name,
                            )

                if not clerk_org:
                    # Fetch organization details from Clerk using the backend API
                    from app.services.clerk import get_clerk_organization
                    org_data = await get_clerk_organization(token_clerk_org_id, settings.clerk_secret_key)
                    org_name = org_data.get("name") if org_data else None
                    if not org_name:
                        org_name = f"Workspace {token_clerk_org_id[:8]}"

                    # Create a new local Organization
                    clerk_org = Organization(
                        clerk_org_id=token_clerk_org_id,
                        name=org_name,
                        plan="free",
                        seats_max=5,
                        ai_credits=100,
                    )
                    bootstrap_db.add(clerk_org)
                    await bootstrap_db.flush()

                    from app.models.settings import WorkspaceSettings, OrgPreferences
                    ws = WorkspaceSettings(org_id=clerk_org.id, name=clerk_org.name)
                    prefs = OrgPreferences(
                        org_id=clerk_org.id,
                        approval_required=False,
                        digest_time="09:00",
                        escalation_window=24,
                    )
                    bootstrap_db.add(ws)
                    bootstrap_db.add(prefs)
                    await bootstrap_db.commit()
                    logger.info("Self-healed: dynamically created missing Organization %s (clerk_org_id=%s)", org_name, token_clerk_org_id)

                if clerk_org is not None and user.active_org_id != clerk_org.id:
                    # Look for an active membership for the user in this
                    # Clerk org. If none, create one (admin role — the
                    # webhook handler will adjust if needed).
                    existing = (await bootstrap_db.execute(
                        select(OrganizationMember).where(
                            OrganizationMember.user_id == user.id,
                            OrganizationMember.org_id == clerk_org.id,
                        )
                    )).scalar_one_or_none()
                    if existing is None:
                        new_membership = OrganizationMember(
                            user_id=user.id,
                            org_id=clerk_org.id,
                            email=user.email.lower(),
                            role="admin",  # default to admin for the first Clerk org a user joins
                            status="active",
                        )
                        bootstrap_db.add(new_membership)
                        await bootstrap_db.commit()
                        logger.info(
                            "Created active membership for user %s in Clerk org %s",
                            user.email, clerk_org.id,
                        )
                    user.active_org_id = clerk_org.id
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                    logger.info(
                        "Migrated existing user email=%s to org_id=%s (Clerk org)",
                        user.email, user.active_org_id,
                    )

        # If the user has no active memberships at all, deny access.
        # We allow the case where the user has at least one pending
        # membership — they're in the middle of accepting an invite,
        # and the explicit `/team/accept` flow is the way forward.
        # (The `OrganizationMember.status` column is the source of
        # truth — the legacy `User.status` column was dropped in
        # step 8.)
        active_count = (await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == "active",
            ).limit(1)
        )).scalar_one_or_none()
        if active_count is None:
            pending_count = (await db.execute(
                select(OrganizationMember.id).where(
                    OrganizationMember.user_id == user.id,
                    OrganizationMember.status == "pending",
                ).limit(1)
            )).scalar_one_or_none()
            if pending_count is None:
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
                    pending_membership = (await bootstrap_db.execute(
                        select(OrganizationMember).where(
                            OrganizationMember.email == email.lower(),
                            OrganizationMember.status == "pending",
                            OrganizationMember.user_id.is_(None),
                        )
                    )).scalar_one_or_none()
                    if pending_membership is not None:
                        # The invitee is signing in for the first time.
                        # We need to create a User row and bind it to
                        # the pending membership.
                        user = User(
                            clerk_user_id=clerk_user_id,
                            email=email,
                            first_name=first_name,
                            last_name=last_name,
                        )
                        bootstrap_db.add(user)
                        await bootstrap_db.flush()
                        # Flush so user.id is populated; now bind.
                        pending_membership.user_id = user.id
                        pending_membership.status = "active"
                        if first_name:
                            user.first_name = first_name
                        if last_name:
                            user.last_name = last_name
                        user.active_org_id = pending_membership.org_id
                        await bootstrap_db.commit()
                        await bootstrap_db.refresh(user)
                        logger.info(
                            "Linked clerk_user_id=%s to pending membership in org %s",
                            clerk_user_id, pending_membership.org_id,
                        )
                        # Re-fetch in caller session and return.
                        result2 = await db.execute(
                            select(User).where(User.clerk_user_id == clerk_user_id)
                        )
                        user = result2.scalar_one_or_none()
                        if user is not None:
                            return user

                if user is None:
                    user = User(
                        clerk_user_id=clerk_user_id,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
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
        # Note: `User.role` was a legacy column (dropped in step 8).
        # The per-membership role on `OrganizationMember` is the
        # source of truth — see `require_admin` for the read path.
            updated = True

        if updated:
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("Self-healed user profile fields from Clerk claims")

        # If the user has no `active_org_id`, set up a personal
        # workspace. The dev bypass and webhook self-heal above
        # should normally have set this up, but this is the
        # last-resort bootstrap for a brand-new Clerk user.
        clerk_org_id = claims.get("org_id")

        # JIT Sync: If the token contains an active Clerk org_id, ensure
        # it is created locally and the user has an active membership row.
        if clerk_org_id and clerk_org_id.startswith("org_"):
            # Check if this organization exists in our DB
            org_res = await db.execute(
                select(Organization).where(Organization.clerk_org_id == clerk_org_id)
            )
            org = org_res.scalar_one_or_none()
            if org is None:
                # Fast INSERT — no Clerk API call here so we don't create a
                # timing window where the concurrent org.created webhook can
                # win the race and leave us with an unhandled IntegrityError.
                from sqlalchemy.exc import IntegrityError as _IntegrityError
                from app.models.settings import WorkspaceSettings, OrgPreferences
                try:
                    org = Organization(
                        clerk_org_id=clerk_org_id,
                        name="New Workspace",
                        plan="free",
                        seats_max=5,
                        ai_credits=100,
                    )
                    db.add(org)
                    await db.flush()

                    ws = WorkspaceSettings(org_id=org.id, name=org.name)
                    prefs = OrgPreferences(
                        org_id=org.id,
                        approval_required=False,
                        digest_time="09:00",
                        escalation_window=24,
                    )
                    db.add(ws)
                    db.add(prefs)
                    await db.flush()
                    logger.info("JIT-Created organization clerk_org_id=%s", clerk_org_id)
                except _IntegrityError:
                    # Webhook beat us — roll back and fetch the existing row.
                    await db.rollback()
                    org_res2 = await db.execute(
                        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
                    )
                    org = org_res2.scalar_one_or_none()
                    # Re-fetch user since rollback expires it
                    user_res2 = await db.execute(
                        select(user.__class__).where(user.__class__.id == user.id)
                    )
                    user = user_res2.scalar_one()
                    logger.info("JIT org creation: recovered from webhook race for clerk_org_id=%s", clerk_org_id)

            if org is not None:
                # Check if the user has an active membership in this org
                memb_res = await db.execute(
                    select(OrganizationMember).where(
                        OrganizationMember.org_id == org.id,
                        OrganizationMember.user_id == user.id,
                    )
                )
                membership = memb_res.scalar_one_or_none()
                membership_updated = False
                if membership is None:
                    try:
                        membership = OrganizationMember(
                            user_id=user.id,
                            org_id=org.id,
                            email=user.email.lower(),
                            role="admin",
                            status="active",
                        )
                        db.add(membership)
                        await db.flush()
                        membership_updated = True
                        logger.info("JIT-Linked user %s to org %s", user.email, clerk_org_id)
                    except _IntegrityError:
                        # Webhook's organizationMembership.created committed this row.
                        await db.rollback()
                        memb_res2 = await db.execute(
                            select(OrganizationMember).where(
                                OrganizationMember.org_id == org.id,
                                OrganizationMember.user_id == user.id,
                            )
                        )
                        membership = memb_res2.scalar_one()
                        user_res3 = await db.execute(
                            select(user.__class__).where(user.__class__.id == user.id)
                        )
                        user = user_res3.scalar_one()
                        logger.info("JIT membership: recovered from webhook race user=%s org=%s", user.email, clerk_org_id)
                elif membership.status != "active":
                    membership.status = "active"
                    db.add(membership)
                    membership_updated = True

                # Update user.active_org_id to point to this org
                user_updated = False
                if user.active_org_id != org.id:
                    user.active_org_id = org.id
                    db.add(user)
                    user_updated = True

                if membership_updated or user_updated:
                    await db.commit()
                    await db.refresh(user)
                    if membership_updated:
                        await db.refresh(membership)

        if user.active_org_id is None:
            # Before creating a "My Workspace" placeholder, check if the user
            # already has any real org memberships. This happens during sign-up
            # when the session is created BEFORE the company form is submitted:
            # the user's JWT hits an API endpoint with no org_id, so we'd normally
            # auto-create "My Workspace". But if `register-workspace` has already
            # created a real org (or will be called momentarily), we should NOT
            # create a placeholder — it will show up as a ghost in the switcher.
            existing_memberships_res = await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == user.id).limit(1)
            )
            has_existing_memberships = existing_memberships_res.scalar_one_or_none() is not None

            if has_existing_memberships:
                # User already belongs to at least one org — pick it as active
                # instead of creating a placeholder. resolve_current_org will also
                # handle this lazily, but set it here for robustness.
                best_mem_res = await db.execute(
                    select(OrganizationMember)
                    .where(OrganizationMember.user_id == user.id, OrganizationMember.status == "active")
                    .order_by(OrganizationMember.created_at.desc())
                    .limit(1)
                )
                best_mem = best_mem_res.scalar_one_or_none()
                if best_mem is not None:
                    user.active_org_id = best_mem.org_id
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                    logger.info("Skipped placeholder creation; assigned active_org_id=%s for user %s", user.active_org_id, user.email)
            else:
                personal_clerk_id = f"manual_{clerk_user_id}"
                org_result = await db.execute(
                    select(Organization).where(Organization.clerk_org_id == personal_clerk_id)
                )
                personal_org = org_result.scalar_one_or_none()
                if personal_org is None:
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

                    # Also create the membership row for the user.
                    membership = OrganizationMember(
                        user_id=user.id,
                        org_id=personal_org.id,
                        email=user.email.lower(),
                        role="admin",
                        status="active",
                    )
                    db.add(membership)
                    await db.flush()
                    logger.info("Automatically created default workspace %s for user %s", personal_org.name, user.email)

                user.active_org_id = personal_org.id
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info("Synchronized user %s to personal workspace %s", user.email, personal_org.id)

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
    """Resolve the active org for the request.

    Order of precedence (after the user has been resolved):
    1. The user's persisted `active_org_id` (DB-driven, set by the
       dev bypass, the migration, the Clerk self-heal, or
       `POST /auth/switch-org`).
    2. A lazy fallback: pick the most-recently-created active
       membership for the user and persist it.

    The Clerk `org_id` JWT claim is *not* used here. It is read
    elsewhere for self-healing but the active org is always
    DB-driven.
    """
    settings = get_settings()

    # Lazy-default for users whose `active_org_id` was lost (e.g. the
    # org was deleted and the dep set it to NULL via ON DELETE SET
    # NULL). Pick a sensible default and persist it.
    if user.active_org_id is None:
        picked = await _pick_default_active_org(user, db)
        if picked is not None:
            user.active_org_id = picked
            db.add(user)
            await db.commit()
            await db.refresh(user)
            logger.info("Lazy-defaulted active_org_id for user %s to %s", user.email, picked)

    if user.active_org_id is None:
        # Last-resort: in dev, fall through to the first org in the
        # DB so the existing test suite still works. Production should
        # never hit this — every user has at least one membership by
        # the time they have a stable session.
        if settings.env == "dev":
            result = await db.execute(select(Organization).order_by(Organization.created_at).limit(1))
            org = result.scalar_one_or_none()
            if org is not None:
                return org
        raise HTTPException(
            status_code=404,
            detail="No workspace found for this user.",
        )

    # Validate the user has an active membership for their active org.
    membership = await _get_active_membership(user, db)
    if membership is None:
        if settings.env == "dev":
            # Dev fallback: if the dev bypass produced an active_org_id
            # but no membership row, the self-heal in
            # `resolve_current_user` will create one on the next
            # request. We re-attempt the self-heal here so the very
            # first request through a freshly-migrated dev user
            # still resolves.
            await _ensure_dev_membership(user, db)
            membership = await _get_active_membership(user, db)
            if membership is not None:
                # Re-resolve the org below with the now-valid membership.
                pass
            else:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have access to that workspace.",
                )
        else:
            raise HTTPException(
                status_code=403,
                detail="You don't have access to that workspace.",
            )

    result = await db.execute(
        select(Organization).where(Organization.id == user.active_org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=404,
            detail="No workspace found for this user.",
        )
    return org


async def get_current_org(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    if not token:
        token = request.query_params.get("token")
    return await resolve_current_org(token=token, user=user, db=db)


async def require_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Admin gate. Reads the role from the active `OrganizationMember`
    row (the multi-org source of truth).

    In dev, if the user has an `active_org_id` but no membership row
    yet (e.g. a freshly-migrated user), self-heal creates one before
    re-checking. This is purely a dev convenience.
    """
    if user.active_org_id is None:
        raise HTTPException(status_code=403, detail="Admin access required")

    res = await db.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == user.active_org_id,
            OrganizationMember.status == "active",
        )
    )
    role = res.scalar_one_or_none()
    if role is None:
        # Membership row missing — dev self-heal, then re-check.
        settings = get_settings()
        if settings.env == "dev":
            await _ensure_dev_membership(user, db)
            res = await db.execute(
                select(OrganizationMember.role).where(
                    OrganizationMember.user_id == user.id,
                    OrganizationMember.org_id == user.active_org_id,
                    OrganizationMember.status == "active",
                )
            )
            role = res.scalar_one_or_none()
        if role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
