from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.audit import AuditLog
    from app.models.organization import Organization
    from app.models.organization_member import OrganizationMember
    from app.models.workflow import Workflow


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    clerk_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Best-effort, debounced touch on every team list call by the current
    # user. Nullable so existing rows don't need a backfill.
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Per-user "currently selected org" pointer. Drives `get_current_org`.
    # Nullable so the migration can backfill and the dep can lazy-default
    # on first request. ON DELETE SET NULL keeps the dep safe if the
    # active org is ever deleted out from under the user.
    active_org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Many-to-many with Organization through `OrganizationMember`. The
    # `delete-orphan` cascade drops the user's memberships when the
    # user is deleted; the FK `ON DELETE CASCADE` on
    # `organization_members.user_id` enforces the same at the DB
    # level.
    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    created_agents: Mapped[list["Agent"]] = relationship(back_populates="creator")
    created_workflows: Mapped[list["Workflow"]] = relationship(back_populates="creator")
    conversations = relationship("Conversation", back_populates="user")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
