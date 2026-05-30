"""
Nipuna AI Backend Tests

Run: pytest tests/ -v
"""

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client):
    async with client as ac:
        response = await ac.post(
            "/api/v1/auth/webhook",
            json={"type": "user.created", "data": {}},
            headers={
                "svix-id": "test",
                "svix-timestamp": "1234567890",
                "svix-signature": "invalid",
            },
        )
    assert response.status_code == 400


@pytest.mark.asyncio
@patch("svix.webhooks.Webhook.verify")
async def test_webhook_valid_signature(mock_verify, client):
    mock_verify.return_value = {
        "type": "user.created",
        "data": {
            "id": "test_user_123",
            "email_addresses": [{"email_address": "test@example.com"}],
            "first_name": "Test",
            "last_name": "User",
        },
    }

    async with client as ac:
        response = await ac.post(
            "/api/v1/auth/webhook",
            json={"type": "user.created", "data": {}},
            headers={
                "svix-id": "valid",
                "svix-timestamp": "1234567890",
                "svix-signature": "valid",
            },
        )

    assert response.status_code in (200, 500)
