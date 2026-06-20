"""LangGraph-based zero-hallucination agentic pipeline with real token/event streaming.

Architecture:
  START -> build_tools -> llm_call -> router_logic
                                        /       \
                             execute_tools     finalize
                                  /               \
                       (loop back to llm_call)    END

Zero-hallucination enforcement:
1. System prompt strictly instructs LLM to ONLY use facts from tool results.
2. Every tool result is validated/sanitised before LLM injection.
3. LLM must cite [SOURCE: <tool_name>] for every fact.
4. If a tool errors, LLM is told exactly what failed — never guesses.
5. SQL queries for Tally are validated before execution.
6. Tool result payloads are truncated to prevent context overflow.
7. Conversation history is windowed to last 20 messages (tool_call rows excluded).
8. Max loop depth = 6, then transparent failure message.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from app.models.agent import Agent
from app.models.conversation import Message
from app.models.organization import Organization
from app.services.ai.sql_validator import validate_sql
from app.services.ai.tool_definitions import map_tool_to_action, PROVIDER_TOOLS_MAPPING
from app.services.mcp.gateway import execute_tool, get_available_tools_for_org
from app.services.mcp.composio_gateway import COMPOSIO_TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 4000
HISTORY_WINDOW = 20
NATIVE_PROVIDERS = {"TALLY", "GSTN"}

# Hard limits to avoid 413 Payload Too Large from Groq
MAX_TOOLS_PER_PROVIDER = 6
MAX_TOOLS_TOTAL = 18
MAX_DESCRIPTION_CHARS = 125

# Fields allowed in a JSON Schema property
_ALLOWED_PROPERTY_KEYS = {"type", "description", "enum", "items", "properties", "required", "anyOf", "oneOf"}


# ──────────────────────────────────────────────────────────────────
# Schema sanitisation (fixes Groq 400)
# ──────────────────────────────────────────────────────────────────

def _sanitize_property(prop: dict) -> dict:
    """Strip keys that Groq/Llama don't accept in property schemas recursively."""
    if not isinstance(prop, dict):
        return {"type": "string"}
    
    clean = {k: v for k, v in prop.items() if k in _ALLOWED_PROPERTY_KEYS}
    
    if "properties" in clean and isinstance(clean["properties"], dict):
        clean["properties"] = {
            pk: _sanitize_property(pv)
            for pk, pv in clean["properties"].items()
        }
        
    if "items" in clean:
        if isinstance(clean["items"], dict):
            clean["items"] = _sanitize_property(clean["items"])
        elif isinstance(clean["items"], list):
            clean["items"] = [_sanitize_property(item) if isinstance(item, dict) else item for item in clean["items"]]
            
    for comb in ["anyOf", "oneOf"]:
        if comb in clean and isinstance(clean[comb], list):
            clean[comb] = [_sanitize_property(item) if isinstance(item, dict) else item for item in clean[comb]]
            
    return clean


def _sanitize_parameters(params: dict) -> dict:
    """Return a clean OpenAI-compatible parameters object."""
    if not isinstance(params, dict):
        return {"type": "object", "properties": {}}

    result: dict = {"type": params.get("type", "object")}

    if "properties" in params:
        result["properties"] = {
            k: _sanitize_property(v)
            for k, v in params["properties"].items()
        }
    else:
        result["properties"] = {}

    if "required" in params:
        result["required"] = [r for r in params["required"] if isinstance(r, str)]

    return result


def _sanitize_tool(tool: dict) -> dict:
    """Return a clean, size-controlled tool schema safe for any LLM provider."""
    raw_desc = (tool.get("description") or "No description.").strip()
    desc = raw_desc[:MAX_DESCRIPTION_CHARS] + "..." if len(raw_desc) > MAX_DESCRIPTION_CHARS else raw_desc
    return {
        "name": tool.get("name", ""),
        "description": desc,
        "parameters": _sanitize_parameters(tool.get("parameters", {})),
        # Preserve internal routing fields
        "provider": tool.get("provider", ""),
        "action": tool.get("action", ""),
    }


# ──────────────────────────────────────────────────────────────────
# Streaming event dataclass
# ──────────────────────────────────────────────────────────────────

@dataclass
class StreamEvent:
    """Emitted during pipeline execution for SSE streaming."""
    type: str  # "thinking" | "tool_start" | "tool_end" | "token" | "done" | "error"
    content: str | None = None
    tool_name: str | None = None
    tool_result: str | None = None
    conversation_id: str | None = None
    tool_calls_made: int | None = None


# ──────────────────────────────────────────────────────────────────
# Pipeline result dataclass
# ──────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    answer: str
    conversation_id: str
    tool_calls_made: int


# ──────────────────────────────────────────────────────────────────
# State definition
# ──────────────────────────────────────────────────────────────────

class GraphState(TypedDict):
    messages: list[BaseMessage]
    org: Organization
    agent: Agent
    db: AsyncSession
    conversation_id: str
    rag_chunks: list[dict]
    
    tools: list[dict]
    tool_route_map: dict[str, tuple[str, str]]
    tool_evidence: dict[str, str]
    
    loop_count: int
    max_loops: int
    tool_calls_made: int
    final_answer: str | None


# ──────────────────────────────────────────────────────────────────
# System prompt template (zero-hallucination rules baked in)
# ──────────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
You are {agent_name}, an AI assistant for {org_name}. Domain: {domain}. Goal: {objective}.

RULES (MANDATORY):
1. Only state facts from tool results. Cite [SOURCE: tool_name] after each fact.
2. If you lack data, call the appropriate tool — never guess.
3. If a tool returns an ERROR, report it honestly. Never invent a result.
4. If the question is outside your connected tools, say so.

CONNECTED INTEGRATIONS: {connected_tools}

TOOL RESULTS (your only facts):
{tool_evidence}
{knowledge_base}"""


def _build_system_prompt_for_state(
    agent_name: str,
    org_name: str,
    domain: str,
    objective: str,
    tools: list[dict],
    tool_evidence: dict[str, str],
    rag_chunks: list[dict],
) -> str:
    seen: set[str] = set()
    providers: list[str] = []
    for t in tools:
        p = t.get("provider", "")
        if p and p not in seen:
            seen.add(p)
            providers.append(p)

    connected_str = ", ".join(providers) if providers else "None (connect tools in Integrations)"

    evidence_parts = [f"[{name}]\n{result}" for name, result in tool_evidence.items()]
    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "(none yet)"

    kb_lines = [f"[KB] {c.get('text', '')[:500]}" for c in rag_chunks[:5]]
    kb_section = "\nKNOWLEDGE BASE:\n" + "\n".join(kb_lines) if kb_lines else ""

    return _SYSTEM_TEMPLATE.format(
        agent_name=agent_name,
        org_name=org_name,
        domain=domain,
        objective=objective,
        connected_tools=connected_str,
        tool_evidence=evidence_str,
        knowledge_base=kb_section,
    )


# ──────────────────────────────────────────────────────────────────
# Grounding enforcement
# ──────────────────────────────────────────────────────────────────

def _enforce_grounding_for_state(answer: str, tool_evidence: dict[str, str]) -> str:
    """If tool evidence exists but LLM forgot to cite sources, append a transparent evidence footer."""
    if not tool_evidence:
        return answer

    has_citation = bool(re.search(r"\[SOURCE:", answer, re.IGNORECASE))
    if has_citation:
        return answer

    footer = "\n\n---\n**Data Sources Used:**"
    for tool_name, result_str in tool_evidence.items():
        snippet = result_str[:400] + "..." if len(result_str) > 400 else result_str
        footer += f"\n\n**[{tool_name}]**\n```\n{snippet}\n```"

    return answer + footer


# ──────────────────────────────────────────────────────────────────
# Async token streaming callback handler
# ──────────────────────────────────────────────────────────────────

class TokenStreamHandler(AsyncCallbackHandler):
    """Callback handler to stream generated tokens to our SSE channel."""
    def __init__(self, callback_fn: Callable[[StreamEvent], None]):
        self.callback_fn = callback_fn

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        if token:
            await self.callback_fn(StreamEvent(type="token", content=token))


# ──────────────────────────────────────────────────────────────────
# Graph Nodes
# ──────────────────────────────────────────────────────────────────

async def node_build_tools(state: GraphState, config: RunnableConfig) -> dict:
    org = state["org"]
    agent = state["agent"]
    db = state["db"]
    callback = config.get("configurable", {}).get("stream_callback")
    
    try:
        connected_map = await get_available_tools_for_org(str(org.id), db)
    except Exception as exc:
        logger.warning("get_available_tools_for_org failed: %s", exc)
        connected_map = {}

    tools: list[dict] = []
    tool_route_map: dict[str, tuple[str, str]] = {}

    for provider, definitions in connected_map.items():
        if len(tools) >= MAX_TOOLS_TOTAL:
            break
        p = provider.upper()

        if p in NATIVE_PROVIDERS:
            curated = PROVIDER_TOOLS_MAPPING.get(p, [])[:MAX_TOOLS_PER_PROVIDER]
            for tool in curated:
                if len(tools) >= MAX_TOOLS_TOTAL:
                    break
                clean = _sanitize_tool(tool)
                tools.append(clean)
                tool_route_map[clean["name"]] = (p, tool.get("action", clean["name"]))
        elif definitions:
            for tool_def in definitions[:MAX_TOOLS_PER_PROVIDER]:
                if len(tools) >= MAX_TOOLS_TOTAL:
                    break
                fn_name = tool_def.get("name", "")
                if not fn_name:
                    continue
                clean = _sanitize_tool({
                    **tool_def,
                    "provider": p,
                    "action": fn_name,
                })
                tools.append(clean)
                tool_route_map[fn_name] = (p, fn_name)

    logger.info("Built tool list: %d tools from %d providers", len(tools), len(connected_map))
    
    prompt = _build_system_prompt_for_state(
        agent_name=agent.name,
        org_name=org.name,
        domain=getattr(agent, "domain", "General"),
        objective=getattr(agent, "objective", "Help the user"),
        tools=tools,
        tool_evidence=state.get("tool_evidence", {}),
        rag_chunks=state.get("rag_chunks", []),
    )
    
    current_msgs = list(state.get("messages", []))
    system_msg = SystemMessage(content=prompt)
    
    if current_msgs and isinstance(current_msgs[0], SystemMessage):
        current_msgs[0] = system_msg
    else:
        current_msgs.insert(0, system_msg)

    if callback:
        await callback(StreamEvent(
            type="thinking",
            content=f"Loaded {len(tools)} tools from {len(connected_map)} connected integrations.",
        ))

    return {
        "messages": current_msgs,
        "tools": tools,
        "tool_route_map": tool_route_map,
    }


async def node_llm_call(state: GraphState, config: RunnableConfig) -> dict:
    from app.config import get_settings
    settings = get_settings()
    callback = config.get("configurable", {}).get("stream_callback")
    
    if callback:
        await callback(StreamEvent(type="thinking", content="Reasoning..."))
        
    provider = (settings.llm_provider or "groq").lower()
    
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model="gpt-4o",
            temperature=0.0,
            streaming=True,
        )
    else:
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model or "llama-3.3-70b-versatile",
            temperature=0.0,
            streaming=True,
        )

    tools = state.get("tools", [])
    if tools:
        llm_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            }
            for t in tools
        ]
        llm = llm.bind_tools(llm_tools)

    handler = TokenStreamHandler(callback) if callback else None
    callbacks = [handler] if handler else []
    
    messages = state["messages"]
    
    try:
        response = await llm.ainvoke(messages, config={"callbacks": callbacks})
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        error_str = str(exc)
        lower_err = error_str.lower()
        is_rate_limit = (
            "429" in error_str
            or "rate_limit_exceeded" in lower_err
            or "rate limit" in lower_err
        )

        if is_rate_limit and ("tokens per day" in lower_err or " tpd" in lower_err or "tpd)" in lower_err):
            user_msg = (
                "Nipuna AI has reached its daily AI usage limit for this model. "
                "Please try again later, or contact support to increase your capacity."
            )
        elif is_rate_limit:
            user_msg = (
                "Nipuna AI is receiving too many requests right now. "
                "Please wait a moment and try again."
            )
        else:
            user_msg = "I encountered an error contacting the AI service. Please try again shortly."

        if callback:
            await callback(StreamEvent(type="error", content=user_msg))

        return {"final_answer": user_msg}

    new_messages = list(messages)
    new_messages.append(response)
    
    tokens_used = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)

    if response.tool_calls:
        content_to_save = response.content or "Invoking integration tool..."
        await _persist_message(
            org_id=state["org"].id,
            conversation_id=state["conversation_id"],
            db=state["db"],
            role="assistant",
            content=content_to_save,
            tokens_used=tokens_used,
            tool_call=True,
        )
        return {
            "messages": new_messages,
        }
    else:
        raw_answer = response.content or ""
        final_answer = _enforce_grounding_for_state(raw_answer, state.get("tool_evidence", {}))
        return {
            "messages": new_messages,
            "final_answer": final_answer,
        }


async def node_execute_tools(state: GraphState, config: RunnableConfig) -> dict:
    callback = config.get("configurable", {}).get("stream_callback")
    db = state["db"]
    org = state["org"]
    
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])
    
    tool_route_map = state["tool_route_map"]
    tool_evidence = dict(state.get("tool_evidence", {}))
    tool_calls_made = state.get("tool_calls_made", 0)
    loop_count = state.get("loop_count", 0)
    
    new_messages = list(state["messages"])
    
    for tc in tool_calls:
        fn_name = tc["name"]
        args = tc["args"]
        call_id = tc["id"]
        
        if fn_name in tool_route_map:
            provider, action = tool_route_map[fn_name]
        else:
            mapped = map_tool_to_action(fn_name)
            provider, action = mapped if mapped else (fn_name.upper(), fn_name)
            
        logger.info(
            "Executing tool: fn=%s provider=%s action=%s params_keys=%s",
            fn_name, provider, action, list(args.keys()),
        )
        
        if callback:
            await callback(StreamEvent(
                type="tool_start",
                tool_name=fn_name,
                content=f"Calling {provider} → {action}",
            ))
            
        # SQL safety check for Tally
        if provider == "TALLY" and action == "query-database":
            sql = args.get("sql", "")
            valid, reason = validate_sql(sql)
            if not valid:
                result_dict = {
                    "error": f"SQL blocked by security validator: {reason}",
                    "result": None,
                }
                logger.warning("Blocked unsafe Tally SQL for org=%s reason=%s", org.id, reason)
            else:
                result_dict = await _safe_execute(provider, action, args, state)
        else:
            result_dict = await _safe_execute(provider, action, args, state)
            
        result_str = _format_result(fn_name, result_dict)
        
        tool_evidence[fn_name] = result_str
        tool_calls_made += 1
        
        await _persist_message(
            org_id=org.id,
            conversation_id=state["conversation_id"],
            db=db,
            role="assistant",
            content=f"[Tool call: {fn_name}]",
            tokens_used=0,
            tool_call=True,
            tool_name=provider,
            tool_action=action,
            tool_result=json.dumps(result_dict),
        )
        
        new_messages.append(ToolMessage(
            content=result_str,
            tool_call_id=call_id,
            name=fn_name,
        ))
        
        if callback:
            await callback(StreamEvent(
                type="tool_end",
                tool_name=fn_name,
                tool_result=result_str[:300] + "..." if len(result_str) > 300 else result_str,
            ))
            
    # Refresh system prompt's evidence (in the first message)
    if new_messages and isinstance(new_messages[0], SystemMessage):
        prompt = _build_system_prompt_for_state(
            agent_name=state["agent"].name,
            org_name=state["org"].name,
            domain=getattr(state["agent"], "domain", "General"),
            objective=getattr(state["agent"], "objective", "Help the user"),
            tools=state["tools"],
            tool_evidence=tool_evidence,
            rag_chunks=state.get("rag_chunks", []),
        )
        new_messages[0] = SystemMessage(content=prompt)
        
    return {
        "messages": new_messages,
        "tool_evidence": tool_evidence,
        "tool_calls_made": tool_calls_made,
        "loop_count": loop_count + 1,
    }


async def node_finalize(state: GraphState, config: RunnableConfig) -> dict:
    final_answer = state.get("final_answer")
    if final_answer is None:
        final_answer = (
            "I reached the maximum number of tool calls without a complete answer. "
            "Please try rephrasing or breaking the question into smaller parts."
        )
    return {"final_answer": final_answer}


# ──────────────────────────────────────────────────────────────────
# Conditional router
# ──────────────────────────────────────────────────────────────────

def router_logic(state: GraphState) -> Literal["execute_tools", "finalize"]:
    if state.get("final_answer") is not None:
        return "finalize"
        
    if state.get("loop_count", 0) >= state.get("max_loops", 6):
        return "finalize"
        
    last_msg = state["messages"][-1]
    if getattr(last_msg, "tool_calls", None):
        return "execute_tools"
        
    return "finalize"


# ──────────────────────────────────────────────────────────────────
# Helper execution / formatting / DB saving
# ──────────────────────────────────────────────────────────────────

async def _safe_execute(provider: str, action: str, params: dict, state: GraphState) -> dict:
    try:
        return await execute_tool(
            org_id=str(state["org"].id),
            tool_name=provider,
            action=action,
            params=params,
        )
    except Exception as exc:
        logger.error("Tool execute error provider=%s action=%s: %s", provider, action, exc)
        return {"error": str(exc), "result": None}


def _format_result(tool_name: str, result_dict: dict) -> str:
    """Sanitise and truncate tool result for LLM injection."""
    if result_dict.get("error"):
        return f"ERROR from {tool_name}: {result_dict['error']}"

    raw = result_dict.get("result", result_dict)
    try:
        formatted = json.dumps(raw, indent=2, ensure_ascii=False, default=str)
    except Exception:
        formatted = str(raw)

    if len(formatted) > MAX_TOOL_RESULT_CHARS:
        formatted = (
            formatted[:MAX_TOOL_RESULT_CHARS]
            + f"\n... [truncated — {len(formatted) - MAX_TOOL_RESULT_CHARS} more chars]"
        )
    return formatted


async def _persist_message(
    org_id: uuid.UUID,
    conversation_id: str,
    db: AsyncSession,
    role: str,
    content: str,
    tokens_used: int = 0,
    tool_call: bool = False,
    tool_name: str | None = None,
    tool_action: str | None = None,
    tool_result: str | None = None,
) -> None:
    """Persist a message to the DB without raising."""
    try:
        msg = Message(
            conversation_id=uuid.UUID(conversation_id),
            role=role,
            content=content,
            tokens_used=tokens_used,
            tool_call=tool_call,
            tool_name=tool_name,
            tool_action=tool_action,
            tool_result=tool_result,
        )
        db.add(msg)
        await db.flush()
    except Exception as exc:
        logger.warning("Failed to persist pipeline message: %s", exc)


# ──────────────────────────────────────────────────────────────────
# Graph compilation
# ──────────────────────────────────────────────────────────────────

workflow = StateGraph(GraphState)

workflow.add_node("build_tools", node_build_tools)
workflow.add_node("llm_call", node_llm_call)
workflow.add_node("execute_tools", node_execute_tools)
workflow.add_node("finalize", node_finalize)

workflow.set_entry_point("build_tools")
workflow.add_edge("build_tools", "llm_call")
workflow.add_conditional_edges(
    "llm_call",
    router_logic,
    {
        "execute_tools": "execute_tools",
        "finalize": "finalize",
    }
)
workflow.add_edge("execute_tools", "llm_call")
workflow.add_edge("finalize", END)

graph = workflow.compile()


# ──────────────────────────────────────────────────────────────────
# Public endpoints
# ──────────────────────────────────────────────────────────────────

async def run_langgraph_pipeline(
    org: Organization,
    agent: Agent,
    conversation_history: list[Message],
    db: AsyncSession,
    rag_chunks: list[dict] | None = None,
    conversation_id: str | None = None,
    stream_callback: Callable[[StreamEvent], None] | None = None,
) -> PipelineResult:
    """Main entrypoint. Runs the full LangGraph StateGraph pipeline."""
    if not conversation_history:
        return PipelineResult(
            answer=f"{agent.name} is ready. How can I help you?",
            conversation_id=conversation_id or "",
            tool_calls_made=0,
        )

    last_user_msg = next(
        (m.content for m in reversed(conversation_history) if m.role == "user"),
        None,
    )
    if not last_user_msg:
        return PipelineResult(
            answer="No message to process.",
            conversation_id=conversation_id or "",
            tool_calls_made=0,
        )

    formatted = _db_messages_to_langchain(conversation_history[-HISTORY_WINDOW:])

    state = GraphState(
        messages=formatted,
        org=org,
        agent=agent,
        db=db,
        conversation_id=conversation_id or "",
        rag_chunks=rag_chunks or [],
        tools=[],
        tool_route_map={},
        tool_evidence={},
        loop_count=0,
        max_loops=6,
        tool_calls_made=0,
        final_answer=None,
    )

    config = {}
    if stream_callback:
        config["configurable"] = {"stream_callback": stream_callback}

    final_state = await graph.ainvoke(state, config=config)

    answer = final_state.get("final_answer") or "I was unable to generate a response."

    if stream_callback:
        await stream_callback(StreamEvent(
            type="done",
            content=answer,
            conversation_id=conversation_id,
            tool_calls_made=final_state.get("tool_calls_made", 0),
        ))

    return PipelineResult(
        answer=answer,
        conversation_id=conversation_id or "",
        tool_calls_made=final_state.get("tool_calls_made", 0),
    )


async def run_langgraph_pipeline_stream(
    org: Organization,
    agent: Agent,
    conversation_history: list[Message],
    db: AsyncSession,
    rag_chunks: list[dict] | None = None,
    conversation_id: str | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Streaming entrypoint. Yields events in real time using an internal async queue."""
    queue = asyncio.Queue()

    async def stream_callback(event: StreamEvent) -> None:
        await queue.put(event)

    formatted = _db_messages_to_langchain(conversation_history[-HISTORY_WINDOW:])

    state = GraphState(
        messages=formatted,
        org=org,
        agent=agent,
        db=db,
        conversation_id=conversation_id or "",
        rag_chunks=rag_chunks or [],
        tools=[],
        tool_route_map={},
        tool_evidence={},
        loop_count=0,
        max_loops=6,
        tool_calls_made=0,
        final_answer=None,
    )

    # Launch StateGraph in an independent background task
    task = asyncio.create_task(
        graph.ainvoke(
            state,
            config={"configurable": {"stream_callback": stream_callback}}
        )
    )

    # Read events from the queue and yield them to the SSE connection in real time
    while not task.done() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.05)
            yield event
            queue.task_done()
        except asyncio.TimeoutError:
            continue

    # Raise task exception if any error occurred during execution
    if task.done() and task.exception():
        raise task.exception()


def _db_messages_to_langchain(history: list[Message]) -> list[BaseMessage]:
    formatted: list[BaseMessage] = []
    for m in history:
        if m.role not in ("user", "assistant"):
            continue
        if getattr(m, "tool_call", False):
            continue
        if m.role == "user":
            formatted.append(HumanMessage(content=m.content or ""))
        elif m.role == "assistant":
            formatted.append(AIMessage(content=m.content or ""))
    return formatted
