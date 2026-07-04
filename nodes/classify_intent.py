from __future__ import annotations

import logging

from schemas import GraphState, IntentResult
from nodes.common import detect_action, detect_sources, is_temporally_ambiguous, looks_business_related, normalize_query

logger = logging.getLogger(__name__)


def classify_intent(state: GraphState) -> dict:
    query = normalize_query(state["query"])
    prev_context = state.get("conversation_context", {})
    sources = detect_sources(query)
    action = detect_action(query)
    ambiguous = is_temporally_ambiguous(query)
    is_follow_up = any(
        phrase in query.lower()
        for phrase in ("what about", "and what about", "same", "that one", "those", "last month", "previous month")
    )
    prior_sources = prev_context.get("last_sources") or []

    if is_follow_up and prior_sources and not sources:
        sources = list(prior_sources)

    if ambiguous:
        result = IntentResult(
            intent="clarify",
            confidence=0.85,
            needs_clarification=True,
            clarification_question="What time range should I use? For example: today, this week, last 30 days, or a specific date range.",
            domain="business_data",
            time_scope=None,
            action=action,
        )
    elif action:
        result = IntentResult(
            intent="tool",
            confidence=0.92,
            needs_clarification=False,
            domain=sources[0] if sources else "gmail",
            action=action,
        )
    elif sources or looks_business_related(query) or (is_follow_up and prior_sources):
        result = IntentResult(
            intent="retrieve",
            confidence=0.88,
            needs_clarification=False,
            domain=sources[0] if sources else (prior_sources[0] if prior_sources else "gmail"),
            action="search_emails" if "gmail" in sources else None,
        )
    else:
        result = IntentResult(
            intent="general",
            confidence=0.5,
            needs_clarification=False,
            domain="general",
        )

    logger.info(
        "node=classify_intent thread_id=%s intent=%s sources=%s confidence=%.2f clarify=%s",
        state.get("thread_id"),
        result.intent,
        sources,
        result.confidence,
        result.needs_clarification,
    )

    return {
        "intent": result,
        "needs_clarification": result.needs_clarification,
        "clarification_question": result.clarification_question,
        "confidence": result.confidence,
        "conversation_context": {
            **state.get("conversation_context", {}),
            "last_query": query,
        },
    }
