"""add message encryption columns + backfill

The PII redaction pass on logs is half a fix — a database dump
still leaks conversation content and tool results. This migration
adds ``messages.content_encrypted`` and
``messages.tool_result_encrypted`` (``LargeBinary`` → ``BYTEA`` on
Postgres) and backfills them with the Fernet-encrypted plaintext
using the existing ``app.utils.encryption`` helper.

We don't drop the plaintext columns in this migration: the read path
in ``chat.py`` and ``tests/`` still uses them, and a one-release
window of dual-write + plaintext fallback is the safe way to ship
the schema. A follow-up migration in PR2 makes the encrypted column
authoritative and drops the plaintext mirrors.

Backfill is per-row Python code. On a populated DB this can take
seconds; the migration runs inside a single transaction so a failure
rolls back cleanly. If the dev DB has no ENCRYPTION_KEY set, the
backfill is skipped (the columns are still created — writes are
skipped too, since ``app/utils/encryption.py`` raises on missing
key).

Revision ID: 20260716_000006
Revises: 20260716_000005
Create Date: 2026-07-16 00:00:06.000000
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "20260716_000006"
down_revision = "20260716_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("content_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("tool_result_encrypted", sa.LargeBinary(), nullable=True),
    )

    # Backfill. On a populated DB (the dev DB has thousands of
    # message rows) this can take a few seconds; we batch in chunks
    # of 500 to keep the WAL manageable. On an empty DB the SELECT
    # returns no rows and the migration is effectively a no-op.
    bind = op.get_bind()
    try:
        from app.utils.encryption import encrypt
    except Exception as exc:  # missing key, missing ENCRYPTION_KEY, etc.
        logger.warning("Skipping message backfill: %s", exc)
        return

    BATCH = 500
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT id, content, tool_result FROM messages "
                "WHERE content_encrypted IS NULL LIMIT :batch"
            ),
            {"batch": BATCH},
        ).fetchall()
        if not rows:
            break
        for row_id, content, tool_result in rows:
            enc_content = encrypt(content).encode("ascii")
            enc_tool = (
                encrypt(tool_result).encode("ascii") if tool_result else None
            )
            bind.execute(
                sa.text(
                    "UPDATE messages SET "
                    "content_encrypted = :content_enc, "
                    "tool_result_encrypted = :tool_result_enc "
                    "WHERE id = :id"
                ),
                {
                    "content_enc": enc_content,
                    "tool_result_enc": enc_tool,
                    "id": row_id,
                },
            )


def downgrade() -> None:
    op.drop_column("messages", "tool_result_encrypted")
    op.drop_column("messages", "content_encrypted")
