"""LangGraph-based zero-hallucination agentic pipeline.

Architecture:
  START → node_build_tools → node_llm_call → route
                                               ↓             ↓
                                         execute_tools   final_answer
                                               ↓
                                         node_llm_call (loop back)

Zero-hallucination enforcement:
1. System prompt strictly instructs LLM to ONLY use facts from tool results.
2. Every tool result is validated/sanitised before LLM injection.
3. LLM must cite [SOURCE: <tool_name>] for every fact.
4. If a tool errors, LLM is told exactly what failed — never guesses.
5. SQL queries for Tally are validated before execution.
6. Tool result payloads are truncated to prevent context overflow.
7. Conversation history is windowed to last 20 messages (tool_call rows excluded).
8. Max loop depth = 6, then transparent failure message.

Tool loading strategy (fixes Composio slug mismatch):
- For Composio-managed tools (Gmail, Slack, GitHub, etc.):
    Load ACTUAL schemas from Composio API via get_available_actions().
    These schemas already have the correct slug as `name`.
    Both the LLM function call name AND execute slug are the same Composio slug.
- For native tools (Tally, GSTN):
    Use our curated PROVIDER_TOOLS_MAPPING schemas.
    These map to native MCP server action names.

Schema sanitisation (fixes Groq 400):
- Strip any JSON-schema fields that Groq/Llama reject (e.g. "default").
- Only allow: type, description, enum, items, properties, required.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.conversation import Conversation, Message
from app.models.organization import Organization
from app.services.ai.llm_client import LLMClient, LLMResponse
from app.services.ai.sql_validator import validate_sql
from app.services.ai.tool_definitions import map_tool_to_action, PROVIDER_TOOLS_MAPPING
from app.services.mcp.gateway import execute_tool, get_available_tools_for_org
from app.services.mcp.composio_gateway import COMPOSIO_TOOLS

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 4000
HISTORY_WINDOW = 20
NATIVE_PROVIDERS = {"TALLY", "GSTN"}

# Hard limits to avoid 413 Payload Too Large from Groq
# Groq's llama-3.3-70b has a ~6000 TPM request limit on free tier;
# each tool schema consumes ~150-400 tokens. Keep total tools small.
MAX_TOOLS_PER_PROVIDER = 6      # max Composio actions loaded per provider
MAX_TOOLS_TOTAL = 18            # absolute cap across all providers
MAX_DESCRIPTION_CHARS = 120     # truncate long descriptions

# Fields allowed in a JSON Schema property (Groq rejects "default", "examples", etc.)
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
    # Truncate description to stay within payload budget
    desc = raw_desc[:MAX_DESCRIPTION_CHARS] + "..." if len(raw_desc) > MAX_DESCRIPTION_CHARS else raw_desc
    return {
        "name": tool.get("name", ""),
        "description": desc,
        "parameters": _sanitize_parameters(tool.get("parameters", {})),
        # Preserve internal routing fields — not sent to LLM
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
# State dataclass
# ──────────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    org: Organization
    agent: Agent
    db: AsyncSession
    conversation_id: str

    messages: list[dict] = field(default_factory=list)

    # Tool schemas to send to LLM (already sanitised)
    tools: list[dict] = field(default_factory=list)

    # Maps LLM function name → (provider, action_slug)
    # For Composio tools:  fn_name == action_slug (they're the same Composio slug)
    # For native tools:    action_slug is the MCP server action name
    tool_route_map: dict[str, tuple[str, str]] = field(default_factory=dict)

    # Accumulated grounded evidence from tool executions
    tool_evidence: dict[str, str] = field(default_factory=dict)

    loop_count: int = 0
    max_loops: int = 6
    tool_calls_made: int = 0

    final_answer: str | None = None

    # Optional async streaming callback
    stream_callback: Callable[[StreamEvent], None] | None = None


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


def _build_system_prompt(state: AgentState, rag_chunks: list[dict]) -> str:
    # List connected providers (deduplicated)
    seen: set[str] = set()
    providers: list[str] = []
    for t in state.tools:
        p = t.get("provider", "")
        if p and p not in seen:
            seen.add(p)
            providers.append(p)

    connected_str = ", ".join(providers) if providers else "None (connect tools in Settings > Integrations)"

    evidence_parts = [f"[{name}]\n{result}" for name, result in state.tool_evidence.items()]
    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "(none yet)"

    kb_lines = [f"[KB] {c.get('text', '')[:500]}" for c in rag_chunks[:5]]
    kb_section = "\nKNOWLEDGE BASE:\n" + "\n".join(kb_lines) if kb_lines else ""

    return _SYSTEM_TEMPLATE.format(
        agent_name=state.agent.name,
        org_name=state.org.name,
        domain=getattr(state.agent, "domain", "General"),
        objective=getattr(state.agent, "objective", "Help the user"),
        connected_tools=connected_str,
        tool_evidence=evidence_str,
        knowledge_base=kb_section,
    )


def _refresh_system_evidence(state: AgentState) -> None:
    """Update only the tool-evidence section of the system message in-place."""
    if not state.messages or state.messages[0]["role"] != "system":
        return

    evidence_parts = [f"[{name}]\n{result}" for name, result in state.tool_evidence.items()]
    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No tool calls made yet."

    old = state.messages[0]["content"]
    new = re.sub(
        r"(TOOL RESULTS \(your only facts\)\n══.*?\n)(.*?)(\n══|$)",
        lambda m: m.group(1) + evidence_str + (m.group(3) if m.group(3) else ""),
        old,
        flags=re.DOTALL,
    )
    state.messages[0]["content"] = new if new != old else old


# ──────────────────────────────────────────────────────────────────
# Node: build tools context
# ──────────────────────────────────────────────────────────────────

async def _node_build_tools(state: AgentState, rag_chunks: list[dict]) -> AgentState:
    """
    Load tools for the org.

    Strategy:
    - Composio tools (Gmail, Slack, etc.): fetch ACTUAL schemas from Composio API.
      The `name` in those schemas IS the Composio execution slug.
      Capped at MAX_TOOLS_PER_PROVIDER to avoid 413 Payload Too Large.
    - Native tools (Tally, GSTN): use our curated PROVIDER_TOOLS_MAPPING.
      These have explicit `provider` and `action` fields for routing.
    """
    try:
        connected_map = await get_available_tools_for_org(str(state.org.id), state.db)
    except Exception as exc:
        logger.warning("get_available_tools_for_org failed: %s", exc)
        connected_map = {}

    tools: list[dict] = []
    tool_route_map: dict[str, tuple[str, str]] = {}

    for provider, definitions in connected_map.items():
        if len(tools) >= MAX_TOOLS_TOTAL:
            logger.debug("Tool cap (%d) reached, skipping provider %s", MAX_TOOLS_TOTAL, provider)
            break

        p = provider.upper()

        if p in NATIVE_PROVIDERS:
            # Use our curated schemas — these have correct action names for the MCP server
            curated = PROVIDER_TOOLS_MAPPING.get(p, [])[:MAX_TOOLS_PER_PROVIDER]
            for tool in curated:
                if len(tools) >= MAX_TOOLS_TOTAL:
                    break
                clean = _sanitize_tool(tool)
                tools.append(clean)
                tool_route_map[clean["name"]] = (p, tool.get("action", clean["name"]))

        elif definitions:
            # Use ACTUAL Composio schemas — `name` field IS the executable slug.
            # Cap per-provider to avoid 413 (Gmail alone returns 50+ schemas).
            for tool_def in definitions[:MAX_TOOLS_PER_PROVIDER]:
                if len(tools) >= MAX_TOOLS_TOTAL:
                    break
                fn_name = tool_def.get("name", "")
                if not fn_name:
                    continue
                clean = _sanitize_tool({
                    **tool_def,
                    "provider": p,
                    "action": fn_name,  # For Composio: fn_name == execution slug
                })
                tools.append(clean)
                tool_route_map[fn_name] = (p, fn_name)

    logger.info("Built tool list: %d tools from %d providers", len(tools), len(connected_map))
    state.tools = tools
    state.tool_route_map = tool_route_map

    prompt = _build_system_prompt(state, rag_chunks)
    if state.messages and state.messages[0]["role"] == "system":
        state.messages[0]["content"] = prompt
    else:
        state.messages.insert(0, {"role": "system", "content": prompt})

    if state.stream_callback:
        await state.stream_callback(StreamEvent(
            type="thinking",
            content=f"Loaded {len(tools)} tools from {len(connected_map)} connected integrations.",
        ))

    return state


# ──────────────────────────────────────────────────────────────────
# Node: LLM call
# ──────────────────────────────────────────────────────────────────

async def _node_llm_call(state: AgentState, llm: LLMClient) -> AgentState:
    if state.stream_callback:
        await state.stream_callback(StreamEvent(type="thinking", content="Reasoning..."))

    # Build LLM-safe tool list (strip internal routing fields)
    llm_tools: list[dict] | None = None
    if state.tools:
        llm_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in state.tools
        ]

    try:
        response: LLMResponse = await llm.chat_with_tools(
            state.messages,
            tools=llm_tools,
        )
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        state.final_answer = (
            "I encountered an error contacting the AI service. Please try again shortly."
        )
        return state

    if response.tool_calls:
        state.messages.append({
            "role": "assistant",
            # IMPORTANT: content must be None (not "") when tool_calls present.
            # Groq rejects empty-string content alongside tool_calls.
            "content": response.content if response.content else None,
            "tool_calls": response.tool_calls,
        })
        await _persist_message(
            state=state,
            role="assistant",
            content=response.content or "Invoking integration tool...",
            tokens_used=response.tokens_used,
            tool_call=True,
        )
    else:
        raw_answer = response.content or ""
        state.final_answer = _enforce_grounding(raw_answer, state)

        if state.stream_callback:
            await state.stream_callback(StreamEvent(type="token", content=state.final_answer))

    return state


# ──────────────────────────────────────────────────────────────────
# Grounding enforcement
# ──────────────────────────────────────────────────────────────────

def _enforce_grounding(answer: str, state: AgentState) -> str:
    """
    If tool evidence exists but LLM forgot to cite sources,
    append a transparent evidence footer so users can verify.
    """
    if not state.tool_evidence:
        return answer

    has_citation = bool(re.search(r"\[SOURCE:", answer, re.IGNORECASE))
    if has_citation:
        return answer

    footer = "\n\n---\n**Data Sources Used:**"
    for tool_name, result_str in state.tool_evidence.items():
        snippet = result_str[:400] + "..." if len(result_str) > 400 else result_str
        footer += f"\n\n**[{tool_name}]**\n```\n{snippet}\n```"

    return answer + footer


# ──────────────────────────────────────────────────────────────────
# Node: execute tools
# ──────────────────────────────────────────────────────────────────

async def _node_execute_tools(state: AgentState) -> AgentState:
    last_msg = state.messages[-1]
    tool_calls: list[dict] = last_msg.get("tool_calls", [])

    for tc in tool_calls:
        fn_name: str = tc["function"]["name"]
        args_str: str = tc["function"]["arguments"]
        call_id: str = tc.get("id", "")

        try:
            params = json.loads(args_str)
        except Exception:
            params = {}

        # Resolve provider and action from the route map
        if fn_name in state.tool_route_map:
            provider, action = state.tool_route_map[fn_name]
        else:
            # Fallback: try our curated mapping
            mapped = map_tool_to_action(fn_name)
            provider, action = mapped if mapped else (fn_name.upper(), fn_name)

        logger.info(
            "Executing tool: fn=%s provider=%s action=%s params_keys=%s",
            fn_name, provider, action, list(params.keys()),
        )

        if state.stream_callback:
            await state.stream_callback(StreamEvent(
                type="tool_start",
                tool_name=fn_name,
                content=f"Calling {provider} → {action}",
            ))

        # SQL safety gate for Tally
        if provider == "TALLY" and action == "query-database":
            sql = params.get("sql", "")
            valid, reason = validate_sql(sql)
            if not valid:
                result_dict: dict = {
                    "error": f"SQL blocked by security validator: {reason}",
                    "result": None,
                }
                logger.warning("Blocked unsafe Tally SQL for org=%s reason=%s", state.org.id, reason)
            else:
                result_dict = await _safe_execute(provider, action, params, state)
        else:
            result_dict = await _safe_execute(provider, action, params, state)

        result_str = _format_result(fn_name, result_dict)

        # Store as grounded evidence
        state.tool_evidence[fn_name] = result_str
        state.tool_calls_made += 1

        # Persist tool call to DB
        await _persist_message(
            state=state,
            role="assistant",
            content=f"[Tool call: {fn_name}]",
            tokens_used=0,
            tool_call=True,
            tool_name=provider,
            tool_action=action,
            tool_result=json.dumps(result_dict),
        )

        # Inject tool result into message thread
        state.messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": fn_name,
            "content": result_str,
        })

        if state.stream_callback:
            await state.stream_callback(StreamEvent(
                type="tool_end",
                tool_name=fn_name,
                tool_result=result_str[:300] + "..." if len(result_str) > 300 else result_str,
            ))

    # Refresh evidence in system prompt so LLM sees fresh grounding
    _refresh_system_evidence(state)
    state.loop_count += 1
    return state


async def _safe_execute(provider: str, action: str, params: dict, state: AgentState) -> dict:
    try:
        return await execute_tool(
            org_id=str(state.org.id),
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


# ──────────────────────────────────────────────────────────────────
# DB persistence helper
# ──────────────────────────────────────────────────────────────────

async def _persist_message(
    state: AgentState,
    role: str,
    content: str,
    tokens_used: int = 0,
    tool_call: bool = False,
    tool_name: str | None = None,
    tool_action: str | None = None,
    tool_result: str | None = None,
) -> None:
    """Persist a message to the DB without raising — pipeline must not fail on DB errors."""
    try:
        msg = Message(
            conversation_id=uuid.UUID(state.conversation_id),
            role=role,
            content=content,
            tokens_used=tokens_used,
            tool_call=tool_call,
            tool_name=tool_name,
            tool_action=tool_action,
            tool_result=tool_result,
        )
        state.db.add(msg)
        await state.db.flush()
    except Exception as exc:
        logger.warning("Failed to persist pipeline message: %s", exc)


# ──────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────

def _route(state: AgentState) -> Literal["execute_tools", "final_answer"]:
    if state.final_answer is not None:
        return "final_answer"

    if state.loop_count >= state.max_loops:
        state.final_answer = (
            "I reached the maximum number of tool calls without a complete answer. "
            "Please try rephrasing or breaking the question into smaller parts."
        )
        return "final_answer"

    last = state.messages[-1] if state.messages else {}
    if last.get("role") == "assistant" and last.get("tool_calls"):
        return "execute_tools"

    return "final_answer"


# ──────────────────────────────────────────────────────────────────
# Public entrypoint — standard (non-streaming)
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
    """
    Main entrypoint. Runs the full LangGraph-style agentic loop with
    zero-hallucination enforcement.
    """
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

    # Window history to last N CLEAN messages.
    # IMPORTANT: exclude tool_call=True messages — they're internal pipeline state
    # (assistant "Invoking tool..." messages or tool result rows) and confuse the LLM
    # if included without their companion tool_calls / tool response structure.
    window = conversation_history[-HISTORY_WINDOW * 2:]  # wider slice before filtering
    formatted: list[dict] = []
    for m in window:
        if m.role not in ("user", "assistant"):
            continue
        if getattr(m, "tool_call", False):
            continue  # skip internal tool-call bookkeeping rows
        formatted.append({"role": m.role, "content": m.content or ""})

    # Keep only the last HISTORY_WINDOW messages after filtering
    formatted = formatted[-HISTORY_WINDOW:]

    state = AgentState(
        org=org,
        agent=agent,
        db=db,
        conversation_id=conversation_id or "",
        messages=formatted,
        stream_callback=stream_callback,
    )

    # Step 1: Load tools + build system prompt
    state = await _node_build_tools(state, rag_chunks or [])

    # Step 2: Agentic loop
    llm = LLMClient()

    while True:
        state = await _node_llm_call(state, llm)

        decision = _route(state)
        if decision == "final_answer":
            break

        # execute_tools path
        state = await _node_execute_tools(state)
        # loop back to llm_call

    answer = state.final_answer or "I was unable to generate a response."

    if stream_callback:
        await stream_callback(StreamEvent(
            type="done",
            content=answer,
            conversation_id=conversation_id,
            tool_calls_made=state.tool_calls_made,
        ))

    return PipelineResult(
        answer=answer,
        conversation_id=conversation_id or "",
        tool_calls_made=state.tool_calls_made,
    )


# ──────────────────────────────────────────────────────────────────
# Public entrypoint — streaming (async generator)
# ──────────────────────────────────────────────────────────────────

async def run_langgraph_pipeline_stream(
    org: Organization,
    agent: Agent,
    conversation_history: list[Message],
    db: AsyncSession,
    rag_chunks: list[dict] | None = None,
    conversation_id: str | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Streaming variant — yields StreamEvent objects as the pipeline executes.
    Used by the SSE endpoint.
    """
    events: list[StreamEvent] = []

    async def collect_event(event: StreamEvent) -> None:
        events.append(event)

    result = await run_langgraph_pipeline(
        org=org,
        agent=agent,
        conversation_history=conversation_history,
        db=db,
        rag_chunks=rag_chunks,
        conversation_id=conversation_id,
        stream_callback=collect_event,
    )

    for event in events:
        yield event

    if not any(e.type == "done" for e in events):
        yield StreamEvent(
            type="done",
            content=result.answer,
            conversation_id=result.conversation_id,
            tool_calls_made=result.tool_calls_made,
        )
