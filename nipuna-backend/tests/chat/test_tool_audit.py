"""tool_audit helper tests.

The audit row is idempotent on
``(message_id, tool_name, tool_action, params_hash)``. The hash
function must be deterministic (same input → same hash) and
key-order-insensitive (so a JSON serialisation that sorts dict
keys differently still produces the same hash).
"""

from __future__ import annotations

from app.services.audit.tool_audit import classify_error, hash_payload


def test_hash_payload_deterministic():
    a = hash_payload({"a": 1, "b": [1, 2, 3], "c": "x"})
    b = hash_payload({"a": 1, "b": [1, 2, 3], "c": "x"})
    assert a == b


def test_hash_payload_key_order_insensitive():
    a = hash_payload({"a": 1, "b": 2, "c": 3})
    b = hash_payload({"c": 3, "a": 1, "b": 2})
    assert a == b


def test_hash_payload_distinct_for_different_input():
    a = hash_payload({"a": 1})
    b = hash_payload({"a": 2})
    assert a != b


def test_classify_error_timeout_by_message():
    assert classify_error(Exception("deadline exceeded")) == "timeout"
    assert classify_error(Exception("request timed out")) == "timeout"


def test_classify_error_rate_limit():
    assert classify_error(Exception("rate limit hit")) == "rate_limit"
    assert classify_error(Exception("429 too many requests")) == "rate_limit"


def test_classify_error_auth():
    assert classify_error(Exception("401 unauthorized")) == "auth"
    assert classify_error(Exception("403 forbidden")) == "auth"


def test_classify_error_not_found():
    assert classify_error(Exception("404 not found")) == "not_found"


def test_classify_error_invalid_input():
    assert classify_error(Exception("400 bad request")) == "invalid_input"


def test_classify_error_unknown_falls_through():
    # A message that matches nothing returns "unknown" — the
    # default branch.
    assert classify_error(Exception("something went wrong")) == "unknown"
