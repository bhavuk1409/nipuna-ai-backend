import pytest
import pytest_asyncio
from app.database import engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup_database_connections():
    """Automatically dispose of connection pool after each test to avoid event loop mismatches."""
    yield
    await engine.dispose()
