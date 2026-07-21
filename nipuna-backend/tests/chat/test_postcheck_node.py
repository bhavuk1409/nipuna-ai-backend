"""Post-check node tests.

The postcheck is the structural enforcement of the 4-pattern
contract. We test the node in isolation to pin the rewrite
behaviour: a draft with an anti-pattern + non-empty evidence
triggers a rewrite (clears final_answer), the counter increments,
and after 2 rewrites the node gives up.
"""

from __future__ import annotations

import asyncio
from typing import Any


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(**overrides):
    base = {
        "tool_evidence": {"tally": "{\"total\": 1000}"},
        "rag_chunks": [],
        "final_answer": "Based on the available, you have ₹1,000.",
        "postcheck_rewrites": 0,
    }
    base.update(overrides)
    return base


def test_postcheck_no_evidence_is_pass_through():
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(tool_evidence={}, rag_chunks=[])
    out = _run(node_postcheck(state, config={}))
    # No evidence -> no check, no rewrite
    assert out == {}


def test_postcheck_clean_answer_with_evidence_passes():
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(final_answer="₹1,000 outstanding. [SOURCE: tally]")
    out = _run(node_postcheck(state, config={}))
    assert out == {}


def test_postcheck_anti_pattern_triggers_rewrite():
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(final_answer="I think you have ₹1,000.")
    out = _run(node_postcheck(state, config={}))
    assert out["final_answer"] is None  # cleared -> routes back to llm_call
    assert out["postcheck_rewrites"] == 1


def test_postcheck_gives_up_after_two_rewrites():
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(
        final_answer="I think you have ₹1,000.",
        postcheck_rewrites=2,
    )
    out = _run(node_postcheck(state, config={}))
    # 2nd rewrite means we've already done 2 — give up. Return the
    # draft with a warning footer.
    assert out["final_answer"].startswith("I think you have ₹1,000.")
    assert "couldn't fully format" in out["final_answer"]


def test_postcheck_empty_draft_is_pass_through():
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(final_answer="")
    out = _run(node_postcheck(state, config={}))
    assert out == {}


def test_postcheck_uses_rag_chunks_as_evidence():
    """A non-empty rag_chunks block is enough to trigger the
    check — even without tool_evidence.
    """
    from app.services.ai.langgraph_pipeline import node_postcheck
    state = _state(
        tool_evidence={},
        rag_chunks=[{"text": "some kb content", "score": 0.8}],
        final_answer="I think the answer is X.",
    )
    out = _run(node_postcheck(state, config={}))
    assert out["final_answer"] is None
    assert out["postcheck_rewrites"] == 1
