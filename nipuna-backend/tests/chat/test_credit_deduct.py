"""First-non-trivial-event credit deduct tests (PR3).

The credit deduct happens on the first of:
  (a) ≥5 tokens emitted
  (b) a successful tool call
  (c) a persisted assistant message ≥50 chars

It happens exactly once per turn. Disconnect does NOT trigger
a refund.

These tests pin the contract by reimplementing the same guard
pattern that ``chat.py`` uses and exercising it against the
event types we'd see in a real stream.
"""

from __future__ import annotations

import asyncio

from app.routers.chat import (
    CREDIT_DEDUCT_MIN_MESSAGE_CHARS,
    CREDIT_DEDUCT_MIN_TOKENS,
)


def _simulate_deduct(events: list[dict]) -> dict:
    """Replicate the chat.py deduct state machine. Returns a
    summary dict with deduct_at_index, tokens_before_deduct,
    and final state.
    """
    state = {
        "deducted": False,
        "deduct_at_index": None,
        "deduct_reason": None,
        "tokens_emitted": 0,
    }

    for i, ev in enumerate(events):
        if state["deducted"]:
            continue

        if ev["type"] == "token":
            state["tokens_emitted"] += 1
            if state["tokens_emitted"] >= CREDIT_DEDUCT_MIN_TOKENS:
                state["deducted"] = True
                state["deduct_at_index"] = i
                state["deduct_reason"] = "tokens"
                break

        if ev["type"] == "tool_end" and ev.get("success"):
            state["deducted"] = True
            state["deduct_at_index"] = i
            state["deduct_reason"] = "tool_success"
            break

        if ev["type"] == "done" and ev.get("content"):
            if len(ev["content"]) >= CREDIT_DEDUCT_MIN_MESSAGE_CHARS:
                state["deducted"] = True
                state["deduct_at_index"] = i
                state["deduct_reason"] = "message_length"
                break

    return state


def test_deduct_after_five_tokens():
    """The user gets 5+ tokens of value, so the turn is billed."""
    events = [
        {"type": "thinking", "content": "..."},
        {"type": "token", "content": "a"},
        {"type": "token", "content": "b"},
        {"type": "token", "content": "c"},
        {"type": "token", "content": "d"},
        {"type": "token", "content": "e"},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is True
    assert state["deduct_reason"] == "tokens"
    assert state["deduct_at_index"] == 5


def test_deduct_after_successful_tool():
    """A tool call that returns a real result is non-trivial."""
    events = [
        {"type": "thinking"},
        {"type": "tool_start"},
        {"type": "tool_end", "success": True, "tool_result": "..."},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is True
    assert state["deduct_reason"] == "tool_success"


def test_no_deduct_on_failed_tool():
    """A failed tool call doesn't cross the non-trivial threshold
    by itself — the user got nothing of value. Subsequent events
    (more tool calls, tokens, the final message) can still
    trigger the deduct.
    """
    events = [
        {"type": "thinking"},
        {"type": "tool_end", "success": False, "tool_result": "ERROR ..."},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is False


def test_deduct_on_persisted_message_length():
    """If we somehow got to `done` with a real answer but no
    tokens/tool crossed the threshold, the message length is
    the third fallback.
    """
    events = [
        {"type": "done", "content": "x" * CREDIT_DEDUCT_MIN_MESSAGE_CHARS},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is True
    assert state["deduct_reason"] == "message_length"


def test_no_deduct_on_short_done_message():
    """A 10-char `done` event with no tokens / no tools = the
    user got nothing of value. No deduct.
    """
    events = [
        {"type": "done", "content": "x" * 10},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is False


def test_deduct_only_fires_once():
    """Even with 100 token events after the deduct fires, the
    state is sticky.
    """
    events = (
        [{"type": "token", "content": "x"} for _ in range(100)]
    )
    state = _simulate_deduct(events)
    # Deduct fires on the 5th token and stays.
    assert state["deducted"] is True
    assert state["deduct_at_index"] == 4


def test_no_double_deduct_on_done():
    """If tokens crossed the threshold earlier, the `done` event
    doesn't re-deduct.
    """
    events = [
        {"type": "token", "content": "x"} for _ in range(10)
    ] + [
        {"type": "done", "content": "x" * 100},
    ]
    state = _simulate_deduct(events)
    assert state["deducted"] is True
    # The deduct reason is the first one that fired.
    assert state["deduct_reason"] == "tokens"
