"""Per-tool-call audit log.

A new, dedicated audit table for the chat pipeline. Distinct from
``AuditLog`` (which is for human-driven org events like
``workspace.deleted``) because:

  - the access pattern is "show me every tool call the AI made
    between t1 and t2 for this org" — high volume, high write rate
  - we want to index by ``(tool_name, created_at)`` for the
    per-tool-metrics query path
  - the ``params_hash`` + ``result_hash`` columns are specific to
    tool-call semantics and don't belong on the human-event log

Every ``node_execute_tools`` invocation in
``app.services.ai.langgraph_pipeline`` writes one row per call.
``record_tool_call`` in ``app.services.audit.tool_audit`` is the
helper. The row is idempotent on
``(message_id, tool_name, tool_action, params_hash)`` so retries
don't double-write.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ToolCallAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tool_call_audit"
    __table_args__ = (
        # Per-org timeline (the common analytics query).
        Index("ix_tool_call_audit_org_created", "org_id", "created_at"),
        # Per-tool timeline (the per-tool-metrics query).
        Index("ix_tool_call_audit_tool_created", "tool_name", "created_at"),
        # Per-user timeline (the "what did user X do?" query).
        Index("ix_tool_call_audit_user_created", "user_id", "created_at"),
        # Idempotency: same call, same params, same row.
        Index(
            "uq_tool_call_audit_idempotency",
            "message_id", "tool_name", "tool_action", "params_hash",
            unique=True,
            postgresql_where="message_id IS NOT NULL",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_action: Mapped[str] = mapped_column(String(128), nullable=False)
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    error_class: Mapped[str | None] = mapped_column(String(32), nullable=True)


__all__ = ["ToolCallAudit"]
