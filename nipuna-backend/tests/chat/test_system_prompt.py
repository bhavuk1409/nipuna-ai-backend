"""System prompt composition tests.

The system prompt is the heart of the chat behaviour. We don't
snapshot the whole thing (templates + per-turn state vary), but
we assert the structural invariants that every prompt must have:
the 4-pattern contract, the NEVER list, and the context-state
block. A missing block would let the model free-form its way to
a vague answer.
"""

from __future__ import annotations

from app.services.ai.langgraph_pipeline import _build_system_prompt_for_state


def _prompt(**overrides):
    defaults = dict(
        agent_name="Nipuna AI",
        org_name="Acme",
        domain="Finance",
        objective="Help with cashflow",
        tools=[],
        tool_evidence={},
        rag_chunks=[],
        tone="professional",
        currency="INR",
        attachments=None,
        user_message="How much is owed?",
        memory_block="",
        tool_calls_made=0,
        history_turns=1,
        template_id="finance_cashflow",
    )
    defaults.update(overrides)
    return _build_system_prompt_for_state(**defaults)


def test_prompt_contains_four_pattern_contract():
    out = _prompt()
    assert "ANSWER_WITH_EVIDENCE" in out
    assert "ASK_CLARIFYING_QUESTION" in out
    assert "EXPLAIN_WHAT_IS_MISSING" in out
    assert "DECLINE_POLITELY" in out


def test_prompt_contains_never_list():
    out = _prompt()
    assert "NEVER" in out
    # Spot-check the worst offenders
    assert "Based on the available" in out
    assert "Approximately" in out
    assert "I think" in out


def test_prompt_contains_voice_and_tone_block():
    out = _prompt()
    assert "VOICE" in out
    assert "Lead with the answer" in out


def test_prompt_includes_template_suffix():
    # finance_cashflow template has a distinctive suffix
    out = _prompt(template_id="finance_cashflow")
    assert "finance" in out.lower() or "cashflow" in out.lower()


def test_prompt_includes_user_data_block():
    out = _prompt(user_message="show me invoices")
    assert "<<<USER_DATA" in out
    assert "show me invoices" in out
    assert "<<<END_USER_DATA" in out


def test_prompt_includes_attachments():
    out = _prompt(attachments=["contents of invoice.pdf", "another file"])
    assert "ATTACHMENTS" in out
    assert "contents of invoice.pdf" in out


def test_prompt_includes_memory_when_provided():
    out = _prompt(memory_block="- user is CFO at Acme")
    assert "KNOWN FACTS" in out
    assert "user is CFO at Acme" in out


def test_prompt_omits_memory_when_empty():
    out = _prompt(memory_block="")
    assert "KNOWN FACTS" not in out


def test_prompt_reflects_currency_and_tone():
    out = _prompt(currency="USD", tone="casual")
    assert "USD" in out
    assert "casual" in out


def test_prompt_includes_context_state():
    out = _prompt(tool_calls_made=2, history_turns=4)
    assert "CONTEXT STATE" in out
    assert "Tool calls so far: 2" in out
    assert "4 turn(s)" in out


def test_prompt_includes_knowledge_base_status():
    # Empty knowledge base: the prompt must say so
    out = _prompt(rag_chunks=[])
    assert "knowledge base" in out.lower()


def test_prompt_includes_connected_integrations():
    out = _prompt(tools=[{"provider": "TALLY"}, {"provider": "GMAIL"}])
    assert "TALLY" in out
    assert "GMAIL" in out


def test_prompt_marks_user_data_untrusted():
    # The user data block must be marked untrusted to defend
    # against prompt injection via the user message.
    out = _prompt()
    assert "UNTRUSTED" in out or "untrusted" in out
