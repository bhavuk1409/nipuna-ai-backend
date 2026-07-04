from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "nipuna-backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))


class GmailSearchInput(BaseModel):
    query: str = Field(..., min_length=1, description="Search query across sender, subject, and body")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of messages to return")


class GmailMessageRef(BaseModel):
    message_id: str
    thread_id: str
    subject: str
    sender: str
    received_at: datetime
    snippet: str


class GmailSearchOutput(BaseModel):
    query: str
    count: int
    messages: list[GmailMessageRef] = Field(default_factory=list)
    source_name: str = "Gmail"
    last_synced_at: datetime


class GmailGetInput(BaseModel):
    message_id: str = Field(..., min_length=1)


class GmailEmailOutput(BaseModel):
    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str]
    received_at: datetime
    body: str
    labels: list[str] = Field(default_factory=list)
    source_name: str = "Gmail"
    last_synced_at: datetime


class GmailSendInput(BaseModel):
    recipient: str = Field(..., min_length=3)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class GmailSendOutput(BaseModel):
    sent: bool
    recipient: str
    subject: str
    message_id: str | None = None
    source_name: str = "Gmail"
    last_synced_at: datetime


class GmailConnector(Protocol):
    async def search_emails(self, query: str, limit: int = 10) -> GmailSearchOutput: ...
    async def get_email(self, message_id: str) -> GmailEmailOutput: ...
    async def send_email(self, recipient: str, subject: str, body: str) -> GmailSendOutput: ...


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class _FixtureMessage:
    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str]
    received_at: datetime
    body: str
    labels: list[str]


class FixtureGmailConnector:
    """Deterministic Gmail reference connector used for local runs and evals."""

    def __init__(self) -> None:
        self._messages = [
            _FixtureMessage(
                message_id="msg-1001",
                thread_id="thr-1",
                subject="Invoice overdue for Acme Corp",
                sender="billing@acme.com",
                recipients=["finance@nipuna.ai"],
                received_at=_parse_timestamp("2026-06-28T10:30:00+05:30"),
                body="Invoice INV-1001 for Acme Corp is overdue by 10 days. Amount due is INR 84,500. Please follow up with the customer.",
                labels=["inbox", "finance"],
            ),
            _FixtureMessage(
                message_id="msg-1002",
                thread_id="thr-2",
                subject="Payment received for invoice INV-1002",
                sender="accounts@widgets.com",
                recipients=["finance@nipuna.ai"],
                received_at=_parse_timestamp("2026-06-29T14:05:00+05:30"),
                body="We received payment for invoice INV-1002. Thank you for the quick turnaround.",
                labels=["inbox", "finance"],
            ),
            _FixtureMessage(
                message_id="msg-1003",
                thread_id="thr-3",
                subject="Weekly sales report",
                sender="sales@nipuna.ai",
                recipients=["ceo@nipuna.ai"],
                received_at=_parse_timestamp("2026-06-30T09:15:00+05:30"),
                body="This week closed three new deals. Total pipeline value is INR 2.4 crore.",
                labels=["inbox", "report"],
            ),
            _FixtureMessage(
                message_id="msg-1004",
                thread_id="thr-4",
                subject="Project kickoff rescheduled",
                sender="pm@studiohub.com",
                recipients=["ops@nipuna.ai"],
                received_at=_parse_timestamp("2026-07-01T16:20:00+05:30"),
                body="The kickoff moved to Thursday at 11:00 AM IST. Please confirm attendance.",
                labels=["inbox", "operations"],
            ),
            _FixtureMessage(
                message_id="msg-1005",
                thread_id="thr-5",
                subject="Vendor renewal reminder",
                sender="procurement@partner.co",
                recipients=["finance@nipuna.ai"],
                received_at=_parse_timestamp("2026-07-02T08:45:00+05:30"),
                body="The annual contract renewal is due next week. Attached is the updated quote.",
                labels=["inbox", "finance"],
            ),
        ]

    async def search_emails(self, query: str, limit: int = 10) -> GmailSearchOutput:
        query_lc = query.lower()
        stopwords = {"the", "and", "for", "with", "from", "this", "that", "about", "what", "show", "find", "list", "me", "of", "in", "on", "to", "a", "an", "is", "are", "latest", "recent"}
        tokens = [token for token in re.split(r"[^a-z0-9]+", query_lc) if token and token not in stopwords and len(token) > 2]

        scored: list[tuple[float, _FixtureMessage]] = []
        for msg in self._messages:
            haystack_tokens = {
                token
                for token in re.split(r"[^a-z0-9]+", " ".join([msg.subject, msg.sender, msg.body, " ".join(msg.labels)]).lower())
                if token
            }
            score = sum(1.0 for token in tokens if token in haystack_tokens)
            if score > 0:
                scored.append((score, msg))

        scored.sort(key=lambda item: (item[0], item[1].received_at), reverse=True)
        chosen = [msg for _, msg in scored[:limit]]

        return GmailSearchOutput(
            query=query,
            count=len(chosen),
            messages=[
                GmailMessageRef(
                    message_id=msg.message_id,
                    thread_id=msg.thread_id,
                    subject=msg.subject,
                    sender=msg.sender,
                    received_at=msg.received_at,
                    snippet=msg.body[:180],
                )
                for msg in chosen
            ],
            last_synced_at=_now_utc(),
        )

    async def get_email(self, message_id: str) -> GmailEmailOutput:
        for msg in self._messages:
            if msg.message_id == message_id:
                return GmailEmailOutput(
                    message_id=msg.message_id,
                    thread_id=msg.thread_id,
                    subject=msg.subject,
                    sender=msg.sender,
                    recipients=msg.recipients,
                    received_at=msg.received_at,
                    body=msg.body,
                    labels=msg.labels,
                    last_synced_at=_now_utc(),
                )
        raise ValueError(f"Gmail message not found: {message_id}")

    async def send_email(self, recipient: str, subject: str, body: str) -> GmailSendOutput:
        return GmailSendOutput(
            sent=True,
            recipient=recipient,
            subject=subject,
            message_id=f"draft-{re.sub(r'[^a-zA-Z0-9]+', '-', recipient).strip('-').lower()}-{abs(sum(ord(ch) for ch in subject)) % 100000}",
            last_synced_at=_now_utc(),
        )


class LiveGmailConnector:
    """Composio-backed Gmail connector. Returns explicit errors when unavailable."""

    def __init__(self) -> None:
        self._cached_gateway: Any | None = None

    def _gateway(self) -> Any:
        if self._cached_gateway is not None:
            return self._cached_gateway

        try:
            from app.services.mcp.composio_gateway import composio_gateway
        except Exception as exc:
            raise RuntimeError(f"Composio gateway unavailable: {exc}") from exc

        self._cached_gateway = composio_gateway
        return self._cached_gateway

    async def search_emails(self, query: str, limit: int = 10) -> GmailSearchOutput:
        result = await self._gateway().execute_action(
            org_id="assistant",
            tool_name="GMAIL",
            action="GMAIL_SEARCH_EMAILS",
            params={"query": query},
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        payload = result.get("result") or result
        messages = []
        for item in (payload or [])[:limit]:
            received_at = item.get("received_at") or item.get("date") or _now_utc().isoformat()
            messages.append(
                GmailMessageRef(
                    message_id=str(item.get("id") or item.get("message_id") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    subject=str(item.get("subject") or ""),
                    sender=str(item.get("from") or item.get("sender") or ""),
                    received_at=_parse_timestamp(str(received_at)),
                    snippet=str(item.get("snippet") or item.get("body") or "")[:180],
                )
            )
        return GmailSearchOutput(
            query=query,
            count=len(messages),
            messages=messages,
            last_synced_at=_now_utc(),
        )

    async def get_email(self, message_id: str) -> GmailEmailOutput:
        result = await self._gateway().execute_action(
            org_id="assistant",
            tool_name="GMAIL",
            action="GMAIL_GET_EMAIL",
            params={"message_id": message_id},
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        payload = result.get("result") or result
        return GmailEmailOutput(
            message_id=str(payload.get("message_id") or message_id),
            thread_id=str(payload.get("thread_id") or ""),
            subject=str(payload.get("subject") or ""),
            sender=str(payload.get("sender") or payload.get("from") or ""),
            recipients=[str(x) for x in payload.get("recipients", [])],
            received_at=_parse_timestamp(str(payload.get("received_at") or _now_utc().isoformat())),
            body=str(payload.get("body") or payload.get("content") or ""),
            labels=[str(x) for x in payload.get("labels", [])],
            last_synced_at=_now_utc(),
        )

    async def send_email(self, recipient: str, subject: str, body: str) -> GmailSendOutput:
        result = await self._gateway().execute_action(
            org_id="assistant",
            tool_name="GMAIL",
            action="GMAIL_SEND_EMAIL",
            params={"recipient": recipient, "subject": subject, "body": body},
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        payload = result.get("result") or result
        return GmailSendOutput(
            sent=bool(payload.get("sent", True)),
            recipient=recipient,
            subject=subject,
            message_id=str(payload.get("message_id") or payload.get("id") or ""),
            last_synced_at=_now_utc(),
        )


def build_runtime_gmail_connector() -> GmailConnector:
    mode = os.getenv("NIPUNA_AI_GMAIL_MODE", "fixture").lower()
    if mode == "live":
        try:
            return LiveGmailConnector()
        except Exception as exc:
            logger.warning("Falling back to fixture Gmail connector: %s", exc)
    return FixtureGmailConnector()


async def _gmail_search_tool(query: str, limit: int = 10) -> dict[str, Any]:
    connector = build_runtime_gmail_connector()
    result = await connector.search_emails(query=query, limit=limit)
    return result.model_dump(mode="json")


async def _gmail_get_tool(message_id: str) -> dict[str, Any]:
    connector = build_runtime_gmail_connector()
    result = await connector.get_email(message_id=message_id)
    return result.model_dump(mode="json")


async def _gmail_send_tool(recipient: str, subject: str, body: str) -> dict[str, Any]:
    connector = build_runtime_gmail_connector()
    result = await connector.send_email(recipient=recipient, subject=subject, body=body)
    return result.model_dump(mode="json")


def build_gmail_tools() -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            name="gmail_search_emails",
            description="Search Gmail messages by sender, subject, body, or label. Returns a structured list of matching messages with timestamps.",
            args_schema=GmailSearchInput,
            coroutine=_gmail_search_tool,
        ),
        StructuredTool.from_function(
            name="gmail_get_email",
            description="Fetch one Gmail message by exact message_id. Returns the full subject, sender, recipients, received_at timestamp, and body.",
            args_schema=GmailGetInput,
            coroutine=_gmail_get_tool,
        ),
        StructuredTool.from_function(
            name="gmail_send_email",
            description="Send or draft a Gmail message. Returns the recipient, subject, generated message_id, and sync timestamp.",
            args_schema=GmailSendInput,
            coroutine=_gmail_send_tool,
        ),
    ]
