import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class AgentConnection:
    websocket: WebSocket
    org_id: UUID
    user_id: UUID
    capabilities: set[str]


class AgentHub:
    def __init__(self) -> None:
        self._connections: dict[str, AgentConnection] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def register(self, agent_id: str, connection: AgentConnection) -> None:
        self._connections[agent_id] = connection

    def unregister(self, agent_id: str) -> None:
        self._connections.pop(agent_id, None)

    def has_capability(self, org_id: UUID | None, capability: str) -> bool:
        for conn in self._connections.values():
            if org_id is not None and conn.org_id != org_id:
                continue
            if capability in conn.capabilities:
                return True
        return False

    async def send_tool_call(
        self,
        org_id: UUID,
        provider: str,
        action: str,
        params: dict[str, Any],
        call_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        connection = None
        for conn in self._connections.values():
            if conn.org_id == org_id and provider.lower() in conn.capabilities:
                connection = conn
                break

        if connection is None:
            return {
                "tool_name": provider.lower(),
                "result": None,
                "error": "No desktop agent connected for this workspace.",
            }

        payload = {
            "type": "tool_call",
            "call_id": call_id,
            "provider": provider,
            "action": action,
            "params": params,
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[call_id] = future

        await connection.websocket.send_text(json.dumps(payload))

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {
                "tool_name": provider.lower(),
                "result": None,
                "error": "Desktop agent timed out while executing the tool.",
            }
        finally:
            self._pending.pop(call_id, None)

    def resolve_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        future = self._pending.get(call_id)
        if future and not future.done():
            future.set_result(result)


agent_hub = AgentHub()
