from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class VectorDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vector_documents"
    __table_args__ = (UniqueConstraint("org_id", "content_hash", name="uq_vector_documents_org_content_hash"),)

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    opensearch_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    organization: Mapped["Organization"] = relationship(back_populates="vector_documents")
