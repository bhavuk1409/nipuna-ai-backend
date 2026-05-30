from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class BillingEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_events"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="INR")
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    organization: Mapped["Organization"] = relationship(back_populates="billing_events")
