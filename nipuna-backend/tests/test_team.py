"""Tests for the team router (multi-org model).

The previous version of this file tested the *old* placeholder-User
invite pattern (`clerk_user_id="invited_*"`, `User.org_id` set on a
placeholder). The new model uses `OrganizationMember` rows, so the
fixtures and assertions here use that table. The endpoint surface
also changed slightly (the path for invites is now `/team/invites/...`
singular, not `/team/invitations/...`).
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
async def setup_test_org_and_admin():
    """Create a test org with an admin user, an active membership, and
    the dev-bypass token decoding setup. The admin's `active_org_id`
    is set so `get_current_org` lands on the test org."""
    async with AsyncSessionLocal() as session:
        org = Organization(
            clerk_org_id=f"test_org_clerk_id_{uuid.uuid4()}",
            name="Test Org",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        session.add(org)
        await session.flush()

        admin = User(
            clerk_user_id=f"test_admin_clerk_id_{uuid.uuid4()}",
            active_org_id=org.id,
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
        )
        session.add(admin)
        await session.flush()

        # Multi-org model: a User only "belongs" to an org via an
        # active `OrganizationMember` row. Add one for the admin so
        # `require_admin` (which reads the membership table) is happy.
        admin_membership = OrganizationMember(
            user_id=admin.id,
            org_id=org.id,
            email=admin.email.lower(),
            role="admin",
            status="active",
        )
        session.add(admin_membership)
        await session.commit()
        await session.refresh(org)
        await session.refresh(admin)

    yield org, admin

    # Clean up after test.
    async with AsyncSessionLocal() as session:
        await session.execute(OrganizationMember.__table__.delete())
        await session.execute(User.__table__.delete())
        await session.execute(Organization.__table__.delete())
        await session.commit()


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
@patch("app.routers.team.send_clerk_org_invitation", new_callable=AsyncMock)
@patch("app.routers.team.lookup_clerk_user_by_email", new_callable=AsyncMock)
async def test_invite_member(
    mock_lookup, mock_send_clerk, mock_jwt_decode, mock_get_jwks,
    client, setup_test_org_and_admin,
):
    """Inviting a brand-new email creates a pending OrganizationMember."""
    org, admin = setup_test_org_and_admin
    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": admin.clerk_user_id,
        "email": admin.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }
    # New email that is not a Clerk user yet.
    mock_lookup.return_value = None

    async with client as ac:
        response = await ac.post(
            "/api/v1/team/invites",
            json={"email": "invitee@example.com", "role": "member"},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "invitee@example.com"
    assert body["role"] == "member"

    # Verify that a pending membership row was created in the database
    # with `user_id IS NULL` (placeholder for a future user).
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.email == "invitee@example.com",
                OrganizationMember.org_id == org.id,
            )
        )
        membership = result.scalar_one_or_none()
        assert membership is not None
        assert membership.status == "pending"
        assert membership.role == "member"
        assert membership.user_id is None


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_accept_invitation(
    mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin,
):
    """An invitee can accept a pending invite. The new endpoint
    requires the user to be authenticated; the invite is found by
    (org_id, current_user.email)."""
    org, admin = setup_test_org_and_admin
    invitee_email = "invitee@example.com"

    # Pre-create a pending membership in the same org for the
    # invitee. The invitee has no User row yet (placeholder).
    async with AsyncSessionLocal() as session:
        pending = OrganizationMember(
            user_id=None,
            org_id=org.id,
            email=invitee_email,
            role="member",
            status="pending",
        )
        session.add(pending)
        await session.commit()
        await session.refresh(pending)
        pending_id = pending.id

    # Pre-create the invitee as a real User (so /auth/me can return
    # them). In a real flow this is the Clerk user who just signed
    # in; in tests we create the row directly.
    async with AsyncSessionLocal() as session:
        invitee = User(
            clerk_user_id=f"test_invitee_clerk_id_{uuid.uuid4()}",
            email=invitee_email,
            first_name="Invited",
            last_name="User",
        )
        session.add(invitee)
        await session.commit()
        await session.refresh(invitee)

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": invitee.clerk_user_id,
        "email": invitee.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.post(
            "/api/v1/team/accept",
            json={"org_id": str(org.id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == invitee_email
    assert body["status"] == "active"

    # Verify the membership row is now active and bound to the user.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(OrganizationMember.id == pending_id)
        )
        m = result.scalar_one()
        assert m.status == "active"
        assert m.user_id == invitee.id


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_decline_invitation(
    mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin,
):
    """Declining an invite flips status to `declined` and keeps the row."""
    org, admin = setup_test_org_and_admin
    invitee_email = "invitee2@example.com"

    async with AsyncSessionLocal() as session:
        invitee = User(
            clerk_user_id=f"test_invitee_clerk_id2_{uuid.uuid4()}",
            email=invitee_email,
            first_name="Invited2",
            last_name="User",
        )
        session.add(invitee)
        await session.flush()

        pending = OrganizationMember(
            user_id=None,
            org_id=org.id,
            email=invitee_email,
            role="member",
            status="pending",
        )
        session.add(pending)
        await session.commit()
        await session.refresh(pending)
        pending_id = pending.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": invitee.clerk_user_id,
        "email": invitee.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.post(
            "/api/v1/team/decline",
            json={"org_id": str(org.id)},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 204, response.text

    # The membership row is now marked `declined`. We preserve the
    # row (rather than deleting) so there's an audit trail of who
    # declined what.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(OrganizationMember.id == pending_id)
        )
        m = result.scalar_one_or_none()
        assert m is not None
        assert m.status == "declined"


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_remove_member_by_admin(
    mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin,
):
    """An admin can remove an active member. The membership row is
    deleted; the user's `active_org_id` is cleared if it pointed at
    the removed org."""
    org, admin = setup_test_org_and_admin

    # Pre-create an active member with both legacy and new columns set.
    async with AsyncSessionLocal() as session:
        active_user = User(
            clerk_user_id=f"test_active_user_clerk_id_{uuid.uuid4()}",
            active_org_id=org.id,
            email="active_user@example.com",
            first_name="Active",
            last_name="User",
        )
        session.add(active_user)
        await session.flush()

        membership = OrganizationMember(
            user_id=active_user.id,
            org_id=org.id,
            email=active_user.email,
            role="member",
            status="active",
        )
        session.add(membership)
        await session.commit()
        await session.refresh(active_user)
        await session.refresh(membership)
        member_id = membership.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": admin.clerk_user_id,
        "email": admin.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.delete(
            f"/api/v1/team/members/{member_id}",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 204, response.text

    # The membership row is gone; the user's `active_org_id` is
    # cleared (so the dep will lazy-pick a new active org on next
    # request).
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(OrganizationMember.id == member_id)
        )
        assert result.scalar_one_or_none() is None

        u = await session.get(User, active_user.id)
        assert u is not None
        assert u.active_org_id is None


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_cancel_invitation_by_admin(
    mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin,
):
    """An admin can cancel a pending invite. The membership row is deleted."""
    org, admin = setup_test_org_and_admin

    async with AsyncSessionLocal() as session:
        invite = OrganizationMember(
            user_id=None,
            org_id=org.id,
            email="invitee_cancel@example.com",
            role="member",
            status="pending",
        )
        session.add(invite)
        await session.commit()
        await session.refresh(invite)
        invite_id = invite.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": admin.clerk_user_id,
        "email": admin.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.delete(
            f"/api/v1/team/invites/{invite_id}",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 204, response.text

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(OrganizationMember.id == invite_id)
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
@patch("app.routers.team.send_clerk_org_invitation", new_callable=AsyncMock)
async def test_resend_invitation(
    mock_send_clerk, mock_jwt_decode, mock_get_jwks,
    client, setup_test_org_and_admin,
):
    """Resending a pending invite re-fires the Clerk email (or returns
    a dev share link)."""
    org, admin = setup_test_org_and_admin

    async with AsyncSessionLocal() as session:
        invite = OrganizationMember(
            user_id=None,
            org_id=org.id,
            email="resend_invitee@example.com",
            role="member",
            status="pending",
        )
        session.add(invite)
        await session.commit()
        await session.refresh(invite)
        invite_id = invite.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": admin.clerk_user_id,
        "email": admin.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.post(
            f"/api/v1/team/invites/{invite_id}/resend",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "resend_invitee@example.com"
    mock_send_clerk.assert_called_once()


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_change_member_role(
    mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin,
):
    """An admin can change a member's role on the membership row."""
    org, admin = setup_test_org_and_admin

    async with AsyncSessionLocal() as session:
        member = User(
            clerk_user_id=f"member_role_change_clerk_id_{uuid.uuid4()}",
            active_org_id=org.id,
            email="member_to_change@example.com",
            first_name="Member",
            last_name="User",
        )
        session.add(member)
        await session.flush()

        membership = OrganizationMember(
            user_id=member.id,
            org_id=org.id,
            email=member.email,
            role="member",
            status="active",
        )
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
        member_id = membership.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": admin.clerk_user_id,
        "email": admin.email,
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    async with client as ac:
        response = await ac.patch(
            f"/api/v1/team/members/{member_id}/role",
            headers={"Authorization": "Bearer fake_token"},
            json={"role": "viewer"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "viewer"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OrganizationMember).where(OrganizationMember.id == member_id)
        )
        m = result.scalar_one()
        assert m.role == "viewer"
