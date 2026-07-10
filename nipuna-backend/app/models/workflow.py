from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, UpdatedAtMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "workflows"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="inactive", index=True)
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list)
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    n8n_workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    organization: Mapped["Organization"] = relationship(back_populates="workflows")
    creator: Mapped["User | None"] = relationship(back_populates="created_workflows")
    executions: Mapped[list["WorkflowExecution"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_executions"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(64), nullable=False, server_default="manual")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    timeline: Mapped[list[str]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list)
    input_json: Mapped[dict[str, Any]] = mapped_column(
        "input", JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    output_json: Mapped[dict[str, Any]] = mapped_column(
        "output", JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    logs: Mapped[list[str]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list)
    n8n_execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    workflow: Mapped["Workflow"] = relationship(back_populates="executions")
