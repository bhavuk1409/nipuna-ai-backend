import asyncio
import json
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal, engine
from app.models.integration import Integration
from app.models.organization import Organization
from app.models.agent import Agent
from app.models.user import User
from app.models.conversation import Message, Conversation
from app.services.ai.pipeline import run_chat_pipeline
from app.services.ai.llm_client import LLMResponse
from app.services.mcp.gateway import get_available_tools_for_org

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop to avoid loop mismatch in DB sessions."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


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
async def test_list_available_integrations(client):
    async with client as ac:
        response = await ac.get("/api/v1/integrations/available")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) >= 12
    
    provider_names = [p["provider"] for p in providers]
    assert "WHATSAPP" in provider_names
    assert "GOOGLE_CALENDAR" in provider_names
    assert "MICROSOFT_TEAMS" in provider_names
    assert "TALLY" in provider_names
    assert "GSTN" in provider_names


@pytest.mark.asyncio
@patch("app.routers.integrations.composio_gateway")
async def test_oauth_callback(mock_composio, client, db_session):
    org_id = uuid.uuid4()
    mock_composio.get_connection_info = AsyncMock(return_value={
        "connection_id": "test_conn_123",
        "tool_name": "GMAIL",
        "entity_id": str(org_id),
        "status": "ACTIVE"
    })
    
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)
    await db_session.commit()
    
    async with client as ac:
        response = await ac.get(
            f"/api/v1/integrations/callback?connection_id=test_conn_123&entity_id={org_id}",
            follow_redirects=False
        )
        
    assert response.status_code == 307
    assert "/dashboard/integrations?success=true&provider=GMAIL" in response.headers["location"]
    
    result = await db_session.execute(
        select(Integration).where(
            Integration.org_id == org_id,
            Integration.provider == "GMAIL"
        )
    )
    integration = result.scalar_one_or_none()
    assert integration is not None
    assert integration.status == "connected"
    assert integration.composio_connection_id == "test_conn_123"
    assert integration.sync_health == 100


@pytest.mark.asyncio
@patch("app.services.mcp.gateway.composio_gateway")
async def test_get_available_tools_for_org(mock_composio, db_session):
    mock_composio.get_available_actions = AsyncMock(return_value=[
        {"name": "GMAIL_SEND_EMAIL", "description": "Send an email", "parameters": {}}
    ])
    
    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)
    
    gmail_integration = Integration(
        org_id=org_id,
        provider="GMAIL",
        display_name="Gmail",
        status="connected",
        composio_connection_id="test_conn_123"
    )
    db_session.add(gmail_integration)
    
    tally_integration = Integration(
        org_id=org_id,
        provider="TALLY",
        display_name="Tally ERP",
        status="connected"
    )
    db_session.add(tally_integration)
    await db_session.commit()
    
    tools = await get_available_tools_for_org(str(org_id), db_session)
    
    assert "GMAIL" in tools
    assert "TALLY" in tools
    assert tools["GMAIL"][0]["name"] == "GMAIL_SEND_EMAIL"
    
    tally_action_names = [t["name"] for t in tools["TALLY"]]
    assert "tally_list_master" in tally_action_names
    assert "tally_ledger_balance" in tally_action_names
    assert "tally_trial_balance" in tally_action_names


@pytest.mark.asyncio
@patch("app.services.ai.pipeline.llm_client")
@patch("app.services.ai.pipeline.execute_tool")
async def test_run_chat_pipeline_with_tool_calling(mock_execute_tool, mock_llm_client, db_session):
    response_1 = LLMResponse(
        content="Let me send that email for you...",
        tool_calls=[
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "gmail_send_email",
                    "arguments": json.dumps({
                        "recipient": "test@example.com",
                        "subject": "Hello",
                        "body": "This is a test email"
                    })
                }
            }
        ],
        tokens_used=100
    )
    response_2 = LLMResponse(
        content="I've successfully sent the email via Gmail.",
        tool_calls=None,
        tokens_used=50
    )
    mock_llm_client.chat_with_tools = AsyncMock(side_effect=[response_1, response_2])
    
    mock_execute_tool.return_value = {
        "tool_name": "GMAIL",
        "result": {"status": "sent", "message_id": "msg_999"},
        "error": None
    }
    
    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)
    
    # Satisfy Agent.created_by restriction
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        clerk_user_id=f"user_{user_id}",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="member",
        status="active"
    )
    db_session.add(user)
    await db_session.flush()
    
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        org_id=org_id,
        name="Mail Bot",
        domain="General",
        objective="Help send emails",
        status="active",
        created_by=user_id
    )
    db_session.add(agent)
    
    conv_id = uuid.uuid4()
    conv = Conversation(id=conv_id, org_id=org_id, agent_id=agent_id, user_id=user_id)
    db_session.add(conv)
    
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content="Please email test@example.com telling them hello"
    )
    db_session.add(user_msg)
    await db_session.commit()
    
    final_response = await run_chat_pipeline(org, agent, [user_msg], db_session)
    
    assert final_response == "I've successfully sent the email via Gmail."
    assert mock_execute_tool.call_count == 1
    assert mock_execute_tool.call_args[1]["tool_name"] == "GMAIL"
    assert mock_execute_tool.call_args[1]["action"] == "GMAIL_SEND_EMAIL"
    
    result = await db_session.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    
    assert len(messages) == 2
    tool_msg = messages[1]
    assert tool_msg.tool_call is True
    assert tool_msg.tool_name == "GMAIL"
    assert tool_msg.tool_action == "GMAIL_SEND_EMAIL"
    assert "msg_999" in tool_msg.tool_result


@pytest.mark.asyncio
@patch("app.routers.integrations.composio_gateway")
async def test_connect_integration_missing_api_key(mock_composio, client, db_session):
    from unittest.mock import MagicMock
    mock_composio.connect_tool = AsyncMock(return_value="")
    
    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)
    
    integration_id = uuid.uuid4()
    integration = Integration(
        id=integration_id,
        org_id=org_id,
        provider="GMAIL",
        display_name="Gmail",
        status="pending"
    )
    db_session.add(integration)
    await db_session.commit()
    
    from app.dependencies import get_current_org, get_current_user
    app.dependency_overrides[get_current_org] = lambda: org
    app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid.uuid4())
    
    try:
        async with client as ac:
            response = await ac.post(
                f"/api/v1/integrations/{integration_id}/connect",
                json={"config": {}}
            )
            
        assert response.status_code == 400
        assert "COMPOSIO_API_KEY" in response.json()["detail"]
        
        result = await db_session.execute(
            select(Integration).where(Integration.id == integration_id)
        )
        updated_integration = result.scalar_one_or_none()
        assert updated_integration.status == "pending"
        
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.routers.integrations.composio_gateway")
async def test_connect_integration_success(mock_composio, client, db_session):
    from unittest.mock import MagicMock
    mock_composio.connect_tool = AsyncMock(return_value="https://connect.composio.dev/link/test_abc")
    
    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)
    
    integration_id = uuid.uuid4()
    integration = Integration(
        id=integration_id,
        org_id=org_id,
        provider="GMAIL",
        display_name="Gmail",
        status="pending"
    )
    db_session.add(integration)
    await db_session.commit()
    
    from app.dependencies import get_current_org, get_current_user
    app.dependency_overrides[get_current_org] = lambda: org
    app.dependency_overrides[get_current_user] = lambda: MagicMock(id=uuid.uuid4())
    
    try:
        async with client as ac:
            response = await ac.post(
                f"/api/v1/integrations/{integration_id}/connect",
                json={"config": {}}
            )
            
        assert response.status_code == 200
        assert response.json() == {"redirect_url": "https://connect.composio.dev/link/test_abc"}
        
        result = await db_session.execute(
            select(Integration).where(Integration.id == integration_id)
        )
        updated_integration = result.scalar_one_or_none()
        assert updated_integration.status == "pending" # status only changes to connected after OAuth callback
        
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.services.ai.langgraph_pipeline.graph.ainvoke")
async def test_run_langgraph_pipeline_new_arguments(mock_ainvoke, db_session):
    from app.services.ai.langgraph_pipeline import run_langgraph_pipeline
    mock_ainvoke.return_value = {"final_answer": "Mocked answer", "tool_calls_made": 1}

    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Test Org", clerk_org_id=f"org_{org_id}")
    db_session.add(org)

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        clerk_user_id=f"user_{user_id}",
        email="test@example.com",
        first_name="Test",
        last_name="User",
        role="member",
        status="active"
    )
    db_session.add(user)
    await db_session.flush()

    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        org_id=org_id,
        name="Mail Bot",
        domain="General",
        objective="Help send emails",
        status="active",
        created_by=user_id
    )
    db_session.add(agent)

    conv_id = uuid.uuid4()
    conv = Conversation(id=conv_id, org_id=org_id, agent_id=agent_id, user_id=user_id)
    db_session.add(conv)

    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content="Please email test@example.com telling them hello"
    )
    db_session.add(user_msg)
    await db_session.commit()

    # Call run_langgraph_pipeline passing the new tone, currency, memory, and attachments
    result = await run_langgraph_pipeline(
        org=org,
        agent=agent,
        conversation_history=[user_msg],
        db=db_session,
        conversation_id=str(conv_id),
        tone="concise",
        currency="USD",
        memory=True,
        attachments=["file.txt"]
    )

    assert result.answer == "Mocked answer"
    assert result.tool_calls_made == 1
    assert mock_ainvoke.call_count == 1
    
    # Verify that GraphState was initialized with the passed args
    called_state = mock_ainvoke.call_args[0][0]
    assert called_state["tone"] == "concise"
    assert called_state["currency"] == "USD"
    assert called_state["memory"] is True
    assert called_state["attachments"] == ["file.txt"]

