"""SQL validator tests.

The validator gates every tool that might run SQL (Tally, GSTN,
future). 6-step pipeline: strip comments, normalise whitespace,
keyword blocklist, single-statement check, LIMIT clause, entity
allow-list. Each step has at least one negative test.
"""

from __future__ import annotations

import pytest

from app.services.ai.sql_validator import MAX_LIMIT, validate_sql


def test_simple_select_passes():
    ok, err = validate_sql("SELECT * FROM $Ledger LIMIT 10")
    assert ok, err


def test_dollar_bracket_syntax_passes():
    ok, err = validate_sql("SELECT $Name FROM $Ledger LIMIT 5")
    assert ok, err


def test_drop_blocked():
    ok, err = validate_sql("DROP TABLE foo")
    assert not ok
    assert "DROP" in err.upper() or "blocked" in err.lower()


def test_delete_blocked():
    ok, err = validate_sql("DELETE FROM $Ledger WHERE 1=1")
    assert not ok


def test_insert_blocked():
    ok, err = validate_sql("INSERT INTO $Ledger VALUES (1)")
    assert not ok


def test_update_blocked():
    ok, err = validate_sql("UPDATE $Ledger SET $Name='x'")
    assert not ok


def test_alter_blocked():
    ok, err = validate_sql("ALTER TABLE $Ledger ADD COLUMN x INT")
    assert not ok


def test_multi_statement_blocked():
    ok, err = validate_sql("SELECT 1; SELECT 2")
    assert not ok
    assert "multiple" in err.lower() or "single" in err.lower()


def test_limit_required():
    ok, err = validate_sql("SELECT * FROM $Ledger")
    assert not ok
    assert "limit" in err.lower()


def test_limit_cap_enforced():
    ok, err = validate_sql(f"SELECT * FROM $Ledger LIMIT {MAX_LIMIT + 1}")
    assert not ok


def test_obfuscated_keyword_blocked():
    # `DR/**/OP` should be caught by the comment-strip step
    ok, err = validate_sql("DR/**/OP TABLE foo")
    assert not ok


def test_unknown_entity_blocked():
    ok, err = validate_sql("SELECT * FROM secret_table LIMIT 10")
    assert not ok
    assert "allow" in err.lower() or "entity" in err.lower()


def test_with_clause_passes():
    ok, err = validate_sql(
        "WITH x AS (SELECT * FROM $Ledger LIMIT 5) SELECT * FROM x LIMIT 5"
    )
    assert ok, err


@pytest.mark.parametrize("blocked", [
    "DROP", "DELETE", "ALTER", "TRUNCATE", "GRANT",
    "REVOKE", "INSERT", "UPDATE", "CREATE", "EXEC",
])
def test_all_blocked_keywords_caught(blocked):
    ok, err = validate_sql(f"{blocked} something LIMIT 1")
    assert not ok, f"{blocked} was not blocked"
