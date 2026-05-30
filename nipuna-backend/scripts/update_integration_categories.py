import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.integration import Integration
from app.services.mcp.gateway import AVAILABLE_PROVIDERS

async def update_categories():
    async with AsyncSessionLocal() as session:
        # Get all integrations
        result = await session.execute(select(Integration))
        integrations = result.scalars().all()
        
        updated_count = 0
        for integration in integrations:
            provider = integration.provider.upper()
            if provider in AVAILABLE_PROVIDERS:
                category = AVAILABLE_PROVIDERS[provider].get("category")
                if integration.category != category:
                    integration.category = category
                    updated_count += 1
        
        await session.commit()
        print(f"Updated {updated_count} integrations with categories.")

if __name__ == "__main__":
    asyncio.run(update_categories())
