import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.database import AsyncSessionLocal, engine
from app.models.alert import Alert
from app.models.organization import Organization
from app.models.user import User
from app.models.agent import Agent

async def main():
    async with AsyncSessionLocal() as db:
        # Check if org already exists
        org_check = await db.execute(select(Organization).limit(1))
        org = org_check.scalar_one_or_none()
        if not org:
            org = Organization(
                id=uuid.uuid4(),
                clerk_org_id="org_mock_clerk_id_12345",
                name="Paytm (Dev)",
                plan="free",
                seats_max=5,
                ai_credits=1000
            )
            db.add(org)
            await db.flush()
            print("Created mock organization:", org.name, org.id)
        else:
            print("Organization already exists:", org.name, org.id)

        # Check if user already exists
        user_check = await db.execute(select(User).limit(1))
        user = user_check.scalar_one_or_none()
        if not user:
            user = User(
                id=uuid.uuid4(),
                clerk_user_id="user_mock_clerk_id_12345",
                org_id=org.id,
                email="dev@nipunaai.in",
                first_name="Dev",
                last_name="User",
                role="admin",
                status="active"
            )
            db.add(user)
            await db.flush()
            print("Created mock user:", user.email, user.id)
        else:
            print("User already exists:", user.email, user.id)

        # Check if default agent already exists
        agent_check = await db.execute(select(Agent).limit(1))
        agent = agent_check.scalar_one_or_none()
        if not agent:
            agent = Agent(
                id=uuid.uuid4(),
                org_id=org.id,
                name="Nipuna AI",
                domain="General Business",
                objective="Analyze cash flow, invoices, communications, and help run business operations.",
                status="active",
                created_by=user.id
            )
            db.add(agent)
            await db.flush()
            print("Created default agent:", agent.name, agent.id)
        else:
            print("Agent already exists:", agent.name, agent.id)

        alerts_check = await db.execute(select(Alert).where(Alert.org_id == org.id).limit(1))
        if not alerts_check.scalar_one_or_none():
            sample_alerts = [
                Alert(
                    org_id=org.id,
                    rule_id="TALLY_SYNC_COMPLETE",
                    severity="info",
                    message="Successfully synced 1,402 entries from local Tally bridge.",
                ),
                Alert(
                    org_id=org.id,
                    rule_id="NEW_OPERATOR_JOINED",
                    severity="info",
                    message="Standard access granted to member developer.",
                ),
                Alert(
                    org_id=org.id,
                    rule_id="INVOICE_INGESTION_STARTED",
                    severity="warning",
                    message="Processing INV-2026-901.pdf and 11 other uploads.",
                    read_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                ),
            ]
            db.add_all(sample_alerts)
            await db.flush()
            print("Seeded sample notifications")
        else:
            print("Notifications already exist")

        await db.commit()
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
