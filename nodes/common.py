from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timezone

from schemas import Citation, RetrievedContextItem


AMBIGUOUS_TIME_WORDS = {
    "recent",
    "latest",
    "new",
    "newest",
    "recently",
    "last",
    "past",
    "today",
}

SOURCE_KEYWORDS = {
    "gmail": {"gmail", "email", "emails", "mail", "inbox", "message", "messages", "draft", "sender", "subject"},
    "slack": {"slack", "channel", "dm", "workspace"},
    "github": {"github", "repo", "repository", "issue", "pull request", "pr"},
    "jira": {"jira", "ticket", "sprint", "story", "bug"},
    "accounting": {"invoice", "invoices", "overdue", "payment", "payments", "receivable", "payable", "ledger", "expense", "revenue", "books"},
    "crm": {"customer", "lead", "pipeline", "deal", "opportunity"},
}

BUSINESS_HINTS = {
    "invoice",
    "invoices",
    "payment",
    "payments",
    "report",
    "reports",
    "sales",
    "finance",
    "kickoff",
    "renewal",
    "vendor",
    "customer",
    "budget",
    "ops",
    "operations",
}

ACTION_KEYWORDS = {
    "send": {"send", "draft", "compose", "post", "message", "reply", "create"},
    "retrieve": {"find", "show", "list", "get", "fetch", "which", "how many"},
}


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip())


def query_tokens(query: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", query.lower()) if token}


def detect_sources(query: str) -> list[str]:
    q = query.lower()
    matches: list[str] = []
    for source, keywords in SOURCE_KEYWORDS.items():
        if any(keyword in q for keyword in keywords):
            matches.append(source)
    if not matches and any(hint in q for hint in BUSINESS_HINTS):
        matches.append("gmail")
    return matches


def looks_business_related(query: str) -> bool:
    q = query.lower()
    return any(hint in q for hint in BUSINESS_HINTS) or any(source_kw in q for kws in SOURCE_KEYWORDS.values() for source_kw in kws)


def detect_action(query: str) -> str | None:
    q = query.lower()
    if any(word in q for word in ACTION_KEYWORDS["send"]) and "email" in q:
        return "send_email"
    if any(word in q for word in ACTION_KEYWORDS["retrieve"]):
        return "search_emails"
    return None


def is_temporally_ambiguous(query: str) -> bool:
    q = query.lower()
    has_ambiguous = any(word in q for word in AMBIGUOUS_TIME_WORDS)
    has_explicit_window = any(token in q for token in ["today", "yesterday", "this week", "this month", "last week", "last month", "in the last", "between"])
    return has_ambiguous and not has_explicit_window


def format_freshness(timestamp: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - timestamp.astimezone(timezone.utc)
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:
        return f"as of {minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"as of {hours} hours ago"
    days = hours // 24
    return f"as of {days} days ago"


def format_timestamp(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat()


def make_citation(item: RetrievedContextItem, evidence: str | None = None) -> Citation:
    return Citation(
        source_name=item.source_name,
        source_id=item.source_id,
        source_type=item.source_type,
        timestamp=item.timestamp,
        freshness=format_freshness(item.timestamp),
        evidence=evidence or item.title,
    )


def lexical_support_score(text: str, item: RetrievedContextItem) -> float:
    text_tokens = query_tokens(text)
    body_tokens = query_tokens(f"{item.title} {item.body}")
    if not text_tokens:
        return 0.0
    overlap = len(text_tokens & body_tokens)
    return overlap / max(len(text_tokens), 1)


def claim_supported(claim: str, context: list[RetrievedContextItem]) -> tuple[bool, list[RetrievedContextItem]]:
    supporting = []
    for item in context:
        if lexical_support_score(claim, item) >= 0.15:
            supporting.append(item)
    return bool(supporting), supporting


def summarize_context(context: list[RetrievedContextItem]) -> str:
    lines: list[str] = []
    for item in context:
        lines.append(
            f"- {item.source_name}: {item.title} ({format_timestamp(item.timestamp)}) :: {item.body}"
        )
    return "\n".join(lines)
