from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization

integration_status_enum = Enum("connected", "disconnected", "error", "pending", name="integration_status_enum")


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (CheckConstraint("sync_health >= 0 AND sync_health <= 100", name="integration_sync_health_range"),)

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(integration_status_enum, nullable=False, server_default="pending", index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_health: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    composio_connection_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    organization: Mapped["Organization"] = relationship(back_populates="integrations")
