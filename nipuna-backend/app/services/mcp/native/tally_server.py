from uuid import uuid4

from app.services.mcp.agent_hub import agent_hub


async def execute_tally_action(action: str, params: dict, org_id: str) -> dict:
    """Route Tally actions to the connected desktop agent."""
    call_id = str(uuid4())
    return await agent_hub.send_tool_call(
        org_id=org_id,
        provider="tally",
        action=action,
        params=params,
        call_id=call_id,
    )
