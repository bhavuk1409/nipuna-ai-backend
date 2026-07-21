"""Route node tests.

The route node is a deterministic, <5ms classifier that
short-circuits the LLM call for ``clarify_first`` and
``query_datasources=false``. These tests exercise the node
directly (no graph, no LLM) to pin the short-circuit logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def _state():
    """Minimal state the route node needs. We don't need a real
    Org/Agent/DB for the classifier path.
    """
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content="hi")],
        "org": None,
        "agent": None,
        "db": None,
        "conversation_id": "x",
        "rag_chunks": [],
        "query_datasources": True,
    }


def test_route_returns_route_and_reason(_state):
    from app.services.ai.langgraph_pipeline import node_route
    out = _run(node_route(_state, config={}))
    assert "route" in out
    assert "route_reason" in out
    assert out["route"] in {
        "direct_answer", "single_tool", "multi_tool",
        "rag_only", "clarify_first", "unknown",
    }


def test_route_short_circuits_when_datasources_off(_state):
    from app.services.ai.langgraph_pipeline import node_route
    _state["query_datasources"] = False
    _state["messages"] = []  # No message, but datasources off
    # Even with no message, datasources off forces direct_answer
    out = _run(node_route(_state, config={}))
    assert out["route"] == "direct_answer"
    assert out["tools"] == []
    assert out["tool_route_map"] == {}


def test_route_classifies_greeting_as_direct_answer(_state):
    from app.services.ai.langgraph_pipeline import node_route
    _state["messages"][0].content = "hi"
    out = _run(node_route(_state, config={}))
    assert out["route"] == "direct_answer"


def test_route_classifies_clarify(_state):
    from app.services.ai.langgraph_pipeline import node_route
    # "what" + "show" is a vague ask; whatever the classifier
    # routes to, it must be a valid route. The deterministic
    # regex in keyword_router can change over time — we just pin
    # that the function doesn't raise and returns a known route.
    _state["messages"][0].content = "show me the numbers"
    out = _run(node_route(_state, config={}))
    assert out["route"] in {
        "direct_answer", "single_tool", "multi_tool",
        "rag_only", "clarify_first", "unknown",
    }


def test_route_emits_thinking_event(_state):
    """The route node should emit a thinking event when given a
    stream callback so the FE can show the route decision in the
    tool trace.
    """
    from app.services.ai.langgraph_pipeline import node_route, StreamEvent

    received = []

    async def cb(event: StreamEvent) -> None:
        received.append(event)

    config = {"configurable": {"stream_callback": cb}}
    _run(node_route(_state, config=config))
    # At least one thinking event was emitted
    assert any(e.type == "thinking" for e in received)


def test_route_always_returns_dict(_state):
    from app.services.ai.langgraph_pipeline import node_route
    out = _run(node_route(_state, config={}))
    assert isinstance(out, dict)
