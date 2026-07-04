from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from nodes.classify_intent import classify_intent
from nodes.clarify import clarify
from nodes.generate_answer import generate_answer
from nodes.ground_and_verify import ground_and_verify
from nodes.retrieve import retrieve
from nodes.route_to_source import route_to_source
from schemas import ChatResponse, GraphState
from tools.gmail import GmailConnector, FixtureGmailConnector, build_runtime_gmail_connector

logger = logging.getLogger(__name__)


@dataclass
class AssistantRuntime:
    gmail_connector: GmailConnector = field(default_factory=FixtureGmailConnector)
    model_name: str = "deterministic"
    source_names: tuple[str, ...] = ("gmail", "slack", "github", "jira", "accounting", "crm")


def build_runtime() -> AssistantRuntime:
    return AssistantRuntime(gmail_connector=build_runtime_gmail_connector())


def _route_after_classification(state: GraphState) -> Literal["route_to_source", "clarify", "generate_answer"]:
    intent = state.get("intent")
    if state.get("needs_clarification"):
        return "clarify"
    if intent and intent.intent == "general":
        return "generate_answer"
    return "route_to_source"


def _route_after_retrieval(state: GraphState) -> Literal["ground_and_verify", "clarify"]:
    if state.get("needs_clarification"):
        return "clarify"
    return "ground_and_verify"


def _route_after_grounding(state: GraphState) -> Literal["generate_answer", "clarify"]:
    if state.get("needs_clarification"):
        return "clarify"
    if state.get("final_answer"):
        return "generate_answer"
    if not state.get("retrieved_context"):
        return "clarify"
    return "generate_answer"


def build_graph(runtime: AssistantRuntime | None = None):
    runtime = runtime or build_runtime()
    checkpointer = MemorySaver()

    workflow = StateGraph(GraphState)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("route_to_source", route_to_source)
    workflow.add_node("retrieve", retrieve)
    workflow.add_node("ground_and_verify", ground_and_verify)
    workflow.add_node("generate_answer", generate_answer)
    workflow.add_node("clarify", clarify)

    workflow.add_edge(START, "classify_intent")
    workflow.add_conditional_edges(
        "classify_intent",
        _route_after_classification,
        {
            "route_to_source": "route_to_source",
            "clarify": "clarify",
            "generate_answer": "generate_answer",
        },
    )
    workflow.add_edge("route_to_source", "retrieve")
    workflow.add_conditional_edges(
        "retrieve",
        _route_after_retrieval,
        {
            "ground_and_verify": "ground_and_verify",
            "clarify": "clarify",
        },
    )
    workflow.add_conditional_edges(
        "ground_and_verify",
        _route_after_grounding,
        {
            "generate_answer": "generate_answer",
            "clarify": "clarify",
        },
    )
    workflow.add_edge("generate_answer", END)
    workflow.add_edge("clarify", END)

    graph = workflow.compile(checkpointer=checkpointer)
    return graph


assistant_graph = build_graph()


def normalize_response(state: dict[str, Any], thread_id: str) -> ChatResponse:
    return ChatResponse(
        thread_id=thread_id,
        answer=state.get("final_answer") or state.get("draft_answer") or "",
        citations=state.get("citations", []),
        sources_queried=state.get("sources_queried", []),
        confidence=float(state.get("confidence", 0.0)),
        needs_clarification=bool(state.get("needs_clarification", False)),
        clarification_question=state.get("clarification_question"),
    )


async def run_chat_turn(thread_id: str, message: str, runtime: AssistantRuntime | None = None) -> ChatResponse:
    _ = runtime or build_runtime()
    result = await assistant_graph.ainvoke(
        {
            "thread_id": thread_id,
            "query": message,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    return normalize_response(result, thread_id)


async def stream_chat_turn(thread_id: str, message: str, runtime: AssistantRuntime | None = None):
    _ = runtime or build_runtime()
    async for event in assistant_graph.astream(
        {
            "thread_id": thread_id,
            "query": message,
        },
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        yield event
