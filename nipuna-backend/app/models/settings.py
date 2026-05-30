from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class WorkspaceSettings(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "workspace_settings"
    __table_args__ = (UniqueConstraint("org_id", name="uq_workspace_settings_org_id"),)

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="workspace_settings")


class OrgPreferences(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "org_preferences"
    __table_args__ = (UniqueConstraint("org_id", name="uq_org_preferences_org_id"),)

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    digest_time: Mapped[str] = mapped_column(String(16), nullable=False, server_default="09:00")
    escalation_window: Mapped[int] = mapped_column(Integer, nullable=False, server_default="24")

    organization: Mapped["Organization"] = relationship(back_populates="org_preferences")
