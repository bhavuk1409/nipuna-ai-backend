from __future__ import annotations

import asyncio
import logging
from typing import Any

from nodes.common import lexical_support_score, summarize_context
from schemas import GraphState, RetrievedContextItem
from tools.gmail import FixtureGmailConnector, GmailConnector, build_runtime_gmail_connector

logger = logging.getLogger(__name__)


def _connector() -> GmailConnector:
    return build_runtime_gmail_connector()


def _route_value(route: Any, key: str, default: Any = None) -> Any:
    if hasattr(route, key):
        return getattr(route, key)
    if isinstance(route, dict):
        return route.get(key, default)
    return default


def _gmail_items_from_search(payload: dict[str, Any], query: str) -> list[RetrievedContextItem]:
    results: list[RetrievedContextItem] = []
    for item in payload.get("messages", []):
        body = item.get("snippet", "")
        results.append(
            RetrievedContextItem(
                source_name="Gmail",
                source_type="email",
                source_id=str(item.get("message_id", "")),
                title=str(item.get("subject", "")),
                body=f"From {item.get('sender', '')}: {body}",
                timestamp=item["received_at"],
                url=None,
                metadata={"thread_id": item.get("thread_id"), "query": query, "sender": item.get("sender")},
                match_score=lexical_support_score(query, RetrievedContextItem(
                    source_name="Gmail",
                    source_type="email",
                    source_id=str(item.get("message_id", "")),
                    title=str(item.get("subject", "")),
                    body=body,
                    timestamp=item["received_at"],
                )),
            )
        )
    return results


async def _retrieve_gmail(state: GraphState, route: dict[str, Any], connector: GmailConnector) -> list[RetrievedContextItem]:
    operation = route["operation"]
    params = route.get("parameters", {})
    query = state["query"]

    if operation == "search_emails":
        result = await connector.search_emails(query=params.get("query", query), limit=int(params.get("limit", 10)))
        return _gmail_items_from_search(result.model_dump(mode="json"), query=query)

    if operation == "send_email":
        clarification = RetrievedContextItem(
            source_name="Gmail",
            source_type="action",
            source_id="send-email-request",
            title="Email send request needs slot filling",
            body="Recipient, subject, and body are required before sending an email safely.",
            timestamp=route.get("timestamp") or result_timestamp_fallback(),
            metadata={"operation": "send_email", "query": query},
        )
        return [clarification]

    if operation == "get_email":
        message_id = params.get("message_id")
        if not message_id:
            return []
        result = await connector.get_email(message_id=message_id)
        payload = result.model_dump(mode="json")
        return [
            RetrievedContextItem(
                source_name="Gmail",
                source_type="email",
                source_id=payload["message_id"],
                title=payload["subject"],
                body=f"From {payload['sender']}: {payload['body']}",
                timestamp=payload["received_at"],
                url=None,
                metadata={"thread_id": payload["thread_id"], "labels": payload.get("labels", [])},
                match_score=1.0,
            )
        ]

    return []


def result_timestamp_fallback():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def retrieve(state: GraphState) -> dict:
    route_plan = state.get("route_plan", [])
    if not route_plan:
        logger.info("node=retrieve thread_id=%s no_routes", state.get("thread_id"))
        return {"retrieved_context": [], "confidence": 0.0}

    connector = _connector()

    tasks = []
    unsupported_sources: list[str] = []
    for route in route_plan:
        retrieval_mode = _route_value(route, "retrieval_mode")
        source_name = _route_value(route, "source_name")
        route_payload = route.model_dump() if hasattr(route, "model_dump") else route
        if retrieval_mode == "unsupported":
            unsupported_sources.append(str(source_name))
            continue
        if source_name == "gmail":
            tasks.append(_retrieve_gmail(state, route_payload, connector))

    retrieved_nested = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    retrieved: list[RetrievedContextItem] = []
    for item in retrieved_nested:
        if isinstance(item, Exception):
            logger.warning("node=retrieve thread_id=%s source_error=%s", state.get("thread_id"), item)
            continue
        retrieved.extend(item)

    retrieved.sort(key=lambda item: item.match_score, reverse=True)
    retrieved = retrieved[:10]

    confidence = 0.0
    if retrieved:
        confidence = min(0.35 + 0.15 * len(retrieved), 0.95)
        confidence = max(confidence, 0.3)

    logger.info(
        "node=retrieve thread_id=%s retrieved=%d confidence=%.2f",
        state.get("thread_id"),
        len(retrieved),
        confidence,
    )

    return {
        "retrieved_context": retrieved,
        "confidence": confidence,
        "unsupported_sources": unsupported_sources,
        "notes": [summarize_context(retrieved[:3])] if retrieved else [],
    }
