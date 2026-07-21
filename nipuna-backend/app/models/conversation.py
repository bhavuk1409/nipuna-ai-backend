from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.organization import Organization
    from app.models.user import User

message_role_enum = Enum("user", "assistant", "system", name="message_role_enum")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    # One client-side id may only map to one server-side row, so the
    # legacy-import dedup is unique per org. NULL means "no client
    # id yet" (the normal post-PR1 case).
    __table_args__ = (
        UniqueConstraint("org_id", "legacy_client_id", name="uq_conversations_org_legacy"),
        Index("ix_conversations_org_last_message", "org_id", "last_message_at"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # User-visible title. Set fire-and-forget from the first user
    # message (truncated, no LLM call) so the sidebar isn't a wall of
    # UUIDs.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The client UUID the FE used while conversations were
    # localStorage-only. Stable across the import; lets us dedup
    # against re-runs of the migration.
    legacy_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Cached for the conversation-list query (cursor-paginated by
    # (last_message_at, id)).
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="conversations")
    agent: Mapped["Agent"] = relationship(back_populates="conversations")
    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(message_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Fernet-encrypted ``content`` (BYTES). Kept nullable so the
    # backfill can populate it incrementally; readers prefer this
    # column when present. The plaintext column stays for one
    # release window as a rollback target. See
    # ``app/services/messages/cipher.py`` (PR2) for the read helper.
    content_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tool_call: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tool_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_action: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_result_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Set by the streaming consumer on disconnect (PR3). NULL on a
    # normal full-length completion. Used by /chat/history to mark
    # partial answers so the FE can render "…response cut off".
    truncated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
