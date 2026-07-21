# Encryption policy

The chat overhaul (PR1) ships column-level encryption for
sensitive PII. This document is the operator runbook for the
key, the rotation policy, and the data-loss boundaries.

## What's encrypted

| column                                | what it holds                       |
|---------------------------------------|-------------------------------------|
| `messages.content_encrypted`          | every chat message (user + AI)      |
| `messages.tool_result_encrypted`      | tool output (invoices, ledgers, etc.) |
| `user_memories.value_encrypted`       | extracted user facts ("CFO at Acme", "prefers INR") |

The plaintext columns (`messages.content`,
`messages.tool_result`, `user_memories.value`) are kept for one
release window as a rollback target. PR2 will make the encrypted
columns authoritative and drop the plaintext mirrors.

## Key

The key is a 32-byte secret, hex-encoded into 64 characters,
provided via the `ENCRYPTION_KEY` env var. The application
uses the Fernet construction (`cryptography.fernet.Fernet`)
on top of the raw key:

```python
key_bytes = bytes.fromhex(os.environ["ENCRYPTION_KEY"])
fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
```

### Generate a key

```bash
openssl rand -hex 32
# e.g. 3f4a... 64 hex chars
```

Set it in every environment (dev, staging, prod) before running
the encryption migration. The migration will skip the backfill
if the key is missing, and new rows will write plaintext to the
encrypted column — a log line that *should* alert.

## Dev

A static `ENCRYPTION_KEY` in `.env` is fine. The key is checked
into `.env.example` for the dev path so a fresh clone is
runnable; the file is git-ignored.

## Staging / Prod

Use AWS KMS. The fetch happens in `app/utils/encryption.py`'s
`_get_fernet` — replace the direct hex-decode with a
`boto3.client("kms").decrypt(...)` call when the env is
`prod`. The env-to-KMS-arn mapping is configured per environment.

A short-lived cache (5 minutes, in-process) keeps the KMS call
rate low; cache invalidation happens on rotation.

## Rotation

A rotation creates a new key, decrypts every row with the old
key, re-encrypts with the new key, and atomically swaps the
key reference. We run this in two phases:

1. **Dual-key window**: the encryption helper supports an
   "old + new" mode where reads try the new key first and fall
   back to the old key. Writes use the new key. Runs for one
   week or one full backup cycle, whichever is longer.
2. **Old-key drop**: the helper stops trying the old key.
   Stale ciphertext (if any) is decrypted in a background job
   and re-encrypted with the new key.

The operator runbook for rotation (not yet implemented — this
is a PR2 follow-up):

```bash
# 1. Generate the new key
openssl rand -hex 32 > new_key.txt
# 2. Run the rotation script
.venv/bin/python scripts/rotate_encryption.py --old <old_key> --new <new_key>
# 3. Swap ENCRYPTION_KEY in the env
# 4. After the dual-key window, redeploy with the simplified
#    helper that only knows the new key
```

## What happens when a key is lost

Every encrypted row becomes unreadable. The plaintext mirror
columns (`messages.content`, etc.) still hold the original
data — that's why they exist. A backup that pre-dates the
encryption migration can also be used to restore the plaintext.

**Do not** delete the plaintext columns before the rotation is
fully baked. PR2's migration to drop them is gated on the
rotation helper being in place and tested end-to-end on staging.

## Compliance

The encryption is symmetric (Fernet / AES-128-CBC + HMAC-SHA256)
with a per-deployment key. This is enough to satisfy "data at
rest is encrypted" in most compliance frameworks; consult your
specific framework for the key-management requirements (some
require per-row keys, per-tenant KMS, etc.).
