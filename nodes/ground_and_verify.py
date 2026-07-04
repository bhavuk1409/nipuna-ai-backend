from __future__ import annotations

import logging

from nodes.common import claim_supported, make_citation, summarize_context
from schemas import GraphState, GroundedClaim

logger = logging.getLogger(__name__)


def _route_value(route: object, key: str, default: object = None):
    if hasattr(route, key):
        return getattr(route, key)
    if isinstance(route, dict):
        return route.get(key, default)
    return default


def ground_and_verify(state: GraphState) -> dict:
    context = state.get("retrieved_context", [])
    unsupported_sources = [str(source) for source in state.get("unsupported_sources", []) if source]

    if not context:
        if unsupported_sources:
            message = (
                "I do not have the requested data connected yet for "
                f"{', '.join(sorted(set(unsupported_sources)))}. "
                "I can answer once that integration is connected."
            )
            logger.info(
                "node=ground_and_verify thread_id=%s unsupported_sources=%s",
                state.get("thread_id"),
                unsupported_sources,
            )
            return {
                "grounded_claims": [],
                "final_answer": message,
                "draft_answer": message,
                "needs_clarification": False,
                "confidence": 0.2,
            }

        logger.info("node=ground_and_verify thread_id=%s no_context", state.get("thread_id"))
        return {
            "grounded_claims": [],
            "needs_clarification": True,
            "clarification_question": "I do not have enough connected data to answer that yet. Which source should I check, and for what time range?",
            "confidence": min(state.get("confidence", 0.0), 0.2),
        }

    grounded: list[GroundedClaim] = []
    supported_count = 0

    for item in context:
        claim_text = f"{item.title} from Gmail at {item.timestamp.isoformat()}"
        supported, supporting_items = claim_supported(claim_text, context)
        citations = [make_citation(supporting_items[0], evidence=supporting_items[0].title)] if supporting_items else [make_citation(item)]
        grounded.append(GroundedClaim(claim=claim_text, supported=supported, citations=citations))
        if supported:
            supported_count += 1

    if grounded and supported_count == 0:
        logger.info("node=ground_and_verify thread_id=%s no_supported_claims", state.get("thread_id"))
        return {
            "grounded_claims": grounded,
            "needs_clarification": True,
            "clarification_question": "I found data, but I cannot safely support the draft answer from the retrieved context. Can you narrow the question?",
            "confidence": min(state.get("confidence", 0.0), 0.35),
        }

    citations = []
    for item in context[:5]:
        citations.append(make_citation(item))

    confidence = min(0.95, max(state.get("confidence", 0.0), 0.55 if supported_count else 0.25))
    draft_answer = summarize_context(context[:5])

    logger.info(
        "node=ground_and_verify thread_id=%s claims=%d supported=%d confidence=%.2f",
        state.get("thread_id"),
        len(grounded),
        supported_count,
        confidence,
    )

    return {
        "grounded_claims": grounded,
        "draft_answer": draft_answer,
        "citations": citations,
        "confidence": confidence,
    }
