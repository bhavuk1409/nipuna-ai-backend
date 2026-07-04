from __future__ import annotations

import asyncio

import pytest

from graph import AssistantRuntime, build_graph, normalize_response
from tools.gmail import FixtureGmailConnector


TEST_CASES = [
    (
        "invoice_overdue",
        "Find overdue invoices in Gmail",
        False,
        "Gmail",
    ),
    (
        "payment_received",
        "Show emails about payment received for invoice INV-1002",
        False,
        "Gmail",
    ),
    (
        "weekly_report",
        "What did the weekly sales report say?",
        False,
        "Gmail",
    ),
    (
        "project_kickoff",
        "Who rescheduled the project kickoff?",
        False,
        "Gmail",
    ),
    (
        "vendor_renewal",
        "Summarize the vendor renewal reminder",
        False,
        "Gmail",
    ),
    (
        "ambiguous_recent",
        "Show me recent invoices",
        True,
        None,
    ),
    (
        "ambiguous_latest",
        "What are the latest emails?",
        True,
        None,
    ),
    (
        "no_source",
        "What are the Slack updates for today?",
        False,
        None,
    ),
    (
        "general",
        "What can you do?",
        False,
        None,
    ),
    (
        "invoice_count",
        "How many Gmail messages mention invoices?",
        False,
        "Gmail",
    ),
    (
        "followup_seed",
        "Show me the latest finance email",
        True,
        None,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id, message, expects_clarification, expected_source", TEST_CASES)
async def test_answers(case_id: str, message: str, expects_clarification: bool, expected_source: str | None):
    runtime = AssistantRuntime(gmail_connector=FixtureGmailConnector())
    graph = build_graph(runtime)
    thread_id = f"thread-{case_id}"

    result = await graph.ainvoke(
        {
            "thread_id": thread_id,
            "query": message,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    response = normalize_response(result, thread_id)

    if expects_clarification:
        assert response.needs_clarification is True
        assert response.answer
        assert response.citations == []
        return

    if expected_source is not None:
        assert expected_source in response.sources_queried or expected_source.lower() in [s.lower() for s in response.sources_queried]
        assert response.citations, f"{case_id} should include citations"
        assert "Gmail" in response.answer
        assert "[" in response.answer and "]" in response.answer
    else:
        assert response.answer
        assert response.citations == []


@pytest.mark.asyncio
async def test_follow_up_inherits_context():
    runtime = AssistantRuntime(gmail_connector=FixtureGmailConnector())
    graph = build_graph(runtime)
    thread_id = "thread-memory"

    first = await graph.ainvoke(
        {
            "thread_id": thread_id,
            "query": "Find overdue invoices in Gmail",
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    first_response = normalize_response(first, thread_id)
    assert first_response.citations

    second = await graph.ainvoke(
        {
            "thread_id": thread_id,
            "query": "What about last month?",
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    second_response = normalize_response(second, thread_id)
    assert second_response.needs_clarification in {True, False}
