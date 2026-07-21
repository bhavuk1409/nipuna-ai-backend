"""SQL safety validator.

Used by the LangGraph pipeline to gate Tally / GSTN SQL queries before
they're sent to the underlying connector. The order of checks matters
(see plan §PR1 — SQL validator hardening):

    1. Strip `--` and `/* */` comments (neutralises `DR/**/OP`-style
       keyword splits).
    2. Normalise whitespace.
    3. Keyword blocklist (DROP, DELETE, ALTER, TRUNCATE, GRANT, REVOKE,
       INSERT, UPDATE, CREATE, EXEC).
    4. Single-statement check: at most one `;`, only as a trailing
       terminator.
    5. `LIMIT` enforcement: SELECT must include `LIMIT N` with
       N ≤ ``MAX_LIMIT``.
    6. Table/entity allow-list: the FROM clause must reference one of
       the Tally/GSTN entity names. We don't have a real Postgres
       schema for these (Tally's a TDL bridge) — the allow-list is a
       product-controlled list, not a database introspection.

The result is a tuple ``(is_safe, reason)`` — the caller surfaces the
reason as a tool error so the LLM can re-attempt.
"""

from __future__ import annotations

import re

# Hard-coded upper bound on LIMIT. Tally/GSTN connectors enforce their
# own caps; this is a belt-and-braces guard against the LLM asking
# for a million-row pull.
MAX_LIMIT = 1000

# Hard-coded blocklist. Order-insensitive: every check is applied
# against the uppercased + comment-stripped query.
_BLOCKED_KEYWORDS: tuple[str, ...] = (
    "DROP",
    "DELETE",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "INSERT",
    "UPDATE",
    "CREATE",
    "EXEC",
    "EXECUTE",
    "XP_",
    "SP_",
)

# Allow-list of Tally / GSTN entities the LLM is permitted to query.
# Keep this list small and product-driven; if a new entity is added
# to the Tally connector, it should be added here too.
_ALLOWED_ENTITIES: tuple[str, ...] = (
    # Tally TDL entities
    "$Ledger",
    "$Group",
    "$Voucher",
    "$StockItem",
    "$Company",
    "$CostCategory",
    "$CostCentre",
    "$Godown",
    "$Batch",
    "Ledger",
    "Group",
    "Voucher",
    "StockItem",
    "Company",
    # GSTN
    "returns",
    "invoices",
    "payments",
    "refunds",
    "taxpayer",
    "filing",
)


def _strip_comments(sql: str) -> str:
    """Remove `-- line` comments and `/* ... */` block comments."""
    # Block comments first (greedy across newlines).
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Line comments: `--` to end-of-line.
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _normalise_whitespace(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _split_statements(sql: str) -> list[str]:
    """Split on `;` and discard empty fragments. Trailing `;` is fine."""
    parts = [p.strip() for p in sql.split(";")]
    return [p for p in parts if p]


def _extract_limit(sql_upper: str) -> int | None:
    """Return the LIMIT value or None if absent / non-numeric."""
    m = re.search(r"\bLIMIT\s+(\d+)\b", sql_upper)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _has_table_allowlist_hit(sql_upper: str) -> bool:
    """True if any of the allowed entities appears in the FROM/JOIN/INTO clause.

    This is a coarse check: we look at the *whole* uppercased query
    for any of the allow-listed tokens. That's intentionally lenient
    — a strict FROM-only check would miss JOINs and CTEs.
    """
    for entity in _ALLOWED_ENTITIES:
        if entity.upper() in sql_upper:
            return True
    return False


def validate_sql(sql: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Empty / non-strings are rejected."""
    if not sql or not isinstance(sql, str):
        return False, "Empty or invalid SQL."

    stripped = _strip_comments(sql)
    cleaned = _normalise_whitespace(stripped)
    if not cleaned:
        return False, "SQL was empty after stripping comments."

    sql_upper = cleaned.upper()

    # Keyword blocklist — case-insensitive match against the comment-stripped SQL.
    for kw in _BLOCKED_KEYWORDS:
        # Word-boundary for short tokens, substring for prefix-style
        # tokens like XP_/SP_ so we still match the function call shape.
        if kw in ("XP_", "SP_"):
            pattern = rf"{re.escape(kw)}\w*"
        else:
            pattern = rf"\b{re.escape(kw)}\b"
        if re.search(pattern, sql_upper):
            return False, f"Blocked keyword: {kw}"

    # Single-statement enforcement.
    statements = _split_statements(cleaned)
    if len(statements) > 1:
        return False, "Multiple statements are not allowed."
    if len(statements) == 0:
        return False, "Empty SQL after parsing."

    statement = statements[0]
    statement_upper = statement.upper()

    # Must be a SELECT (read-only). We deliberately do not allow
    # INSERT/UPDATE/DELETE — the keyword blocklist catches those, but
    # this is the second guard.
    if not statement_upper.startswith("SELECT") and not statement_upper.startswith("WITH"):
        return False, "Only SELECT/WITH (read-only) queries are allowed."

    # LIMIT enforcement.
    limit_value = _extract_limit(statement_upper)
    if limit_value is None:
        return False, "Queries must include an explicit LIMIT clause."
    if limit_value > MAX_LIMIT:
        return False, f"LIMIT must be <= {MAX_LIMIT}; got {limit_value}."

    # Table / entity allow-list.
    if not _has_table_allowlist_hit(statement_upper):
        return False, "FROM clause does not reference any allowed entity."

    return True, ""


__all__ = ["MAX_LIMIT", "validate_sql"]
