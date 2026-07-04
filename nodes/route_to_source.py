from __future__ import annotations

import logging

from schemas import GraphState, SourceRoute
from nodes.common import detect_action, detect_sources, looks_business_related

logger = logging.getLogger(__name__)


SUPPORTED_SOURCES = {"gmail", "slack", "github", "jira", "accounting", "crm"}


def route_to_source(state: GraphState) -> dict:
    query = state["query"]
    intent = state.get("intent")
    prev_context = state.get("conversation_context", {})
    sources = detect_sources(query)
    action = intent.action if intent else detect_action(query)
    if not sources and prev_context.get("last_sources"):
        follow_up_indicators = ("what about", "and what about", "same", "those", "that one", "last month", "previous month")
        if any(indicator in query.lower() for indicator in follow_up_indicators):
            sources = list(prev_context["last_sources"])

    if not sources and intent and intent.intent == "general" and not looks_business_related(query):
        logger.info("node=route_to_source thread_id=%s routes=0 reason=general", state.get("thread_id"))
        return {"route_plan": [], "sources_queried": [], "notes": ["general"]}

    if not sources:
        sources = ["gmail"] if action == "send_email" else []
    if not sources and looks_business_related(query):
        sources = ["gmail"]

    route_plan: list[SourceRoute] = []
    for source in sources:
        if source not in SUPPORTED_SOURCES:
            route_plan.append(
                SourceRoute(
                    source_name=source,
                    retrieval_mode="unsupported",
                    operation="unsupported",
                    reason=f"{source} is not connected in this deployment.",
                )
            )
            continue

        if source == "gmail":
            operation = action or "search_emails"
            retrieval_mode = "action" if operation == "send_email" else "structured"
            params = {"query": query, "limit": 10}
            if operation == "send_email":
                params = {"query": query}
            route_plan.append(
                SourceRoute(
                    source_name="gmail",
                    retrieval_mode=retrieval_mode,
                    operation=operation,
                    parameters=params,
                    reason="Gmail is the connected source for email/inbox questions.",
                )
            )
        else:
            route_plan.append(
                SourceRoute(
                    source_name=source,
                    retrieval_mode="unsupported",
                    operation="unsupported",
                    reason=f"{source} routing is scaffolded but not yet implemented.",
                )
            )

    sources_queried = [route.source_name for route in route_plan]

    logger.info(
        "node=route_to_source thread_id=%s sources=%s operations=%s",
        state.get("thread_id"),
        sources_queried,
        [route.operation for route in route_plan],
    )

    return {
        "route_plan": route_plan,
        "sources_queried": sources_queried,
    }
