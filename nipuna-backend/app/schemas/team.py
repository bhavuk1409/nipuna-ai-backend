"""Pydantic schemas for the team router.

Owner role semantics: the backend stores `role ∈ {admin, member, viewer}`.
The frontend treats the role as a 4-value enum, where "owner" is a
*display* role. We resolve owner at read time as the admin in the org
with the lowest `created_at` (tie-break: lowest `id`).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


_INVITABLE_ROLES = ("admin", "member", "viewer")

# Lightweight email regex — full RFC 5322 is overkill for a free-text field.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class TeamMemberResponse(BaseModel):
    id: UUID
    name: str
    email: str
    role: Literal["owner", "admin", "member", "viewer"]
    status: str
    last_active: datetime | None
    is_you: bool


class PendingInviteResponse(BaseModel):
    id: UUID
    email: str
    role: Literal["admin", "member", "viewer"]
    sent_at: datetime
    invited_by: str
    dev_share_link: str | None = None
    delivery_note: str | None = None
    invite_code: str | None = None
    expires_at: datetime | None = None


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: Literal["admin", "member", "viewer"] = "member"
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("email")
    @classmethod
    def _normalise_and_validate_email(cls, v: str) -> str:
        normalised = v.strip().lower()
        if not _EMAIL_RE.match(normalised):
            raise ValueError("Enter a valid email address.")
        return normalised


class ChangeRoleRequest(BaseModel):
    role: Literal["admin", "member", "viewer"]


class AcceptInviteRequest(BaseModel):
    """Body for `POST /api/v1/team/accept`. `org_id` is the workspace
    the current user is accepting an invitation to."""

    org_id: UUID


class TeamListResponse(BaseModel):
    members: list[TeamMemberResponse]
    pending_invites: list[PendingInviteResponse]
    owner_id: UUID | None = None


__all__ = [
    "TeamMemberResponse",
    "PendingInviteResponse",
    "InviteMemberRequest",
    "ChangeRoleRequest",
    "AcceptInviteRequest",
    "TeamListResponse",
    "_INVITABLE_ROLES",
]
