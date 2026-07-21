"""End-to-end eval test driver.

Runs the 10-case skeleton through the mock LLM provider and asserts
each case's must_contain / must_not_contain / tool count. With
``RUN_LIVE_LLM=1`` it would run the real pipeline; the test
runner plumbing for that is a PR5 follow-up (it needs a real
``Organization`` and ``Agent``, not just the entities conftest).

Skipped unless ``RUN_EVAL=1``.
"""

from __future__ import annotations

import pytest

from tests.eval.eval_runner import load_cases, run_case_sync


def test_skeleton_loads():
    """The YAML parses and has at least 10 cases."""
    cases = load_cases()
    assert len(cases) >= 10, f"Expected ≥10 skeleton cases, got {len(cases)}"
    # Spot-check the structure of the first case
    first = cases[0]
    assert first.id
    assert first.query
    assert first.pattern in {
        "answer_with_evidence",
        "ask_clarifying",
        "explain_missing",
        "decline",
    }


@pytest.mark.parametrize("case_index", list(range(10)))
def test_skeleton_case_passes(case_index: int):
    """Each case satisfies its must_contain / must_not_contain when
    run through the mock provider. With a real LLM, the assertions
    would be the same but the answer text would differ.
    """
    cases = load_cases()
    if case_index >= len(cases):
        pytest.skip(f"case index {case_index} not in skeleton")
    case = cases[case_index]
    result = run_case_sync(case)
    answer = result["answer"]

    for needle in case.must_contain:
        assert needle.lower() in answer.lower(), (
            f"[{case.id}] expected '{needle}' in response"
        )
    for forbidden in case.must_not_contain:
        assert forbidden.lower() not in answer.lower(), (
            f"[{case.id}] did not expect '{forbidden}' in response"
        )

    tool_count = len(result.get("tool_calls", []))
    assert case.tool_calls_min <= tool_count <= case.tool_calls_max, (
        f"[{case.id}] tool count {tool_count} out of bounds "
        f"[{case.tool_calls_min}, {case.tool_calls_max}]"
    )
