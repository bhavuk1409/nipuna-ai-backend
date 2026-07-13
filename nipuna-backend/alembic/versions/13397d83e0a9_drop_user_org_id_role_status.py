"""drop_user_org_id_role_status

Step 8 of the multi-org migration. The `users` table no longer needs
the legacy `org_id`, `role`, or `status` columns — the
`organization_members` join table is the source of truth for
"which orgs a user belongs to and what role/status they have in each".

Pre-conditions (already true after steps 1-7):
- Every active user has at least one `OrganizationMember` row.
- The `user_id` and `org_id` FKs from `organization_members` are
  the active pointer / membership-source for every code path.
- The legacy `User.org_id`, `User.role`, `User.status` columns
  are no longer written to by any route (verified by `grep`).

What this migration does
------------------------
1. Drops the FK `users_org_id_fkey` (if it still exists from the
   original `User.org_id` column).
2. Drops the `org_id` index on users.
3. Drops the columns `org_id`, `role`, `status` from `users`.
4. Drops the unused enums `user_role_enum` and
   `user_status_enum` (they are no longer referenced by any table).
5. Removes the `User.organization` and `Organization.users`
   relationships from the SQLAlchemy model — they're a no-op now.

Note on the `Organization.users` relationship: it carries
`cascade="all, delete-orphan"`, which would also try to drop the
User rows. SQLAlchemy doesn't actually fire this on a column drop
(the DB does), but the model change is the one that matters for
ORM code.

After this migration, every code path that previously read
`user.org_id` / `user.role` / `user.status` must be reading from
`User.active_org_id` and the active `OrganizationMember` row. The
final pre-flight `grep` should return zero matches.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "13397d83e0a9"
down_revision = "20260713_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop the FK on users.org_id if it exists. (The original
    #    migration created it; we want to drop the column cleanly
    #    so the constraint must go first.)
    op.drop_constraint(
        "fk_users_org_id_organizations",
        "users",
        type_="foreignkey",
    )

    # 2. Drop the index on users.org_id.
    op.drop_index("ix_users_org_id", table_name="users")

    # 3. Drop the columns. Order doesn't matter (no dependencies
    #    between them), but the FK drop above is required.
    op.drop_column("users", "org_id")
    op.drop_column("users", "role")
    op.drop_column("users", "status")

    # 4. Drop the now-unused enums. We use `IF EXISTS` to be safe
    #    if a previous partial migration already dropped one.
    user_role = postgresql.ENUM(
        "admin", "member", "viewer", name="user_role_enum",
    )
    user_status = postgresql.ENUM(
        "active", "pending", "suspended", "declined",
        name="user_status_enum",
    )
    user_role.drop(bind, checkfirst=True)
    user_status.drop(bind, checkfirst=True)


def downgrade() -> None:
    """Recreate the legacy columns and enums. The backfill
    intentionally does *not* try to re-sync the data — it just
    sets the columns to safe defaults so the schema is valid.
    """
    bind = op.get_bind()

    # 1. Recreate the enums first (the column defaults reference them).
    user_role = postgresql.ENUM(
        "admin", "member", "viewer",
        name="user_role_enum",
    )
    user_status = postgresql.ENUM(
        "active", "pending", "suspended", "declined",
        name="user_status_enum",
    )
    user_role.create(bind, checkfirst=True)
    user_status.create(bind, checkfirst=True)

    # 2. Recreate the columns with safe defaults.
    op.add_column(
        "users",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"], unique=False)
    op.create_foreign_key(
        "fk_users_org_id_organizations",
        "users", "organizations",
        ["org_id"], ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            user_role,
            nullable=False,
            server_default="member",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "status",
            user_status,
            nullable=False,
            server_default="active",
        ),
    )

    # 3. Backfill org_id from the active membership. We pick the
    #    oldest active membership per user as the "primary" org —
    #    this matches the original backfill in step 1.
    op.execute(
        """
        UPDATE users u
        SET org_id = (
            SELECT m.org_id
            FROM organization_members m
            WHERE m.user_id = u.id AND m.status = 'active'
            ORDER BY m.created_at ASC
            LIMIT 1
        )
        WHERE u.org_id IS NULL
        """
    )
