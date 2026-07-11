"""Safe structured condition evaluation for IF nodes.

Deliberately does NOT use eval()/exec(). An IF node's `data.parameters` is
expected to look like:

    {"left": "{{ Finance Agent.output.amount }}", "operator": ">", "right": 10000}

`left`/`right` are resolved through the templating engine first, then
compared. Numeric-looking strings are coerced to numbers for comparison.
"""

from __future__ import annotations

from typing import Any

_OPERATORS = {
    ">": lambda a, b: _num(a) > _num(b),
    "<": lambda a, b: _num(a) < _num(b),
    ">=": lambda a, b: _num(a) >= _num(b),
    "<=": lambda a, b: _num(a) <= _num(b),
    "==": lambda a, b: _num(a, allow_str=True) == _num(b, allow_str=True),
    "!=": lambda a, b: _num(a, allow_str=True) != _num(b, allow_str=True),
    "contains": lambda a, b: str(b) in str(a),
    "not_contains": lambda a, b: str(b) not in str(a),
}


def _num(value: Any, allow_str: bool = False) -> Any:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return value if allow_str else 0
    return value if allow_str else 0


def evaluate(parameters: dict[str, Any]) -> bool:
    operator = str(parameters.get("operator", ">")).lower()
    left = parameters.get("left")
    right = parameters.get("right")
    fn = _OPERATORS.get(operator)
    if fn is None:
        return False
    try:
        return bool(fn(left, right))
    except (TypeError, ValueError):
        return False
