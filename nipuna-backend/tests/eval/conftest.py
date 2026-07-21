"""Eval harness — configures pytest to skip eval tests by default.

Eval tests are gated on ``RUN_EVAL=1`` so the default ``pytest
tests/`` stays fast (a few seconds) and the expensive LLM-backed
runs only happen on the nightly cron or when explicitly requested
on PR with the ``run-eval`` label.

The test cases themselves live in ``tests/eval/chat_eval_skeleton.yaml``
and are loaded by ``eval_runner.py``. They are not Python modules
— ``collect_ignore_glob`` here keeps pytest from trying to import
the YAML.
"""

from __future__ import annotations

import os

import pytest

# Treat any .yaml / .yml under tests/eval as data, not a test
# module. Without this, pytest tries to collect the YAML and fails.
collect_ignore_glob = ["*.yaml", "*.yml"]


def pytest_collection_modifyitems(config, items):
    """Skip every test collected under this directory unless
    ``RUN_EVAL=1`` is set. Runs at collection time so the
    ``--collect-only`` view shows the skips too.
    """
    if os.environ.get("RUN_EVAL") == "1":
        return
    here = os.path.dirname(__file__)
    skip = pytest.mark.skip(
        reason="RUN_EVAL not set; eval tests are skipped by default"
    )
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(skip)
