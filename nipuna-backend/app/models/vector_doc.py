from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class VectorDocument(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "vector_documents"
    __table_args__ = (UniqueConstraint("org_id", "content_hash", name="uq_vector_documents_org_content_hash"),)

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Legacy opensearch id; kept so the cutover doesn't break the
    # dev path. New code goes through pgvector.
    opensearch_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Free-form metadata the FE shows in the knowledge-base panel
    # (e.g. original filename, MIME, size).
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Last successful embedding timestamp. Used by /knowledge/status
    # so the FE can show "last indexed at X" instead of a wall of
    # created_at rows.
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="vector_documents")
