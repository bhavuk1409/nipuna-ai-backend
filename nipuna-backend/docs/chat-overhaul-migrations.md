# Chat overhaul — migration runbook

The chat overhaul ships across 5 stacked PRs. The migrations in
this directory run in order; some of them are not runnable inside
a transaction and **must be invoked by hand**. This file is the
operator runbook.

## PR1 migrations (this PR)

| revision                              | what it does                       | runnable by `alembic upgrade` |
|---------------------------------------|------------------------------------|-------------------------------|
| `20260716_000001_add_pgvector_with_variant` | Enable `vector` extension + create `vector_chunks` table | Yes |
| `20260716_000002_add_vector_chunks_hnsw_index` | Create HNSW index on `vector_chunks.embedding` | **No — manual, see below** |
| `20260716_000003_add_agent_template_fields` | Add `template_id`, `icon`, `color` to `agents` | Yes |
| `20260716_000004_add_conversation_metadata` | Add `title`, `archived_at`, `legacy_client_id`, `last_message_at` to `conversations` | Yes |
| `20260716_000005_add_message_truncated_at` | Add `truncated_at` to `messages` | Yes |
| `20260716_000006_add_message_encryption` | Add `content_encrypted`, `tool_result_encrypted` to `messages`; backfill from plaintext | Yes (requires `ENCRYPTION_KEY` set) |
| `20260716_000007_add_user_memory` | Create `user_memories` table | Yes |
| `20260716_000008_add_tool_call_audit` | Create `tool_call_audit` table | Yes |
| `20260716_000009_add_vector_document_metadata` | Add `title`, `last_indexed_at`, `updated_at` to `vector_documents` | Yes |

## Standard upgrade (dev, CI)

```bash
cd /Users/bhavukagrawal/nipuna-ai-backend/nipuna-backend
export ENCRYPTION_KEY="$(openssl rand -hex 32)"  # 64 hex chars
alembic upgrade head
```

The encryption migration (`000006`) reads every existing message
and writes the Fernet-encrypted ciphertext to the new
`content_encrypted` / `tool_result_encrypted` columns. On a
populated DB this takes a few seconds; the migration is
transactional, so a failure rolls back cleanly.

If `ENCRYPTION_KEY` is unset, the migration creates the columns
but skips the backfill and logs a warning. New rows will then
write plaintext to the new columns until the operator provides
a key. **Set the key in every env before running the
encryption migration.**

## Manual HNSW index (`000002`)

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction, and
Alembic wraps every migration in one. Run the index creation
out-of-band:

```bash
cd /Users/bhavukagrawal/nipuna-ai-backend/nipuna-backend
alembic upgrade 20260716_000002 --sql > /tmp/hnsw_index.sql
psql "$DATABASE_URL" -f /tmp/hnsw_index.sql
```

The migration itself uses `IF NOT EXISTS`, so re-running it on a
DB that already has the index is a no-op. Stamping the revision
without running the SQL will leave the index missing; the
search code falls back to a sequential scan, which is fine for
staging but not for prod.

To stamp the migration as "applied" without running it:

```bash
alembic stamp 20260716_000002
```

## Rollback (don't, but if you must)

`alembic downgrade -1` rolls back the most recent migration. The
encryption migration is a one-way trip for the encrypted columns:
a downgrade drops the columns, leaving the plaintext intact
(because the down doesn't re-decrypt), but any code that reads
the encrypted column will fail.

The HNSW index migration is a no-op on downgrade if the index
doesn't exist.

## Adding a new migration in this series

1. Pick the next revision id. The convention is
   `YYYYMMDD_HHMMSS_short_description.py`.
2. Set `down_revision` to the most recent revision in the chain.
   At PR1 cut time, the head is `20260716_000009`.
3. Use `op.add_column` / `op.create_table` for the schema
   change. If you need a non-transactional step (concurrent
   index, `CREATE EXTENSION`, etc.), document the manual run
   command here.
4. Run the migration on the dev DB and confirm `alembic
   upgrade head` is green.
5. Run the existing test suite: `pytest tests/ -q
   --ignore=tests/eval`.

## Verification after PR1 lands

```bash
# Migrations apply cleanly
alembic upgrade head

# All existing tests pass
pytest tests/ -q --ignore=tests/eval

# Eval harness loads and passes under mock
RUN_EVAL=1 pytest tests/eval -q

# The model is the right type on Postgres, TEXT on SQLite
.venv/bin/python -c "from app.models import VectorChunk; print(VectorChunk.embedding.type)"
# Postgres: VECTOR(1536)  /  SQLite: TEXT
```
