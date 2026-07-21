"""Per-user, per-org structured memory.

Memories are key-value facts the AI extracts from conversations:
"user is a CFO at Acme", "user prefers INR", "user works with Tally
for accounting", "user said their fiscal year ends March 31". After
extraction (PR4 — gpt-4o-mini) the top-N memories are injected into
the system prompt under ``KNOWN FACTS ABOUT THIS USER``.

The ``value_encrypted`` column stores the Fernet-encrypted bytes
(see ``app/utils/encryption.py``) so a database dump doesn't leak
personal facts. The legacy ``value`` column is kept as a plaintext
mirror for one release window so a rollback doesn't lose data;
``app/services/memory/manager.py`` prefers the encrypted column when
present and falls back to the legacy one. A follow-up migration in
PR2 drops ``value`` once we have full encryption coverage.

``(user_id, key)`` is unique so the upsert is a no-op when a fact
is re-extracted. Soft-delete via ``archived`` so we can keep the
provenance row but exclude it from the injected block.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin


class UserMemory(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        # The extractor can archive-and-reinsert on contradiction.
        # The uniqueness invariant is on the *active* rows only —
        # the partial index below expresses that. A plain
        # UniqueConstraint would block the reinsert.
        Index(
            "uq_user_memories_user_key_active",
            "user_id", "key",
            unique=True,
            postgresql_where=text("archived IS FALSE"),
        ),
        Index("ix_user_memories_user_org", "user_id", "org_id"),
        Index("ix_user_memories_user_active", "user_id", "archived"),
        # Confidence must be in [0, 100] — values are stored as
        # percentages for human readability in psql.
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_user_memories_confidence_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain-text mirror. Kept for one release window as a rollback
    # target — readers (app/services/memory/manager.py) prefer the
    # encrypted column when present.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Fernet-encrypted ``value``. Nullable during the backfill; the
    # application writes both columns on insert once PR2 ships.
    value_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    confidence: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="70"
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )


__all__ = ["UserMemory"]
