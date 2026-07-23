"""OrganizationMember — the many-to-many join between users and organizations.

This replaces the old `User.org_id` scalar: a user can now belong to many
organizations at once, with a per-org `role` and `status`. The user's
*active* org is tracked separately on `User.active_org_id` (a single FK)
so we have a cheap "current workspace" pointer for every request.

Pending invites are first-class rows: when an admin invites an email
that has no Clerk account yet, we insert an `OrganizationMember` with
`user_id = NULL`, `email = <invitee>`, `status = "pending"`. The row
gets bound to a real `User` when the invitee signs in (via
`organizationMembership.created` webhook, or the dev bypass, or the
synthetic TEAM_INVITATION accept flow).

The `clerk_user_id="invited_*"` placeholder pattern from the old model
is gone; the membership row itself is the placeholder.

Indexes
-------
- `org_id`              — "list members of org X"
- `(user_id, status)`   — "list active memberships of user X" (the dep's
                          hot path on every request)
- `email`               — "find pending invites for this email" (the
                          synthetic-notification path)
- `(user_id, org_id)`   UNIQUE — the invariant we never want broken

We also add a partial unique index on `(org_id, lower(email)) WHERE
user_id IS NULL` so two admins can't invite the same email to the
same org before the invitee signs up. The full unique constraint
allows `user_id IS NULL` rows (they bypass it because NULL ≠ NULL in
Postgres), so we need the explicit partial index for that case.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING


from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User

# Per-membership role. Same 3 values as the old `User.role` enum.
# "owner" is still a *display* role derived at read time (oldest active
# admin per org), not a stored value.
member_role_enum = Enum(
    "admin", "member", "viewer",
    name="organization_member_role_enum",
)

# Per-membership status. "declined" was added in 94237c994123 to the
# old user_status_enum; we keep the same set on the membership level.
member_status_enum = Enum(
    "active", "pending", "suspended", "declined",
    name="organization_member_status_enum",
)


class OrganizationMember(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "organization_members"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Lowercased at the application layer; the index is on the
    # lower(email) expression so case-insensitive lookups are cheap.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    role: Mapped[str] = mapped_column(
        member_role_enum,
        nullable=False,
        server_default="member",
    )
    status: Mapped[str] = mapped_column(
        member_status_enum,
        nullable=False,
        server_default="active",
    )

    # ── Invite token fields ──────────────────────────────────────────────────
    # invite_token: a short secrets.token_urlsafe(32) string generated when
    # the admin creates an invite. The frontend shows this as the "invite code"
    # the new user enters during onboarding. NULL for memberships created by
    # the Clerk webhook (i.e., admin-to-self or accepted Clerk invitations).
    invite_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    # Optional expiry for the token (default: no expiry).
    invite_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Who generated this invite (for audit / display).
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User | None"] = relationship(back_populates="memberships", foreign_keys="[OrganizationMember.user_id]")

    __table_args__ = (
        # A user can only have one membership per org. (The `user_id IS
        # NULL` case — pending invites before sign-in — is *not* covered
        # by this; we use a partial unique index for that, see below.)
        UniqueConstraint(
            "user_id", "org_id",
            name="uq_organization_members_user_org",
        ),
        # The "oldest active admin" / "list my active memberships"
        # queries hit (user_id, status) together — the dep reads this
        # on every request.
        Index(
            "ix_organization_members_user_id_status",
            "user_id", "status",
        ),
        # Case-insensitive email lookup. Postgres can use the index
        # for `lower(email) = lower(:p)` predicates.
        Index(
            "ix_organization_members_lower_email",
            text("lower(email)"),
        ),
        # Two admins can't both invite the same email to the same org
        # before that email is bound to a User. NULLS are not distinct
        # in normal unique indexes, so we need an explicit partial
        # unique index that scopes the constraint to `user_id IS NULL`
        # rows.
        Index(
            "uq_organization_members_pending_email",
            "org_id", text("lower(email)"),
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        # Belt-and-braces: an active membership must have either a
        # user_id or an email. Pending invites always have email and
        # *may* have user_id; active rows are guaranteed to have
        # user_id (the webhook handler enforces this for Clerk rows,
        # and the dev bypass / onboarding create both).
        CheckConstraint(
            "user_id IS NOT NULL OR email IS NOT NULL",
            name="ck_organization_members_has_identity",
        ),
    )


__all__ = ["OrganizationMember", "member_role_enum", "member_status_enum"]
