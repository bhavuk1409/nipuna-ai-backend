from __future__ import annotations

import logging
from collections import defaultdict

from nodes.common import format_timestamp, make_citation
from schemas import AnswerPayload, Citation, GraphState, RetrievedContextItem

logger = logging.getLogger(__name__)


def _answer_from_gmail(context: list[RetrievedContextItem]) -> tuple[str, list[Citation]]:
    if not context:
        return "", []

    lines = []
    citations = []
    for idx, item in enumerate(context[:5], start=1):
        citation = make_citation(item)
        citations.append(citation)
        sender = item.metadata.get("sender") or item.body.split(":", 1)[0].replace("From ", "")
        lines.append(
            f"{idx}. {item.title} from {sender} "
            f"received {format_timestamp(item.timestamp)} [{citation.source_name} | {citation.freshness}]"
        )
    return "\n".join(lines), citations


def generate_answer(state: GraphState) -> dict:
    if state.get("needs_clarification"):
        return {}

    if state.get("final_answer") and not state.get("retrieved_context"):
        return {
            "draft_answer": state["final_answer"],
            "final_answer": state["final_answer"],
            "citations": state.get("citations", []),
            "confidence": max(state.get("confidence", 0.0), 0.2),
        }

    context = state.get("retrieved_context", [])
    intent = state.get("intent")

    if not context and intent and intent.intent == "general":
        answer = (
            "I can help with business questions once a source is connected. "
            "Right now the reference implementation is grounded on Gmail."
        )
        payload = AnswerPayload(
            answer=answer,
            citations=[],
            sources_queried=state.get("sources_queried", []),
            confidence=0.45,
        )
        logger.info("node=generate_answer thread_id=%s general_answer", state.get("thread_id"))
        return {"draft_answer": payload.answer, "final_answer": payload.answer, "citations": payload.citations, "confidence": payload.confidence}

    if not context:
        return {}

    grouped = defaultdict(list)
    for item in context:
        grouped[item.source_name].append(item)

    if "Gmail" in grouped:
        gmail_items = grouped["Gmail"]
        answer_lines = [f"I found {len(gmail_items)} Gmail message(s) relevant to your request:"]
        gmail_summary, citations = _answer_from_gmail(gmail_items)
        if gmail_summary:
            answer_lines.append(gmail_summary)
        answer = "\n".join(answer_lines)
    else:
        citations = [make_citation(item) for item in context[:5]]
        answer = "I found grounded context from the connected source(s), but no summarizer is implemented for that source yet."

    if state.get("draft_answer") and "Gmail" in grouped:
        answer = f"{answer}\n\nGrounded context:\n{state['draft_answer']}"

    payload = AnswerPayload(
        answer=answer,
        citations=citations,
        sources_queried=state.get("sources_queried", []),
        confidence=max(state.get("confidence", 0.0), 0.6 if citations else 0.3),
    )

    logger.info(
        "node=generate_answer thread_id=%s citations=%d confidence=%.2f",
        state.get("thread_id"),
        len(payload.citations),
        payload.confidence,
    )

    return {
        "draft_answer": payload.answer,
        "final_answer": payload.answer,
        "citations": payload.citations,
        "confidence": payload.confidence,
        "conversation_context": {
            **state.get("conversation_context", {}),
            "last_sources": list(dict.fromkeys(item.source_name.lower() for item in context)),
            "last_time_scope": intent.time_scope if intent else None,
        },
    }
