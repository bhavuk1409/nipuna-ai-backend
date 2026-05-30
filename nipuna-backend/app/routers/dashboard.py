from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.agent import Agent
from app.models.conversation import Message
from app.models.integration import Integration
from app.models.organization import Organization
from app.models.user import User
from app.schemas.dashboard import DashboardOverview, RecentActivity

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverview:
    active_agents_result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.org_id == org.id,
            Agent.status == "active",
        )
    )
    active_agents = active_agents_result.scalar() or 0

    tasks_closed_result = await db.execute(
        select(func.count(Message.id))
        .select_from(Message)
        .join(Message.conversation)
        .where(
            Message.role == "assistant",
            Message.conversation.has(org_id=org.id),
        )
    )
    tasks_closed = tasks_closed_result.scalar() or 0

    sync_health_result = await db.execute(
        select(func.coalesce(func.avg(Integration.sync_health), 100)).where(
            Integration.org_id == org.id,
            Integration.status == "connected",
        )
    )
    system_health = int(sync_health_result.scalar() or 100)

    from app.models.conversation import Conversation
    recent_messages_result = await db.execute(
        select(Message)
        .join(Message.conversation)
        .where(Conversation.org_id == org.id)
        .options(joinedload(Message.conversation))
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = recent_messages_result.scalars().all()

    recent_activity = [
        RecentActivity(
            type="chat",
            description=msg.content[:120] if msg.content else "",
        )
        for msg in recent_messages
    ]

    return DashboardOverview(
        active_agents=active_agents,
        tasks_closed=tasks_closed,
        system_health=system_health,
        recent_activity=recent_activity,
    )
