from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.audit import AuditLog
    from app.models.conversation import Conversation
    from app.models.organization import Organization
    from app.models.workflow import Workflow

user_role_enum = Enum("admin", "member", "viewer", name="user_role_enum")
user_status_enum = Enum("active", "pending", "suspended", "declined", name="user_status_enum")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    clerk_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False, server_default="member")
    status: Mapped[str] = mapped_column(user_status_enum, nullable=False, server_default="pending")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="users")
    created_agents: Mapped[list["Agent"]] = relationship(back_populates="creator")
    created_workflows: Mapped[list["Workflow"]] = relationship(back_populates="creator")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
