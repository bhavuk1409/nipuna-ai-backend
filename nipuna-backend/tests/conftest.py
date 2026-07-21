import os
import sys

# Force tests to use local SQLite test database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"
os.environ["ENV"] = "test"
# A dummy 64-hex-char key so the encryption module can import
# without raising on a fresh checkout. The encryption migration
# uses this if present; tests don't exercise the real Fernet
# roundtrip except in test_message_encryption.py.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "0" * 64,
)

import pytest
import pytest_asyncio
from app.database import engine
from app.models import Base


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Create database tables before tests and drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(autouse=True)
async def cleanup_database_connections():
    """Automatically dispose of connection pool after each test to avoid event loop mismatches."""
    yield
    await engine.dispose()

