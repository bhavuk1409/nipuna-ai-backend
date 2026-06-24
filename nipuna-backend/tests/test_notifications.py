import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.dependencies import get_current_org, get_current_user
from app.main import app
from app.models.alert import Alert
from app.models.organization import Organization
from app.models.user import User


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.mark.asyncio
async def test_notifications_lifecycle(client, db_session):
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    user = User(
        id=user_id,
        clerk_user_id=f"user_{user_id}",
        org_id=org_id,
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="admin",
        status="active",
    )
    unread_alert = Alert(
        org_id=org_id,
        rule_id="CREDIT_LOW",
        severity="warning",
        message="AI credits low: 8 remaining",
    )
    read_alert = Alert(
        org_id=org_id,
        rule_id="SEAT_LIMIT",
        severity="warning",
        message="Seat limit reached: 5/5",
    )
    read_alert.read_at = datetime.now(timezone.utc)

    db_session.add_all([org, user, unread_alert, read_alert])
    await db_session.commit()

    app.dependency_overrides[get_current_org] = lambda: org
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with client as ac:
            list_response = await ac.get("/api/v1/notifications")
            assert list_response.status_code == 200
            payload = list_response.json()
            assert payload["unread_count"] == 1
            assert len(payload["notifications"]) == 2
            assert payload["notifications"][0]["read"] is False

            mark_response = await ac.post(f"/api/v1/notifications/{unread_alert.id}/read")
            assert mark_response.status_code == 200
            assert mark_response.json()["read"] is True

            clear_response = await ac.delete("/api/v1/notifications")
            assert clear_response.status_code == 200

        remaining = await db_session.execute(select(Alert).where(Alert.org_id == org_id))
        assert remaining.scalars().all() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dynamic_team_invitations(client, db_session):
    org_id_1 = uuid.uuid4()
    org_id_2 = uuid.uuid4()
    user_id = uuid.uuid4()

    org1 = Organization(id=org_id_1, name="My Current Org", clerk_org_id=f"org_{org_id_1}")
    org2 = Organization(id=org_id_2, name="Inviting Org", clerk_org_id=f"org_{org_id_2}")
    
    # Active logged in user
    user = User(
        id=user_id,
        clerk_user_id=f"user_{user_id}",
        org_id=org_id_1,
        email="user@example.com",
        first_name="Active",
        last_name="User",
        role="admin",
        status="active",
    )
    
    # Pending invitation user record under Org 2
    pending_invite = User(
        id=uuid.uuid4(),
        clerk_user_id=f"invited_{uuid.uuid4()}",
        org_id=org_id_2,
        email="user@example.com",
        first_name="",
        last_name="",
        role="member",
        status="pending",
    )

    db_session.add_all([org1, org2, user, pending_invite])
    await db_session.commit()

    app.dependency_overrides[get_current_org] = lambda: org1
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with client as ac:
            list_response = await ac.get("/api/v1/notifications")
            assert list_response.status_code == 200
            payload = list_response.json()
            assert payload["unread_count"] == 1
            assert len(payload["notifications"]) == 1
            
            notif = payload["notifications"][0]
            assert notif["rule_id"] == "TEAM_INVITATION"
            assert notif["target_org_id"] == str(org_id_2)
            assert notif["read"] is False
            assert "Inviting Org" in notif["description"]

            # Try marking dynamic team invitation as read
            mark_response = await ac.post(f"/api/v1/notifications/{pending_invite.id}/read")
            assert mark_response.status_code == 200
            assert mark_response.json()["read"] is True
            assert mark_response.json()["target_org_id"] == str(org_id_2)
    finally:
        app.dependency_overrides.clear()

