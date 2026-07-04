from __future__ import annotations

import logging

from schemas import AnswerPayload, GraphState

logger = logging.getLogger(__name__)


def clarify(state: GraphState) -> dict:
    intent = state.get("intent")
    question = state.get("clarification_question")
    if not question and intent:
        question = intent.clarification_question
    if not question:
        question = "I need one more detail to answer safely. Which source should I check, and what time range should I use?"

    payload = AnswerPayload(
        answer=question,
        citations=[],
        sources_queried=state.get("sources_queried", []),
        confidence=min(state.get("confidence", 0.0), 0.4),
        needs_clarification=True,
        clarification_question=question,
    )

    logger.info("node=clarify thread_id=%s question=%s", state.get("thread_id"), question)

    return {
        "final_answer": payload.answer,
        "draft_answer": payload.answer,
        "citations": payload.citations,
        "needs_clarification": True,
        "clarification_question": question,
        "confidence": payload.confidence,
    }

