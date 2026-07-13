"""organization_membership

Add the `organization_members` join table, backfill it from the old
`User.org_id` column, and add a new `User.active_org_id` pointer that
drives `get_current_org`.

The original `User.org_id` / `User.role` / `User.status` columns stay in
place during this migration — they're a load-bearing shortcut for the
dev bypass, the onboarding route, and a handful of read paths. A
follow-up migration (step 8) drops them after the team router and
auth router are rewritten to read from `OrganizationMember`.

Revision ID: 20260713_000001
Revises: 7a8b3c1d4e2f
Create Date: 2026-07-13 00:00:01.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260713_000001"
down_revision = "7a8b3c1d4e2f"
branch_labels = None
depends_on = None


def _create_enums(bind) -> None:
    """Create the per-membership enums. Idempotent — uses checkfirst."""
    member_role = postgresql.ENUM(
        "admin", "member", "viewer",
        name="organization_member_role_enum",
        create_type=False,
    )
    member_status = postgresql.ENUM(
        "active", "pending", "suspended", "declined",
        name="organization_member_status_enum",
        create_type=False,
    )
    member_role.create(bind, checkfirst=True)
    member_status.create(bind, checkfirst=True)


def upgrade() -> None:
    bind = op.get_bind()
    _create_enums(bind)

    member_role = postgresql.ENUM(
        "admin", "member", "viewer",
        name="organization_member_role_enum",
        create_type=False,
    )
    member_status = postgresql.ENUM(
        "active", "pending", "suspended", "declined",
        name="organization_member_status_enum",
        create_type=False,
    )

    # 1. Create the table.
    op.create_table(
        "organization_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            member_role,
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            member_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"],
            name=op.f("fk_organization_members_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint(
            "user_id", "org_id",
            name=op.f("uq_organization_members_user_org"),
        ),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR email IS NOT NULL",
            name=op.f("ck_organization_members_has_identity"),
        ),
    )

    # 2. Standard indexes.
    op.create_index(
        op.f("ix_organization_members_user_id"),
        "organization_members", ["user_id"], unique=False,
    )
    op.create_index(
        op.f("ix_organization_members_org_id"),
        "organization_members", ["org_id"], unique=False,
    )
    op.create_index(
        "ix_organization_members_user_id_status",
        "organization_members", ["user_id", "status"], unique=False,
    )
    op.create_index(
        "ix_organization_members_lower_email",
        "organization_members", [sa.text("lower(email)")], unique=False,
    )

    # 3. Partial unique index — two admins can't invite the same email
    # to the same org before that email is bound to a User. NULLs are
    # not distinct in normal unique indexes, so the explicit
    # `postgresql_where` is required.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_members_pending_email
        ON organization_members (org_id, lower(email))
        WHERE user_id IS NULL
        """
    )

    # 4. Backfill from `users.org_id`. The old `User` row already has
    # email, role, status, and timestamps — copy them into the
    # membership row. The `'invited_*'` clerk_user_id placeholder is
    # gone; we now use the membership's own status='pending' for
    # placeholder invites.
    #
    # Cast role and status to the new enum types so the assignment
    # succeeds (the value sets are identical, but PostgreSQL enums
    # are nominal types — `user_role_enum` ≠
    # `organization_member_role_enum`).
    op.execute(
        """
        INSERT INTO organization_members
            (id, user_id, org_id, email, role, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            u.id,
            u.org_id,
            lower(u.email),
            u.role::text::organization_member_role_enum,
            CASE
                WHEN u.status IN ('active', 'pending', 'suspended', 'declined')
                    THEN u.status::text::organization_member_status_enum
                ELSE 'active'::text::organization_member_status_enum
            END,
            u.created_at,
            u.created_at
        FROM users u
        WHERE u.org_id IS NOT NULL
        """
    )

    # 5. Add `users.active_org_id`. Nullable so we can backfill
    # incrementally; the dep lazy-defaults on first request if it's
    # still NULL. ON DELETE SET NULL keeps the dep safe if the active
    # org is deleted out from under the user.
    op.add_column(
        "users",
        sa.Column("active_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_users_active_org_id_organizations"),
        "users", "organizations",
        ["active_org_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_users_active_org_id"),
        "users", ["active_org_id"], unique=False,
    )

    # 6. Backfill `active_org_id` to the user's oldest active membership.
    # Users with no membership get NULL; the dep handles that on first
    # request by picking the most-recently-created membership.
    op.execute(
        """
        UPDATE users u
        SET active_org_id = (
            SELECT m.org_id
            FROM organization_members m
            WHERE m.user_id = u.id
            ORDER BY m.created_at ASC
            LIMIT 1
        )
        WHERE u.active_org_id IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_users_active_org_id", table_name="users")
    op.drop_constraint(
        op.f("fk_users_active_org_id_organizations"),
        "users", type_="foreignkey",
    )
    op.drop_column("users", "active_org_id")

    op.execute("DROP INDEX IF EXISTS uq_organization_members_pending_email")
    op.drop_index("ix_organization_members_lower_email", table_name="organization_members")
    op.drop_index("ix_organization_members_user_id_status", table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_org_id"), table_name="organization_members")
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_table("organization_members")

    member_role = postgresql.ENUM(
        "admin", "member", "viewer",
        name="organization_member_role_enum",
    )
    member_status = postgresql.ENUM(
        "active", "pending", "suspended", "declined",
        name="organization_member_status_enum",
    )
    member_role.drop(bind, checkfirst=True)
    member_status.drop(bind, checkfirst=True)
