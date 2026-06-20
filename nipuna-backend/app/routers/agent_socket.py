import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import resolve_current_org, resolve_current_user
from app.models.integration import Integration
from app.models.organization import Organization
from app.models.user import User
from app.services.mcp.agent_hub import AgentConnection, agent_hub

logger = logging.getLogger(__name__)
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

    try:
        user = await resolve_current_user(token=token, db=db)
        org = await resolve_current_org(token=token, user=user, db=db)
    except HTTPException as exc:
        logger.warning("WebSocket auth failed: %s", exc.detail)
        await websocket.close(code=4401)
        return

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

                # Automatically mark Tally integration as connected in the DB if agent has tally capability
                if "tally" in capabilities:
                    result = await db.execute(
                        select(Integration).where(
                            Integration.org_id == org.id,
                            Integration.provider == "TALLY",
                        )
                    )
                    integration = result.scalar_one_or_none()
                    if not integration:
                        from app.services.mcp.gateway import AVAILABLE_PROVIDERS
                        meta = AVAILABLE_PROVIDERS["TALLY"]
                        integration = Integration(
                            org_id=org.id,
                            provider="TALLY",
                            display_name=meta["display_name"],
                            description=meta.get("description"),
                            category=meta.get("category"),
                        )
                        db.add(integration)
                    integration.status = "connected"
                    integration.sync_health = 100
                    integration.last_synced = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info("Automatically marked Tally integration as connected for org %s", org.id)

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
            try:
                conn = agent_hub._connections.get(agent_id)
                if conn and "tally" in conn.capabilities:
                    # Automatically mark Tally integration as disconnected in the DB
                    result = await db.execute(
                        select(Integration).where(
                            Integration.org_id == conn.org_id,
                            Integration.provider == "TALLY",
                        )
                    )
                    integration = result.scalar_one_or_none()
                    if integration:
                        integration.status = "disconnected"
                        await db.commit()
                        logger.info("Automatically marked Tally integration as disconnected for org %s", conn.org_id)
            except Exception as e:
                logger.error("Failed to mark Tally integration as disconnected: %s", e)
            agent_hub.unregister(agent_id)
