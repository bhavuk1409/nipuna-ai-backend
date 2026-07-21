"""Anti-pattern post-check tests.

The post-check is the structural fix for the 4-pattern contract.
The system prompt alone is leaky; the post-check makes the rule
enforceable. These tests pin the matching so a future refactor
doesn't silently drop coverage.
"""

from __future__ import annotations

from app.services.ai.langgraph_pipeline import _draft_has_anti_pattern


def test_clean_answer_passes():
    assert _draft_has_anti_pattern(
        "You have 3 unpaid invoices totalling ₹1,23,456. [SOURCE: tally]"
    ) is None


def test_clarifying_question_passes():
    assert _draft_has_anti_pattern(
        "Which time period would you like to see?"
    ) is None


def test_based_on_available_rejected():
    assert _draft_has_anti_pattern(
        "Based on the available information, your cashflow is positive."
    ) == "based on the available"


def test_i_think_rejected():
    assert _draft_has_anti_pattern(
        "I think the answer is around 1000."
    ) == "i think"


def test_approximately_rejected():
    assert _draft_has_anti_pattern(
        "Approximately 50% of revenue is outstanding."
    ) == "approximately"


def test_dont_have_access_rejected():
    assert _draft_has_anti_pattern(
        "I don't have access to your ledger."
    ) == "i don't have access to"


def test_i_am_not_sure_rejected():
    assert _draft_has_anti_pattern(
        "I am not sure, but I think it might be 50."
    ) == "i am not sure"


def test_as_an_ai_rejected():
    assert _draft_has_anti_pattern(
        "As an AI language model, I cannot tell you."
    ) == "as an ai"


def test_empty_draft_returns_none():
    assert _draft_has_anti_pattern("") is None
    assert _draft_has_anti_pattern(None) is None


def test_mixed_case_caught():
    # The regex is case-insensitive
    assert _draft_has_anti_pattern("BASED ON THE AVAILABLE DATA") == "based on the available"
