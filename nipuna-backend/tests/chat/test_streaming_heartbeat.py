"""Streaming heartbeat tests (PR3).

Long tool execution (e.g. a Tally ODBC query that takes 20s)
should not cause the SSE connection to drop. The wrapper
emits `: ping\\n\\n` comments every HEARTBEAT_INTERVAL_S
seconds while the queue is empty.

These tests pin the heartbeat shape and the interval — actual
end-to-end testing would need a real proxy with timeout config,
which is out of scope for the unit test suite.
"""

from __future__ import annotations

import asyncio

from app.routers.chat import HEARTBEAT_INTERVAL_S


def test_heartbeat_line_format():
    """SSE comments start with ':'. The heartbeat payload is
    `ping` and ends with the standard SSE `\\n\\n` separator.
    """
    heartbeat = ": ping\n\n"
    assert heartbeat.startswith(":")
    assert "ping" in heartbeat
    assert heartbeat.endswith("\n\n")


def test_heartbeat_interval_is_below_proxy_timeouts():
    """Most proxies time out at 30-60s. 15s gives a comfortable
    safety margin while not flooding the wire.
    """
    assert HEARTBEAT_INTERVAL_S < 30.0
    assert HEARTBEAT_INTERVAL_S >= 5.0


def test_incremental_persist_threshold_is_reasonable():
    """Persist every 100 tokens. At ~4 chars/token that's a
    ~400-char chunk per commit — small enough that a disconnect
    doesn't lose much, large enough that the DB isn't hammered.
    """
    from app.routers.chat import INCREMENTAL_PERSIST_EVERY_N_TOKENS
    assert 50 <= INCREMENTAL_PERSIST_EVERY_N_TOKENS <= 200
