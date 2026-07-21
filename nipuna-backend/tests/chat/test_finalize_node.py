"""Finalize node tests.

The finalize node handles two non-LLM paths: clarify_first (when
the route was 'clarify_first', return a templated question) and
the safety-net message when the loop is exhausted. The final
answer is also PII-redacted before it leaves the pipeline.
"""

from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_finalize_clarify_first_returns_clarifying_question():
    from app.services.ai.langgraph_pipeline import node_finalize
    state = {"route": "clarify_first", "final_answer": None}
    out = _run(node_finalize(state, config={}))
    assert "?" in out["final_answer"]
    assert "Could you" in out["final_answer"] or "more specific" in out["final_answer"].lower()


def test_finalize_loop_exhausted_returns_helpful_message():
    from app.services.ai.langgraph_pipeline import node_finalize
    state = {"route": "multi_tool", "final_answer": None}
    out = _run(node_finalize(state, config={}))
    assert "maximum" in out["final_answer"].lower()
    assert "tool calls" in out["final_answer"].lower()


def test_finalize_passes_through_existing_answer():
    from app.services.ai.langgraph_pipeline import node_finalize
    state = {"final_answer": "Here is the answer."}
    out = _run(node_finalize(state, config={}))
    assert out["final_answer"] == "Here is the answer."


def test_finalize_redacts_pii_in_answer():
    """PII redaction is the last line of defence: any PAN / Aadhaar
    that survived the LLM is stripped before the answer reaches
    the FE.
    """
    from app.services.ai.langgraph_pipeline import node_finalize
    state = {"final_answer": "Your PAN is ABCDE1234F and you owe ₹1,000."}
    out = _run(node_finalize(state, config={}))
    assert "ABCDE1234F" not in out["final_answer"]
    assert "[PAN]" in out["final_answer"]
