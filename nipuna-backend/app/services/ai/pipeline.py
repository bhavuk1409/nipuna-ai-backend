import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.conversation import Message
from app.models.organization import Organization
from app.services.ai.context_builder import build_context
from app.services.ai.embedding_client import embedding_client
from app.services.ai.llm_client import llm_client, LLMResponse
from app.services.ai.vector_store import vector_store
from app.services.mcp.gateway import get_available_tools_for_org, execute_tool
from app.services.ai.tool_definitions import map_tool_to_action

logger = logging.getLogger(__name__)


async def run_chat_pipeline(
    org: Organization,
    agent: Agent,
    conversation_history: list[Message],
    db: AsyncSession,
) -> str:
    if not conversation_history:
        return f"Agent {agent.name} is ready. How can I help you?"

    last_user_msg = None
    for msg in reversed(conversation_history):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    if not last_user_msg:
        return "No message to process."

    try:
        query_embedding = await embedding_client.embed(last_user_msg)
    except Exception:
        query_embedding = []

    rag_chunks = []
    if query_embedding:
        rag_chunks = await vector_store.search(str(org.id), query_embedding)

    system_prompt = await build_context(org, agent, rag_chunks)

    # 1. Fetch connected tools for the org
    connected_tools_map = await get_available_tools_for_org(str(org.id), db)
    
    # Compile tool definitions for the LLM using curated schemas where available,
    # or fallback to gateway definitions for others to prevent payload limits.
    from app.services.ai.tool_definitions import PROVIDER_TOOLS_MAPPING
    
    tools = []
    for provider, definitions in connected_tools_map.items():
        provider_upper = provider.upper()
        if provider_upper in PROVIDER_TOOLS_MAPPING:
            tools.extend(PROVIDER_TOOLS_MAPPING[provider_upper])
        else:
            tools.extend(definitions[:10])  # safeguard fallback: limit to max 10 actions per provider


    # Prepare message history for LLM
    formatted_messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        formatted_messages.append({"role": msg.role, "content": msg.content})

    # Tool calling loop (max depth 5)
    max_loops = 5
    loop_count = 0
    
    while loop_count < max_loops:
        # Call LLM with tool definitions
        response: LLMResponse = await llm_client.chat_with_tools(formatted_messages, tools=tools if tools else None)
        
        # If no tool calls, we're done
        if not response.tool_calls:
            return response.content or "No response from AI."

        # Process tool calls
        logger.info("Agent %s requested %d tool call(s) at loop %d", agent.name, len(response.tool_calls), loop_count)
        
        # Append the assistant message requesting the tool call to history
        assistant_msg_payload = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": response.tool_calls
        }
        formatted_messages.append(assistant_msg_payload)
        
        # Insert this tool-calling assistant message into our DB for history / audit
        tool_call_msg = Message(
            conversation_id=conversation_history[0].conversation_id,
            role="assistant",
            content=response.content or "Invoking integration tool...",
            tokens_used=response.tokens_used,
            tool_call=True,
        )
        db.add(tool_call_msg)
        await db.flush()

        for tool_call in response.tool_calls:
            tool_name = tool_call["function"]["name"]
            arguments_str = tool_call["function"]["arguments"]
            call_id = tool_call.get("id", "")
            
            try:
                params = json.loads(arguments_str)
            except Exception as exc:
                params = {}
                logger.warning("Failed to parse tool call arguments: %s", exc)

            # Map the function name to provider and action
            mapped = map_tool_to_action(tool_name)
            if not mapped:
                provider = tool_name.upper()
                action = tool_name
            else:
                provider, action = mapped

            logger.info("Executing tool action: provider=%s, action=%s, params=%s", provider, action, params)
            
            # Execute tool action
            result_dict = await execute_tool(
                org_id=str(org.id),
                tool_name=provider,
                action=action,
                params=params,
            )
            
            # Update the Message DB record with the execution result
            tool_call_msg.tool_name = provider
            tool_call_msg.tool_action = action
            tool_call_msg.tool_result = json.dumps(result_dict)
            await db.flush()

            # Append tool response message to formatted messages for the next LLM call
            result_str = json.dumps(result_dict)
            formatted_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": tool_name,
                "content": result_str
            })

        loop_count += 1

    return "Max tool calling loop depth reached."
