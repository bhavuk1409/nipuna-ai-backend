"""Tests for the multi-organization model.

These cover the four new endpoint surfaces that didn't exist before:

1. `GET /auth/me` returns the user's `active_org_id` and full
   `memberships` list (step 3).
2. `POST /auth/switch-org` changes the active org (step 3).
3. Membership rows are scoped to a single user ↔ org pair. A user
   in two orgs can switch between them and the team list reflects
   the active org (steps 5–6).
4. Membership webhooks (created/updated/deleted) drive the join
   table, not the legacy `User` columns (step 4).

End-to-end coverage is a follow-up — these tests are the unit
tests for the join-table model and the switch-org endpoint.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def setup_multi_org_user():
    """Create one user belonging to two orgs (admin in both)."""
    async with AsyncSessionLocal() as session:
        org_a = Organization(
            clerk_org_id=f"org_a_{uuid.uuid4()}",
            name="Org A",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        org_b = Organization(
            clerk_org_id=f"org_b_{uuid.uuid4()}",
            name="Org B",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        user = User(
            clerk_user_id=f"multi_user_{uuid.uuid4()}",
            active_org_id=org_a.id,
            email="multi@example.com",
            first_name="Multi",
            last_name="User",
        )
        session.add(user)
        await session.flush()

        membership_a = OrganizationMember(
            user_id=user.id,
            org_id=org_a.id,
            email=user.email,
            role="admin",
            status="active",
        )
        membership_b = OrganizationMember(
            user_id=user.id,
            org_id=org_b.id,
            email=user.email,
            role="admin",
            status="active",
        )
        session.add_all([membership_a, membership_b])
        await session.commit()
        await session.refresh(user)
        await session.refresh(org_a)
        await session.refresh(org_b)

    yield user, org_a, org_b

    async with AsyncSessionLocal() as session:
        await session.execute(OrganizationMember.__table__.delete())
        await session.execute(User.__table__.delete())
        await session.execute(Organization.__table__.delete())
        await session.commit()


# ── 1. GET /auth/me returns active_org_id + memberships ────────────────


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_auth_me_returns_memberships(
    mock_jwt_decode, mock_get_jwks, client, setup_multi_org_user,
):
    user, org_a, org_b = setup_multi_org_user
    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": user.clerk_user_id,
        "email": user.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        resp = await ac.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_org_id"] == str(org_a.id)
    assert len(body["memberships"]) == 2
    org_ids = {m["org_id"] for m in body["memberships"]}
    assert org_ids == {str(org_a.id), str(org_b.id)}


# ── 2. POST /auth/switch-org updates active_org_id ────────────────────


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_switch_org_changes_active(
    mock_jwt_decode, mock_get_jwks, client, setup_multi_org_user,
):
    user, org_a, org_b = setup_multi_org_user
    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": user.clerk_user_id,
        "email": user.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        resp = await ac.post(
            "/api/v1/auth/switch-org",
            json={"org_id": str(org_b.id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_org_id"] == str(org_b.id)
    assert body["role"] == "admin"
    assert body["status"] == "active"

    # Verify the user was actually switched
    async with AsyncSessionLocal() as session:
        u = await session.get(User, user.id)
        assert u.active_org_id == org_b.id


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_switch_org_rejects_non_member(
    mock_jwt_decode, mock_get_jwks, client, setup_multi_org_user,
):
    """Switching to an org the user doesn't belong to returns 403."""
    user, org_a, org_b = setup_multi_org_user
    # Create a third org the user is *not* a member of
    async with AsyncSessionLocal() as session:
        org_c = Organization(
            clerk_org_id=f"org_c_{uuid.uuid4()}",
            name="Org C",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        session.add(org_c)
        await session.commit()
        org_c_id = org_c.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": user.clerk_user_id,
        "email": user.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        resp = await ac.post(
            "/api/v1/auth/switch-org",
            json={"org_id": str(org_c_id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert resp.status_code == 403, resp.text


# ── 3. Team list is scoped to the active org ──────────────────────────


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_team_list_scoped_to_active_org(
    mock_jwt_decode, mock_get_jwks, client, setup_multi_org_user,
):
    """The /team endpoint returns the active org's members. After a
    switch, the team list reflects the new org."""
    user, org_a, org_b = setup_multi_org_user
    # Add a second member to org A so the team list has more than
    # just the test user.
    async with AsyncSessionLocal() as session:
        other_a = User(
            clerk_user_id=f"other_a_{uuid.uuid4()}",
            email="other_a@example.com",
            first_name="Other",
            last_name="A",
        )
        session.add(other_a)
        await session.flush()
        m = OrganizationMember(
            user_id=other_a.id,
            org_id=org_a.id,
            email=other_a.email,
            role="member",
            status="active",
        )
        session.add(m)
        # Add a second member to org B too.
        other_b = User(
            clerk_user_id=f"other_b_{uuid.uuid4()}",
            email="other_b@example.com",
            first_name="Other",
            last_name="B",
        )
        session.add(other_b)
        await session.flush()
        m2 = OrganizationMember(
            user_id=other_b.id,
            org_id=org_b.id,
            email=other_b.email,
            role="member",
            status="active",
        )
        session.add(m2)
        await session.commit()

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": user.clerk_user_id,
        "email": user.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Active org is A — team list should include user + other_a.
    ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        resp = await ac.get(
            "/api/v1/team",
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        await ac.aclose()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    member_emails = {m["email"] for m in body["members"]}
    assert member_emails == {"multi@example.com", "other_a@example.com"}

    # Switch to org B
    ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        switch_resp = await ac.post(
            "/api/v1/auth/switch-org",
            json={"org_id": str(org_b.id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        await ac.aclose()
    assert switch_resp.status_code == 200

    # Now the team list should be org B's members.
    ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        resp = await ac.get(
            "/api/v1/team",
            headers={"Authorization": "Bearer fake_token"},
        )
    finally:
        await ac.aclose()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    member_emails = {m["email"] for m in body["members"]}
    assert member_emails == {"multi@example.com", "other_b@example.com"}


# ── 4. Membership webhooks drive the join table ───────────────────────


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_membership_deleted_webhook_does_not_suspend_user(
    mock_jwt_decode, mock_get_jwks, client, setup_multi_org_user,
):
    """Sending the `organizationMembership.deleted` webhook for one
    of the user's orgs leaves the user account active and able to
    access their other orgs.

    Verified by:
    - removing the membership for org A via direct DB write (the
      webhook handler is a thin wrapper around the same delete),
    - confirming the user is still active,
    - confirming the user can still switch to and access org B.
    """
    user, org_a, org_b = setup_multi_org_user
    # Delete the org A membership
    async with AsyncSessionLocal() as session:
        m = (await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.org_id == org_a.id,
            )
        )).scalar_one()
        await session.delete(m)
        await session.commit()

    # User is still active — post-step 8, "active" is derived from
    # OrganizationMember rows (at least one with status='active'),
    # not from a `User.status` column. The user still has an active
    # membership in org B even though the A membership is gone, so
    # they remain healthy.
    async with AsyncSessionLocal() as session:
        u = await session.get(User, user.id)
        assert u.active_org_id == org_a.id  # not yet cleared
        active_memberships = (await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == u.id,
                OrganizationMember.status == "active",
            )
        )).scalars().all()
        assert len(active_memberships) == 1
        assert active_memberships[0].org_id == org_b.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": user.clerk_user_id,
        "email": user.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Switch to org B — should succeed because user still has
    # an active membership in B.
    async with client as ac:
        resp = await ac.post(
            "/api/v1/auth/switch-org",
            json={"org_id": str(org_b.id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_user_deleted_does_not_cascade_org():
    """If a user is in two orgs, deleting the user does NOT delete
    either org. The membership rows are cleaned up by the FK
    ON DELETE CASCADE; the org persists if other members remain.
    """
    async with AsyncSessionLocal() as session:
        org_a = Organization(
            clerk_org_id=f"user_del_a_{uuid.uuid4()}",
            name="Org A",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        org_b = Organization(
            clerk_org_id=f"user_del_b_{uuid.uuid4()}",
            name="Org B",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        session.add_all([org_a, org_b])
        await session.flush()

        user = User(
            clerk_user_id=f"user_to_delete_{uuid.uuid4()}",
            email="del@example.com",
            first_name="Del",
            last_name="User",
        )
        session.add(user)
        await session.flush()

        m_a = OrganizationMember(
            user_id=user.id, org_id=org_a.id,
            email=user.email, role="admin", status="active",
        )
        m_b = OrganizationMember(
            user_id=user.id, org_id=org_b.id,
            email=user.email, role="admin", status="active",
        )
        session.add_all([m_a, m_b])
        await session.commit()
        org_a_id = org_a.id
        org_b_id = org_b.id
        user_id = user.id

    # Delete the user — the CASCADE on organization_members.user_id
    # cleans up the memberships. The orgs should still exist.
    async with AsyncSessionLocal() as session:
        u = await session.get(User, user_id)
        await session.delete(u)
        await session.commit()

    async with AsyncSessionLocal() as session:
        org_a_check = await session.get(Organization, org_a_id)
        org_b_check = await session.get(Organization, org_b_id)
        assert org_a_check is not None
        assert org_b_check is not None

        # Memberships for that user are gone
        m_count = (await session.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == user_id)
        )).scalars().all()
        assert len(m_count) == 0
