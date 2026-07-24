"""Helpers for talking to the Clerk Backend API from the team router.

Why this module exists
----------------------
The team router needs two Clerk calls to power a real invite flow:

1. *Email lookup* — given the invitee's email, does a Clerk user
   already exist? If yes, we don't need to send Clerk an email; the
   user can be surfaced in-app via a synthetic notification. If no,
   we need to call Clerk's `POST /v1/organizations/{id}/invitations`
   so Clerk sends a real email with an accept link.
2. *Org invitation* — send the email via Clerk.

Both calls use the same `Authorization: Bearer {CLERK_SECRET_KEY}`
header. We keep the helpers here (rather than inlining httpx in the
router) so the call sites stay short and the auth/header pattern is
reusable for any future Clerk call.

The helpers all return *None* on a clean "no" (email not in Clerk)
and raise `ClerkAPIError` on a real failure. Callers can therefore
distinguish "no user" from "Clerk is down" by exception handling.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Clerk Backend API base. v1 has been stable for years; bump if Clerk
# ships a v2 path and we update in lockstep.
_CLERK_API_BASE = "https://api.clerk.com/v1"

# Connect/read timeouts — short enough to fail fast in a request
# handler, long enough to ride out Clerk's occasional latency.
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ClerkAPIError(Exception):
    """Raised when a Clerk Backend API call fails for any reason other
    than "resource not found".

    Callers should treat this as a 502 to the frontend — Clerk is an
    upstream we depend on, not a user error.
    """


def _headers(secret_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
        # Clerk returns JSON by default; explicit Accept keeps the
        # response stable if their defaults shift.
        "Accept": "application/json",
    }


async def lookup_clerk_user_by_email(
    email: str,
    secret_key: str | None,
) -> str | None:
    """Return the Clerk user id for `email`, or `None` if no such user.

    Looks up via `GET /v1/users?email_address=...`. Clerk returns a
    *flat JSON array* of user objects (not the `{"data": [...]}`
    wrapper used by the other list endpoints). Empty array → `None`.
    4xx/5xx → `ClerkAPIError`.

    The endpoint matches case-insensitively, but we still lowercase
    `email` defensively at the call site.
    """
    if not secret_key:
        # No Clerk key configured (dev/sandbox). Treat as "not found"
        # so the caller falls through to writing the local placeholder
        # without trying to send an email.
        return None

    params = {"email_address": email.strip().lower()}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CLERK_API_BASE}/users",
                params=params,
                headers=_headers(secret_key),
            )
    except httpx.HTTPError as exc:
        logger.warning("Clerk user lookup transport error for %s: %s", email, exc)
        raise ClerkAPIError("Clerk user lookup failed.") from exc

    if resp.status_code == 404:
        # Some Clerk deployments return 404 for an unknown user; the
        # spec lists this as 200 + empty list, but 404 is safer to
        # treat as "no user" too.
        return None
    if not resp.is_success:
        logger.warning(
            "Clerk user lookup returned %s for %s: %s",
            resp.status_code, email, resp.text[:200],
        )
        raise ClerkAPIError(f"Clerk user lookup failed ({resp.status_code}).")

    # `GET /v1/users` (the list endpoint) returns a flat array of
    # user objects, not a `{"data": [...]}` wrapper. Empty array
    # means no user with that email.
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ClerkAPIError("Clerk user lookup returned non-JSON.") from exc
    if not isinstance(payload, list):
        # Defensive: a future Clerk change that wraps in {"data": ...}
        # would still work if we check for that shape.
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]
        else:
            raise ClerkAPIError(
                "Clerk user lookup returned an unexpected payload shape."
            )
    if not payload:
        return None
    user_id = payload[0].get("id") if isinstance(payload[0], dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise ClerkAPIError("Clerk user lookup returned a malformed payload.")
    return user_id


async def get_clerk_organization(
    clerk_org_id: str,
    secret_key: str | None,
) -> dict[str, Any] | None:
    """Fetch organization details from Clerk Backend API.

    Returns the JSON payload of the organization or None if the request failed.
    """
    if not secret_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CLERK_API_BASE}/organizations/{clerk_org_id}",
                headers=_headers(secret_key),
            )
            if resp.is_success:
                return resp.json()
    except Exception as exc:
        logger.warning("Clerk organization lookup error for %s: %s", clerk_org_id, exc)
    return None


def _to_clerk_role(role: str) -> str:
    """Map our internal role → Clerk's `org:*` role string.

    `admin` → `org:admin`. `member` / `viewer` → `org:member`
    (Clerk has no viewer concept; the membership webhook handler
    preserves the original `viewer` role on the User row when it
    sees `org:member` arrive — see `app/routers/auth.py:217`).
    """
    if role == "admin":
        return "org:admin"
    if role in ("member", "viewer"):
        return "org:member"
    # Defensive: callers validate the role against the schema, so this
    # is a programming error, not a user error.
    raise ValueError(f"Unsupported role for Clerk invitation: {role!r}")


__all__ = [
    "ClerkAPIError",
    "lookup_clerk_user_by_email",
    "get_clerk_organization",
]

