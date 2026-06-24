import pytest
from unittest.mock import patch, AsyncMock
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models.user import User
from app.models.organization import Organization
import pytest_asyncio


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def setup_test_org_and_admin():
    async with AsyncSessionLocal() as session:
        # Create organization
        org = Organization(
            clerk_org_id="test_org_clerk_id",
            name="Test Org",
            plan="free",
            seats_max=5,
            ai_credits=100,
        )
        session.add(org)
        await session.flush()

        # Create admin user
        admin = User(
            clerk_user_id="test_admin_clerk_id",
            org_id=org.id,
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
            role="admin",
            status="active",
        )
        session.add(admin)
        await session.commit()
        await session.refresh(org)
        await session.refresh(admin)

    yield org, admin

    # Clean up after test
    async with AsyncSessionLocal() as session:
        await session.execute(User.__table__.delete())
        await session.execute(Organization.__table__.delete())
        await session.commit()


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
@patch("app.services.notifications.email.send_email", new_callable=AsyncMock)
async def test_invite_member(mock_send_email, mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin
    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "test_admin_clerk_id",
        "org_id": "test_org_clerk_id",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Invite a member
    async with client as ac:
        response = await ac.post(
            "/api/v1/team/invite",
            json={"email": "invitee@example.com", "role": "member"},
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "invitation_sent"

    # Verify that a pending user record was created in the database
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "invitee@example.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.status == "pending"
        assert user.role == "member"
        assert user.org_id == org.id


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_accept_invitation(mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin

    # Pre-create a pending user
    async with AsyncSessionLocal() as session:
        invited_user = User(
            clerk_user_id="test_invitee_clerk_id",
            org_id=org.id,
            email="invitee@example.com",
            first_name="Invited",
            last_name="User",
            role="member",
            status="pending",
        )
        session.add(invited_user)
        await session.commit()
        await session.refresh(invited_user)
        invited_user_id = invited_user.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "test_invitee_clerk_id",
        "org_id": "test_org_clerk_id",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Call /team/accept
    async with client as ac:
        response = await ac.post(
            "/api/v1/team/accept",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify status changed to active
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == invited_user_id)
        )
        user = result.scalar_one()
        assert user.status == "active"


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_decline_invitation(mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin

    # Pre-create a pending user
    async with AsyncSessionLocal() as session:
        invited_user = User(
            clerk_user_id="test_invitee_clerk_id2",
            org_id=org.id,
            email="invitee2@example.com",
            first_name="Invited2",
            last_name="User",
            role="member",
            status="pending",
        )
        session.add(invited_user)
        await session.commit()
        await session.refresh(invited_user)
        invited_user_id = invited_user.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "test_invitee_clerk_id2",
        "org_id": "test_org_clerk_id",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Call /team/decline
    async with client as ac:
        response = await ac.post(
            "/api/v1/team/decline",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify status changed to declined and org_id remains
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == invited_user_id)
        )
        user = result.scalar_one()
        assert user.status == "declined"
        assert user.org_id == org.id


@pytest.mark.asyncio
async def test_public_decline_invitation(client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin

    # Pre-create a pending user
    async with AsyncSessionLocal() as session:
        invited_user = User(
            clerk_user_id="invited_public_decline_token",
            org_id=org.id,
            email="invitee_public@example.com",
            first_name="",
            last_name="",
            role="member",
            status="pending",
        )
        session.add(invited_user)
        await session.commit()

    # Call public decline endpoint
    async with client as ac:
        response = await ac.post(
            f"/api/v1/team/public-decline?email=invitee_public@example.com&org_id={org.id}",
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify status changed to declined and org_id remains
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "invitee_public@example.com")
        )
        user = result.scalar_one()
        assert user.status == "declined"
        assert user.org_id == org.id


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_remove_member_by_admin(mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin

    # Pre-create an active user
    async with AsyncSessionLocal() as session:
        active_user = User(
            clerk_user_id="test_active_user_clerk_id",
            org_id=org.id,
            email="active_user@example.com",
            first_name="Active",
            last_name="User",
            role="member",
            status="active",
        )
        session.add(active_user)
        await session.commit()
        await session.refresh(active_user)
        active_user_id = active_user.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "test_admin_clerk_id",
        "org_id": "test_org_clerk_id",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Call DELETE /team/members/{member_id}
    async with client as ac:
        response = await ac.delete(
            f"/api/v1/team/members/{active_user_id}",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify status changed to suspended and org_id cleared
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == active_user_id)
        )
        user = result.scalar_one()
        assert user.status == "suspended"
        assert user.org_id is None


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_cancel_invitation_by_admin(mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org, admin = setup_test_org_and_admin

    # Pre-create a pending user
    async with AsyncSessionLocal() as session:
        invited_user = User(
            clerk_user_id="invited_cancel_token",
            org_id=org.id,
            email="invitee_cancel@example.com",
            first_name="",
            last_name="",
            role="member",
            status="pending",
        )
        session.add(invited_user)
        await session.commit()
        await session.refresh(invited_user)
        invited_user_id = invited_user.id

    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "test_admin_clerk_id",
        "org_id": "test_org_clerk_id",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Call DELETE /team/invitations/{member_id}
    async with client as ac:
        response = await ac.delete(
            f"/api/v1/team/invitations/{invited_user_id}",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify user record is deleted
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == invited_user_id)
        )
        user = result.scalar_one_or_none()
        assert user is None


@pytest.mark.asyncio
@patch("app.dependencies.get_jwks")
@patch("jose.jwt.decode")
async def test_existing_user_invitation_migration(mock_jwt_decode, mock_get_jwks, client, setup_test_org_and_admin):
    org_a, admin = setup_test_org_and_admin
    
    # Create another org (Org B)
    async with AsyncSessionLocal() as session:
        org_b = Organization(
            name="Org B",
            seats_max=5,
            clerk_org_id="manual_org_b",
        )
        session.add(org_b)
        await session.commit()
        await session.refresh(org_b)
        org_b_id = org_b.id

        # Create an existing active user in Org A
        existing_user = User(
            clerk_user_id="existing_user_clerk_id",
            org_id=org_a.id,
            email="existing_user@example.com",
            first_name="John",
            last_name="Doe",
            role="member",
            status="active",
        )
        session.add(existing_user)

        # Create a pending invitation for this same user's email under Org B
        pending_invite = User(
            clerk_user_id="invited_temp_id_123",
            org_id=org_b_id,
            email="existing_user@example.com",
            first_name="",
            last_name="",
            role="admin",
            status="pending",
        )
        session.add(pending_invite)
        await session.commit()

    mock_get_jwks.return_value = {}
    # Log in as the existing user switching to Org B
    mock_jwt_decode.return_value = {
        "sub": "existing_user_clerk_id",
        "email": "existing_user@example.com",
        "org_id": "manual_org_b",
        "iss": "https://elegant-locust-4.clerk.accounts.dev",
    }

    # Calling any authenticated endpoint triggers get_current_user token bootstrap resolver
    async with client as ac:
        response = await ac.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer fake_token"},
        )
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["status"] == "pending"
    assert user_data["role"] == "admin"
    
    # Verify DB state
    async with AsyncSessionLocal() as session:
        # The temporary invitation record should be deleted
        temp_check = await session.execute(
            select(User).where(User.clerk_user_id == "invited_temp_id_123")
        )
        assert temp_check.scalar_one_or_none() is None

        # The existing user record should be updated
        user_check = await session.execute(
            select(User).where(User.clerk_user_id == "existing_user_clerk_id")
        )
        db_user = user_check.scalar_one_or_none()
        assert db_user is not None
        assert db_user.org_id == org_b_id
        assert db_user.status == "pending"
        assert db_user.role == "admin"
