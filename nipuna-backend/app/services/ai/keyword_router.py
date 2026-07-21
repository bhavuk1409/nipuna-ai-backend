"""Deterministic route classifier for the chat pipeline.

Goal: skip the LLM call entirely for queries we can classify in <5ms,
so the first-token latency stays under the user's perception of
"snappy." Falls back to ``unknown`` for ambiguous queries, which the
graph then routes through the full LLM-based reasoning path.

Five classes:
- ``direct_answer``   — chit-chat, definitions, greetings. No tools.
- ``single_tool``     — one obvious tool needed.
- ``multi_tool``      — conjunction-driven ("and", "then", "also") or
                        multiple entities mentioned.
- ``rag_only``        — knowledge-base question, no live data needed.
- ``clarify_first``   — ambiguous; surface a templated clarifying
                        question and skip the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Route = Literal[
    "direct_answer",
    "single_tool",
    "multi_tool",
    "rag_only",
    "clarify_first",
    "unknown",
]


@dataclass
class Classification:
    route: Route
    """The deterministic class."""
    reason: str
    """Human-readable reason — for the eval harness and for offline tuning."""


# Patterns that strongly suggest "no tool needed" — definitions, chit-chat.
_DIRECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(hi|hello|hey|thanks|thank you|thx|ty)\b", re.IGNORECASE),
    re.compile(r"^\s*what('?| i)s\s+(a|an|the)\s+\w+", re.IGNORECASE),
    re.compile(r"^\s*define\s+\w+", re.IGNORECASE),
    re.compile(r"^\s*explain\s+(what|how|why)\s+\w+", re.IGNORECASE),
    re.compile(r"^\s*who\s+(are|is)\s+(you|nipuna)", re.IGNORECASE),
    re.compile(r"^\s*can\s+you\s+help\b", re.IGNORECASE),
)

# Patterns that strongly suggest "knowledge base, no live data".
_RAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(policy|handbook|sop|standard operating procedure|guideline|runbook|documentation|doc)\b", re.IGNORECASE),
    re.compile(r"\baccording to (our|the) (manual|docs|handbook|policy)\b", re.IGNORECASE),
    re.compile(r"\bin (our|the) (handbook|docs|documentation)\b", re.IGNORECASE),
)

# Patterns that strongly suggest "ambiguous, ask first".
_CLARIFY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*help\b", re.IGNORECASE),
    re.compile(r"^\s*what('?| i)s\s+(my|our|the)\b", re.IGNORECASE),  # "what is my…" needs entity
    re.compile(r"^\s*show\s+me\s+everything\b", re.IGNORECASE),
    re.compile(r"^\s*analy[sz]e\s*$", re.IGNORECASE),
)

# Conjunctions / multi-step markers.
_MULTI_CONJUNCTIONS: tuple[str, ...] = (
    " and ",
    " then ",
    " also ",
    " plus ",
    " as well as ",
    " after that ",
    " additionally ",
    ", then ",
)

# Provider entity hints — used to detect single-tool queries. We use
# these as a "strong signal that at least one tool is relevant" — the
# graph decides *which* tool through the LLM, but the router can
# confidently say "this isn't chit-chat."
_PROVIDER_HINTS: tuple[str, ...] = (
    "tally",
    "gst",
    "gstn",
    "invoice",
    "invoices",
    "ledger",
    "voucher",
    "customer",
    "customers",
    "outstanding",
    "receivable",
    "payable",
    "cash flow",
    "cashflow",
    "expense",
    "expenses",
    "revenue",
    "profit",
    "loss",
    "balance sheet",
    "pnl",
    "p&l",
    "tax",
    "gmail",
    "email",
    "emails",
    "inbox",
    "stripe",
    "hubspot",
    "slack",
    "sheet",
    "sheets",
    "spreadsheet",
    "workflow",
    "alert",
    "alerts",
    "agent",
)


def _has_multi_conjunction(query: str) -> bool:
    q_lower = " " + query.lower() + " "
    for marker in _MULTI_CONJUNCTIONS:
        if marker in q_lower:
            return True
    return False


def _provider_hint_count(query: str) -> int:
    q_lower = query.lower()
    return sum(1 for hint in _PROVIDER_HINTS if hint in q_lower)


def classify(query: str) -> Classification:
    """Return a deterministic route for the given user query.

    The function is total: every input returns a Classification. For
    ambiguous queries it returns ``unknown`` and the graph falls
    through to the full LLM-based path.
    """
    if not query or not query.strip():
        return Classification("clarify_first", "empty query")

    q = query.strip()

    for pat in _DIRECT_PATTERNS:
        if pat.search(q):
            return Classification("direct_answer", f"matched direct pattern: {pat.pattern!r}")

    for pat in _RAG_PATTERNS:
        if pat.search(q):
            return Classification("rag_only", f"matched rag pattern: {pat.pattern!r}")

    for pat in _CLARIFY_PATTERNS:
        if pat.search(q):
            return Classification("clarify_first", f"matched clarify pattern: {pat.pattern!r}")

    # If we have a conjunction AND a provider hint, it's multi-tool.
    has_conj = _has_multi_conjunction(q)
    hint_count = _provider_hint_count(q)

    if has_conj and hint_count >= 1:
        return Classification("multi_tool", f"conjunction + {hint_count} provider hint(s)")

    if hint_count >= 2:
        return Classification("multi_tool", f"{hint_count} provider hint(s) without conjunction")

    if hint_count == 1:
        return Classification("single_tool", "1 provider hint, no conjunction")

    # Long, free-form query with no markers — let the LLM figure it out.
    if len(q) < 12:
        return Classification("clarify_first", "very short, no markers")

    return Classification("unknown", "no signal — fall through to LLM")


__all__ = ["Classification", "Route", "classify"]
