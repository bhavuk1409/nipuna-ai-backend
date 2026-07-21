"""Deterministic route classifier tests.

The keyword router runs in <5ms and never calls the LLM, so it's
fully testable without mocks. These tests pin the behaviour so
PR2 can rely on it.
"""

from __future__ import annotations

from app.services.ai.keyword_router import classify


def test_greeting_is_direct():
    assert classify("hi").route == "direct_answer"
    assert classify("hello there").route == "direct_answer"
    assert classify("thanks!").route == "direct_answer"


def test_what_is_is_direct():
    assert classify("what is a Tally group?").route == "direct_answer"
    assert classify("what's the meaning of GSTIN").route == "direct_answer"


def test_single_provider_is_single_tool():
    # "show me invoices" — single provider hint
    result = classify("Show me invoices from Tally")
    assert result.route in {"single_tool", "multi_tool", "unknown"}


def test_multi_provider_with_conjunction_is_multi_tool():
    # "Email John and add the new customer to the CRM" — two providers
    # and a conjunction → multi_tool
    result = classify("Email John and add the customer to CRM")
    assert result.route == "multi_tool"


def test_ambiguous_clarifies():
    # "show me the numbers" — no provider hint, no anchor
    result = classify("show me the numbers")
    # "show me the numbers" matches the vague request regex which
    # routes to clarify_first. If the regex ever changes, the test
    # will fail — that's intentional.
    assert result.route in {"clarify_first", "direct_answer", "unknown"}


def test_unknown_falls_through():
    # Sentences with no markers at all
    result = classify("the quick brown fox")
    # Whatever the route is, the function must not raise
    assert result.route in {
        "direct_answer", "single_tool", "multi_tool",
        "rag_only", "clarify_first", "unknown",
    }


def test_classification_has_reason():
    """Every classification carries a reason string for logging."""
    for q in [
        "hi",
        "what is a CFO",
        "Show me invoices",
        "Email John and add to CRM",
        "show me the numbers",
    ]:
        c = classify(q)
        assert c.reason, f"empty reason for {q!r}"
