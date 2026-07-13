"""Schemas for the multi-organization switcher and `/auth/me` profile.

The `/auth/me` endpoint returns a `UserProfileResponse` with the
user's `active_org_id` and the full list of their memberships. The
`/auth/switch-org` endpoint takes a `SwitchOrgRequest` and returns a
`SwitchOrgResponse` confirming the new active org.

All schemas are read-only payloads on the wire; the only mutation
allowed via these endpoints is `active_org_id`, which is
intentionally DB-driven and not Clerk-driven.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


MemberRole = Literal["admin", "member", "viewer"]
MemberStatus = Literal["active", "pending", "suspended", "declined"]


class MembershipSummary(BaseModel):
    """One row in the user's membership list.

    `id` is the `OrganizationMember.id` — the frontend can use this
    for React keys and to drive the "leave workspace" / role-change
    flows (post-Step-6). The frontend never sends this back; it sends
    `org_id` for switch-org.
    """

    id: UUID
    org_id: UUID
    org_name: str
    role: MemberRole
    status: MemberStatus
    is_active: bool
    created_at: datetime
    clerk_org_id: str | None = None
    logo_url: str | None = None



class UserProfileResponse(BaseModel):
    """Shape returned by `GET /api/v1/auth/me`."""

    id: UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    # Per-user active-org pointer. Always present once the user
    # has at least one active membership.
    active_org_id: UUID | None = None
    # List of every membership the user has across all orgs.
    memberships: list[MembershipSummary] = Field(default_factory=list)
    # Role in the active organization
    role: str = "member"
    logo_url: str | None = None




class SwitchOrgRequest(BaseModel):
    org_id: UUID


class SwitchOrgResponse(BaseModel):
    active_org_id: UUID
    role: MemberRole
    status: MemberStatus


class UploadLogoRequest(BaseModel):
    logo_data: str
    # If provided, upload logo for this specific org (not the active one).
    # The caller must be an admin of the target org.
    org_id: UUID | None = None


class RegisterWorkspaceRequest(BaseModel):
    """Sent by the frontend immediately after Clerk's `createOrganization`
    to pre-register the org in our DB before redirecting to /dashboard.
    This ensures the membership row exists when the page reloads.
    """

    clerk_org_id: str
    name: str


__all__ = [
    "MemberRole",
    "MemberStatus",
    "MembershipSummary",
    "UserProfileResponse",
    "SwitchOrgRequest",
    "SwitchOrgResponse",
    "UploadLogoRequest",
    "RegisterWorkspaceRequest",
]
