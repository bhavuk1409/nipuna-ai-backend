"""Per-user read-state for synthetic notifications.

Synthetic notifications (e.g. `TEAM_INVITATION` derived from a
pending `OrganizationMember` row) don't have an `Alert` row to
attach `read_at` to. We persist the read-state here instead, keyed
by `(user_id, synthetic_id)` so the same (placeholder, org) pair
maps to the same synthetic UUID across polls (see
`_SYNTHETIC_TEAM_INVITATION_NS` in `app/routers/notifications.py`).

`list_notifications` joins against this table to set the `read` flag
on each synthetic entry; `mark_notification_read` upserts a row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint("user_id", "synthetic_id", name="uq_notification_reads_user_synth"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    synthetic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Tag for which kind of synthetic this is — useful for analytics
    # and for filtering on the bell. We keep it as a free-form string
    # so we can add more synthetic kinds without migrations.
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["NotificationRead"]
