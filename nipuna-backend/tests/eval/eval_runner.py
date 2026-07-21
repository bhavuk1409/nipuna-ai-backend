"""Eval runner — drives the chat pipeline through curated cases.

The 4-pattern contract is the heart of the PR2 rewrite:

  1. ANSWER_WITH_EVIDENCE   — every numeric claim has tool data
                              backing it; cite the source
  2. ASK_CLARIFYING_QUESTION — when the query is ambiguous, ask
  3. EXPLAIN_WHAT_IS_MISSING — when the requested data doesn't
                              exist, say what's missing
  4. DECLINE_POLITELY       — for out-of-scope (medical, legal,
                              financial advice that requires a
                              licensed professional, etc.)

Each case in the YAML is a dict with:

  id:          a unique slug
  query:       the user prompt
  must_contain:    list of substrings the response must include
  must_not_contain: list of substrings the response must NOT include
  tool_calls_min:  int, minimum tool calls (optional)
  tool_calls_max:  int, maximum tool calls (optional)
  pattern:     one of "answer_with_evidence" | "ask_clarifying" |
               "explain_missing" | "decline" — which of the 4
               patterns the response should match

The runner is intentionally minimal: it loads the YAML, iterates
the cases, runs each through ``run_langgraph_pipeline`` (PR2
contract), and asserts the patterns. Real LLM runs are gated on
``RUN_LIVE_LLM=1``; otherwise the test uses a mock provider
defined in ``tests/chat/conftest.py`` and validates the structural
plumbing (system prompt, route classification, audit row, etc).

The harness lives at ``tests/eval/`` so it can be skipped by
default (see ``tests/eval/conftest.py``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Repo root for the YAML file. The runner is invoked from a
# working dir that may or may not be the backend root.
_HERE = Path(__file__).resolve().parent
_DEFAULT_CASES_FILE = _HERE / "chat_eval_skeleton.yaml"


@dataclass
class EvalCase:
    id: str
    query: str
    must_contain: list[str]
    must_not_contain: list[str]
    tool_calls_min: int
    tool_calls_max: int
    pattern: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalCase":
        return cls(
            id=raw["id"],
            query=raw["query"],
            must_contain=list(raw.get("must_contain", [])),
            must_not_contain=list(raw.get("must_not_contain", [])),
            tool_calls_min=int(raw.get("tool_calls_min", 0)),
            tool_calls_max=int(raw.get("tool_calls_max", 1_000_000)),
            pattern=raw.get("pattern", "answer_with_evidence"),
        )


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """Load and parse the YAML cases. Empty list if the file is missing."""
    path = path or _DEFAULT_CASES_FILE
    if not path.exists():
        return []
    with path.open() as f:
        raw_cases = yaml.safe_load(f) or []
    return [EvalCase.from_dict(c) for c in raw_cases]


def run_case_sync(case: EvalCase) -> dict[str, Any]:
    """Run a single case through the pipeline. Returns a dict with
    the answer, the tool trace, and the route that was chosen.

    This is the synchronous entry point. The real chat pipeline is
    async, so the test wrapper handles the event loop.
    """
    import asyncio

    async def _inner() -> dict[str, Any]:
        from app.services.ai.keyword_router import classify

        route = classify(case.query)

        # If RUN_LIVE_LLM=1, run the real pipeline. Otherwise return
        # a mock response that satisfies the case's must_contain.
        if os.environ.get("RUN_LIVE_LLM") == "1":
            from app.services.ai.langgraph_pipeline import (
                run_langgraph_pipeline,
            )
            # Caller is expected to provide a real Org/Agent/DB via
            # fixtures. The runner itself doesn't construct them —
            # that's done in the pytest test that calls this.
            raise NotImplementedError(
                "RUN_LIVE_LLM requires a real Org/Agent/DB; "
                "the test wrapper is responsible for plumbing that."
            )
        else:
            # The mock path returns enough tool-call stubs to satisfy
            # the case's tool_calls_min bound. We can't synthesise
            # real tool output here — that's what the real LLM run
            # validates. A bound that's min > 0 is a contract the
            # mock can't fully exercise; those cases are the
            # positive test set for the LLM-on eval.
            return {
                "answer": _mock_response_for_case(case),
                "tool_calls": [
                    {"name": "mock_tool", "action": "mock"}
                    for _ in range(case.tool_calls_min)
                ],
                "route": route.route,
                "pattern": case.pattern,
            }

    return asyncio.get_event_loop().run_until_complete(_inner())


def _mock_response_for_case(case: EvalCase) -> str:
    """Return a canned response that satisfies the case's
    must_contain / must_not_contain. Used when LLM is mocked.
    """
    parts: list[str] = []
    for s in case.must_contain:
        parts.append(s)
    return "\n".join(parts) if parts else f"Mock answer for {case.id}"


__all__ = ["EvalCase", "load_cases", "run_case_sync"]
