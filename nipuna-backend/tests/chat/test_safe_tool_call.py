"""safe_tool_call + read-only classification tests.

The safe-tool-call wrapper is the centralised gate for every
tool that runs SQL or routes through Tally. These tests pin the
behaviour so a future refactor doesn't silently regress.
"""

from __future__ import annotations

from app.services.ai.safe_tool_call import (
    READ_ONLY_TOOLS,
    SQL_TOOLS,
    is_read_only,
    requires_sql_validation,
    safe_sql_params,
)


def test_sql_tools_have_at_least_tally():
    # Anything that ends up running Tally/GSTN SQL must be in the
    # SQL_TOOLS dict; the gate won't run otherwise.
    assert "TALLY" in SQL_TOOLS
    assert "query-database" in SQL_TOOLS["TALLY"]


def test_safe_sql_params_returns_cleaned_on_valid():
    cleaned, err = safe_sql_params(
        "TALLY", "query-database",
        {"sql": "SELECT * FROM $Ledger LIMIT 10"},
    )
    assert err is None
    assert cleaned == {"sql": "SELECT * FROM $Ledger LIMIT 10"}


def test_safe_sql_params_blocks_unsafe():
    # DROP is in the keyword blocklist; validator should reject.
    _, err = safe_sql_params(
        "TALLY", "query-database",
        {"sql": "DROP TABLE foo"},
    )
    assert err is not None
    assert "blocked" in err.lower() or "DROP" in err.upper()


def test_safe_sql_params_passes_through_non_sql_tool():
    # A tool that doesn't require SQL validation should pass through
    # without any checks.
    cleaned, err = safe_sql_params("GMAIL", "search_emails", {"q": "test"})
    assert err is None
    assert cleaned == {"q": "test"}


def test_is_read_only_known_pairs():
    # Every (provider, action) in READ_ONLY_TOOLS classifies as
    # read-only.
    for provider, actions in READ_ONLY_TOOLS.items():
        for action in actions:
            assert is_read_only(provider, action), (
                f"({provider}, {action}) is in READ_ONLY_TOOLS but not classified as such"
            )


def test_is_read_only_unknown_action_is_false():
    # A read-only provider with an action that isn't in the
    # allow-list is NOT classified as read-only.
    assert not is_read_only("GMAIL", "send_email")


def test_requires_sql_validation_known_pairs():
    # Every (provider, action) in SQL_TOOLS requires SQL validation.
    for provider, actions in SQL_TOOLS.items():
        for action in actions:
            assert requires_sql_validation(provider, action), (
                f"({provider}, {action}) is in SQL_TOOLS but not gated"
            )
