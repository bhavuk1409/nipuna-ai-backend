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
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.mark.asyncio
@patch("app.routers.onboarding.get_jwks")
@patch("jose.jwt.decode")
@patch("app.services.notifications.email.send_email", new_callable=AsyncMock)
async def test_onboarding_welcome_email(mock_send_email, mock_jwt_decode, mock_get_jwks, client, db_session):
    # Setup mocks
    mock_get_jwks.return_value = {}
    mock_jwt_decode.return_value = {
        "sub": "clerk_user_onboarding_test",
        "org_id": "clerk_org_onboarding_test"
    }

    # Prepare onboarding payload
    payload = {
        "company_name": "Test Onboarding Corp",
        "team_size": "11-50 members",
        "industry": "Artificial Intelligence",
        "email": "welcome-test@nipunaai.in",
        "first_name": "TestFirst",
        "last_name": "TestLast"
    }

    # Call onboarding route
    async with client as ac:
        response = await ac.post(
            "/api/v1/onboarding",
            json=payload,
            headers={"Authorization": "Bearer fake_token"}
        )

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "ok"
    assert "org_id" in res_data

    # Let event loop run background tasks (since email is sent using asyncio.create_task)
    import asyncio
    await asyncio.sleep(0.1)

    # Verify user fields were updated/created in DB
    result = await db_session.execute(
        select(User).where(User.clerk_user_id == "clerk_user_onboarding_test")
    )
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "welcome-test@nipunaai.in"
    assert user.first_name == "TestFirst"
    assert user.last_name == "TestLast"

    # Verify email was triggered via send_email helper with correct arguments
    mock_send_email.assert_called_once()
    called_args, called_kwargs = mock_send_email.call_args
    assert called_kwargs["to"] == "welcome-test@nipunaai.in"
    assert called_kwargs["from_email"] == "Nipuna AI <onboarding@nipunaai.in>"
    assert "TestFirst" in called_kwargs["subject"]
    assert "Test Onboarding Corp" in called_kwargs["html"]
    assert "Zero Hallucination Financial Copilot" in called_kwargs["html"]
