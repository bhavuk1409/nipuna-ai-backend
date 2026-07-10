from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.alert import Alert, AlertRule
    from app.models.audit import AuditLog
    from app.models.billing import BillingEvent
    from app.models.conversation import Conversation
    from app.models.integration import Integration
    from app.models.settings import OrgPreferences, WorkspaceSettings
    from app.models.user import User
    from app.models.vector_doc import VectorDocument
    from app.models.workflow import Workflow

organization_plan_enum = Enum(
    "free",
    "starter",
    "growth",
    "enterprise",
    name="organization_plan_enum",
)


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    clerk_org_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(organization_plan_enum, nullable=False, server_default="free")
    seats_max: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    ai_credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    agents: Mapped[list["Agent"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    integrations: Mapped[list["Integration"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    alert_rules: Mapped[list["AlertRule"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    billing_events: Mapped[list["BillingEvent"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    workspace_settings: Mapped["WorkspaceSettings | None"] = relationship(back_populates="organization", cascade="all, delete-orphan", uselist=False)
    org_preferences: Mapped["OrgPreferences | None"] = relationship(back_populates="organization", cascade="all, delete-orphan", uselist=False)
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    vector_documents: Mapped[list["VectorDocument"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
