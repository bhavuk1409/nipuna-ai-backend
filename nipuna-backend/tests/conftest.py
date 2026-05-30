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

