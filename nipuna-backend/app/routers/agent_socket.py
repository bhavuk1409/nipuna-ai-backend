import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.services.mcp.agent_hub import AgentConnection, agent_hub

router = APIRouter(prefix="/ws", tags=["agent-socket"])


@router.websocket("/agents")
async def agents_socket(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    auth_header = websocket.headers.get("authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    user = await get_current_user(token=token, db=db)
    org = await get_current_org(token=token, user=user, db=db)

    await websocket.accept()
    agent_id = None
    try:
        while True:
            payload = await websocket.receive_text()
            message = json.loads(payload)
            message_type = message.get("type")

            if message_type == "register":
                agent_id = message.get("agent_id")
                capabilities = set(message.get("capabilities", []))
                if not agent_id:
                    await websocket.send_text(json.dumps({"type": "error", "message": "agent_id required"}))
                    continue
                agent_hub.register(
                    agent_id,
                    AgentConnection(
                        websocket=websocket,
                        org_id=org.id,
                        user_id=user.id,
                        capabilities=capabilities,
                    ),
                )
                await websocket.send_text(json.dumps({"type": "registered", "agent_id": agent_id}))
                continue

            if message_type == "tool_result":
                call_id = message.get("call_id")
                result = message.get("result")
                error = message.get("error")
                provider = message.get("provider")
                action = message.get("action")
                response = {
                    "tool_name": (provider or "").lower(),
                    "result": result,
                    "error": error,
                    "action": action,
                }
                if call_id:
                    agent_hub.resolve_tool_result(call_id, response)
                continue

            await websocket.send_text(json.dumps({"type": "error", "message": "Unknown message type"}))
    except WebSocketDisconnect:
        if agent_id:
            agent_hub.unregister(agent_id)
