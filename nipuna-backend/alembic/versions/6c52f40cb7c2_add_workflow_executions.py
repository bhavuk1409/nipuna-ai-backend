"""add workflow executions

Revision ID: 6c52f40cb7c2
Revises: 1f67d8bb7f40
Create Date: 2026-07-10 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "6c52f40cb7c2"
down_revision = "1f67d8bb7f40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=64), server_default="manual", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("logs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("n8n_execution_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_workflow_executions_org_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], name=op.f("fk_workflow_executions_workflow_id_workflows"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
    )
    op.create_index(op.f("ix_workflow_executions_n8n_execution_id"), "workflow_executions", ["n8n_execution_id"], unique=False)
    op.create_index(op.f("ix_workflow_executions_org_id"), "workflow_executions", ["org_id"], unique=False)
    op.create_index(op.f("ix_workflow_executions_status"), "workflow_executions", ["status"], unique=False)
    op.create_index(op.f("ix_workflow_executions_workflow_id"), "workflow_executions", ["workflow_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_executions_workflow_id"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_status"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_org_id"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_n8n_execution_id"), table_name="workflow_executions")
    op.drop_table("workflow_executions")
