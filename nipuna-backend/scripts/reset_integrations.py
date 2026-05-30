import asyncio
from sqlalchemy import update
from app.database import AsyncSessionLocal, engine
from app.models.integration import Integration

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Integration).values(
                status="disconnected",
                composio_connection_id=None,
                sync_health=0
            )
        )
        await session.commit()
    await engine.dispose()
    print("Database successfully reset. All integrations are now set to disconnected.")

if __name__ == "__main__":
    asyncio.run(main())
