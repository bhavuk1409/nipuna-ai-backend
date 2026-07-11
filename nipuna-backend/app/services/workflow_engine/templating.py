"""Tiny template resolver for `{{ Node Title.field }}` expressions.

Matches the syntax already used in the frontend mock data, e.g.:
    "input": "{{ Extract Invoice.output }}"

`context` maps node title -> that node's produced output (any JSON value).
`.output` (or no field at all) returns the whole value; any other field
name is looked up inside the value if it's a dict.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except TypeError:
        return str(value)


def _lookup(expr: str, context: dict[str, Any]) -> Any:
    parts = [p.strip() for p in expr.split(".")]
    if not parts or not parts[0]:
        return None
    node_title = parts[0]
    rest = parts[1:]

    node_value = context.get(node_title)
    if node_value is None:
        return None

    # No further path — the whole node value.
    if not rest:
        return node_value

    # `{{ Node.output }}` or `{{ Node.output.sub.field }}` — the `.output`
    # segment is a *transparency* operator (unwraps the node's stored
    # `{"output": ..., "status": ..., ...}` envelope), not a literal field
    # name. This matches the natural-feeling frontend template:
    # `{{ Extract Invoice.output.amount }}` where the engine stored
    # `{"output": {"amount": 100}}` under "Extract Invoice".
    if rest[0] == "output":
        if isinstance(node_value, dict) and "output" in node_value:
            current: Any = node_value.get("output")
        else:
            current = node_value
        rest = rest[1:]
    else:
        current = node_value

    for segment in rest:
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


def resolve(value: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve `{{ ... }}` placeholders in strings/dicts/lists."""
    if isinstance(value, str):
        if _TEMPLATE_RE.fullmatch(value.strip()):
            # Whole string is a single placeholder — preserve the underlying type.
            expr = _TEMPLATE_RE.fullmatch(value.strip()).group(1)
            return _lookup(expr, context)

        def _sub(match: re.Match[str]) -> str:
            return _stringify(_lookup(match.group(1), context))

        return _TEMPLATE_RE.sub(_sub, value)

    if isinstance(value, dict):
        return {k: resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, context) for v in value]
    return value
