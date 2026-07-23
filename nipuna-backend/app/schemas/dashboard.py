from datetime import datetime
from pydantic import BaseModel


class RecentActivity(BaseModel):
    type: str
    description: str
    created_at: datetime | None = None


class DashboardOverview(BaseModel):
    active_agents: int
    tasks_closed: int
    system_health: int
    recent_activity: list[RecentActivity]
