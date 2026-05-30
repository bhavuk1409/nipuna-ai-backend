from pydantic import BaseModel


class RecentActivity(BaseModel):
    type: str
    description: str


class DashboardOverview(BaseModel):
    active_agents: int
    tasks_closed: int
    system_health: int
    recent_activity: list[RecentActivity]
