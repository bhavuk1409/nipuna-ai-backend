"""Strip legacy User() constructor kwargs (status, role, org_id) from test files.

The previous regex pass missed some patterns. This is more thorough:
- Any line in tests/ that has User( and then later includes status=/role=/org_id=
  We remove those lines (only if they're inside a User() call).
- We also strip standalone lines that are only `status="active"`, `role="admin"`, etc.

Approach: find every User( block, scan its lines, drop any with the legacy
kwarg names, then reassemble the call.
"""
import re
from pathlib import Path

LEGACY_KEYS = {"status", "role", "org_id"}

# Files we need to fix
files = [
    Path("tests/test_mcp_gateway.py"),
    Path("tests/test_onboarding.py"),
    Path("tests/test_team.py"),
    Path("tests/test_multi_org.py"),
    Path("tests/test_notifications.py"),
    Path("tests/test_auth.py"),
    Path("tests/test_chat.py"),
    Path("tests/test_settings.py"),
    Path("tests/test_agent.py"),
]


def find_matching_paren(text, start):
    """Given the index of an opening `(`, return the index of the matching
    `)`. Tracks nesting and ignores parens inside strings."""
    depth = 0
    i = start
    in_str = None  # current string delimiter or None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ('"', "'"):
                in_str = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def find_user_calls(text):
    """Yield (start_idx_of_call, end_idx_of_call) for each User(...) call."""
    pattern = re.compile(r"\bUser\(")
    for m in pattern.finditer(text):
        open_paren = m.end() - 1
        close_paren = find_matching_paren(text, open_paren)
        if close_paren == -1:
            continue
        yield open_paren, close_paren


def strip_legacy_kwargs(call_body):
    """Remove lines that contain only a legacy kwarg assignment."""
    lines = call_body.splitlines(keepends=True)
    out = []
    for line in lines:
        stripped = line.strip()
        # Match lines like:    status="active",      or  role="admin",
        # also     status="active"   (no trailing comma)
        if any(
            re.match(rf"^\s*{key}\s*=\s*['\"][^'\"]*['\"]\s*,?\s*$", line)
            for key in LEGACY_KEYS
        ):
            continue
        out.append(line)
    return "".join(out)


def process(text):
    # Process all User() calls — need to do it from the end backwards to keep
    # offsets valid.
    calls = sorted(find_user_calls(text), key=lambda c: c[0], reverse=True)
    for start, end in calls:
        call_body = text[start + 1 : end]  # content between the parens
        new_body = strip_legacy_kwargs(call_body)
        text = text[: start + 1] + new_body + text[end:]
    return text


def main():
    for f in files:
        if not f.exists():
            print(f"skip {f} (not found)")
            continue
        original = f.read_text()
        new = process(original)
        if new != original:
            f.write_text(new)
            print(f"updated {f}")
        else:
            print(f"unchanged {f}")


if __name__ == "__main__":
    main()
