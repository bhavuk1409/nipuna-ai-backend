"""
migrate_manual_orgs_to_clerk.py
================================
One-shot migration: for every Organization whose `clerk_org_id` starts with
`manual_`, create a real Clerk organization via the Clerk Backend API, add all
active members as Clerk org members, and update `clerk_org_id` in the local DB.

Run from the backend root:
    .venv/bin/python scripts/migrate_manual_orgs_to_clerk.py

Safe to re-run: orgs that already have a real `org_` clerk_org_id are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import httpx

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _clerk_headers(secret_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def create_clerk_org(name: str, secret_key: str) -> str | None:
    """Create a Clerk organization and return its ID."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{CLERK_API_BASE}/organizations",
            json={"name": name},
            headers=_clerk_headers(secret_key),
        )
    if resp.is_success:
        data = resp.json()
        clerk_org_id = data.get("id")
        logger.info("  Created Clerk org '%s' → %s", name, clerk_org_id)
        return clerk_org_id
    logger.error("  Failed to create Clerk org '%s': %s %s", name, resp.status_code, resp.text[:300])
    return None


async def add_clerk_org_member(clerk_org_id: str, clerk_user_id: str, role: str, secret_key: str) -> bool:
    """Add a user to a Clerk org as admin or member."""
    clerk_role = "org:admin" if role == "admin" else "org:member"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{CLERK_API_BASE}/organizations/{clerk_org_id}/memberships",
            json={"user_id": clerk_user_id, "role": clerk_role},
            headers=_clerk_headers(secret_key),
        )
    if resp.is_success:
        logger.info("    Added Clerk user %s to org %s as %s", clerk_user_id, clerk_org_id, clerk_role)
        return True
    # 422 often means they're already a member — treat as success
    if resp.status_code == 422:
        logger.info("    User %s already in org %s (skipped)", clerk_user_id, clerk_org_id)
        return True
    logger.warning("    Failed to add user %s to org %s: %s %s", clerk_user_id, clerk_org_id, resp.status_code, resp.text[:200])
    return False


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    secret_key = os.getenv("CLERK_SECRET_KEY", "")
    if not secret_key or not secret_key.startswith("sk_"):
        logger.error("CLERK_SECRET_KEY not set or invalid. Set it in .env")
        sys.exit(1)

    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.organization import Organization
    from app.models.organization_member import OrganizationMember
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        # Find all manual_ orgs
        manual_orgs = (await db.execute(
            select(Organization)
            .where(Organization.clerk_org_id.like("manual_%"))
            .order_by(Organization.created_at)
        )).scalars().all()

        logger.info("Found %d manual orgs to migrate.", len(manual_orgs))

        for org in manual_orgs:
            logger.info("\nProcessing: '%s' (local id=%s, old clerk_org_id=%s)", org.name, org.id, org.clerk_org_id)

            # Get active members with their clerk_user_id
            members = (await db.execute(
                select(OrganizationMember, User)
                .join(User, User.id == OrganizationMember.user_id)
                .where(
                    OrganizationMember.org_id == org.id,
                    OrganizationMember.status == "active",
                    OrganizationMember.user_id.isnot(None),
                )
            )).all()

            if not members:
                logger.info("  No active members — skipping (orphan org)")
                continue

            # Create the Clerk org
            new_clerk_org_id = await create_clerk_org(org.name, secret_key)
            if not new_clerk_org_id:
                logger.error("  Skipping '%s' — could not create Clerk org", org.name)
                continue

            # Add all active members
            for membership, user in members:
                if not user.clerk_user_id:
                    logger.warning("    User %s has no clerk_user_id — skipping", user.email)
                    continue
                await add_clerk_org_member(new_clerk_org_id, user.clerk_user_id, membership.role, secret_key)

            # Update the DB
            old_clerk_org_id = org.clerk_org_id
            org.clerk_org_id = new_clerk_org_id
            db.add(org)
            await db.commit()
            logger.info("  Updated DB: clerk_org_id %s → %s", old_clerk_org_id, new_clerk_org_id)

    logger.info("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
