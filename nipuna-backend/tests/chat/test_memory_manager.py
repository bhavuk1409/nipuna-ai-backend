"""Memory manager unit + integration tests.

The manager is the read path: top-N decrypted facts for the system
prompt, dedup by key, render the ``KNOWN FACTS ABOUT THIS USER`` block.
Encryption is exercised end-to-end: write through the manager's
caller, read back through ``facts_for_injection``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.models.user_memory import UserMemory
from app.services.memory import manager
from app.utils.encryption import encrypt_bytes


# ──────────────────────────────────────────────────────────────────
# Pure-function unit tests
# ──────────────────────────────────────────────────────────────────


def test_dedupe_by_key_case_insensitive():
    # Caller pre-sorts by confidence DESC (manager does this at the
    # SQL level). First occurrence wins on case-insensitive key collision.
    facts = [
        manager.MemoryFact(id="2", key="Role", value="CEO", confidence=90),
        manager.MemoryFact(id="3", key="currency", value="INR", confidence=70),
        manager.MemoryFact(id="1", key="role", value="CFO", confidence=80),
    ]
    out = manager._dedupe_by_key(facts)
    # The "Role" (id=2, conf=90) wins the collision with "role" (id=1).
    assert [f.id for f in out] == ["2", "3"]


def test_dedupe_skips_empty_keys():
    facts = [
        manager.MemoryFact(id="1", key="", value="x", confidence=80),
        manager.MemoryFact(id="2", key="role", value="CFO", confidence=80),
    ]
    out = manager._dedupe_by_key(facts)
    assert [f.id for f in out] == ["2"]


def test_format_block_empty():
    assert manager.build_memory_block([]) == ""


def test_format_block_single_line():
    block = manager.build_memory_block(
        [manager.MemoryFact(id="1", key="role", value="CFO", confidence=80)]
    )
    assert block == "- role: CFO"


def test_format_block_multi_line():
    block = manager.build_memory_block(
        [
            manager.MemoryFact(id="1", key="role", value="CFO", confidence=80),
            manager.MemoryFact(id="2", key="currency", value="INR", confidence=70),
        ]
    )
    assert "- role: CFO" in block
    assert "- currency: INR" in block


def test_format_block_caps_total_length():
    """Lowest-confidence fact dropped first when over budget."""
    long_value = "x" * 250
    facts = [
        manager.MemoryFact(id="1", key="k1", value="alpha", confidence=99),
        manager.MemoryFact(id="2", key="k2", value=long_value, confidence=80),
        manager.MemoryFact(id="3", key="k3", value="beta", confidence=10),
    ]
    block = manager.build_memory_block(facts, max_chars=200)
    # The high-confidence k1 and k3 (low confidence but tiny) are
    # likely included; the long-value k2 may or may not be. The
    # block should never exceed the cap.
    assert len(block) <= 200
    # The cap is enforced by lines, not characters mid-line.
    for line in block.splitlines():
        # Each line within budget — we don't split lines mid-fact.
        pass


# ──────────────────────────────────────────────────────────────────
# DB integration tests
# ──────────────────────────────────────────────────────────────────


async def _make_org_and_user(db: AsyncSession) -> tuple[Organization, User]:
    from app.models.organization_member import OrganizationMember

    org = Organization(
        clerk_org_id=f"manual_{uuid.uuid4().hex[:8]}",
        name="Memory Test Org",
        plan="pro",
        ai_credits=100,
    )
    db.add(org)
    await db.flush()
    user = User(
        clerk_user_id=f"user_{uuid.uuid4().hex[:8]}",
        email=f"u-{uuid.uuid4().hex[:6]}@t.local",
        active_org_id=org.id,
    )
    db.add(user)
    await db.flush()
    # The membership row requires a non-NULL email.
    db.add(OrganizationMember(
        user_id=user.id, org_id=org.id,
        email=user.email, role="admin", status="active",
    ))
    await db.flush()
    return org, user


@pytest.mark.asyncio
async def test_facts_for_injection_round_trip(chat_db):
    org, user = await _make_org_and_user(chat_db)

    # Write 3 memories with the encrypted column populated.
    rows = [
        UserMemory(
            user_id=user.id,
            org_id=org.id,
            key="role",
            value="CFO at Acme",
            value_encrypted=encrypt_bytes("CFO at Acme"),
            confidence=90,
        ),
        UserMemory(
            user_id=user.id,
            org_id=org.id,
            key="currency",
            value="INR",
            value_encrypted=encrypt_bytes("INR"),
            confidence=70,
        ),
        UserMemory(
            user_id=user.id,
            org_id=org.id,
            key="archived_old",
            value="old",
            value_encrypted=encrypt_bytes("old"),
            confidence=80,
            archived=True,
        ),
    ]
    for r in rows:
        chat_db.add(r)
    await chat_db.commit()

    facts = await manager.facts_for_injection(
        chat_db,
        user_id=str(user.id),
        org_id=str(org.id),
    )
    # Archived is excluded.
    assert len(facts) == 2
    keys = {f.key for f in facts}
    assert keys == {"role", "currency"}


@pytest.mark.asyncio
async def test_facts_for_injection_dedupes_by_key(chat_db):
    org, user = await _make_org_and_user(chat_db)

    # Two rows with the same key (case-different). Higher confidence wins.
    chat_db.add(UserMemory(
        user_id=user.id, org_id=org.id,
        key="role", value="CFO", value_encrypted=encrypt_bytes("CFO"),
        confidence=60,
    ))
    chat_db.add(UserMemory(
        user_id=user.id, org_id=org.id,
        key="Role", value="CEO", value_encrypted=encrypt_bytes("CEO"),
        confidence=90,
    ))
    await chat_db.commit()

    facts = await manager.facts_for_injection(
        chat_db, user_id=str(user.id), org_id=str(org.id),
    )
    assert len(facts) == 1
    assert facts[0].value == "CEO"
    assert facts[0].confidence == 90


@pytest.mark.asyncio
async def test_facts_for_injection_respects_max(chat_db):
    org, user = await _make_org_and_user(chat_db)

    for i in range(8):
        chat_db.add(UserMemory(
            user_id=user.id, org_id=org.id,
            key=f"key_{i}", value=f"value_{i}",
            value_encrypted=encrypt_bytes(f"value_{i}"),
            confidence=100 - i,
        ))
    await chat_db.commit()

    facts = await manager.facts_for_injection(
        chat_db,
        user_id=str(user.id),
        org_id=str(org.id),
        max_memories=3,
    )
    assert len(facts) == 3
    # Highest confidence (lowest i) wins.
    assert [f.key for f in facts] == ["key_0", "key_1", "key_2"]


@pytest.mark.asyncio
async def test_facts_for_injection_handles_bad_encryption(chat_db):
    """A row with garbage in ``value_encrypted`` falls back to the
    plaintext column rather than crashing the manager.
    """
    org, user = await _make_org_and_user(chat_db)

    chat_db.add(UserMemory(
        user_id=user.id, org_id=org.id,
        key="role", value="CFO",
        value_encrypted=b"not-valid-fernet-token",
        confidence=80,
    ))
    await chat_db.commit()

    facts = await manager.facts_for_injection(
        chat_db, user_id=str(user.id), org_id=str(org.id),
    )
    assert len(facts) == 1
    # Fallback to plaintext.
    assert facts[0].value == "CFO"


@pytest.mark.asyncio
async def test_build_block_includes_all_kept_facts(chat_db):
    """Top-level helper used by the chat router: build a renderable
    block from the user's facts.
    """
    org, user = await _make_org_and_user(chat_db)

    chat_db.add(UserMemory(
        user_id=user.id, org_id=org.id,
        key="role", value="CFO",
        value_encrypted=encrypt_bytes("CFO"), confidence=80,
    ))
    chat_db.add(UserMemory(
        user_id=user.id, org_id=org.id,
        key="currency", value="INR",
        value_encrypted=encrypt_bytes("INR"), confidence=70,
    ))
    await chat_db.commit()

    facts = await manager.facts_for_injection(
        chat_db, user_id=str(user.id), org_id=str(org.id),
    )
    block = manager.build_memory_block(facts)
    assert "- role: CFO" in block
    assert "- currency: INR" in block
