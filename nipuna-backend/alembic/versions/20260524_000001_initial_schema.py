"""initial_schema

Revision ID: 20260524_000001
Revises:
Create Date: 2026-05-24 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260524_000001"
down_revision = None
branch_labels = None
depends_on = None


organization_plan_enum = postgresql.ENUM(
    "free", "starter", "growth", "enterprise", name="organization_plan_enum", create_type=False
)
user_role_enum = postgresql.ENUM("admin", "member", "viewer", name="user_role_enum", create_type=False)
user_status_enum = postgresql.ENUM(
    "active", "pending", "suspended", name="user_status_enum", create_type=False
)
agent_status_enum = postgresql.ENUM(
    "active", "paused", "error", "deleted", name="agent_status_enum", create_type=False
)
message_role_enum = postgresql.ENUM("user", "assistant", "system", name="message_role_enum", create_type=False)
integration_status_enum = postgresql.ENUM(
    "connected", "disconnected", "error", "pending", name="integration_status_enum", create_type=False
)
alert_severity_enum = postgresql.ENUM(
    "info", "warning", "critical", name="alert_severity_enum", create_type=False
)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    bind = op.get_bind()
    organization_plan_enum.create(bind, checkfirst=True)
    user_role_enum.create(bind, checkfirst=True)
    user_status_enum.create(bind, checkfirst=True)
    agent_status_enum.create(bind, checkfirst=True)
    message_role_enum.create(bind, checkfirst=True)
    integration_status_enum.create(bind, checkfirst=True)
    alert_severity_enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("clerk_org_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan", organization_plan_enum, server_default=sa.text("'free'"), nullable=False),
        sa.Column("seats_max", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("ai_credits", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("clerk_org_id", name=op.f("uq_organizations_clerk_org_id")),
    )
    op.create_index(op.f("ix_organizations_clerk_org_id"), "organizations", ["clerk_org_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("role", user_role_enum, server_default=sa.text("'member'"), nullable=False),
        sa.Column("status", user_status_enum, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_users_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("clerk_user_id", name=op.f("uq_users_clerk_user_id")),
    )
    op.create_index(op.f("ix_users_clerk_user_id"), "users", ["clerk_user_id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_org_id"), "users", ["org_id"], unique=False)

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", agent_status_enum, server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_agents_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_agents_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index(op.f("ix_agents_created_by"), "agents", ["created_by"], unique=False)
    op.create_index(op.f("ix_agents_org_id"), "agents", ["org_id"], unique=False)
    op.create_index(op.f("ix_agents_status"), "agents", ["status"], unique=False)

    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("status", integration_status_enum, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=True),
        sa.Column("sync_health", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
        sa.Column("composio_connection_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sync_health >= 0 AND sync_health <= 100", name=op.f("ck_integrations_integration_sync_health_range")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_integrations_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
    )
    op.create_index(op.f("ix_integrations_composio_connection_id"), "integrations", ["composio_connection_id"], unique=False)
    op.create_index(op.f("ix_integrations_org_id"), "integrations", ["org_id"], unique=False)
    op.create_index(op.f("ix_integrations_provider"), "integrations", ["provider"], unique=False)
    op.create_index(op.f("ix_integrations_status"), "integrations", ["status"], unique=False)

    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(length=120), nullable=False),
        sa.Column("severity", alert_severity_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_alert_rules_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_rules")),
        sa.UniqueConstraint("org_id", "rule_id", name="uq_alert_rules_org_rule_id"),
    )
    op.create_index(op.f("ix_alert_rules_org_id"), "alert_rules", ["org_id"], unique=False)
    op.create_index(op.f("ix_alert_rules_rule_id"), "alert_rules", ["rule_id"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(length=120), nullable=False),
        sa.Column("severity", alert_severity_enum, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_alerts_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_org_id"), "alerts", ["org_id"], unique=False)
    op.create_index(op.f("ix_alerts_rule_id"), "alerts", ["rule_id"], unique=False)

    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("razorpay_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=8), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_billing_events_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_events")),
    )
    op.create_index(op.f("ix_billing_events_event_type"), "billing_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_billing_events_org_id"), "billing_events", ["org_id"], unique=False)
    op.create_index(op.f("ix_billing_events_razorpay_payment_id"), "billing_events", ["razorpay_payment_id"], unique=False)
    op.create_index(op.f("ix_billing_events_razorpay_subscription_id"), "billing_events", ["razorpay_subscription_id"], unique=False)
    op.create_index(op.f("ix_billing_events_status"), "billing_events", ["status"], unique=False)

    op.create_table(
        "workspace_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_workspace_settings_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_settings")),
        sa.UniqueConstraint("org_id", name="uq_workspace_settings_org_id"),
    )
    op.create_index(op.f("ix_workspace_settings_org_id"), "workspace_settings", ["org_id"], unique=False)

    op.create_table(
        "org_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("digest_time", sa.String(length=16), server_default=sa.text("'09:00'"), nullable=False),
        sa.Column("escalation_window", sa.Integer(), server_default=sa.text("24"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_org_preferences_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_preferences")),
        sa.UniqueConstraint("org_id", name="uq_org_preferences_org_id"),
    )
    op.create_index(op.f("ix_org_preferences_org_id"), "org_preferences", ["org_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_audit_log_org_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_org_id"), "audit_log", ["org_id"], unique=False)
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False)

    op.create_table(
        "vector_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("opensearch_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_vector_documents_org_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vector_documents")),
        sa.UniqueConstraint("org_id", "content_hash", name="uq_vector_documents_org_content_hash"),
    )
    op.create_index(op.f("ix_vector_documents_opensearch_id"), "vector_documents", ["opensearch_id"], unique=False)
    op.create_index(op.f("ix_vector_documents_org_id"), "vector_documents", ["org_id"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name=op.f("fk_conversations_agent_id_agents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_conversations_org_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_conversations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("org_id", "agent_id", "user_id", name="uq_conversations_org_agent_user"),
    )
    op.create_index(op.f("ix_conversations_agent_id"), "conversations", ["agent_id"], unique=False)
    op.create_index(op.f("ix_conversations_org_id"), "conversations", ["org_id"], unique=False)
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name=op.f("fk_messages_conversation_id_conversations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_org_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_agent_id"), table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_vector_documents_org_id"), table_name="vector_documents")
    op.drop_index(op.f("ix_vector_documents_opensearch_id"), table_name="vector_documents")
    op.drop_table("vector_documents")

    op.drop_index(op.f("ix_audit_log_user_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_org_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(op.f("ix_org_preferences_org_id"), table_name="org_preferences")
    op.drop_table("org_preferences")

    op.drop_index(op.f("ix_workspace_settings_org_id"), table_name="workspace_settings")
    op.drop_table("workspace_settings")

    op.drop_index(op.f("ix_billing_events_status"), table_name="billing_events")
    op.drop_index(op.f("ix_billing_events_razorpay_subscription_id"), table_name="billing_events")
    op.drop_index(op.f("ix_billing_events_razorpay_payment_id"), table_name="billing_events")
    op.drop_index(op.f("ix_billing_events_org_id"), table_name="billing_events")
    op.drop_index(op.f("ix_billing_events_event_type"), table_name="billing_events")
    op.drop_table("billing_events")

    op.drop_index(op.f("ix_alerts_rule_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_org_id"), table_name="alerts")
    op.drop_table("alerts")

    op.drop_index(op.f("ix_alert_rules_rule_id"), table_name="alert_rules")
    op.drop_index(op.f("ix_alert_rules_org_id"), table_name="alert_rules")
    op.drop_table("alert_rules")

    op.drop_index(op.f("ix_integrations_status"), table_name="integrations")
    op.drop_index(op.f("ix_integrations_provider"), table_name="integrations")
    op.drop_index(op.f("ix_integrations_org_id"), table_name="integrations")
    op.drop_index(op.f("ix_integrations_composio_connection_id"), table_name="integrations")
    op.drop_table("integrations")

    op.drop_index(op.f("ix_agents_status"), table_name="agents")
    op.drop_index(op.f("ix_agents_org_id"), table_name="agents")
    op.drop_index(op.f("ix_agents_created_by"), table_name="agents")
    op.drop_table("agents")

    op.drop_index(op.f("ix_users_org_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_clerk_user_id"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_organizations_clerk_org_id"), table_name="organizations")
    op.drop_table("organizations")

    bind = op.get_bind()
    alert_severity_enum.drop(bind, checkfirst=True)
    integration_status_enum.drop(bind, checkfirst=True)
    message_role_enum.drop(bind, checkfirst=True)
    agent_status_enum.drop(bind, checkfirst=True)
    user_status_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)
    organization_plan_enum.drop(bind, checkfirst=True)
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
