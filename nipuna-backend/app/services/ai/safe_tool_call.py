"""Per-tool safety wrapper.

Every tool call that might run SQL goes through `safe_tool_call` so
the SQL validator, query timeout, and audit trail apply uniformly.
Today only Tally + GSTN emit SQL; future tools (e.g. a SQL agent)
should reuse this wrapper too. See `app/services/ai/sql_validator.py`
for the actual SQL checks.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.ai.sql_validator import validate_sql

logger = logging.getLogger(__name__)

# Tools that take a `sql` parameter and must be validated.
SQL_TOOLS: dict[str, set[str]] = {
    "TALLY": {"query-database"},
    "GSTN": {"query"},
}

# Tools whose results are safe to cache (read-only). Writes must never
# be cached or the same write will be replayed on retry.
READ_ONLY_TOOLS: dict[str, set[str]] = {
    "TALLY": {"query-database", "list-companies", "list-ledgers", "get-outstanding"},
    "GSTN": {"query", "list-returns"},
    "GMAIL": {"search_emails", "get_message"},
    "STRIPE": {"list_invoices", "list_customers", "list_payments"},
    "HUBSPOT": {"list_contacts", "list_deals"},
    "SLACK": {"list_channels", "list_messages"},
    "GOOGLE_SHEETS": {"read", "list_tabs"},
}


def requires_sql_validation(provider: str, action: str) -> bool:
    """True if a (provider, action) pair is expected to run SQL and must be validated."""
    p = (provider or "").upper()
    a = action or ""
    return a in SQL_TOOLS.get(p, set())


def is_read_only(provider: str, action: str) -> bool:
    """True if a (provider, action) pair is read-only and safe to cache."""
    p = (provider or "").upper()
    a = action or ""
    return a in READ_ONLY_TOOLS.get(p, set())


def safe_sql_params(provider: str, action: str, params: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Validate SQL params for a tool call. Returns (cleaned_params, error_message).

    On success: returns the original params and `None`.
    On failure: returns the original params and a human-readable reason
    that the caller can surface to the LLM as a tool error.
    """
    if not requires_sql_validation(provider, action):
        return params, None

    sql = params.get("sql") or params.get("query") or ""
    if not sql:
        return params, "Tool expected a SQL query but none was provided."

    valid, reason = validate_sql(sql)
    if not valid:
        logger.warning(
            "Blocked unsafe SQL for provider=%s action=%s reason=%s",
            provider, action, reason,
        )
        return params, f"SQL blocked by security validator: {reason}"
    return params, None


class ToolCallTimer:
    """Tiny context manager for measuring tool latency."""

    def __init__(self) -> None:
        self.elapsed_ms: int = 0

    def __enter__(self) -> "ToolCallTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)


__all__ = [
    "READ_ONLY_TOOLS",
    "SQL_TOOLS",
    "ToolCallTimer",
    "is_read_only",
    "requires_sql_validation",
    "safe_sql_params",
]
