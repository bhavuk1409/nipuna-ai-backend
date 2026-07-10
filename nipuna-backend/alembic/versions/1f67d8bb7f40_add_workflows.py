"""add workflows

Revision ID: 1f67d8bb7f40
Revises: 94237c994123
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "1f67d8bb7f40"
down_revision = "94237c994123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="inactive", nullable=False),
        sa.Column("nodes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edges", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("n8n_workflow_id", sa.String(length=255), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_workflows_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_workflows_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
    )
    op.create_index(op.f("ix_workflows_created_by"), "workflows", ["created_by"], unique=False)
    op.create_index(op.f("ix_workflows_n8n_workflow_id"), "workflows", ["n8n_workflow_id"], unique=False)
    op.create_index(op.f("ix_workflows_org_id"), "workflows", ["org_id"], unique=False)
    op.create_index(op.f("ix_workflows_status"), "workflows", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workflows_status"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_org_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_n8n_workflow_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_created_by"), table_name="workflows")
    op.drop_table("workflows")
